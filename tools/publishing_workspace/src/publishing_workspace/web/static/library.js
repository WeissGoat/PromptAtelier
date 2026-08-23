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
      favorite_mode: "all", // "all" | "favorited" | "unfavorited"
      posted_mode: "all",   // "all" | "posted" | "unposted"
    },
    offset: 0,
    limit: 60,
    hasMore: true,
    loadingPage: false,
    requestToken: 0,
    loadedAssets: new Map(),
    selectedAssetIds: new Set(),
    datasetAssets: [],
    datasetImportId: null,
    cardElements: new Map(),

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
    expandedFacetCategories: new Set(["clothing"]),
    activeExportJob: null,
    exportPollTimer: null,
  };

  const FACET_CONFIG = [
    { key: "clothing", label: "服装", icon: "👗" },
    { key: "phase", label: "阶段", icon: "⏳" },
    { key: "subtype", label: "子分类", icon: "📂" },
    { key: "cast", label: "角色类型", icon: "👥" },
    { key: "pose", label: "体态姿势", icon: "🧘" },
    { key: "environment", label: "环境背景", icon: "🏞️" },
    { key: "tone", label: "基调风格", icon: "🎨" },
    { key: "flags", label: "标记", icon: "🚩" },
    { key: "species", label: "种族", icon: "🐾" },
    { key: "domain", label: "领域", icon: "🌐" },
  ];

  const FACET_LABELS = Object.fromEntries(FACET_CONFIG.map((f) => [f.key, f.label]));

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

    quickFilterSection: document.querySelector(".quick-filter-section"),
    facetAccordion: document.getElementById("facet-accordion"),
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

    importProgressWrap: document.getElementById("import-progress-wrap"),
    importProgressStatus: document.getElementById("import-progress-status"),
    importProgressText: document.getElementById("import-progress-text"),
    importProgressFill: document.getElementById("import-progress-fill"),
    emptySnapshotGuide: document.getElementById("empty-snapshot-guide"),

    galleryProgressBanner: document.getElementById("gallery-progress-banner"),
    galleryProgressTitle: document.getElementById("gallery-progress-title"),
    galleryProgressCount: document.getElementById("gallery-progress-count"),
    galleryProgressFill: document.getElementById("gallery-progress-fill"),

    submissionEditorTitle: document.getElementById("submission-editor-title"),
    newSubmissionBtn: document.getElementById("new-submission-btn"),
    historySubmissionSelect: document.getElementById("history-submission-select"),
    legacyConvertBanner: document.getElementById("legacy-convert-banner"),
    submissionForm: document.getElementById("submission-form"),
    submissionTitle: document.getElementById("submission-title"),
    submissionDate: document.getElementById("submission-date"),
    submissionTime: document.getElementById("submission-time"),
    clearScheduleBtn: document.getElementById("clear-schedule-btn"),
    submissionTaskBadge: document.getElementById("submission-task-badge"),
    submissionRevBadge: document.getElementById("submission-rev-badge"),
    tabAll: document.getElementById("tab-all"),
    tabPost: document.getElementById("tab-post"),
    tabCover: document.getElementById("tab-cover"),
    badgeCountAll: document.getElementById("badge-count-all"),
    badgeCountPost: document.getElementById("badge-count-post"),
    badgeCountCover: document.getElementById("badge-count-cover"),
    clearCurrentSetBtn: document.getElementById("clear-current-set-btn"),
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

    // Pro Lightbox Viewer
    previewDialog: document.getElementById("preview-dialog"),
    previewImage: document.getElementById("preview-image"),
    closePreview: document.getElementById("close-preview"),
    lightboxFilename: document.getElementById("lightbox-filename"),
    lightboxFilepath: document.getElementById("lightbox-filepath"),
    lightboxCounter: document.getElementById("lightbox-counter"),
    lightboxPrevBtn: document.getElementById("lightbox-prev-btn"),
    lightboxNextBtn: document.getElementById("lightbox-next-btn"),
    lightboxFavoriteBtn: document.getElementById("lightbox-favorite-btn"),
    lightboxFavLabel: document.getElementById("lightbox-fav-label"),
    lightboxPostedBtn: document.getElementById("lightbox-posted-btn"),
    lightboxPostedLabel: document.getElementById("lightbox-posted-label"),
    lightboxRevealBtn: document.getElementById("lightbox-reveal-btn"),

    lbMetaDimensions: document.getElementById("lb-meta-dimensions"),
    lbMetaSize: document.getElementById("lb-meta-size"),
    lbMetaMtime: document.getElementById("lb-meta-mtime"),
    lbMetaSeed: document.getElementById("lb-meta-seed"),
    lbMetaModel: document.getElementById("lb-meta-model"),
    lbMetaSampler: document.getElementById("lb-meta-sampler"),
    lbMetaSteps: document.getElementById("lb-meta-steps"),
    lbMetaScale: document.getElementById("lb-meta-scale"),
    lbMetaNoise: document.getElementById("lb-meta-noise"),

    lbNodeArtist: document.getElementById("lb-node-artist"),
    lbNodeCharacter: document.getElementById("lb-node-character"),
    lbNodeGroup: document.getElementById("lb-node-group"),
    lbNodeAction: document.getElementById("lb-node-action"),

    lbFacetsSection: document.getElementById("lb-facets-section"),
    lbFacetsList: document.getElementById("lb-facets-list"),

    lbPromptBox: document.getElementById("lb-prompt-box"),
    lbCopyPrompt: document.getElementById("lb-copy-prompt"),
    lbNegativeBox: document.getElementById("lb-negative-box"),
    lbCopyNeg: document.getElementById("lb-copy-neg"),
    lbRawParameters: document.getElementById("lb-raw-parameters"),
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

  // ================= 收藏 (Favorites) localStorage 持久化 =================

  const FAVORITES_KEY_PREFIX = "pw_favorites_";

  function getFavoritesSet(importId) {
    if (!importId) return new Set();
    if (importId === "__all__") {
      const combined = new Set();
      try {
        for (let i = 0; i < localStorage.length; i++) {
          const k = localStorage.key(i);
          if (k && k.startsWith(FAVORITES_KEY_PREFIX)) {
            const raw = localStorage.getItem(k);
            if (raw) {
              const arr = JSON.parse(raw);
              for (const id of arr) combined.add(id);
            }
          }
        }
      } catch {}
      return combined;
    }
    try {
      const raw = localStorage.getItem(FAVORITES_KEY_PREFIX + importId);
      return raw ? new Set(JSON.parse(raw)) : new Set();
    } catch {
      return new Set();
    }
  }

  function saveFavoritesSet(importId, favSet) {
    if (!importId) return;
    const key = importId === "__all__" ? `${FAVORITES_KEY_PREFIX}global` : FAVORITES_KEY_PREFIX + importId;
    localStorage.setItem(key, JSON.stringify([...favSet]));
  }

  async function syncFavoritesFromServer(importId) {
    if (!importId) return;
    try {
      const url = importId === "__all__" ? "/api/favorites" : `/api/favorites?import_id=${encodeURIComponent(importId)}`;
      const res = await fetch(url);
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data.favorites) && data.favorites.length > 0) {
          const favSet = getFavoritesSet(importId);
          let changed = false;
          for (const id of data.favorites) {
            if (!favSet.has(id)) {
              favSet.add(id);
              changed = true;
            }
          }
          if (changed) {
            saveFavoritesSet(importId, favSet);
          }
        }
      }
    } catch {}
  }

  function isAssetFavorited(assetId) {
    return getFavoritesSet(state.filters.import_id).has(assetId);
  }

  function toggleFavorite(assetId) {
    const importId = state.filters.import_id;
    if (!importId) return false;
    const favSet = getFavoritesSet(importId);
    const nowFav = !favSet.has(assetId);
    if (nowFav) {
      favSet.add(assetId);
    } else {
      favSet.delete(assetId);
    }
    saveFavoritesSet(importId, favSet);

    // 异步同步至 Catalog 持久化
    fetch("/api/favorites/toggle", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ asset_id: assetId, import_id: importId, favorited: nowFav }),
    }).catch(() => {});

    return nowFav;
  }

  // ================= 快照独立筛选记忆与持久化 =================

  const SNAPSHOT_FILTERS_KEY_PREFIX = "pw_snapshot_filters_";
  const LAST_SELECTED_IMPORT_KEY = "pw_last_selected_import";

  function getDefaultFilters(importId = "") {
    return {
      import_id: importId,
      text: "",
      artist: "",
      character: "",
      action_group: "",
      action: "",
      facets: {},
      favorite_mode: "all",
      posted_mode: "all",
    };
  }

  function getSnapshotFilters(importId) {
    if (!importId) return getDefaultFilters("");
    try {
      const raw = localStorage.getItem(SNAPSHOT_FILTERS_KEY_PREFIX + importId);
      if (raw) {
        const saved = JSON.parse(raw);
        return {
          ...getDefaultFilters(importId),
          ...saved,
          import_id: importId,
          facets: saved.facets || {},
        };
      }
    } catch {}
    return getDefaultFilters(importId);
  }

  function saveSnapshotFilters(importId, filters) {
    if (!importId) return;
    try {
      const toSave = {
        text: filters.text || "",
        artist: filters.artist || "",
        character: filters.character || "",
        action_group: filters.action_group || "",
        action: filters.action || "",
        facets: filters.facets || {},
        favorite_mode: filters.favorite_mode || "all",
        posted_mode: filters.posted_mode || "all",
      };
      localStorage.setItem(SNAPSHOT_FILTERS_KEY_PREFIX + importId, JSON.stringify(toSave));
    } catch {}
  }

  function syncFilterInputsFromState() {
    if (elements.textFilter) elements.textFilter.value = state.filters.text || "";
    if (elements.artistFilter) elements.artistFilter.value = state.filters.artist || "";
    if (elements.characterFilter) elements.characterFilter.value = state.filters.character || "";
    if (elements.groupFilter) elements.groupFilter.value = state.filters.action_group || "";
    if (elements.actionFilter) elements.actionFilter.value = state.filters.action || "";

    document.querySelectorAll(".node-picker").forEach((picker) => {
      const input = picker.querySelector(".field-control");
      const clearBtn = picker.querySelector(".node-clear");
      if (input && clearBtn) {
        clearBtn.hidden = !input.value.trim();
      }
    });

    syncQuickFilterButtons();
    renderFacetAccordion();
    renderActiveChips();
  }

  // ================= 导入快照与 Facet 筛选 =================

  async function loadImportsList() {
    try {
      const res = await fetch("/api/imports");
      if (res.ok) {
        const data = await res.json();
        elements.importSelect.innerHTML = `
          <option value="">-- 请选择导入快照 --</option>
          <option value="__all__">🌟 全部导入素材 (全量浏览)</option>
        `;
        for (const item of data) {
          const opt = document.createElement("option");
          opt.value = item.import_id;
          opt.textContent = `${item.import_id} (${item.source_ref})`;
          elements.importSelect.appendChild(opt);
        }

        // 默认自动恢复选中上次打开的快照
        const lastSelected = localStorage.getItem(LAST_SELECTED_IMPORT_KEY);
        let restored = false;
        if (lastSelected) {
          const matchedOpt = Array.from(elements.importSelect.options).find(
            (opt) => opt.value === lastSelected
          );
          if (matchedOpt) {
            elements.importSelect.value = lastSelected;
            await switchSnapshot(lastSelected);
            restored = true;
          }
        }
        if (!restored && !state.filters.import_id) {
          await switchSnapshot("");
        }
      }
    } catch (err) {
      console.warn("加载导入列表失败", err);
      if (!state.filters.import_id) {
        await switchSnapshot("");
      }
    }
  }

  // ================= 真正服务端驱动的按需流式瀑布流 =================

  function updateGalleryProgress(loading = false) {
    if (!elements.galleryProgressBanner) return;
    const total = state.total || 0;
    const loaded = state.loadedAssets.size;

    if (!state.filters.import_id || total === 0) {
      elements.galleryProgressBanner.classList.add("hidden");
      return;
    }

    elements.galleryProgressBanner.classList.remove("hidden");
    const percent = total > 0 ? Math.min(100, Math.round((loaded / total) * 100)) : 0;

    if (elements.galleryProgressFill) {
      elements.galleryProgressFill.style.width = `${Math.max(1, percent)}%`;
    }

    if (elements.galleryProgressCount) {
      elements.galleryProgressCount.textContent = `已呈现 ${loaded.toLocaleString()} / ${total.toLocaleString()} (${percent}%)`;
    }

    if (!state.hasMore || loaded >= total) {
      elements.galleryProgressBanner.classList.add("completed");
      if (elements.galleryProgressTitle) {
        elements.galleryProgressTitle.textContent = `已全部载入 (共 ${total.toLocaleString()} 项)`;
      }
    } else {
      elements.galleryProgressBanner.classList.remove("completed");
      if (elements.galleryProgressTitle) {
        elements.galleryProgressTitle.textContent = loading
          ? `正在加载下一批素材...`
          : `流式浏览中 (向下滚动自动载入)`;
      }
    }
  }

  async function loadAssetsPage(reset = false) {
    const importId = state.filters.import_id;
    if (!importId) return;

    if (reset) {
      state.requestToken++;
      state.offset = 0;
      state.hasMore = true;
      state.loadingPage = false;
      state.loadedAssets.clear();
      state.cardElements.clear();
      elements.assetWaterfall.innerHTML = "";
      if (elements.endOfResults) elements.endOfResults.classList.add("hidden");
      if (elements.importProgressWrap) elements.importProgressWrap.classList.add("hidden");
      updateGalleryProgress(true);
    }

    if (state.loadingPage || !state.hasMore) {
      return;
    }

    state.loadingPage = true;
    const currentToken = state.requestToken;
    if (elements.loadingSpinner) elements.loadingSpinner.classList.remove("hidden");
    updateGalleryProgress(true);

    try {
      const params = new URLSearchParams();
      params.set("offset", String(state.offset));
      params.set("limit", String(state.limit));
      if (importId !== "__all__") {
        params.set("import_id", importId);
      }
      if (state.filters.text) params.set("text", state.filters.text);
      if (state.filters.artist) params.set("artist", state.filters.artist);
      if (state.filters.character) params.set("character", state.filters.character);
      if (state.filters.action_group) params.set("action_group", state.filters.action_group);
      if (state.filters.action) params.set("action", state.filters.action);
      if (Object.keys(state.filters.facets).length > 0) {
        params.set("facets", JSON.stringify(state.filters.facets));
      }
      if (state.filters.posted_mode === "posted") {
        params.set("posted", "true");
      } else if (state.filters.posted_mode === "unposted") {
        params.set("posted", "false");
      }
      if (state.filters.favorite_mode !== "all") {
        params.set("favorite_mode", state.filters.favorite_mode);
        const favSet = getFavoritesSet(importId);
        params.set("favorite_ids", JSON.stringify([...favSet]));
      }

      const res = await fetch(`/api/library/assets?${params.toString()}`);
      if (!res.ok) {
        throw new Error(`加载素材失败 (${res.status})`);
      }

      if (currentToken !== state.requestToken) {
        return;
      }

      const page = await res.json();
      state.total = page.total || 0;
      state.hasMore = page.has_more;
      state.offset = page.next_offset !== null && page.next_offset !== undefined
        ? page.next_offset
        : (state.offset + page.items.length);

      if (page.items.length === 0 && state.loadedAssets.size === 0) {
        elements.assetWaterfall.innerHTML = `
          <div class="empty-snapshot-guide">
            <div class="empty-guide-icon">🔍</div>
            <h3>未找到匹配的素材</h3>
            <p>请尝试调整搜索关键词、清除节点或分类属性筛选条件</p>
          </div>
        `;
      } else {
        for (const item of page.items) {
          if (!state.loadedAssets.has(item.asset_id)) {
            state.loadedAssets.set(item.asset_id, item);
            const card = renderAssetCard(item);
            state.cardElements.set(item.asset_id, card);
            elements.assetWaterfall.appendChild(card);
          }
        }
      }

      // 更新角标状态
      if (elements.assetCountBadge) {
        elements.assetCountBadge.textContent = `共 ${state.total.toLocaleString()} 张 (已载入 ${state.loadedAssets.size.toLocaleString()} 张)`;
      }

      updateGalleryProgress(false);

      if (!state.hasMore && state.loadedAssets.size > 0) {
        if (elements.endOfResults) elements.endOfResults.classList.remove("hidden");
      }
    } catch (err) {
      console.error("加载素材分页异常:", err);
      if (currentToken === state.requestToken) {
        showNotice(`加载素材异常：${err.message}`, "error");
      }
    } finally {
      if (currentToken === state.requestToken) {
        state.loadingPage = false;
        if (elements.loadingSpinner) elements.loadingSpinner.classList.add("hidden");
        updateGalleryProgress(false);
      }
    }
  }

  async function switchSnapshot(importId) {
    // 1. 如果之前有选中的快照，保存旧快照的当前独立筛选
    if (state.filters.import_id && state.filters.import_id !== importId) {
      saveSnapshotFilters(state.filters.import_id, state.filters);
    }

    // 2. 记忆当前最后选中的快照
    if (importId) {
      localStorage.setItem(LAST_SELECTED_IMPORT_KEY, importId);
    } else {
      localStorage.removeItem(LAST_SELECTED_IMPORT_KEY);
    }

    // 3. 并行从服务端同步已持久化的收藏标记 (不阻塞瀑布流首屏与 Facets 加载)
    syncFavoritesFromServer(importId).then(() => {
      if (state.filters.favorite_mode !== "all") {
        applyClientFilter();
      }
    });

    // 4. 加载目标快照独立的专属筛选配置
    state.filters = getSnapshotFilters(importId);
    state.selectedAssetIds.clear();
    updateSelectionBadges();

    // 5. 同步更新所有 UI 筛选控件
    syncFilterInputsFromState();

    if (!importId) {
      if (elements.importProgressWrap) elements.importProgressWrap.classList.add("hidden");
      if (elements.galleryProgressBanner) elements.galleryProgressBanner.classList.add("hidden");
      if (elements.assetCountBadge) elements.assetCountBadge.textContent = "";
      elements.assetWaterfall.innerHTML = `
        <div id="empty-snapshot-guide" class="empty-snapshot-guide">
          <div class="empty-guide-icon">📂</div>
          <h3>请选择导入快照</h3>
          <p>在左侧选择数据源快照即可开始流式加载并浏览、筛选素材</p>
        </div>
      `;
      state.loadedAssets.clear();
      state.cardElements.clear();
      renderActiveChips();
      return;
    }

    loadFacets();
    loadAssetsPage(true);
  }

  function applyInstantFilters() {
    if (state.filters.import_id) {
      saveSnapshotFilters(state.filters.import_id, state.filters);
    }
    renderActiveChips();
    if (state.filters.import_id) {
      loadAssetsPage(true);
    }
  }

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
          applyInstantFilters();
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
            applyInstantFilters();
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
            renderFacetAccordion();
            applyInstantFilters();
          },
        });
      }
    }

    if (state.filters.favorite_mode !== "all") {
      activeItems.push({
        type: "quick",
        label: "收藏状态",
        value: state.filters.favorite_mode === "favorited" ? "⭐ 仅看已收藏" : "☆ 仅看未收藏",
        clear: () => {
          state.filters.favorite_mode = "all";
          syncQuickFilterButtons();
          applyInstantFilters();
        },
      });
    }

    if (state.filters.posted_mode !== "all") {
      activeItems.push({
        type: "quick",
        label: "投稿状态",
        value: state.filters.posted_mode === "posted" ? "📮 仅看已投稿" : "📥 仅看未投稿",
        clear: () => {
          state.filters.posted_mode = "all";
          syncQuickFilterButtons();
          applyInstantFilters();
        },
      });
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
      const url = (state.filters.import_id && state.filters.import_id !== "__all__")
        ? `/api/library/facets?import_id=${encodeURIComponent(state.filters.import_id)}`
        : "/api/library/facets";
      const res = await fetch(url);
      if (res.ok) {
        state.availableFacets = await res.json();
        renderFacetAccordion();
      }
    } catch (err) {
      console.warn("加载 Facet 选项失败", err);
    }
  }

  function renderFacetAccordion() {
    if (!elements.facetAccordion) return;
    elements.facetAccordion.innerHTML = "";

    const availableCategories = Object.keys(state.availableFacets);
    if (!availableCategories.length) {
      elements.facetAccordion.innerHTML = '<div class="facet-empty-hint">当前快照无可用的 classify 属性标签</div>';
      if (elements.clearFacetsBtn) elements.clearFacetsBtn.hidden = true;
      return;
    }

    let hasAnySelected = false;
    for (const conf of FACET_CONFIG) {
      const cat = conf.key;
      const tags = state.availableFacets[cat] || [];
      if (!tags.length) continue;

      const selectedTags = state.filters.facets[cat] || [];
      const selectedCount = selectedTags.length;
      if (selectedCount > 0) hasAnySelected = true;

      const isOpen = state.expandedFacetCategories.has(cat);

      const itemEl = document.createElement("div");
      itemEl.className = `facet-accordion-item ${isOpen ? "open" : ""} ${selectedCount > 0 ? "has-selected" : ""}`;
      itemEl.dataset.category = cat;

      const headerBtn = document.createElement("button");
      headerBtn.type = "button";
      headerBtn.className = "facet-accordion-header";
      headerBtn.innerHTML = `
        <span class="facet-accordion-title">
          <span>${conf.icon}</span>
          <span>${conf.label} (${cat})</span>
        </span>
        <span class="facet-accordion-meta">
          ${selectedCount > 0 ? `<span class="facet-accordion-badge">${selectedCount}</span>` : ""}
          <span class="facet-accordion-arrow">▶</span>
        </span>
      `;

      headerBtn.addEventListener("click", () => {
        if (state.expandedFacetCategories.has(cat)) {
          state.expandedFacetCategories.delete(cat);
        } else {
          state.expandedFacetCategories.add(cat);
        }
        renderFacetAccordion();
      });

      const bodyEl = document.createElement("div");
      bodyEl.className = "facet-accordion-body";

      const chipsContainer = document.createElement("div");
      chipsContainer.className = "facet-chips-container";

      for (const tag of tags) {
        const isSelected = selectedTags.includes(tag);
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = `facet-tag-chip ${isSelected ? "active" : ""}`;
        chip.innerHTML = `${isSelected ? "✓ " : ""}${escapeHtml(tag)}`;
        chip.addEventListener("click", (e) => {
          e.stopPropagation();
          if (isSelected) {
            state.filters.facets[cat] = state.filters.facets[cat].filter((x) => x !== tag);
            if (!state.filters.facets[cat].length) {
              delete state.filters.facets[cat];
            }
          } else {
            if (!state.filters.facets[cat]) state.filters.facets[cat] = [];
            state.filters.facets[cat].push(tag);
          }
          renderFacetAccordion();
          applyInstantFilters();
        });
        chipsContainer.appendChild(chip);
      }

      bodyEl.appendChild(chipsContainer);
      itemEl.appendChild(headerBtn);
      itemEl.appendChild(bodyEl);
      elements.facetAccordion.appendChild(itemEl);
    }

    if (elements.clearFacetsBtn) {
      elements.clearFacetsBtn.hidden = !hasAnySelected;
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

    const hasUsage = item.usage && item.usage.length > 0;
    const usageBadgeHtml = hasUsage
      ? `<span class="asset-usage-badge" title="已投稿/使用: ${escapeHtml(item.usage.join(", "))}">已投稿</span>`
      : "";

    const isFav = isAssetFavorited(item.asset_id);
    const selectedArr = Array.from(state.selectedAssetIds);
    const orderIdx = selectedArr.indexOf(item.asset_id);
    const isSelected = orderIdx !== -1;
    const orderBadgeHtml = isSelected ? `<span class="asset-order-badge">${orderIdx + 1}</span>` : "";

    card.innerHTML = `
      <div class="asset-thumb-wrap" style="aspect-ratio: ${ratio};">
        <input type="checkbox" class="asset-checkbox" ${isSelected ? "checked" : ""}>
        ${orderBadgeHtml}
        ${usageBadgeHtml}
        <button class="asset-star-btn ${isFav ? "starred" : ""}" type="button" title="收藏">★</button>
        <img class="asset-thumb" loading="lazy" src="${previewUrl}" alt="${escapeHtml(item.display_name)}">
      </div>
      <div class="asset-info">
        <div class="asset-name" title="${escapeHtml(item.display_name)}">${escapeHtml(item.display_name)}</div>
        <div class="asset-dims">${item.width || 0} × ${item.height || 0} (${item.image_format || "PNG"})</div>
      </div>
    `;

    const checkbox = card.querySelector(".asset-checkbox");
    const starBtn = card.querySelector(".asset-star-btn");

    // 收藏按钮点击
    starBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      e.preventDefault();
      const nowFav = toggleFavorite(item.asset_id);
      starBtn.classList.toggle("starred", nowFav);
      // 弹出动画
      starBtn.classList.remove("star-pop");
      void starBtn.offsetWidth; // 强制 reflow 以重触发动画
      starBtn.classList.add("star-pop");
      // 如果正在筛选收藏状态，重新过滤
      if (state.filters.favorite_mode !== "all") {
        applyClientFilter();
      }
    });

    checkbox.addEventListener("change", (e) => {
      e.stopPropagation();
      toggleAssetSelection(item.asset_id, checkbox.checked);
    });

    // 点击缩略图或双击卡片打开大图与详情 Lightbox
    const thumbImg = card.querySelector(".asset-thumb");
    if (thumbImg) {
      thumbImg.addEventListener("click", (e) => {
        e.stopPropagation();
        openLightbox(item.asset_id);
      });
    }

    card.addEventListener("click", () => {
      const newState = !state.selectedAssetIds.has(item.asset_id);
      checkbox.checked = newState;
      toggleAssetSelection(item.asset_id, newState);
    });

    card.addEventListener("dblclick", (e) => {
      e.stopPropagation();
      openLightbox(item.asset_id);
    });

    return card;
  }

  function toggleAssetSelection(assetId, isSelected) {
    if (isSelected) {
      if (!state.selectedAssetIds.has(assetId)) {
        state.selectedAssetIds.add(assetId);
      }
    } else {
      state.selectedAssetIds.delete(assetId);
    }
    updateSelectionBadges();
  }

  function updateSelectionBadges() {
    const selectedArr = Array.from(state.selectedAssetIds);
    elements.selectedCountBadge.textContent = `已选 ${selectedArr.length} 项`;

    // 遍历瀑布流中已渲染的卡片，同步其选中态和次序徽章
    elements.assetWaterfall.querySelectorAll(".asset-card").forEach((card) => {
      const aid = card.dataset.assetId;
      const idx = selectedArr.indexOf(aid);
      const cb = card.querySelector(".asset-checkbox");
      let orderBadge = card.querySelector(".asset-order-badge");

      if (idx !== -1) {
        card.classList.add("selected");
        if (cb) cb.checked = true;
        const orderNum = idx + 1;
        if (!orderBadge) {
          orderBadge = document.createElement("span");
          orderBadge.className = "asset-order-badge";
          const wrap = card.querySelector(".asset-thumb-wrap");
          if (wrap) wrap.appendChild(orderBadge);
        }
        orderBadge.textContent = String(orderNum);
      } else {
        card.classList.remove("selected");
        if (cb) cb.checked = false;
        if (orderBadge) orderBadge.remove();
      }
    });
  }

  function clearAllAssetSelection() {
    state.selectedAssetIds.clear();
    updateSelectionBadges();
  }

  // ================= Pro Lightbox 大图与图片详情控制器 =================

  state.lightbox = {
    activeAssetId: null,
    assetList: [],
    currentIndex: -1,
  };

  function getVisibleAssetIds() {
    const list = [];
    state.loadedAssets.forEach((item, assetId) => {
      list.push(assetId);
    });
    return list;
  }

  async function openLightbox(assetId, customAssetList = null) {
    if (Array.isArray(customAssetList) && customAssetList.length > 0) {
      state.lightbox.assetList = [...customAssetList];
    } else {
      state.lightbox.assetList = getVisibleAssetIds();
    }
    state.lightbox.currentIndex = state.lightbox.assetList.indexOf(assetId);
    if (state.lightbox.currentIndex === -1 && state.lightbox.assetList.length > 0) {
      state.lightbox.currentIndex = 0;
      assetId = state.lightbox.assetList[0];
    }
    state.lightbox.activeAssetId = assetId;

    if (!elements.previewDialog.open) {
      elements.previewDialog.showModal();
    }

    await renderLightboxCurrent();
  }

  function navigateLightbox(step) {
    if (!state.lightbox.assetList.length) return;
    const total = state.lightbox.assetList.length;
    let nextIdx = state.lightbox.currentIndex + step;
    if (nextIdx < 0) nextIdx = total - 1;
    if (nextIdx >= total) nextIdx = 0;
    state.lightbox.currentIndex = nextIdx;
    state.lightbox.activeAssetId = state.lightbox.assetList[nextIdx];
    renderLightboxCurrent();
  }

  async function renderLightboxCurrent() {
    const assetId = state.lightbox.activeAssetId;
    if (!assetId) return;

    const item = state.loadedAssets.get(assetId);
    const total = state.lightbox.assetList.length;
    const currentNum = state.lightbox.currentIndex + 1;

    // 1. 顶部 Header 状态
    elements.lightboxCounter.textContent = `${currentNum} / ${total}`;
    elements.lightboxFilename.textContent = item?.display_name || assetId;
    elements.lightboxFilepath.textContent = item?.path || "";

    // 2. 左侧大图
    elements.previewImage.src = `/api/assets/${encodeURIComponent(assetId)}/preview`;
    elements.previewImage.alt = item?.display_name || assetId;

    // 3. 基础与节点信息初始填充
    if (item) {
      elements.lbMetaDimensions.textContent = `${item.width || 0} × ${item.height || 0}`;
      elements.lbNodeArtist.textContent = item.values?.artist || "未指定";
      elements.lbNodeCharacter.textContent = item.values?.character || "未指定";
      elements.lbNodeGroup.textContent = item.values?.action_group || "未指定";
      elements.lbNodeAction.textContent = item.values?.action || "未指定";

      // Classify 标签
      elements.lbFacetsList.innerHTML = "";
      if (item.facets && Object.keys(item.facets).length > 0) {
        elements.lbFacetsSection.hidden = false;
        for (const [field, vals] of Object.entries(item.facets)) {
          if (Array.isArray(vals) && vals.length > 0) {
            const fieldLabel = FACET_LABELS[field] || field;
            for (const val of vals) {
              const badge = document.createElement("span");
              badge.className = "lb-facet-badge";
              badge.textContent = `${fieldLabel}: ${val}`;
              elements.lbFacetsList.appendChild(badge);
            }
          }
        }
      } else {
        elements.lbFacetsSection.hidden = true;
      }
    } else {
      elements.lbMetaDimensions.textContent = "-";
      elements.lbNodeArtist.textContent = "-";
      elements.lbNodeCharacter.textContent = "-";
      elements.lbNodeGroup.textContent = "-";
      elements.lbNodeAction.textContent = "-";
      elements.lbFacetsSection.hidden = true;
    }

    // 4. 按钮状态初始同步
    updateLightboxButtonStates(assetId);

    // 5. 异步获取完整 PNG 元数据
    try {
      const res = await fetch(`/api/assets/${encodeURIComponent(assetId)}/details`);
      if (res.ok && state.lightbox.activeAssetId === assetId) {
        const detail = await res.json();
        elements.lightboxFilename.textContent = detail.display_name || assetId;
        elements.lightboxFilepath.textContent = detail.path || "";
        const gen = detail.generation_info || {};
        elements.lbMetaDimensions.textContent = `${detail.width} × ${detail.height} (${detail.image_format || "PNG"})`;
        elements.lbMetaSize.textContent = gen.file_size_human || "-";
        elements.lbMetaMtime.textContent = gen.modified_at || "-";
        elements.lbMetaSeed.textContent = gen.seed ?? "-";
        elements.lbMetaModel.textContent = gen.model || "-";
        elements.lbMetaSampler.textContent = gen.sampler || "-";
        elements.lbMetaSteps.textContent = gen.steps ?? "-";
        elements.lbMetaScale.textContent = gen.scale ?? "-";
        elements.lbMetaNoise.textContent = gen.noise_schedule || "-";

        elements.lbPromptBox.textContent = gen.prompt || "无 Prompt 记录";
        elements.lbNegativeBox.textContent = gen.negative_prompt || "无 Negative 记录";

        elements.lbRawParameters.textContent =
          gen.raw_parameters ||
          (gen.all_chunks && Object.keys(gen.all_chunks).length ? JSON.stringify(gen.all_chunks, null, 2) : "无原始参数");

        // 更新投稿与收藏状态
        updateLightboxButtonStates(assetId, detail.is_favorited, detail.is_posted);
      }
    } catch (err) {
      console.warn("获取素材详情失败", err);
    }
  }

  function updateLightboxButtonStates(assetId, serverFav = null, serverPosted = null) {
    const isFav = serverFav !== null ? serverFav : isAssetFavorited(assetId);
    elements.lightboxFavoriteBtn.classList.toggle("active-fav", isFav);
    elements.lightboxFavLabel.textContent = isFav ? "已收藏 ⭐" : "收藏 ☆";

    const item = state.loadedAssets.get(assetId);
    const isPosted = serverPosted !== null ? serverPosted : Boolean(item?.usage && item.usage.length > 0);
    elements.lightboxPostedBtn.classList.toggle("active-posted", isPosted);
    elements.lightboxPostedLabel.textContent = isPosted ? "已投稿 📮" : "标记已投稿 📥";
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
        scheduled_at: data.scheduled_at || null,
        currentSetTab: "all",
        legacyInlineSource: null,
      };
      elements.legacyConvertBanner.classList.add("hidden");

      if (data.scheduled_at) {
        const [dPart, tPart] = data.scheduled_at.split("T");
        if (elements.submissionDate) elements.submissionDate.value = dPart || "";
        if (elements.submissionTime && tPart) {
          elements.submissionTime.value = tPart.slice(0, 5) || "20:00";
        }
      } else {
        if (elements.submissionDate) elements.submissionDate.value = "";
        if (elements.submissionTime) elements.submissionTime.value = "20:00";
      }

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
      scheduled_at: null,
      currentSetTab: "all",
      legacyInlineSource: null,
    };
    elements.legacyConvertBanner.classList.add("hidden");
    elements.historySubmissionSelect.value = "";
    if (elements.submissionDate) elements.submissionDate.value = "";
    if (elements.submissionTime) elements.submissionTime.value = "20:00";
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
      elements.setItemsContainer.innerHTML = '<div class="helper-text" style="padding:16px 10px;text-align:center;">当前集合为空，可从中间素材列表勾选后点击“加入当前集合”</div>';
      return;
    }

    for (let index = 0; index < assetIds.length; index++) {
      const assetId = assetIds[index];
      const asset = state.loadedAssets.get(assetId);
      const displayName = asset ? asset.display_name : assetId;
      const previewUrl = `/api/assets/${encodeURIComponent(assetId)}/preview`;

      // 提取副标题信息（尺寸 + 角色/画风）
      let subMeta = "";
      if (asset) {
        const dims = asset.width && asset.height ? `${asset.width}×${asset.height}` : "";
        const char = asset.values?.character || "";
        const art = asset.values?.artist || "";
        subMeta = [dims, char, art].filter(Boolean).join(" · ") || assetId.slice(0, 16);
      } else {
        subMeta = assetId.length > 24 ? `${assetId.slice(0, 12)}...${assetId.slice(-8)}` : assetId;
      }

      const row = document.createElement("div");
      row.className = "set-item-row";
      row.title = "点击查看大图与生成详情";
      row.innerHTML = `
        <span class="set-item-idx">#${index + 1}</span>
        <img class="set-item-thumb" src="${previewUrl}" alt="thumb" loading="lazy">
        <div class="set-item-info">
          <span class="set-item-title" title="${escapeHtml(displayName)}">${escapeHtml(displayName)}</span>
          <span class="set-item-meta" title="${escapeHtml(subMeta)}">${escapeHtml(subMeta)}</span>
        </div>
      `;

      // 点击整行直接打开大图与详情（并在当前集合列表中前后切换）
      row.addEventListener("click", () => {
        openLightbox(assetId, [...assetIds]);
      });

      const actionsWrap = document.createElement("div");
      actionsWrap.className = "set-item-actions";

      if (index > 0) {
        const upBtn = document.createElement("button");
        upBtn.className = "set-item-action-btn";
        upBtn.type = "button";
        upBtn.textContent = "↑";
        upBtn.title = "上移";
        upBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          const item = state.currentSubmission.sets[activeSet].splice(index, 1)[0];
          state.currentSubmission.sets[activeSet].splice(index - 1, 0, item);
          syncSubmissionFormUI();
        });
        actionsWrap.appendChild(upBtn);
      }

      if (index < assetIds.length - 1) {
        const downBtn = document.createElement("button");
        downBtn.className = "set-item-action-btn";
        downBtn.type = "button";
        downBtn.textContent = "↓";
        downBtn.title = "下移";
        downBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          const item = state.currentSubmission.sets[activeSet].splice(index, 1)[0];
          state.currentSubmission.sets[activeSet].splice(index + 1, 0, item);
          syncSubmissionFormUI();
        });
        actionsWrap.appendChild(downBtn);
      }

      const removeBtn = document.createElement("button");
      removeBtn.className = "set-item-action-btn btn-remove";
      removeBtn.type = "button";
      removeBtn.textContent = "✕";
      removeBtn.title = "从当前集合移除";
      removeBtn.addEventListener("click", (e) => {
        e.stopPropagation();
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

    const dateVal = elements.submissionDate ? elements.submissionDate.value : "";
    const timeVal = elements.submissionTime ? elements.submissionTime.value || "20:00" : "20:00";
    let scheduledAt = null;
    if (dateVal) {
      scheduledAt = `${dateVal}T${timeVal}:00+08:00`;
    }

    const payload = {
      title: title,
      source_import_id: sub.source_import_id || state.filters.import_id || null,
      sets: sub.sets,
      revision: sub.task_id ? sub.revision : null,
      scheduled_at: scheduledAt,
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
      if (savedData.scheduled_at) {
        showNotice(`投稿保存成功！任务 ID: ${savedData.task_id}，已同步排期至日历 (${dateVal} ${timeVal})`, "info");
      } else {
        showNotice(`投稿保存成功！任务 ID：${savedData.task_id}`, "info");
      }

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
        scheduled_at: savedData.scheduled_at || null,
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
    switchSnapshot(e.target.value);
  });

  function applyTextSearch() {
    const val = elements.textFilter.value.trim();
    if (state.filters.text !== val) {
      state.filters.text = val;
      applyInstantFilters();
    }
  }

  let textSearchTimer = null;
  elements.textFilter.addEventListener("input", () => {
    state.filters.text = elements.textFilter.value.trim();
    clearTimeout(textSearchTimer);
    textSearchTimer = setTimeout(() => {
      applyInstantFilters();
    }, 250);
  });

  elements.textFilter.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      clearTimeout(textSearchTimer);
      applyTextSearch();
    }
  });

  elements.searchAssetsBtn.addEventListener("click", () => {
    clearTimeout(textSearchTimer);
    applyTextSearch();
  });

  // 快速筛选（收藏与投稿三态分段选择器）事件
  function syncQuickFilterButtons() {
    if (!elements.quickFilterSection) return;
    const favRow = elements.quickFilterSection.querySelector('[data-filter-type="favorite"]');
    if (favRow) {
      favRow.querySelectorAll(".segment-btn").forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.val === state.filters.favorite_mode);
      });
    }
    const postRow = elements.quickFilterSection.querySelector('[data-filter-type="posted"]');
    if (postRow) {
      postRow.querySelectorAll(".segment-btn").forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.val === state.filters.posted_mode);
      });
    }
  }

  if (elements.quickFilterSection) {
    elements.quickFilterSection.addEventListener("click", (e) => {
      const btn = e.target.closest(".segment-btn");
      if (!btn) return;
      const row = btn.closest(".quick-filter-row");
      if (!row) return;
      const filterType = row.dataset.filterType;
      const val = btn.dataset.val;

      if (filterType === "favorite") {
        state.filters.favorite_mode = val;
      } else if (filterType === "posted") {
        state.filters.posted_mode = val;
      }

      syncQuickFilterButtons();
      loadAssetsPage(true);
    });
  }

  elements.resetFiltersBtn.addEventListener("click", () => {
    state.filters = {
      import_id: state.filters.import_id,
      text: "",
      artist: "",
      character: "",
      action_group: "",
      action: "",
      facets: {},
      favorite_mode: "all",
      posted_mode: "all",
    };
    elements.textFilter.value = "";
    elements.artistFilter.value = "";
    elements.characterFilter.value = "";
    elements.groupFilter.value = "";
    elements.actionFilter.value = "";
    document.querySelectorAll(".node-clear").forEach((btn) => (btn.hidden = true));
    syncQuickFilterButtons();
    renderFacetAccordion();
    loadAssetsPage(true);
  });

  if (elements.clearAllChips) {
    elements.clearAllChips.addEventListener("click", () => {
      elements.resetFiltersBtn.click();
    });
  }

  if (elements.clearFacetsBtn) {
    elements.clearFacetsBtn.addEventListener("click", () => {
      state.filters.facets = {};
      renderFacetAccordion();
      loadAssetsPage(true);
    });
  }

  // 全选 / 清选 / 加入集合
  elements.selectAllVisibleBtn.addEventListener("click", () => {
    state.loadedAssets.forEach((item, id) => {
      state.selectedAssetIds.add(id);
    });
    updateSelectionBadges();
  });

  // 瀑布流滚动触底监听 (真·按需分页加载)
  if (elements.scrollSentinel) {
    const scrollObserver = new IntersectionObserver(
      (entries) => {
        if (
          entries[0].isIntersecting &&
          state.hasMore &&
          !state.loadingPage &&
          state.filters.import_id
        ) {
          loadAssetsPage(false);
        }
      },
      { rootMargin: "400px" }
    );
    scrollObserver.observe(elements.scrollSentinel);
  }

  elements.clearSelectionBtn.addEventListener("click", () => {
    clearAllAssetSelection();
  });

  elements.addToSetBtn.addEventListener("click", () => {
    if (!state.selectedAssetIds.size) {
      showNotice("请先勾选需要加入的素材", "warning");
      return;
    }
    const count = state.selectedAssetIds.size;
    const activeSet = state.currentSubmission.currentSetTab;
    const currentList = state.currentSubmission.sets[activeSet];
    for (const id of state.selectedAssetIds) {
      if (!currentList.includes(id)) {
        currentList.push(id);
      }
    }
    syncSubmissionFormUI();
    // 需求 3：点击加入集合后自动清选
    clearAllAssetSelection();
    showNotice(`已将 ${count} 项素材加入【${activeSet}】集合，并已自动清选`, "info");
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

  // 清空当前集合
  if (elements.clearCurrentSetBtn) {
    elements.clearCurrentSetBtn.addEventListener("click", () => {
      const activeSet = state.currentSubmission.currentSetTab;
      state.currentSubmission.sets[activeSet] = [];
      syncSubmissionFormUI();
      showNotice(`已清空【${activeSet}】集合`, "info");
    });
  }

  // 快捷排期预设芯片
  document.querySelectorAll(".schedule-quick-presets .preset-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const offset = parseInt(chip.dataset.offsetDays, 10) || 0;
      const targetDate = new Date();
      targetDate.setDate(targetDate.getDate() + offset);
      const y = targetDate.getFullYear();
      const m = String(targetDate.getMonth() + 1).padStart(2, "0");
      const d = String(targetDate.getDate()).padStart(2, "0");
      if (elements.submissionDate) {
        elements.submissionDate.value = `${y}-${m}-${d}`;
      }
    });
  });

  if (elements.clearScheduleBtn) {
    elements.clearScheduleBtn.addEventListener("click", () => {
      if (elements.submissionDate) elements.submissionDate.value = "";
    });
  }

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
    snapshotCache.clear();
    loadImportsList();
    loadFacets();
    loadHistoricalSubmissions();
    switchSnapshot(state.filters.import_id);
  });

  // Pro Lightbox 事件绑定
  if (elements.closePreview) {
    elements.closePreview.addEventListener("click", () => {
      elements.previewDialog.close();
    });
  }

  if (elements.lightboxPrevBtn) {
    elements.lightboxPrevBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      navigateLightbox(-1);
    });
  }

  if (elements.lightboxNextBtn) {
    elements.lightboxNextBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      navigateLightbox(1);
    });
  }

  // 键盘左右箭头切换大图
  document.addEventListener("keydown", (e) => {
    if (!elements.previewDialog.open) return;
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      navigateLightbox(-1);
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      navigateLightbox(1);
    }
  });

  // 收藏切换
  if (elements.lightboxFavoriteBtn) {
    elements.lightboxFavoriteBtn.addEventListener("click", () => {
      const aid = state.lightbox.activeAssetId;
      if (!aid) return;
      const nowFav = toggleFavorite(aid);
      updateLightboxButtonStates(aid, nowFav);

      // 同步卡片视图上的金星
      const card = elements.assetWaterfall.querySelector(`[data-asset-id="${aid}"]`);
      if (card) {
        const starBtn = card.querySelector(".asset-star-btn");
        if (starBtn) {
          starBtn.classList.toggle("starred", nowFav);
          starBtn.classList.remove("star-pop");
          void starBtn.offsetWidth;
          starBtn.classList.add("star-pop");
        }
      }
    });
  }

  // 投稿状态切换
  if (elements.lightboxPostedBtn) {
    elements.lightboxPostedBtn.addEventListener("click", async () => {
      const aid = state.lightbox.activeAssetId;
      if (!aid) return;
      const item = state.loadedAssets.get(aid);
      const currentlyPosted = Boolean(item?.usage && item.usage.length > 0);
      const nextPosted = !currentlyPosted;

      try {
        const res = await fetch(`/api/assets/${encodeURIComponent(aid)}/toggle-posted`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ posted: nextPosted }),
        });
        if (res.ok) {
          if (item) {
            item.usage = nextPosted ? ["posted"] : [];
          }
          updateLightboxButtonStates(aid, null, nextPosted);

          // 同步更新瀑布流卡片上的角标
          const card = elements.assetWaterfall.querySelector(`[data-asset-id="${aid}"]`);
          if (card) {
            let badge = card.querySelector(".asset-usage-badge");
            if (nextPosted) {
              if (!badge) {
                const wrap = card.querySelector(".asset-thumb-wrap");
                badge = document.createElement("span");
                badge.className = "asset-usage-badge";
                badge.textContent = "已投稿";
                wrap.appendChild(badge);
              }
            } else {
              if (badge) badge.remove();
            }
          }
          showNotice(nextPosted ? "已标记为【已投稿】" : "已取消【已投稿】标记", "info");
        }
      } catch (err) {
        showNotice(`标记投稿失败: ${err.message}`, "error");
      }
    });
  }

  // 打开所在文件夹
  if (elements.lightboxRevealBtn) {
    elements.lightboxRevealBtn.addEventListener("click", async () => {
      const aid = state.lightbox.activeAssetId;
      if (!aid) return;
      try {
        const res = await fetch(`/api/assets/${encodeURIComponent(aid)}/reveal`, {
          method: "POST",
        });
        if (res.ok) {
          showNotice("已在资源管理器中打开并高亮文件", "info");
        } else {
          const err = await res.json();
          showNotice(err.detail || "打开失败", "error");
        }
      } catch (err) {
        showNotice(`打开文件失败: ${err.message}`, "error");
      }
    });
  }

  // 复制路径与提示词
  if (elements.lightboxFilepath) {
    elements.lightboxFilepath.addEventListener("click", () => {
      const text = elements.lightboxFilepath.textContent;
      if (text) {
        navigator.clipboard.writeText(text);
        showNotice("已复制文件路径", "info");
      }
    });
  }

  if (elements.lbCopyPrompt) {
    elements.lbCopyPrompt.addEventListener("click", () => {
      const text = elements.lbPromptBox.textContent;
      if (text && text !== "无 Prompt 记录") {
        navigator.clipboard.writeText(text);
        showNotice("已复制 Prompt", "info");
      }
    });
  }

  if (elements.lbCopyNeg) {
    elements.lbCopyNeg.addEventListener("click", () => {
      const text = elements.lbNegativeBox.textContent;
      if (text && text !== "无 Negative 记录") {
        navigator.clipboard.writeText(text);
        showNotice("已复制 Negative Prompt", "info");
      }
    });
  }

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
                applyInstantFilters();
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
      const query = inputEl.value.trim();
      state.filters[role] = query;
      applyInstantFilters();

      clearTimeout(timer);
      timer = setTimeout(() => {
        fetchAndShowOptions(query);
      }, 120);
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
            applyInstantFilters();
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
        applyInstantFilters();
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

  // 初始化加载 (优先自动恢复上次选中的快照，并按需加载历史投稿与URL参数)
  (async function initApp() {
    await loadImportsList();
    await loadHistoricalSubmissions();
    await initFromUrl();
  })();
})();
