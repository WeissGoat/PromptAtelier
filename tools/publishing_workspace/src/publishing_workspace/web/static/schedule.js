(() => {
  "use strict";

  const state = {
    month: new Date().toISOString().slice(0, 7),
    plan: null,
    selectedEntryId: null,
    draftEntry: null,
    selectedSet: "post",
    selectedAssetIds: new Set(),
    searchResults: [],
    tasks: [],
    imports: [],
    facets: {},
    filters: { import_id: "", text: "", artist: "", character: "", action_group: "", action: "", facets: {} },
    draggedEntryId: null,
    draggedAssetId: null,
  };

  const $ = (id) => document.getElementById(id);
  const elements = {
    monthPicker: $("month-picker"),
    previousMonth: $("previous-month"),
    nextMonth: $("next-month"),
    createPlan: $("create-plan"),
    toggleLock: $("toggle-lock"),
    planStatus: $("plan-status"),
    notice: $("notice"),
    calendarTitle: $("calendar-title"),
    calendarSubtitle: $("calendar-subtitle"),
    calendarGrid: $("calendar-grid"),
    newEntry: $("new-entry"),
    resetEditor: $("reset-editor"),
    editorTitle: $("editor-title"),
    entryForm: $("entry-form"),
    entryId: $("entry-id"),
    entryTitle: $("entry-title"),
    entryDate: $("entry-date"),
    entryTime: $("entry-time"),
    contentKind: $("content-kind"),
    inlineSource: $("inline-source"),
    taskSource: $("task-source"),
    taskSelect: $("task-select"),
    taskIdInput: $("task-id-input"),
    setLists: $("set-lists"),
    saveEntry: $("save-entry"),
    deleteEntry: $("delete-entry"),
    importSelect: $("import-select"),
    textFilter: $("text-filter"),
    artistFilter: $("artist-filter"),
    characterFilter: $("character-filter"),
    groupFilter: $("group-filter"),
    actionFilter: $("action-filter"),
    facetFilters: $("facet-filters"),
    clearFacets: $("clear-facets"),
    searchAssets: $("search-assets"),
    addToSet: $("add-to-set"),
    addSelectedAssets: $("add-selected-assets"),
    assetResults: $("asset-results"),
    assetCount: $("asset-count"),
    previewDialog: $("preview-dialog"),
    previewImage: $("preview-image"),
    previewCaption: $("preview-caption"),
    closePreview: $("close-preview"),
  };

  function showNotice(message, kind = "") {
    elements.notice.textContent = message || "";
    elements.notice.className = `notice ${kind}`.trim();
  }

  async function request(url, options = {}) {
    const response = await fetch(url, { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
    const body = await response.json().catch(() => null);
    if (!response.ok) {
      const message = body?.detail?.message || body?.detail || `请求失败：${response.status}`;
      const error = new Error(message);
      error.status = response.status;
      error.payload = body;
      throw error;
    }
    return body;
  }

  function monthDate(month) {
    const [year, number] = month.split("-").map(Number);
    return new Date(year, number - 1, 1);
  }

  function formatMonth(date) {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
  }

  function localParts(iso, timeZone) {
    const date = new Date(iso);
    const values = new Intl.DateTimeFormat("en-CA", {
      timeZone, year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hour12: false, hourCycle: "h23",
    }).formatToParts(date).reduce((result, part) => {
      result[part.type] = part.value;
      return result;
    }, {});
    return { date: `${values.year}-${values.month}-${values.day}`, time: `${values.hour}:${values.minute}` };
  }

  function timeZoneOffset(date, timeZone) {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone, year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false, hourCycle: "h23",
    }).formatToParts(date).reduce((result, part) => {
      result[part.type] = part.value;
      return result;
    }, {});
    const represented = Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day), Number(parts.hour), Number(parts.minute), Number(parts.second));
    return represented - date.getTime();
  }

  function fieldsToIso(dateText, timeText) {
    const timeZone = state.plan?.timezone || "Asia/Shanghai";
    const provisional = new Date(`${dateText}T${timeText}:00Z`);
    const offset = timeZoneOffset(provisional, timeZone);
    const sign = offset >= 0 ? "+" : "-";
    const minutes = Math.abs(offset / 60000);
    return `${dateText}T${timeText}:00${sign}${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
  }

  function currentEntry() {
    return state.plan?.entries?.find((item) => item.entry_id === state.selectedEntryId) || state.draftEntry || null;
  }

  function isLocked() { return state.plan?.status === "locked"; }

  function updateControls() {
    const loaded = Boolean(state.plan);
    elements.newEntry.disabled = !loaded || isLocked();
    elements.saveEntry.disabled = !loaded || isLocked();
    elements.deleteEntry.disabled = !loaded || !state.selectedEntryId || isLocked();
    elements.toggleLock.disabled = !loaded;
    elements.toggleLock.textContent = isLocked() ? "解锁计划" : "锁定计划";
    elements.planStatus.textContent = !loaded ? "未创建" : (isLocked() ? "已锁定" : `草稿 · r${state.plan.revision}`);
    elements.planStatus.classList.toggle("locked", isLocked());
    elements.monthPicker.value = state.month;
    elements.contentKind.disabled = isLocked();
    elements.taskSelect.disabled = isLocked();
    elements.taskIdInput.disabled = isLocked();
    elements.entryTitle.disabled = isLocked();
    elements.entryDate.disabled = isLocked();
    elements.entryTime.disabled = isLocked();
  }

  async function loadPlan() {
    state.plan = null;
    state.selectedEntryId = null;
    state.draftEntry = null;
    renderAll();
    try {
      state.plan = await request(`/api/plans/${state.month}`);
      showNotice("");
    } catch (error) {
      if (error.status === 404) {
        showNotice("这个月还没有计划，点击“创建空计划”开始。", "warning");
      } else {
        showNotice(error.message, "error");
      }
    }
    renderAll();
  }

  async function createPlan() {
    try {
      state.plan = await request(`/api/plans/${state.month}`, { method: "POST" });
      state.selectedEntryId = null;
      state.draftEntry = null;
      showNotice(`已创建 ${state.month} 空计划。`);
      renderAll();
    } catch (error) {
      if (error.status === 409) await loadPlan();
      else showNotice(error.message, "error");
    }
  }

  async function refreshImports() {
    try {
      state.imports = await request("/api/imports");
      elements.importSelect.innerHTML = `<option value="">全部导入</option>`;
      for (const item of state.imports) {
        const option = document.createElement("option");
        option.value = item.import_id;
        option.textContent = `${item.source_ref || item.import_id} · ${item.import_id.slice(0, 8)}`;
        elements.importSelect.append(option);
      }
    } catch (error) { showNotice(error.message, "error"); }
  }

  async function refreshTasks() {
    try {
      state.tasks = await request("/api/tasks");
      elements.taskSelect.innerHTML = `<option value="">选择已有任务</option>`;
      for (const item of state.tasks) {
        const option = document.createElement("option");
        option.value = item.task_id;
        option.textContent = `${item.title} · ${item.task_id}`;
        elements.taskSelect.append(option);
      }
    } catch (error) { showNotice(error.message, "error"); }
  }

  async function refreshFacets() {
    try {
      const query = state.filters.import_id ? `?import_id=${encodeURIComponent(state.filters.import_id)}` : "";
      state.facets = await request(`/api/assets/facets${query}`);
      renderFacets();
    } catch (error) { showNotice(error.message, "error"); }
  }

  function renderFacets() {
    elements.facetFilters.innerHTML = "";
    for (const [field, values] of Object.entries(state.facets)) {
      if (!values.length) continue;
      const group = document.createElement("div");
      group.className = "facet-group";
      group.innerHTML = `<span class="facet-name">${escapeHtml(field)}</span>`;
      for (const value of values) {
        const label = document.createElement("label");
        label.className = "facet-option";
        const checked = state.filters.facets[field]?.includes(value) ? " checked" : "";
        label.innerHTML = `<input type="checkbox" data-facet-field="${escapeAttr(field)}" data-facet-value="${escapeAttr(value)}"${checked}> ${escapeHtml(value)}`;
        group.append(label);
      }
      elements.facetFilters.append(group);
    }
    if (!elements.facetFilters.children.length) elements.facetFilters.innerHTML = `<div class="empty-state">暂无 facet</div>`;
  }

  async function searchAssets() {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(state.filters)) {
      if (key !== "facets" && value) params.set(key, value);
    }
    if (Object.keys(state.filters.facets).length) params.set("facets", JSON.stringify(state.filters.facets));
    try {
      state.searchResults = await request(`/api/assets/search?${params}`);
      renderAssets();
    } catch (error) { showNotice(error.message, "error"); }
  }

  function renderAssets() {
    elements.assetCount.textContent = String(state.searchResults.length);
    if (!state.searchResults.length) {
      elements.assetResults.className = "asset-results empty-state";
      elements.assetResults.textContent = "没有匹配的素材";
      return;
    }
    elements.assetResults.className = "asset-results";
    elements.assetResults.innerHTML = "";
    for (const asset of state.searchResults) {
      const card = document.createElement("article");
      card.className = "asset-card";
      const checked = state.selectedAssetIds.has(asset.asset_id) ? " checked" : "";
      const warning = asset.warnings.length ? `<span class="warning-badge">风险 ${asset.warnings.length}</span>` : "";
      const usage = asset.usage.length ? `<span class="usage-badge">已用 ${asset.usage.length}</span>` : "";
      const tags = ["character", "action_group", "action"].flatMap((key) => (asset.values[key] || []).slice(0, 1)).join(" · ");
      card.innerHTML = `
        <img class="thumb preview-trigger" src="${previewUrl(asset.asset_id)}" alt="" data-asset-id="${escapeAttr(asset.asset_id)}" data-caption="${escapeAttr(asset.display_name)}">
        <div class="asset-main"><div class="asset-name" title="${escapeAttr(asset.display_name)}">${escapeHtml(asset.display_name)}${warning}${usage}</div><div class="asset-tags" title="${escapeAttr(tags)}">${escapeHtml(tags || "无节点信息")}</div></div>
        <div class="asset-actions"><label><input type="checkbox" class="asset-check" data-asset-id="${escapeAttr(asset.asset_id)}"${checked}> 选择</label><button class="preview-trigger" type="button" data-asset-id="${escapeAttr(asset.asset_id)}" data-caption="${escapeAttr(asset.display_name)}">预览</button></div>`;
      elements.assetResults.append(card);
    }
  }

  function selectedSets() {
    const content = currentEntry()?.content;
    return content?.kind === "inline_selection" ? content.sets : { all: [], post: [], cover: [] };
  }

  function renderSetLists() {
    const sets = selectedSets();
    elements.setLists.innerHTML = "";
    for (const setName of ["all", "post", "cover"]) {
      const list = document.createElement("div");
      list.className = "set-list";
      list.dataset.set = setName;
      list.addEventListener("dragover", (event) => event.preventDefault());
      list.addEventListener("drop", (event) => reorderAsset(event, setName, list));
      if (state.selectedSet === setName) list.classList.add("active-list");
      for (const assetId of sets[setName] || []) list.append(makeSetItem(assetId, setName));
      elements.setLists.append(list);
    }
    for (const setName of ["all", "post", "cover"]) $(`${setName}-count`).textContent = String((sets[setName] || []).length);
  }

  function makeSetItem(assetId, setName) {
    const item = document.createElement("div");
    item.className = "set-item";
    item.draggable = true;
    item.dataset.assetId = assetId;
    item.innerHTML = `<img src="${previewUrl(assetId)}" alt=""><span class="set-item-name" title="${escapeAttr(assetId)}">${escapeHtml(assetId)}</span><button class="remove-item" type="button" aria-label="移除" title="移除">&#10005;</button>`;
    item.addEventListener("dragstart", (event) => { state.draggedAssetId = assetId; event.dataTransfer.setData("text/plain", assetId); });
    item.querySelector("img").addEventListener("click", () => openPreview(assetId, assetId));
    item.querySelector(".remove-item").addEventListener("click", () => removeAsset(setName, assetId));
    return item;
  }

  function reorderAsset(event, setName, list) {
    event.preventDefault();
    const assetId = event.dataTransfer.getData("text/plain") || state.draggedAssetId;
    if (!assetId || !currentEntry() || currentEntry().content.kind !== "inline_selection") return;
    const sets = cloneSets(currentEntry().content.sets);
    const current = sets[setName] || [];
    const sourceIndex = current.indexOf(assetId);
    if (sourceIndex >= 0) current.splice(sourceIndex, 1);
    const target = [...list.querySelectorAll(".set-item")].find((element) => element !== event.target && element.getBoundingClientRect().top > event.clientY);
    const targetIndex = target ? current.indexOf(target.dataset.assetId) : current.length;
    current.splice(Math.max(0, targetIndex), 0, assetId);
    replaceCurrentInlineSets(sets);
    renderSetLists();
  }

  function cloneSets(sets) { return { all: [...(sets?.all || [])], post: [...(sets?.post || [])], cover: [...(sets?.cover || [])] }; }

  function replaceCurrentInlineSets(sets) {
    const entry = currentEntry();
    if (!entry || entry.content.kind !== "inline_selection") return;
    entry.content.sets = sets;
  }

  function addAssetToSet(assetId, setName) {
    const entry = currentEntry();
    if (!entry || entry.content.kind !== "inline_selection") {
      showNotice("请先新建或选择一个散图投稿。", "warning");
      return;
    }
    const sets = cloneSets(entry.content.sets);
    if (!sets[setName].includes(assetId)) sets[setName].push(assetId);
    replaceCurrentInlineSets(sets);
    renderSetLists();
  }

  function removeAsset(setName, assetId) {
    const sets = cloneSets(selectedSets());
    sets[setName] = sets[setName].filter((value) => value !== assetId);
    replaceCurrentInlineSets(sets);
    renderSetLists();
  }

  function renderEditor() {
    const entry = currentEntry();
    elements.editorTitle.textContent = entry ? "编辑投稿" : "新建投稿";
    elements.entryId.value = entry?.entry_id || "";
    elements.entryTitle.value = entry?.title || "";
    if (entry) {
      const parts = localParts(entry.scheduled_at, state.plan.timezone);
      elements.entryDate.value = parts.date;
      elements.entryTime.value = parts.time;
      elements.contentKind.value = entry.content.kind;
      if (entry.content.kind === "task") {
        elements.taskSelect.value = entry.content.task_id;
        elements.taskIdInput.value = entry.content.task_id;
      }
    } else {
      elements.entryDate.value = `${state.month}-01`;
      elements.entryTime.value = "20:00";
      elements.contentKind.value = "inline_selection";
      elements.taskSelect.value = "";
      elements.taskIdInput.value = "";
    }
    const inline = elements.contentKind.value === "inline_selection";
    elements.inlineSource.classList.toggle("hidden", !inline);
    elements.taskSource.classList.toggle("hidden", inline);
    renderSetLists();
  }

  function prepareNewEntry(dateText = `${state.month}-01`) {
    state.selectedEntryId = null;
    state.draftEntry = {
      entry_id: "",
      title: "",
      scheduled_at: `${dateText}T20:00:00+08:00`,
      content: { kind: "inline_selection", source_import_id: state.filters.import_id || null, sets: { all: [], post: [], cover: [] } },
    };
    renderEditor();
    elements.entryDate.value = dateText;
    elements.entryTitle.focus();
  }

  function renderCalendar() {
    elements.calendarTitle.textContent = `${state.month} 投稿日历`;
    elements.calendarSubtitle.textContent = state.plan?.timezone || "Asia/Shanghai";
    elements.calendarGrid.innerHTML = "";
    if (!state.plan) {
      elements.calendarGrid.innerHTML = `<div class="empty-state" style="grid-column: 1 / -1">计划尚未创建</div>`;
      return;
    }
    const first = monthDate(state.month);
    const startOffset = (first.getDay() + 6) % 7;
    const days = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
    for (let index = 0; index < startOffset; index++) {
      const blank = document.createElement("div"); blank.className = "calendar-cell outside"; elements.calendarGrid.append(blank);
    }
    for (let day = 1; day <= days; day++) {
      const dateText = `${state.month}-${String(day).padStart(2, "0")}`;
      const cell = document.createElement("div");
      cell.className = "calendar-cell";
      cell.dataset.date = dateText;
      cell.addEventListener("click", () => prepareNewEntry(dateText));
      cell.addEventListener("dragover", (event) => { event.preventDefault(); cell.classList.add("drop-target"); });
      cell.addEventListener("dragleave", () => cell.classList.remove("drop-target"));
      cell.addEventListener("drop", (event) => moveEntry(event, dateText, cell));
      const label = document.createElement("div"); label.className = "date-label"; label.innerHTML = `<strong>${day}</strong><span>${weekdayText(day, first)}</span>`;
      const list = document.createElement("div"); list.className = "entry-list";
      state.plan.entries.filter((entry) => localParts(entry.scheduled_at, state.plan.timezone).date === dateText).sort((a, b) => a.scheduled_at.localeCompare(b.scheduled_at)).forEach((entry) => list.append(makeEntryCard(entry)));
      cell.append(label, list); elements.calendarGrid.append(cell);
    }
  }

  function weekdayText(day, first) { return ["一", "二", "三", "四", "五", "六", "日"][(first.getDay() + day - 2 + 7) % 7]; }

  function makeEntryCard(entry) {
    const card = document.createElement("article"); card.className = "entry-card"; card.draggable = !isLocked(); card.dataset.entryId = entry.entry_id;
    const parts = localParts(entry.scheduled_at, state.plan.timezone);
    let count = "任务";
    if (entry.content.kind === "inline_selection") count = `散图 · post ${(entry.content.sets.post || []).length}`;
    card.innerHTML = `<div class="entry-time">${escapeHtml(parts.time)}</div><div class="entry-title" title="${escapeAttr(entry.title)}">${escapeHtml(entry.title)}</div><div class="entry-meta">${count}</div>`;
    card.addEventListener("click", (event) => { event.stopPropagation(); state.selectedEntryId = entry.entry_id; renderAll(); });
    card.addEventListener("dragstart", (event) => { state.draggedEntryId = entry.entry_id; event.dataTransfer.setData("text/plain", entry.entry_id); });
    return card;
  }

  async function moveEntry(event, dateText, cell) {
    cell.classList.remove("drop-target");
    const entryId = event.dataTransfer.getData("text/plain") || state.draggedEntryId;
    if (!entryId || isLocked()) return;
    try {
      state.plan = await request(`/api/plans/${state.month}/entries/${encodeURIComponent(entryId)}/date`, { method: "PATCH", body: JSON.stringify({ revision: state.plan.revision, target_date: dateText }) });
      showNotice("投稿日期已更新。"); renderAll();
    } catch (error) { await recoverAfterMutationError(error); }
  }

  async function saveEntry(event) {
    event.preventDefault();
    if (!state.plan || isLocked()) return;
    const entryId = elements.entryId.value || `entry-${Date.now().toString(36)}`;
    const kind = elements.contentKind.value;
    let content;
    if (kind === "task") {
      const taskId = elements.taskIdInput.value.trim() || elements.taskSelect.value;
      if (!taskId) { showNotice("请选择或输入投稿任务。", "warning"); return; }
      content = { kind: "task", task_id: taskId };
    } else {
      content = { kind: "inline_selection", source_import_id: state.filters.import_id || null, sets: cloneSets(selectedSets()) };
      if (!content.sets.post.length) { showNotice("散图投稿至少需要一张 post 图片。", "warning"); return; }
    }
    const payload = { revision: state.plan.revision, entry: { entry_id: entryId, scheduled_at: fieldsToIso(elements.entryDate.value, elements.entryTime.value), title: elements.entryTitle.value.trim(), content, execution: { build_on_due: true, notify_on_complete: true, publish: false } } };
    try {
      const method = state.selectedEntryId ? "PUT" : "POST";
      const url = state.selectedEntryId ? `/api/plans/${state.month}/entries/${encodeURIComponent(entryId)}` : `/api/plans/${state.month}/entries`;
      state.plan = await request(url, { method, body: JSON.stringify(payload) });
      state.selectedEntryId = entryId;
      state.draftEntry = null;
      showNotice("投稿已保存。"); renderAll();
    } catch (error) { await recoverAfterMutationError(error); }
  }

  async function deleteEntry() {
    if (!state.selectedEntryId || !state.plan || isLocked()) return;
    if (!window.confirm("确定删除这条投稿吗？")) return;
    try {
      state.plan = await request(`/api/plans/${state.month}/entries/${encodeURIComponent(state.selectedEntryId)}?revision=${state.plan.revision}`, { method: "DELETE" });
      state.selectedEntryId = null; showNotice("投稿已删除。"); renderAll();
    } catch (error) { await recoverAfterMutationError(error); }
  }

  async function toggleLock() {
    if (!state.plan) return;
    const action = isLocked() ? "unlock" : "lock";
    try {
      state.plan = await request(`/api/plans/${state.month}/${action}`, { method: "POST", body: JSON.stringify({ revision: state.plan.revision }) });
      showNotice(isLocked() ? "计划已锁定。" : "计划已解锁。"); renderAll();
    } catch (error) { showNotice(error.message, "error"); }
  }

  async function recoverAfterMutationError(error) {
    if (error.status === 409) {
      showNotice("计划已被其他页面修改，已重新载入最新版本。", "warning");
      await loadPlan();
    } else showNotice(error.message, "error");
  }

  function renderAll() { updateControls(); renderCalendar(); renderEditor(); }

  function previewUrl(assetId) { return `/api/assets/${encodeURIComponent(assetId)}/preview`; }
  function openPreview(assetId, caption) { elements.previewImage.src = previewUrl(assetId); elements.previewCaption.textContent = caption; elements.previewDialog.showModal(); }
  function escapeHtml(value) { return String(value ?? "").replace(/[&<>\"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[char])); }
  function escapeAttr(value) { return escapeHtml(value); }

  function readFilters() {
    state.filters.import_id = elements.importSelect.value;
    state.filters.text = elements.textFilter.value.trim();
    state.filters.artist = elements.artistFilter.value.trim();
    state.filters.character = elements.characterFilter.value.trim();
    state.filters.action_group = elements.groupFilter.value.trim();
    state.filters.action = elements.actionFilter.value.trim();
  }

  function bindEvents() {
    elements.previousMonth.addEventListener("click", () => { const date = monthDate(state.month); date.setMonth(date.getMonth() - 1); state.month = formatMonth(date); loadPlan(); });
    elements.nextMonth.addEventListener("click", () => { const date = monthDate(state.month); date.setMonth(date.getMonth() + 1); state.month = formatMonth(date); loadPlan(); });
    elements.monthPicker.addEventListener("change", () => { state.month = elements.monthPicker.value; loadPlan(); });
    elements.createPlan.addEventListener("click", createPlan);
    elements.toggleLock.addEventListener("click", toggleLock);
    elements.newEntry.addEventListener("click", () => prepareNewEntry());
    elements.resetEditor.addEventListener("click", () => prepareNewEntry());
    elements.entryForm.addEventListener("submit", saveEntry);
    elements.deleteEntry.addEventListener("click", deleteEntry);
    elements.contentKind.addEventListener("change", () => {
      const entry = currentEntry();
      if (entry) {
        if (elements.contentKind.value === "task") {
          const taskId = entry.content.kind === "task" ? entry.content.task_id : "";
          entry.content = { kind: "task", task_id: taskId };
        } else {
          const sets = entry.content.kind === "inline_selection" ? entry.content.sets : { all: [], post: [], cover: [] };
          entry.content = { kind: "inline_selection", source_import_id: state.filters.import_id || null, sets: cloneSets(sets) };
        }
      }
      renderEditor();
    });
    elements.taskSelect.addEventListener("change", () => { if (elements.taskSelect.value) elements.taskIdInput.value = elements.taskSelect.value; });
    document.querySelectorAll(".set-tab").forEach((tab) => tab.addEventListener("click", () => { state.selectedSet = tab.dataset.set; document.querySelectorAll(".set-tab").forEach((item) => item.classList.toggle("active", item === tab)); renderSetLists(); }));
    elements.searchAssets.addEventListener("click", () => { readFilters(); searchAssets(); });
    [elements.textFilter, elements.artistFilter, elements.characterFilter, elements.groupFilter, elements.actionFilter].forEach((input) => input.addEventListener("keydown", (event) => { if (event.key === "Enter") { readFilters(); searchAssets(); } }));
    elements.importSelect.addEventListener("change", async () => { readFilters(); await refreshFacets(); await searchAssets(); });
    elements.clearFacets.addEventListener("click", () => { state.filters.facets = {}; renderFacets(); searchAssets(); });
    elements.facetFilters.addEventListener("change", (event) => { const input = event.target; if (!input.dataset.facetField) return; const field = input.dataset.facetField; const value = input.dataset.facetValue; const values = new Set(state.filters.facets[field] || []); input.checked ? values.add(value) : values.delete(value); if (values.size) state.filters.facets[field] = [...values]; else delete state.filters.facets[field]; searchAssets(); });
    elements.addSelectedAssets.addEventListener("click", () => { for (const assetId of state.selectedAssetIds) addAssetToSet(assetId, elements.addToSet.value); showNotice(`已加入 ${state.selectedAssetIds.size} 张素材到 ${elements.addToSet.value}。`); });
    elements.assetResults.addEventListener("change", (event) => { const input = event.target; if (!input.classList.contains("asset-check")) return; input.checked ? state.selectedAssetIds.add(input.dataset.assetId) : state.selectedAssetIds.delete(input.dataset.assetId); });
    elements.assetResults.addEventListener("click", (event) => { const trigger = event.target.closest(".preview-trigger"); if (trigger) openPreview(trigger.dataset.assetId, trigger.dataset.caption); });
    elements.closePreview.addEventListener("click", () => elements.previewDialog.close());
    elements.previewDialog.addEventListener("click", (event) => { if (event.target === elements.previewDialog) elements.previewDialog.close(); });
  }

  async function bootstrap() {
    elements.monthPicker.value = state.month;
    bindEvents();
    await Promise.all([refreshImports(), refreshTasks(), refreshFacets()]);
    await loadPlan();
  }

  bootstrap().catch((error) => showNotice(error.message, "error"));
})();
