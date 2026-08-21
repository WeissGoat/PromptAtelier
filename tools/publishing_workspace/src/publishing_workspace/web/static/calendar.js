(function () {
  "use strict";

  const state = {
    month: "",
    plan: null,
    submissions: [],
    selectedEntryId: null,
    draggedEntryId: null,
  };

  const elements = {
    monthPicker: document.getElementById("month-picker"),
    prevMonth: document.getElementById("previous-month"),
    nextMonth: document.getElementById("next-month"),
    planStatus: document.getElementById("plan-status"),
    notice: document.getElementById("notice"),
    calendarTitle: document.getElementById("calendar-title"),
    calendarSubtitle: document.getElementById("calendar-subtitle"),
    calendarGrid: document.getElementById("calendar-grid"),
    newEntryBtn: document.getElementById("new-entry"),
    editorTitle: document.getElementById("editor-title"),
    resetEditorBtn: document.getElementById("reset-editor"),
    entryForm: document.getElementById("entry-form"),
    entryId: document.getElementById("entry-id"),
    entryTitle: document.getElementById("entry-title"),
    entryDate: document.getElementById("entry-date"),
    entryTime: document.getElementById("entry-time"),
    taskSelect: document.getElementById("task-select"),
    legacyNotice: document.getElementById("legacy-notice"),
    convertLegacyLink: document.getElementById("convert-legacy-link"),
    taskLinkBox: document.getElementById("task-link-box"),
    gotoLibraryLink: document.getElementById("goto-library-link"),
    saveEntryBtn: document.getElementById("save-entry"),
    deleteEntryBtn: document.getElementById("delete-entry"),
  };

  function showNotice(message, type = "info") {
    elements.notice.textContent = message;
    elements.notice.className = `notice ${type}`;
  }

  function clearNotice() {
    elements.notice.textContent = "";
    elements.notice.className = "notice";
  }

  function getQueryMonth() {
    const params = new URLSearchParams(window.location.search);
    const month = params.get("month");
    if (month && /^\d{4}-(0[1-9]|1[0-2])$/.test(month)) {
      return month;
    }
    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, "0");
    return `${y}-${m}`;
  }

  function shiftMonth(monthStr, offset) {
    const [yStr, mStr] = monthStr.split("-");
    let y = parseInt(yStr, 10);
    let m = parseInt(mStr, 10) + offset;
    while (m > 12) {
      m -= 12;
      y += 1;
    }
    while (m < 1) {
      m += 12;
      y -= 1;
    }
    return `${y}-${String(m).padStart(2, "0")}`;
  }

  async function loadSubmissionsList() {
    try {
      const res = await fetch("/api/submissions");
      if (res.ok) {
        state.submissions = await res.json();
        updateTaskOptions();
      }
    } catch (err) {
      console.warn("加载投稿列表失败", err);
    }
  }

  function updateTaskOptions() {
    const currentVal = elements.taskSelect.value;
    elements.taskSelect.innerHTML = '<option value="">-- 选择已有投稿任务 --</option>';
    for (const sub of state.submissions) {
      const opt = document.createElement("option");
      opt.value = sub.task_id;
      const count = sub.counts && typeof sub.counts.post === "number" ? ` (${sub.counts.post}图)` : "";
      opt.textContent = `${sub.title || sub.task_id}${count}`;
      elements.taskSelect.appendChild(opt);
    }
    if (currentVal) {
      elements.taskSelect.value = currentVal;
    }
  }

  async function loadPlan(month) {
    state.month = month;
    elements.monthPicker.value = month;
    elements.calendarTitle.textContent = `${month} 投稿排期`;
    elements.newEntryBtn.disabled = true;
    clearNotice();

    try {
      const res = await fetch(`/api/plans/${month}`);
      if (!res.ok) {
        throw new Error(`加载计划失败 (${res.status})`);
      }
      state.plan = await res.json();
      elements.calendarSubtitle.textContent = state.plan.timezone || "Asia/Shanghai";
      elements.planStatus.textContent = state.plan.status === "locked" ? "已锁定" : "草稿";
      elements.planStatus.className = `status-badge ${state.plan.status === "locked" ? "locked" : ""}`;
      elements.newEntryBtn.disabled = state.plan.status === "locked";
      renderCalendarGrid();
      resetEditor();
    } catch (err) {
      showNotice(err.message, "error");
    }
  }

  function renderCalendarGrid() {
    elements.calendarGrid.innerHTML = "";
    if (!state.plan) return;

    const [yearStr, monthStr] = state.month.split("-");
    const year = parseInt(yearStr, 10);
    const month = parseInt(monthStr, 10);

    const firstDay = new Date(year, month - 1, 1);
    let startDayOfWeek = firstDay.getDay() - 1; // 0 = Monday
    if (startDayOfWeek === -1) startDayOfWeek = 6; // Sunday

    const daysInMonth = new Date(year, month, 0).getDate();
    const daysInPrevMonth = new Date(year, month - 1, 0).getDate();

    const todayStr = new Date().toISOString().slice(0, 10);

    // 填充上月末尾几天
    for (let i = startDayOfWeek - 1; i >= 0; i--) {
      const cell = document.createElement("div");
      cell.className = "calendar-cell other-month";
      const dayNum = daysInPrevMonth - i;
      cell.innerHTML = `<div class="cell-header"><span class="cell-day">${dayNum}</span></div>`;
      elements.calendarGrid.appendChild(cell);
    }

    // 填充当月每天
    for (let day = 1; day <= daysInMonth; day++) {
      const dayStr = String(day).padStart(2, "0");
      const dateStr = `${state.month}-${dayStr}`;
      const cell = document.createElement("div");
      cell.className = "calendar-cell";
      if (dateStr === todayStr) {
        cell.classList.add("today");
      }
      cell.dataset.date = dateStr;

      cell.innerHTML = `<div class="cell-header"><span class="cell-day">${day}</span></div><div class="cell-entries"></div>`;

      // 拖拽目的地事件
      cell.addEventListener("dragover", (e) => {
        if (state.draggedEntryId && state.plan.status !== "locked") {
          e.preventDefault();
          cell.classList.add("drag-over");
        }
      });
      cell.addEventListener("dragleave", () => {
        cell.classList.remove("drag-over");
      });
      cell.addEventListener("drop", (e) => {
        e.preventDefault();
        cell.classList.remove("drag-over");
        if (state.draggedEntryId && state.plan.status !== "locked") {
          handleEntryMove(state.draggedEntryId, dateStr);
        }
      });

      // 双击单元格新建排期
      cell.addEventListener("dblclick", () => {
        if (state.plan.status !== "locked") {
          openNewEntryForDate(dateStr);
        }
      });

      const entriesContainer = cell.querySelector(".cell-entries");
      const dayEntries = (state.plan.entries || []).filter((e) => {
        return e.scheduled_at && e.scheduled_at.startsWith(dateStr);
      });

      for (const entry of dayEntries) {
        const card = createEntryCard(entry);
        entriesContainer.appendChild(card);
      }

      elements.calendarGrid.appendChild(cell);
    }
  }

  function createEntryCard(entry) {
    const card = document.createElement("div");
    card.className = "entry-card";
    if (state.selectedEntryId === entry.entry_id) {
      card.classList.add("selected");
    }
    card.draggable = state.plan.status !== "locked";

    const isTask = entry.content && entry.content.kind === "task";
    const isInline = entry.content && entry.content.kind === "inline_selection";

    let badgeText = isTask ? "task" : "散图";
    let badgeClass = isInline ? "entry-badge legacy" : "entry-badge";

    let timeStr = "";
    if (entry.scheduled_at) {
      const match = entry.scheduled_at.match(/T(\d{2}:\d{2})/);
      if (match) timeStr = match[1];
    }

    card.innerHTML = `
      <div class="entry-card-title">${escapeHtml(entry.title)}</div>
      <div class="entry-card-meta">
        <span class="entry-card-time">${timeStr}</span>
        <span class="${badgeClass}">${badgeText}</span>
      </div>
    `;

    card.addEventListener("dragstart", (e) => {
      state.draggedEntryId = entry.entry_id;
      e.dataTransfer.setData("text/plain", entry.entry_id);
    });
    card.addEventListener("dragend", () => {
      state.draggedEntryId = null;
    });

    card.addEventListener("click", (e) => {
      e.stopPropagation();
      selectEntry(entry);
    });

    return card;
  }

  function escapeHtml(str) {
    if (!str) return "";
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function handleEntryMove(entryId, targetDate) {
    if (!state.plan) return;
    clearNotice();

    try {
      const res = await fetch(`/api/plans/${state.month}/entries/${entryId}/date`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          revision: state.plan.revision,
          target_date: targetDate,
        }),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail?.message || `移动日期失败 (${res.status})`);
      }
      state.plan = await res.json();
      showNotice(`已将排期移动至 ${targetDate}`, "info");
      renderCalendarGrid();
      if (state.selectedEntryId === entryId) {
        const updated = (state.plan.entries || []).find((e) => e.entry_id === entryId);
        if (updated) selectEntry(updated);
      }
    } catch (err) {
      showNotice(err.message, "error");
    }
  }

  function selectEntry(entry) {
    state.selectedEntryId = entry.entry_id;
    elements.editorTitle.textContent = "编辑排期";
    elements.entryId.value = entry.entry_id;
    elements.entryTitle.value = entry.title || "";

    if (entry.scheduled_at) {
      elements.entryDate.value = entry.scheduled_at.slice(0, 10);
      const timeMatch = entry.scheduled_at.match(/T(\d{2}:\d{2})/);
      if (timeMatch) elements.entryTime.value = timeMatch[1];
    }

    const isTask = entry.content && entry.content.kind === "task";
    const isInline = entry.content && entry.content.kind === "inline_selection";

    if (isTask) {
      elements.taskSelect.value = entry.content.task_id || "";
      elements.legacyNotice.classList.add("hidden");
      elements.taskLinkBox.classList.remove("hidden");
      elements.gotoLibraryLink.href = `/library?submission_id=${encodeURIComponent(entry.content.task_id)}`;
    } else if (isInline) {
      elements.taskSelect.value = "";
      elements.legacyNotice.classList.remove("hidden");
      elements.convertLegacyLink.href = `/library?plan_id=${encodeURIComponent(state.month)}&entry_id=${encodeURIComponent(entry.entry_id)}`;
      elements.taskLinkBox.classList.add("hidden");
    } else {
      elements.taskSelect.value = "";
      elements.legacyNotice.classList.add("hidden");
      elements.taskLinkBox.classList.add("hidden");
    }

    elements.saveEntryBtn.disabled = state.plan.status === "locked";
    elements.deleteEntryBtn.disabled = state.plan.status === "locked";

    renderCalendarGrid();
  }

  function openNewEntryForDate(dateStr) {
    resetEditor();
    elements.entryDate.value = dateStr || `${state.month}-01`;
  }

  function resetEditor() {
    state.selectedEntryId = null;
    elements.editorTitle.textContent = "新建排期";
    elements.entryId.value = "";
    elements.entryTitle.value = "";
    elements.entryDate.value = `${state.month}-01`;
    elements.entryTime.value = "20:00";
    elements.taskSelect.value = "";
    elements.legacyNotice.classList.add("hidden");
    elements.taskLinkBox.classList.add("hidden");
    elements.saveEntryBtn.disabled = !state.plan || state.plan.status === "locked";
    elements.deleteEntryBtn.disabled = true;
    renderCalendarGrid();
  }

  async function handleFormSubmit(e) {
    e.preventDefault();
    if (!state.plan || state.plan.status === "locked") return;

    const title = elements.entryTitle.value.trim();
    const dateVal = elements.entryDate.value;
    const timeVal = elements.entryTime.value || "20:00";
    const taskId = elements.taskSelect.value.trim();
    const entryIdVal = elements.entryId.value.trim();

    if (!title || !dateVal) {
      showNotice("请填写标题和日期", "warning");
      return;
    }

    let scheduledAt = `${dateVal}T${timeVal}:00+08:00`;

    let contentObj = null;
    if (taskId) {
      contentObj = { kind: "task", task_id: taskId };
    } else {
      // 保持旧 inline 或创建空 inline
      contentObj = {
        kind: "inline_selection",
        sets: { all: [], post: [], cover: [] },
      };
    }

    const isEdit = Boolean(entryIdVal);
    const targetEntryId = isEdit ? entryIdVal : `entry-${Date.now().toString(36)}`;

    const payload = {
      revision: state.plan.revision,
      entry: {
        entry_id: targetEntryId,
        scheduled_at: scheduledAt,
        title: title,
        content: contentObj,
      },
    };

    try {
      let res;
      if (isEdit) {
        res = await fetch(`/api/plans/${state.month}/entries/${targetEntryId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
      } else {
        res = await fetch(`/api/plans/${state.month}/entries`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
      }

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        if (res.status === 409) {
          throw new Error("计划已被更新（revision 冲突），请刷新页面后重试。");
        }
        throw new Error(errData.detail?.message || `保存排期失败 (${res.status})`);
      }

      state.plan = await res.json();
      showNotice(isEdit ? "排期已更新" : "排期已创建", "info");
      renderCalendarGrid();
      const updated = (state.plan.entries || []).find((x) => x.entry_id === targetEntryId);
      if (updated) selectEntry(updated);
    } catch (err) {
      showNotice(err.message, "error");
    }
  }

  async function handleDeleteEntry() {
    if (!state.plan || !state.selectedEntryId || state.plan.status === "locked") return;
    if (!confirm("确定要删除此排期吗？")) return;

    try {
      const res = await fetch(
        `/api/plans/${state.month}/entries/${state.selectedEntryId}?revision=${state.plan.revision}`,
        { method: "DELETE" }
      );
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail?.message || `删除排期失败 (${res.status})`);
      }
      state.plan = await res.json();
      showNotice("排期已删除", "info");
      resetEditor();
    } catch (err) {
      showNotice(err.message, "error");
    }
  }

  // 事件监听绑定
  elements.monthPicker.addEventListener("change", (e) => {
    if (e.target.value) loadPlan(e.target.value);
  });
  elements.prevMonth.addEventListener("click", () => {
    loadPlan(shiftMonth(state.month, -1));
  });
  elements.nextMonth.addEventListener("click", () => {
    loadPlan(shiftMonth(state.month, 1));
  });
  elements.newEntryBtn.addEventListener("click", () => {
    resetEditor();
  });
  elements.resetEditorBtn.addEventListener("click", () => {
    resetEditor();
  });
  elements.entryForm.addEventListener("submit", handleFormSubmit);
  elements.deleteEntryBtn.addEventListener("click", handleDeleteEntry);

  elements.taskSelect.addEventListener("change", (e) => {
    const selectedTaskId = e.target.value;
    if (selectedTaskId) {
      elements.taskLinkBox.classList.remove("hidden");
      elements.gotoLibraryLink.href = `/library?submission_id=${encodeURIComponent(selectedTaskId)}`;
      elements.legacyNotice.classList.add("hidden");
    } else {
      elements.taskLinkBox.classList.add("hidden");
    }
  });

  // 初始化
  loadSubmissionsList();
  loadPlan(getQueryMonth());
})();
