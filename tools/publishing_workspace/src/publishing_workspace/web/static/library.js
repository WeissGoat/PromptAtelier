(function () {
  "use strict";

  const state = {
    filters: {
      import_id: "",
      text: "",
      artist: "",
      character: "",
      action_group: "",
      action: "",
      facets: {},
    },
    offset: 0,
    limit: 60,
    hasMore: true,
    loadingPage: false,
    requestToken: 0,
    loadedAssets: new Map(),
    selectedAssetIds: new Set(),

    currentSubmission: {
      task_id: null,
      title: "",
      source_import_id: null,
      revision: 1,
      sets: { all: [], post: [], cover: [] },
      currentSetTab: "all",
      legacyInlineSource: null, // { plan_id, entry_id, plan_revision }
    },

    historicalSubmissions: [],
    availableFacets: {},
    activeFacetCategory: "clothing",
    facetTagSearch: "",
    activeExportJob: null,
    exportPollTimer: null,
  };

  const FACET_LABELS = {
    clothing: "服装",
    phase: "阶段",
    subtype: "子分类",
    cast: "角色类型",
    pose: "体态姿势",
    environment: "环境背景",
    tone: "基调风格",
    flags: "标记",
    species: "物种",
    domain: "领域",
  };

  const ROLE_LABELS = {
    text: "关键词",
    artist: "画风",
    character: "角色",
    action_group: "动作组",
    action: "动作",
  };

  const elements = {
    notice: document.getElementById("notice"),
    refreshAllBtn: document.getElementById("refresh-all"),
    resetFiltersBtn: document.getElementById("reset-filters"),
    importSelect: document.getElementById("import-select"),
    textFilter: document.getElementById("text-filter"),
    searchAssetsBtn: document.getElementById("search-assets-btn"),
    artistFilter: document.getElementById("artist-filter"),
    characterFilter: document.getElementById("character-filter"),
    groupFilter: document.getElementById("group-filter"),
    actionFilter: document.getElementById("action-filter"),

    activeFilterChips: document.getElementById("active-filter-chips"),
    activeChipsList: document.getElementById("active-chips-list"),
    clearAllChips: document.getElementById("clear-all-chips"),

    facetCategoryTabs: document.getElementById("facet-category-tabs"),
    facetTagsPanel: document.getElementById("facet-tags-panel"),
    facetSearchInput: document.getElementById("facet-search-input"),
    facetChipsContainer: document.getElementById("facet-chips-container"),
    clearFacetsBtn: document.getElementById("clear-facets-btn"),

    assetCountBadge: document.getElementById("asset-count-badge"),
    selectedCountBadge: document.getElementById("selected-count-badge"),
    selectAllVisibleBtn: document.getElementById("select-all-visible-btn"),
    clearSelectionBtn: document.getElementById("clear-selection-btn"),
    addToSetBtn: document.getElementById("add-to-set-btn"),
    assetWaterfall: document.getElementById("asset-waterfall"),
    scrollSentinel: document.getElementById("scroll-sentinel"),
    loadingSpinner: document.getElementById("loading-spinner"),
    endOfResults: document.getElementById("end-of-results"),

    submissionEditorTitle: document.getElementById("submission-editor-title"),
    newSubmissionBtn: document.getElementById("new-submission-btn"),
    historySubmissionSelect: document.getElementById("history-submission-select"),
    legacyConvertBanner: document.getElementById("legacy-convert-banner"),
    submissionForm: document.getElementById("submission-form"),
    submissionTitle: document.getElementById("submission-title"),
    submissionTaskBadge: document.getElementById("submission-task-badge"),
    submissionRevBadge: document.getElementById("submission-rev-badge"),
    tabAll: document.getElementById("tab-all"),
    tabPost: document.getElementById("tab-post"),
    tabCover: document.getElementById("tab-cover"),
    badgeCountAll: document.getElementById("badge-count-all"),
    badgeCountPost: document.getElementById("badge-count-post"),
    badgeCountCover: document.getElementById("badge-count-cover"),
    setItemsContainer: document.getElementById("set-items-container"),
    saveSubmissionBtn: document.getElementById("save-submission-btn"),

    startExportBtn: document.getElementById("start-export-btn"),
    exportProgressBox: document.getElementById("export-progress-box"),
    progressBarFill: document.getElementById("progress-bar-fill"),
    progressPhase: document.getElementById("progress-phase"),
    progressPercent: document.getElementById("progress-percent"),
    progressFile: document.getElementById("progress-file"),
    exportCompletedBox: document.getElementById("export-completed-box"),
    openExportDirBtn: document.getElementById("open-export-dir-btn"),
    exportErrorBox: document.getElementById("export-error-box"),
    exportErrorText: document.getElementById("export-error-text"),

    previewDialog: document.getElementById("preview-dialog"),
    previewImage: document.getElementById("preview-image"),
    previewCaption: document.getElementById("preview-caption"),
    closePreview: document.getElementById("close-preview"),
  };

  function showNotice(message, type = "info") {
    elements.notice.textContent = message;
    elements.notice.className = `notice ${type}`;
  }

  function clearNotice() {
    elements.notice.textContent = "";
    elements.notice.className = "notice";
  }

  function escapeHtml(str) {
    if (!str) return "";
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // ================= 导入快照与 Facet 筛选 =================

  async function loadImportsList() {
    try {
      const res = await fetch("/api/imports");
      if (res.ok) {
        const data = await res.json();
        elements.importSelect.innerHTML = '<option value="">全部导入</option>';
        for (const item of data) {
          const opt = document.createElement("option");
          opt.value = item.import_id;
          opt.textContent = `${item.import_id} (${item.source_ref})`;
          elements.importSelect.appendChild(opt);
        }
      }
    } catch (err) {
      console.warn("加载导入列表失败", err);
    }
  }

  // ================= 导入快照、Facet 筛选与已生效条件 =================

  function renderActiveChips() {
    if (!elements.activeChipsList) return;
    elements.activeChipsList.innerHTML = "";
    const activeItems = [];

    if (state.filters.text) {
      activeItems.push({
        type: "text",
        label: "关键词",
        value: state.filters.text,
        clear: () => {
          state.filters.text = "";
          elements.textFilter.value = "";
          renderActiveChips();
          loadAssetPage({ reset: true });
        },
      });
    }

    for (const role of ["artist", "character", "action_group", "action"]) {
      if (state.filters[role]) {
        const inputEl = {
          artist: elements.artistFilter,
          character: elements.characterFilter,
          action_group: elements.groupFilter,
          action: elements.actionFilter,
        }[role];
        activeItems.push({
          type: "node",
          role: role,
          label: ROLE_LABELS[role] || role,
          value: state.filters[role],
          clear: () => {
            state.filters[role] = "";
            if (inputEl) {
              inputEl.value = "";
              const clearBtn = inputEl.closest(".node-picker")?.querySelector(".node-clear");
              if (clearBtn) clearBtn.hidden = true;
            }
            renderActiveChips();
            loadAssetPage({ reset: true });
          },
        });
      }
    }

    for (const [field, values] of Object.entries(state.filters.facets)) {
      for (const val of values) {
        activeItems.push({
          type: "facet",
          field: field,
          label: FACET_LABELS[field] || field,
          value: val,
          clear: () => {
            state.filters.facets[field] = state.filters.facets[field].filter((x) => x !== val);
            if (!state.filters.facets[field].length) {
              delete state.filters.facets[field];
            }
            renderFacetCategoryTabs();
            renderFacetChips();
            renderActiveChips();
            loadAssetPage({ reset: true });
          },
        });
      }
    }

    if (!activeItems.length) {
      if (elements.activeFilterChips) elements.activeFilterChips.hidden = true;
      return;
    }

    if (elements.activeFilterChips) elements.activeFilterChips.hidden = false;
    for (const item of activeItems) {
      const chip = document.createElement("span");
      chip.className = "active-chip";
      chip.innerHTML = `<span class="active-chip-role">${escapeHtml(item.label)}:</span> <strong>${escapeHtml(item.value)}</strong>`;
      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "active-chip-remove";
      removeBtn.textContent = "✕";
      removeBtn.title = "移除该筛选";
      removeBtn.addEventListener("click", item.clear);
      chip.appendChild(removeBtn);
      elements.activeChipsList.appendChild(chip);
    }
  }

  async function loadFacets() {
    try {
      const url = state.filters.import_id
        ? `/api/library/facets?import_id=${encodeURIComponent(state.filters.import_id)}`
        : "/api/library/facets";
      const res = await fetch(url);
      if (res.ok) {
        state.availableFacets = await res.json();
        const categories = Object.keys(state.availableFacets);
        if (categories.length && !categories.includes(state.activeFacetCategory)) {
          state.activeFacetCategory = categories[0];
        }
        renderFacetCategoryTabs();
        renderFacetChips();
      }
    } catch (err) {
      console.warn("加载 Facet 选项失败", err);
    }
  }

  function renderFacetCategoryTabs() {
    if (!elements.facetCategoryTabs) return;
    elements.facetCategoryTabs.innerHTML = "";
    const categories = Object.keys(state.availableFacets);
    if (!categories.length) {
      elements.facetCategoryTabs.innerHTML = '<small class="muted">无可用分类属性</small>';
      return;
    }

    let hasAnySelected = false;
    for (const cat of categories) {
      const selectedCount = (state.filters.facets[cat] || []).length;
      if (selectedCount > 0) hasAnySelected = true;

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `facet-tab-btn ${cat === state.activeFacetCategory ? "active" : ""}`;
      const name = FACET_LABELS[cat] || cat;
      const countTag = selectedCount > 0 ? `<span class="facet-tab-badge">${selectedCount}</span>` : "";
      btn.innerHTML = `${escapeHtml(name)}${countTag}`;
      btn.addEventListener("click", () => {
        state.activeFacetCategory = cat;
        state.facetTagSearch = "";
        if (elements.facetSearchInput) elements.facetSearchInput.value = "";
        renderFacetCategoryTabs();
        renderFacetChips();
      });
      elements.facetCategoryTabs.appendChild(btn);
    }

    if (elements.clearFacetsBtn) {
      elements.clearFacetsBtn.hidden = !hasAnySelected;
    }
  }

  function renderFacetChips() {
    if (!elements.facetChipsContainer) return;
    elements.facetChipsContainer.innerHTML = "";
    const cat = state.activeFacetCategory;
    if (!cat || !state.availableFacets[cat]) {
      elements.facetChipsContainer.innerHTML = '<div class="facet-empty-hint">请选择上方分类维度</div>';
      return;
    }

    const allTags = state.availableFacets[cat] || [];
    const searchNeedle = state.facetTagSearch.trim().toLowerCase();
    const filteredTags = searchNeedle
      ? allTags.filter((tag) => tag.toLowerCase().includes(searchNeedle))
      : allTags;

    if (!filteredTags.length) {
      elements.facetChipsContainer.innerHTML = `<div class="facet-empty-hint">未找到匹配 "${escapeHtml(state.facetTagSearch)}" 的标签</div>`;
      return;
    }

    const selectedList = state.filters.facets[cat] || [];
    for (const tag of filteredTags) {
      const isSelected = selectedList.includes(tag);
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = `facet-tag-chip ${isSelected ? "active" : ""}`;
      chip.innerHTML = `${isSelected ? "✓ " : ""}${escapeHtml(tag)}`;
      chip.addEventListener("click", () => {
        if (isSelected) {
          state.filters.facets[cat] = state.filters.facets[cat].filter((x) => x !== tag);
          if (!state.filters.facets[cat].length) {
            delete state.filters.facets[cat];
          }
        } else {
          if (!state.filters.facets[cat]) state.filters.facets[cat] = [];
          state.filters.facets[cat].push(tag);
        }
        renderFacetCategoryTabs();
        renderFacetChips();
        renderActiveChips();
        loadAssetPage({ reset: true });
      });
      elements.facetChipsContainer.appendChild(chip);
    }
  }

  // ================= 瀑布流素材检索与无限滚动 =================

  async function loadAssetPage({ reset = false } = {}) {
    if (state.loadingPage) return;
    if (reset) {
      state.requestToken += 1;
      state.offset = 0;
      state.hasMore = true;
      state.loadedAssets.clear();
      state.selectedAssetIds.clear();
      updateSelectionBadge();
      elements.assetWaterfall.classList.add("loading");
    }

    if (!state.hasMore) return;

    const currentToken = state.requestToken;
    state.loadingPage = true;
    elements.loadingSpinner.classList.remove("hidden");
    elements.endOfResults.classList.add("hidden");

    try {
      const params = new URLSearchParams();
      params.set("offset", String(state.offset));
      params.set("limit", String(state.limit));

      if (state.filters.import_id) params.set("import_id", state.filters.import_id);
      if (state.filters.text) params.set("text", state.filters.text);
      if (state.filters.artist) params.set("artist", state.filters.artist);
      if (state.filters.character) params.set("character", state.filters.character);
      if (state.filters.action_group) params.set("action_group", state.filters.action_group);
      if (state.filters.action) params.set("action", state.filters.action);

      const facetKeys = Object.keys(state.filters.facets);
      if (facetKeys.length) {
        const facetsPayload = {};
        for (const k of facetKeys) {
          if (state.filters.facets[k].length) {
            facetsPayload[k] = state.filters.facets[k];
          }
        }
        if (Object.keys(facetsPayload).length) {
          params.set("facets", JSON.stringify(facetsPayload));
        }
      }

      const res = await fetch(`/api/library/assets?${params.toString()}`);
      if (!res.ok) {
        throw new Error(`加载素材失败 (${res.status})`);
      }

      const page = await res.json();
      if (currentToken !== state.requestToken) {
        // 请求过期，丢弃
        return;
      }

      state.hasMore = page.has_more;
      state.offset = page.next_offset !== null ? page.next_offset : state.offset + page.items.length;

      if (elements.assetCountBadge) {
        elements.assetCountBadge.textContent = page.total !== undefined ? `(共 ${page.total.toLocaleString()} 张)` : "";
      }
      renderActiveChips();

      if (reset) {
        elements.assetWaterfall.innerHTML = "";
      }

      for (const item of page.items) {
        if (!state.loadedAssets.has(item.asset_id)) {
          state.loadedAssets.set(item.asset_id, item);
          renderAssetCard(item);
        }
      }

      if (!state.loadedAssets.size) {
        elements.assetWaterfall.innerHTML = '<div class="helper-text" style="grid-column: 1 / -1; padding: 40px 20px; text-align: center;">没有找到符合当前筛选条件的素材</div>';
      }

      if (!state.hasMore && state.loadedAssets.size > 0) {
        elements.endOfResults.classList.remove("hidden");
      }
    } catch (err) {
      showNotice(err.message, "error");
    } finally {
      state.loadingPage = false;
      elements.loadingSpinner.classList.add("hidden");
      elements.assetWaterfall.classList.remove("loading");
    }
  }

  function renderAssetCard(item) {
    const card = document.createElement("div");
    card.className = "asset-card";
    card.dataset.assetId = item.asset_id;
    if (state.selectedAssetIds.has(item.asset_id)) {
      card.classList.add("selected");
    }

    const ratio = item.width && item.height ? `${item.width} / ${item.height}` : "1 / 1";
    const previewUrl = `/api/assets/${encodeURIComponent(item.asset_id)}/preview`;

    card.innerHTML = `
      <div class="asset-thumb-wrap" style="aspect-ratio: ${ratio};">
        <input type="checkbox" class="asset-checkbox" ${state.selectedAssetIds.has(item.asset_id) ? "checked" : ""}>
        <img class="asset-thumb" loading="lazy" src="${previewUrl}" alt="${escapeHtml(item.display_name)}">
      </div>
      <div class="asset-info">
        <div class="asset-name" title="${escapeHtml(item.display_name)}">${escapeHtml(item.display_name)}</div>
        <div class="asset-dims">${item.width || 0} × ${item.height || 0} (${item.image_format || "PNG"})</div>
      </div>
    `;

    const checkbox = card.querySelector(".asset-checkbox");

    checkbox.addEventListener("change", (e) => {
      e.stopPropagation();
      toggleAssetSelection(item.asset_id, checkbox.checked);
    });

    card.addEventListener("click", () => {
      const newState = !state.selectedAssetIds.has(item.asset_id);
      checkbox.checked = newState;
      toggleAssetSelection(item.asset_id, newState);
    });

    // 双击打开大图预览
    card.addEventListener("dblclick", () => {
      openPreview(previewUrl, item.display_name);
    });

    elements.assetWaterfall.appendChild(card);
  }

  function toggleAssetSelection(assetId, isSelected) {
    if (isSelected) {
      state.selectedAssetIds.add(assetId);
    } else {
      state.selectedAssetIds.delete(assetId);
    }
    const card = elements.assetWaterfall.querySelector(`[data-asset-id="${assetId}"]`);
    if (card) {
      card.classList.toggle("selected", isSelected);
    }
    updateSelectionBadge();
  }

  function updateSelectionBadge() {
    elements.selectedCountBadge.textContent = `已选 ${state.selectedAssetIds.size} 项`;
  }

  function openPreview(src, title) {
    elements.previewImage.src = src;
    elements.previewCaption.textContent = title || "";
    elements.previewDialog.showModal();
  }

  // ================= Submission 编辑器 =================

  async function loadHistoricalSubmissions() {
    try {
      const res = await fetch("/api/submissions");
      if (res.ok) {
        state.historicalSubmissions = await res.json();
        elements.historySubmissionSelect.innerHTML = '<option value="">-- 选择历史投稿进行编辑 --</option>';
        for (const sub of state.historicalSubmissions) {
          const opt = document.createElement("option");
          opt.value = sub.task_id;
          const postCount = sub.counts && typeof sub.counts.post === "number" ? ` (${sub.counts.post}图)` : "";
          opt.textContent = `${sub.title || sub.task_id}${postCount}`;
          elements.historySubmissionSelect.appendChild(opt);
        }
      }
    } catch (err) {
      console.warn("加载历史投稿列表失败", err);
    }
  }

  async function loadSubmissionDetail(taskId) {
    clearNotice();
    try {
      const res = await fetch(`/api/submissions/${encodeURIComponent(taskId)}`);
      if (!res.ok) {
        throw new Error(`加载投稿详情失败 (${res.status})`);
      }
      const data = await res.json();
      state.currentSubmission = {
        task_id: data.task_id,
        title: data.title || "",
        source_import_id: data.source_import_id || null,
        revision: data.revision || 1,
        sets: {
          all: data.sets?.all || [],
          post: data.sets?.post || [],
          cover: data.sets?.cover || [],
        },
        currentSetTab: "all",
        legacyInlineSource: null,
      };
      elements.legacyConvertBanner.classList.add("hidden");
      syncSubmissionFormUI();
      checkLastExportForTask(taskId);
    } catch (err) {
      showNotice(err.message, "error");
    }
  }

  function resetSubmissionEditor() {
    state.currentSubmission = {
      task_id: null,
      title: "",
      source_import_id: state.filters.import_id || null,
      revision: 1,
      sets: { all: [], post: [], cover: [] },
      currentSetTab: "all",
      legacyInlineSource: null,
    };
    elements.legacyConvertBanner.classList.add("hidden");
    elements.historySubmissionSelect.value = "";
    syncSubmissionFormUI();
    resetExportUI();
  }

  function syncSubmissionFormUI() {
    const sub = state.currentSubmission;
    elements.submissionEditorTitle.textContent = sub.task_id ? "编辑投稿" : "新建投稿";
    elements.submissionTitle.value = sub.title;
    elements.submissionTaskBadge.textContent = sub.task_id ? sub.task_id : "未生成任务";
    elements.submissionRevBadge.textContent = `Rev ${sub.revision}`;

    // 更新 Tab 按钮与角标
    elements.badgeCountAll.textContent = String(sub.sets.all.length);
    elements.badgeCountPost.textContent = String(sub.sets.post.length);
    elements.badgeCountCover.textContent = String(sub.sets.cover.length);

    elements.tabAll.classList.toggle("active", sub.currentSetTab === "all");
    elements.tabPost.classList.toggle("active", sub.currentSetTab === "post");
    elements.tabCover.classList.toggle("active", sub.currentSetTab === "cover");

    elements.startExportBtn.disabled = !sub.task_id;

    renderSetItems();
  }

  function renderSetItems() {
    elements.setItemsContainer.innerHTML = "";
    const activeSet = state.currentSubmission.currentSetTab;
    const assetIds = state.currentSubmission.sets[activeSet] || [];

    if (!assetIds.length) {
      elements.setItemsContainer.innerHTML = '<div class="helper-text" style="padding:10px;text-align:center;">当前集合为空，可从中间素材列表勾选后点击“加入当前集合”</div>';
      return;
    }

    for (let index = 0; index < assetIds.length; index++) {
      const assetId = assetIds[index];
      const asset = state.loadedAssets.get(assetId);
      const displayName = asset ? asset.display_name : assetId;
      const previewUrl = `/api/assets/${encodeURIComponent(assetId)}/preview`;

      const row = document.createElement("div");
      row.className = "set-item-row";
      row.innerHTML = `
        <img class="set-item-thumb" src="${previewUrl}" alt="thumb" loading="lazy">
        <span class="set-item-title" title="${escapeHtml(displayName)}">${escapeHtml(displayName)}</span>
      `;

      const actionsWrap = document.createElement("div");
      actionsWrap.style.display = "flex";
      actionsWrap.style.alignItems = "center";
      actionsWrap.style.gap = "2px";

      if (index > 0) {
        const upBtn = document.createElement("button");
        upBtn.className = "set-item-remove";
        upBtn.type = "button";
        upBtn.textContent = "↑";
        upBtn.title = "上移";
        upBtn.addEventListener("click", () => {
          const item = state.currentSubmission.sets[activeSet].splice(index, 1)[0];
          state.currentSubmission.sets[activeSet].splice(index - 1, 0, item);
          syncSubmissionFormUI();
        });
        actionsWrap.appendChild(upBtn);
      }

      if (index < assetIds.length - 1) {
        const downBtn = document.createElement("button");
        downBtn.className = "set-item-remove";
        downBtn.type = "button";
        downBtn.textContent = "↓";
        downBtn.title = "下移";
        downBtn.addEventListener("click", () => {
          const item = state.currentSubmission.sets[activeSet].splice(index, 1)[0];
          state.currentSubmission.sets[activeSet].splice(index + 1, 0, item);
          syncSubmissionFormUI();
        });
        actionsWrap.appendChild(downBtn);
      }

      const removeBtn = document.createElement("button");
      removeBtn.className = "set-item-remove";
      removeBtn.type = "button";
      removeBtn.textContent = "✕";
      removeBtn.title = "从当前集合移除";
      removeBtn.addEventListener("click", () => {
        state.currentSubmission.sets[activeSet].splice(index, 1);
        syncSubmissionFormUI();
      });
      actionsWrap.appendChild(removeBtn);

      row.appendChild(actionsWrap);
      elements.setItemsContainer.appendChild(row);
    }
  }

  async function handleSubmissionSubmit(e) {
    e.preventDefault();
    clearNotice();

    const sub = state.currentSubmission;
    const title = elements.submissionTitle.value.trim();
    if (!title) {
      showNotice("投稿标题不能为空", "warning");
      return;
    }
    if (!sub.sets.all.length) {
      showNotice("all 集合不能为空", "warning");
      return;
    }

    const payload = {
      title: title,
      source_import_id: sub.source_import_id || state.filters.import_id || null,
      sets: sub.sets,
      revision: sub.task_id ? sub.revision : null,
    };

    try {
      let res;
      if (sub.task_id) {
        res = await fetch(`/api/submissions/${encodeURIComponent(sub.task_id)}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
      } else {
        res = await fetch("/api/submissions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
      }

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        if (res.status === 409) {
          throw new Error("投稿版本已发生变化（revision 冲突），请刷新后重试。");
        }
        throw new Error(errData.detail?.message || `保存投稿失败 (${res.status})`);
      }

      const savedData = await res.json();
      showNotice(`投稿保存成功！任务 ID：${savedData.task_id}`, "info");

      // 如果来自旧计划散图转换，保存后关联回月度计划
      if (sub.legacyInlineSource) {
        await associateTaskToMonthlyPlan(savedData.task_id, sub.legacyInlineSource);
        sub.legacyInlineSource = null;
        elements.legacyConvertBanner.classList.add("hidden");
      }

      state.currentSubmission = {
        task_id: savedData.task_id,
        title: savedData.title,
        source_import_id: savedData.source_import_id,
        revision: savedData.revision,
        sets: savedData.sets,
        currentSetTab: sub.currentSetTab,
        legacyInlineSource: null,
      };

      syncSubmissionFormUI();
      loadHistoricalSubmissions();
    } catch (err) {
      showNotice(err.message, "error");
    }
  }

  async function associateTaskToMonthlyPlan(taskId, legacySource) {
    try {
      const { plan_id, entry_id, plan_revision } = legacySource;
      const planRes = await fetch(`/api/plans/${encodeURIComponent(plan_id)}`);
      if (!planRes.ok) return;
      const plan = await planRes.json();
      const entry = (plan.entries || []).find((e) => e.entry_id === entry_id);
      if (!entry) return;

      const updatePayload = {
        revision: plan_revision || plan.revision,
        entry: {
          entry_id: entry.entry_id,
          scheduled_at: entry.scheduled_at,
          title: entry.title,
          content: { kind: "task", task_id: taskId },
        },
      };

      const putRes = await fetch(
        `/api/plans/${encodeURIComponent(plan_id)}/entries/${encodeURIComponent(entry_id)}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(updatePayload),
        }
      );
      if (putRes.ok) {
        showNotice(`已将任务 ${taskId} 关联至月计划 ${plan_id}`, "info");
      }
    } catch (err) {
      console.warn("关联月计划失败", err);
    }
  }

  // ================= 导出发布包流程 =================

  function resetExportUI() {
    elements.startExportBtn.disabled = !state.currentSubmission.task_id;
    elements.exportProgressBox.classList.add("hidden");
    elements.exportCompletedBox.classList.add("hidden");
    elements.exportErrorBox.classList.add("hidden");
    if (state.exportPollTimer) {
      clearInterval(state.exportPollTimer);
      state.exportPollTimer = null;
    }
  }

  async function checkLastExportForTask(taskId) {
    resetExportUI();
    try {
      const res = await fetch(`/api/submissions/${encodeURIComponent(taskId)}/exports`);
      if (res.ok) {
        const jobs = await res.json();
        if (jobs && jobs.length > 0) {
          const latest = jobs[0];
          handleExportJobUpdate(latest);
        }
      }
    } catch (err) {
      // 忽略导出任务不存在
    }
  }

  async function handleStartExport() {
    const taskId = state.currentSubmission.task_id;
    if (!taskId) return;
    clearNotice();
    resetExportUI();

    try {
      const res = await fetch(`/api/submissions/${encodeURIComponent(taskId)}/exports`, {
        method: "POST",
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail?.message || `启动导出失败 (${res.status})`);
      }
      const job = await res.json();
      handleExportJobUpdate(job);
    } catch (err) {
      showNotice(err.message, "error");
    }
  }

  function handleExportJobUpdate(job) {
    state.activeExportJob = job;

    if (job.status === "queued" || job.status === "running") {
      elements.exportProgressBox.classList.remove("hidden");
      elements.exportCompletedBox.classList.add("hidden");
      elements.exportErrorBox.classList.add("hidden");
      elements.startExportBtn.disabled = true;

      elements.progressBarFill.style.width = `${job.percent || 0}%`;
      elements.progressPhase.textContent = `阶段: ${job.phase || job.status} (${job.processed || 0}/${job.total || 0})`;
      elements.progressPercent.textContent = `${job.percent || 0}%`;
      elements.progressFile.textContent = job.current_filename || "";

      if (!state.exportPollTimer) {
        state.exportPollTimer = setInterval(pollActiveExport, 1000);
      }
    } else if (job.status === "completed") {
      if (state.exportPollTimer) {
        clearInterval(state.exportPollTimer);
        state.exportPollTimer = null;
      }
      elements.exportProgressBox.classList.add("hidden");
      elements.exportCompletedBox.classList.remove("hidden");
      elements.exportErrorBox.classList.add("hidden");
      elements.startExportBtn.disabled = false;
    } else if (job.status === "failed" || job.status === "interrupted") {
      if (state.exportPollTimer) {
        clearInterval(state.exportPollTimer);
        state.exportPollTimer = null;
      }
      elements.exportProgressBox.classList.add("hidden");
      elements.exportCompletedBox.classList.add("hidden");
      elements.exportErrorBox.classList.remove("hidden");
      elements.exportErrorText.textContent = `导出失败: ${job.error || "任务中断"}`;
      elements.startExportBtn.disabled = false;
    }
  }

  async function pollActiveExport() {
    if (!state.activeExportJob?.job_id) return;
    try {
      const res = await fetch(`/api/export-jobs/${encodeURIComponent(state.activeExportJob.job_id)}`);
      if (res.ok) {
        const job = await res.json();
        handleExportJobUpdate(job);
      }
    } catch (err) {
      console.warn("轮询导出状态失败", err);
    }
  }

  async function handleOpenExportDir() {
    if (!state.activeExportJob?.job_id) return;
    try {
      const res = await fetch(`/api/export-jobs/${encodeURIComponent(state.activeExportJob.job_id)}/open-output`, {
        method: "POST",
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail?.message || `打开目录失败 (${res.status})`);
      }
    } catch (err) {
      showNotice(err.message, "error");
    }
  }

  // ================= 页面初始化与 URL 参数处理 =================

  async function initFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const submissionId = params.get("submission_id");
    const planId = params.get("plan_id");
    const entryId = params.get("entry_id");

    if (submissionId) {
      await loadSubmissionDetail(submissionId);
    } else if (planId && entryId) {
      await loadLegacyInlineFromPlan(planId, entryId);
    }
  }

  async function loadLegacyInlineFromPlan(planId, entryId) {
    try {
      const res = await fetch(`/api/plans/${encodeURIComponent(planId)}`);
      if (res.ok) {
        const plan = await res.json();
        const entry = (plan.entries || []).find((e) => e.entry_id === entryId);
        if (entry && entry.content?.kind === "inline_selection") {
          state.currentSubmission = {
            task_id: null,
            title: entry.title || "从计划导入的散图",
            source_import_id: entry.content.source_import_id || null,
            revision: 1,
            sets: {
              all: entry.content.sets?.all || [],
              post: entry.content.sets?.post || [],
              cover: entry.content.sets?.cover || [],
            },
            currentSetTab: "all",
            legacyInlineSource: {
              plan_id: planId,
              entry_id: entryId,
              plan_revision: plan.revision,
            },
          };
          elements.legacyConvertBanner.classList.remove("hidden");
          syncSubmissionFormUI();
        }
      }
    } catch (err) {
      console.warn("从计划加载散图失败", err);
    }
  }

  // ================= 事件绑定 =================

  elements.importSelect.addEventListener("change", (e) => {
    state.filters.import_id = e.target.value;
    loadFacets();
    loadAssetPage({ reset: true });
  });

  function applyTextSearch() {
    const val = elements.textFilter.value.trim();
    if (state.filters.text !== val) {
      state.filters.text = val;
      renderActiveChips();
      loadAssetPage({ reset: true });
    }
  }

  elements.textFilter.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      applyTextSearch();
    }
  });

  elements.searchAssetsBtn.addEventListener("click", applyTextSearch);

  elements.resetFiltersBtn.addEventListener("click", () => {
    state.filters = {
      import_id: "",
      text: "",
      artist: "",
      character: "",
      action_group: "",
      action: "",
      facets: {},
    };
    elements.importSelect.value = "";
    elements.textFilter.value = "";
    elements.artistFilter.value = "";
    elements.characterFilter.value = "";
    elements.groupFilter.value = "";
    elements.actionFilter.value = "";
    document.querySelectorAll(".node-clear").forEach((btn) => (btn.hidden = true));
    renderFacetCategoryTabs();
    renderFacetChips();
    renderActiveChips();
    loadAssetPage({ reset: true });
  });

  if (elements.clearAllChips) {
    elements.clearAllChips.addEventListener("click", () => {
      elements.resetFiltersBtn.click();
    });
  }

  if (elements.clearFacetsBtn) {
    elements.clearFacetsBtn.addEventListener("click", () => {
      state.filters.facets = {};
      renderFacetCategoryTabs();
      renderFacetChips();
      renderActiveChips();
      loadAssetPage({ reset: true });
    });
  }

  if (elements.facetSearchInput) {
    elements.facetSearchInput.addEventListener("input", (e) => {
      state.facetTagSearch = e.target.value;
      renderFacetChips();
    });
  }

  // 全选 / 清选 / 加入集合
  elements.selectAllVisibleBtn.addEventListener("click", () => {
    for (const [id] of state.loadedAssets) {
      state.selectedAssetIds.add(id);
    }
    const cards = elements.assetWaterfall.querySelectorAll(".asset-card");
    cards.forEach((c) => {
      c.classList.add("selected");
      const cb = c.querySelector(".asset-checkbox");
      if (cb) cb.checked = true;
    });
    updateSelectionBadge();
  });

  elements.clearSelectionBtn.addEventListener("click", () => {
    state.selectedAssetIds.clear();
    const cards = elements.assetWaterfall.querySelectorAll(".asset-card");
    cards.forEach((c) => {
      c.classList.remove("selected");
      const cb = c.querySelector(".asset-checkbox");
      if (cb) cb.checked = false;
    });
    updateSelectionBadge();
  });

  elements.addToSetBtn.addEventListener("click", () => {
    if (!state.selectedAssetIds.size) {
      showNotice("请先勾选需要加入的素材", "warning");
      return;
    }
    const activeSet = state.currentSubmission.currentSetTab;
    const currentList = state.currentSubmission.sets[activeSet];
    for (const id of state.selectedAssetIds) {
      if (!currentList.includes(id)) {
        currentList.push(id);
      }
    }
    showNotice(`已将 ${state.selectedAssetIds.size} 项素材加入 ${activeSet} 集合`, "info");
    syncSubmissionFormUI();
  });

  // 集合 Tab 切换
  elements.tabAll.addEventListener("click", () => {
    state.currentSubmission.currentSetTab = "all";
    syncSubmissionFormUI();
  });
  elements.tabPost.addEventListener("click", () => {
    state.currentSubmission.currentSetTab = "post";
    syncSubmissionFormUI();
  });
  elements.tabCover.addEventListener("click", () => {
    state.currentSubmission.currentSetTab = "cover";
    syncSubmissionFormUI();
  });

  elements.newSubmissionBtn.addEventListener("click", () => {
    resetSubmissionEditor();
  });

  elements.historySubmissionSelect.addEventListener("change", (e) => {
    if (e.target.value) {
      loadSubmissionDetail(e.target.value);
    }
  });

  elements.submissionForm.addEventListener("submit", handleSubmissionSubmit);

  elements.startExportBtn.addEventListener("click", handleStartExport);
  elements.openExportDirBtn.addEventListener("click", handleOpenExportDir);

  elements.refreshAllBtn.addEventListener("click", () => {
    loadImportsList();
    loadFacets();
    loadHistoricalSubmissions();
    loadAssetPage({ reset: true });
  });

  elements.closePreview.addEventListener("click", () => {
    elements.previewDialog.close();
  });

  // 节点选择器绑定 (支持聚焦浏览、实时防抖、键盘导航)
  function bindNodePicker(role, inputEl, clearEl) {
    const picker = inputEl.closest(".node-picker");
    const optionsEl = picker.querySelector(".node-options");

    function updateClearButton() {
      if (clearEl) {
        clearEl.hidden = !inputEl.value.trim();
      }
    }

    let keyboardIndex = -1;

    async function fetchAndShowOptions(query = "") {
      try {
        const importParam = state.filters.import_id ? `&import_id=${encodeURIComponent(state.filters.import_id)}` : "";
        const res = await fetch(`/api/nodes?role=${role}&q=${encodeURIComponent(query)}&limit=30${importParam}`);
        if (res.ok) {
          const data = await res.json();
          optionsEl.innerHTML = "";
          keyboardIndex = -1;
          if (data.nodes?.length) {
            const header = document.createElement("div");
            header.className = "node-options-header";
            header.textContent = query ? `匹配到 ${data.nodes.length} 个候选` : `可选 / 推荐候选 (${data.nodes.length})`;
            optionsEl.appendChild(header);

            data.nodes.forEach((n, idx) => {
              const val = n.name || n.value || "";
              const optBtn = document.createElement("button");
              optBtn.type = "button";
              optBtn.className = "node-option";
              optBtn.dataset.index = idx;
              optBtn.innerHTML = `<strong>${escapeHtml(val)}</strong><span class="node-option-ref">${escapeHtml(n.ref || "")}</span>`;
              optBtn.addEventListener("click", () => {
                inputEl.value = val;
                state.filters[role] = val;
                updateClearButton();
                optionsEl.classList.remove("open");
                renderActiveChips();
                loadAssetPage({ reset: true });
              });
              optionsEl.appendChild(optBtn);
            });
            optionsEl.classList.add("open");
          } else {
            optionsEl.innerHTML = '<div class="node-options-empty">无匹配节点（回车应用自由文本）</div>';
            optionsEl.classList.add("open");
          }
        }
      } catch (err) {
        console.warn("节点搜索失败", err);
      }
    }

    // 聚焦或点击时直接弹出候选项列表
    inputEl.addEventListener("focus", () => {
      fetchAndShowOptions(inputEl.value.trim());
    });
    inputEl.addEventListener("click", () => {
      if (!optionsEl.classList.contains("open")) {
        fetchAndShowOptions(inputEl.value.trim());
      }
    });

    let timer = null;
    inputEl.addEventListener("input", () => {
      updateClearButton();
      clearTimeout(timer);
      timer = setTimeout(() => {
        const query = inputEl.value.trim();
        if (!query) {
          if (state.filters[role] !== "") {
            state.filters[role] = "";
            renderActiveChips();
            loadAssetPage({ reset: true });
          }
        }
        fetchAndShowOptions(query);
      }, 100);
    });

    inputEl.addEventListener("keydown", (e) => {
      const items = optionsEl.querySelectorAll(".node-option");
      if (e.key === "ArrowDown") {
        e.preventDefault();
        if (!optionsEl.classList.contains("open")) {
          fetchAndShowOptions(inputEl.value.trim());
          return;
        }
        if (items.length) {
          keyboardIndex = (keyboardIndex + 1) % items.length;
          items.forEach((item, idx) => {
            item.classList.toggle("keyboard-active", idx === keyboardIndex);
          });
          items[keyboardIndex]?.scrollIntoView({ block: "nearest" });
        }
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        if (items.length) {
          keyboardIndex = (keyboardIndex - 1 + items.length) % items.length;
          items.forEach((item, idx) => {
            item.classList.toggle("keyboard-active", idx === keyboardIndex);
          });
          items[keyboardIndex]?.scrollIntoView({ block: "nearest" });
        }
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (keyboardIndex >= 0 && items[keyboardIndex]) {
          items[keyboardIndex].click();
        } else {
          optionsEl.classList.remove("open");
          const query = inputEl.value.trim();
          if (state.filters[role] !== query) {
            state.filters[role] = query;
            updateClearButton();
            renderActiveChips();
            loadAssetPage({ reset: true });
          }
        }
      } else if (e.key === "Escape") {
        optionsEl.classList.remove("open");
      }
    });

    clearEl.addEventListener("click", () => {
      inputEl.value = "";
      updateClearButton();
      optionsEl.classList.remove("open");
      if (state.filters[role] !== "") {
        state.filters[role] = "";
        renderActiveChips();
        loadAssetPage({ reset: true });
      }
    });

    document.addEventListener("click", (e) => {
      if (!picker.contains(e.target)) {
        optionsEl.classList.remove("open");
      }
    });

    updateClearButton();
  }

  bindNodePicker("artist", elements.artistFilter, document.querySelector('[data-node-role="artist"] .node-clear'));
  bindNodePicker("character", elements.characterFilter, document.querySelector('[data-node-role="character"] .node-clear'));
  bindNodePicker("action_group", elements.groupFilter, document.querySelector('[data-node-role="action_group"] .node-clear'));
  bindNodePicker("action", elements.actionFilter, document.querySelector('[data-node-role="action"] .node-clear'));

  // 无限滚动 IntersectionObserver
  const observer = new IntersectionObserver((entries) => {
    if (entries[0].isIntersecting && state.hasMore && !state.loadingPage) {
      loadAssetPage();
    }
  }, { rootMargin: "200px" });

  observer.observe(elements.scrollSentinel);

  // 初始化加载
  loadImportsList();
  loadFacets();
  loadHistoricalSubmissions();
  loadAssetPage({ reset: true });
  initFromUrl();
})();
