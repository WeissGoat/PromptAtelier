import { FolderOpen, Layers, LoaderCircle, RefreshCw, Search, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { apiGet, apiPost, errorMessage, thumbUrl } from "../api/client";
import type {
  HistoryImage,
  HistoryIndexingStatus,
  HistoryNodeFilter,
  HistoryRun,
  HistoryRunImagesResponse,
  HistoryRunKind,
  HistorySearchResponse,
} from "../api/types";
import { HistoryNodeFilterPicker } from "../components/HistoryNodeFilterPicker";
import { ImageDetailDialog, type ImageDetailItem } from "../components/ImageDetailDialog";
import { TileSizeToggle } from "../components/TileSizeToggle";
import { formatImageTiming } from "../generation/timing";
import { loadTileSize, tileGridStyle, tileSizes, type TileSize } from "../generation/tileSize";
import {
  buildHistoryHash,
  HISTORY_ROLE_LABELS,
  nodeFilterKey,
  parseHistoryHashNodes,
  sameNodeFilter,
} from "../history/historyFilter";
import type { OpenImageNodeInCustom } from "../workspace/useOpenImageNodeInCustom";

const PAGE_SIZE = 300;
const SEARCH_PAGE_SIZE = 200;
const SELECTED_RUN_KEY = "promptatelier.history-run/v1";
const ALL_MATCHES_ID = "__all_matches__";

const kindLabels: Record<HistoryRunKind, string> = {
  compare: "Compare",
  random: "Random",
  sequential: "Sequential",
  "sequential-all": "Sequential",
  primary: "Primary",
  contract: "契约",
  studio: "Compare Studio",
  loose: "散图",
  other: "其他",
};
const kindFilters: Array<{ key: string; label: string }> = [
  { key: "all", label: "全部" },
  { key: "compare", label: "Compare" },
  { key: "random", label: "Random" },
  { key: "sequential", label: "Sequential" },
  { key: "primary", label: "Primary" },
  { key: "contract", label: "契约" },
  { key: "studio", label: "Compare Studio" },
  { key: "loose", label: "散图" },
  { key: "other", label: "其他" },
];
const roleOrder = ["character", "action", "clothing", "artist"];

function loadSelectedRun(): string {
  try {
    return window.localStorage.getItem(SELECTED_RUN_KEY) ?? "";
  } catch {
    return "";
  }
}

function saveSelectedRun(id: string): void {
  try {
    window.localStorage.setItem(SELECTED_RUN_KEY, id);
  } catch {
    // 只在当前页面记住。
  }
}

function formatDateTime(seconds: number): string {
  const date = new Date(seconds * 1000);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** group_001_seed_42 → Group 1 · Seed 42；其他目录名原样显示。 */
export function groupTitle(group: string): string {
  const match = /^group_(\d+)_seed_(-?\d+)$/.exec(group);
  return match ? `Group ${Number(match[1])} · Seed ${match[2]}` : group;
}

function runTitle(run: HistoryRun): string {
  return run.job?.label || run.name;
}

/** 这一批里各图之间不同的节点角色（如顺序跑动作时只有 action 在变）。 */
function varyingRoles(images: HistoryImage[]): Set<string> {
  const values = new Map<string, Set<string>>();
  for (const image of images) {
    for (const node of image.info.nodes) {
      if (!values.has(node.role)) values.set(node.role, new Set());
      values.get(node.role)!.add(node.name);
    }
  }
  return new Set([...values.entries()].filter(([, names]) => names.size > 1).map(([role]) => role));
}

/** 图下的说明：变化的节点排前面，不变的放后面；画风名一般很长，只有它在变时才显示。 */
function imageCaption(image: HistoryImage, varying: Set<string>): string {
  const rank = (role: string) => (varying.has(role) ? 0 : 10) + Math.max(0, roleOrder.indexOf(role));
  const names = [...image.info.nodes]
    .filter((node) => node.role !== "artist" || varying.has("artist"))
    .sort((a, b) => rank(a.role) - rank(b.role))
    .map((node) => node.name);
  return names.join(" · ") || image.filename;
}

function matchesQuery(image: HistoryImage, query: string): boolean {
  if (!query) return true;
  const haystack = [
    image.filename,
    image.group,
    image.info.backend ?? "",
    String(image.info.seed ?? ""),
    ...image.info.nodes.map((node) => node.name),
  ].join(" ").toLowerCase();
  return query.toLowerCase().split(/\s+/).filter(Boolean).every((part) => haystack.includes(part));
}

type HistoryPageProps = {
  onOpenNode?: OpenImageNodeInCustom;
  externalFilterRequest?: { nodes: HistoryNodeFilter[]; seq: number } | null;
};

export function HistoryPage({ onOpenNode, externalFilterRequest }: HistoryPageProps) {
  const [runs, setRuns] = useState<HistoryRun[]>([]);
  const [runsError, setRunsError] = useState("");
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [kind, setKind] = useState("all");

  const [nodeFilters, setNodeFilters] = useState<HistoryNodeFilter[]>(() => {
    if (externalFilterRequest?.nodes.length) return externalFilterRequest.nodes;
    if (typeof window !== "undefined") return parseHistoryHashNodes(window.location.hash);
    return [];
  });
  const isNodeSearchMode = nodeFilters.length > 0;

  const [selectedId, setSelectedId] = useState<string>(() => (
    (externalFilterRequest?.nodes.length || (typeof window !== "undefined" && parseHistoryHashNodes(window.location.hash).length > 0))
      ? ALL_MATCHES_ID
      : loadSelectedRun()
  ));

  const [images, setImages] = useState<HistoryImage[]>([]);
  const [total, setTotal] = useState(0);
  const [imagesError, setImagesError] = useState("");
  const [loadingImages, setLoadingImages] = useState(false);
  const [query, setQuery] = useState("");
  const [backend, setBackend] = useState("all");
  const [searchBackends, setSearchBackends] = useState<string[]>([]);
  const [matchedRunCounts, setMatchedRunCounts] = useState<Map<string, number>>(new Map());
  const [indexing, setIndexing] = useState<HistoryIndexingStatus | null>(null);
  const [tileSize, setTileSize] = useState<TileSize>(loadTileSize);
  const [detail, setDetail] = useState<{ items: ImageDetailItem[]; index: number } | null>(null);
  const [folderStatus, setFolderStatus] = useState("");
  const searchReqId = useRef(0);
  const lastExternalSeq = useRef<number>(externalFilterRequest?.seq ?? 0);

  // 外部（例如 Custom 页节点卡片）发起跳转筛选时，更新节点筛选并切到「全部匹配」。
  useEffect(() => {
    if (!externalFilterRequest || externalFilterRequest.seq === lastExternalSeq.current) return;
    lastExternalSeq.current = externalFilterRequest.seq;
    setNodeFilters(externalFilterRequest.nodes);
    setSelectedId(externalFilterRequest.nodes.length ? ALL_MATCHES_ID : loadSelectedRun());
    setQuery("");
    setBackend("all");
    setKind("all");
  }, [externalFilterRequest]);

  // 把当前节点筛选同步到 URL hash，刷新页面后不丢失。
  useEffect(() => {
    if (typeof window === "undefined") return;
    const rawHash = window.location.hash;
    if (!rawHash || rawHash.startsWith("#/results")) {
      const nextHash = buildHistoryHash(nodeFilters);
      if (rawHash !== nextHash) {
        window.history.replaceState(null, "", nextHash);
      }
    }
  }, [nodeFilters]);

  const refreshRuns = useCallback(async () => {
    setLoadingRuns(true);
    setRunsError("");
    try {
      const response = await apiGet<{ runs: HistoryRun[] }>("/history/runs");
      setRuns(response.runs);
      setSelectedId((current) => {
        if (current === ALL_MATCHES_ID) return current;
        return response.runs.some((run) => run.id === current) ? current : response.runs[0]?.id ?? "";
      });
    } catch (error) {
      setRunsError(errorMessage(error));
    } finally {
      setLoadingRuns(false);
    }
  }, []);

  const loadRunImages = useCallback(async (runId: string, offset: number) => {
    if (!runId || runId === ALL_MATCHES_ID) return;
    setLoadingImages(true);
    setImagesError("");
    try {
      const params = new URLSearchParams({ run_id: runId, offset: String(offset), limit: String(PAGE_SIZE) });
      const response = await apiGet<HistoryRunImagesResponse>(`/history/images?${params}`);
      setImages((current) => offset ? [...current, ...response.images] : response.images);
      setTotal(response.total);
    } catch (error) {
      setImagesError(errorMessage(error));
    } finally {
      setLoadingImages(false);
    }
  }, []);

  const loadSearchImages = useCallback(async (offset: number, refresh = false) => {
    const reqId = ++searchReqId.current;
    setLoadingImages(true);
    setImagesError("");
    try {
      const params = new URLSearchParams({
        offset: String(offset),
        limit: String(SEARCH_PAGE_SIZE),
      });
      if (refresh) params.set("refresh", "true");
      if (nodeFilters.length) {
        params.set(
          "nodes",
          JSON.stringify(
            nodeFilters.map((n) => ({
              role: n.role,
              name: n.name,
              ...(n.ref ? { ref: n.ref } : {}),
            })),
          ),
        );
      }
      if (query.trim()) params.set("q", query.trim());
      if (backend !== "all") params.set("backend", backend);
      if (kind !== "all") params.set("kind", kind);
      if (selectedId && selectedId !== ALL_MATCHES_ID) params.set("run_id", selectedId);

      const response = await apiGet<HistorySearchResponse>(`/history/search?${params.toString()}`);
      if (reqId !== searchReqId.current) return;
      setImages((current) => offset ? [...current, ...response.images] : response.images);
      setTotal(response.total);
      setSearchBackends(response.backends);
      setIndexing(response.indexing);
      setMatchedRunCounts(new Map(response.matched_runs.map((item) => [item.id, item.match_count])));
    } catch (error) {
      if (reqId !== searchReqId.current) return;
      setImagesError(errorMessage(error));
    } finally {
      if (reqId === searchReqId.current) setLoadingImages(false);
    }
  }, [backend, kind, nodeFilters, query, selectedId]);

  useEffect(() => {
    void refreshRuns();
  }, [refreshRuns]);

  // 非节点筛选模式：按选中的批次加载图片（保持原有流畅体验）。
  useEffect(() => {
    if (isNodeSearchMode) return;
    setImages([]);
    setTotal(0);
    setQuery("");
    setBackend("all");
    setFolderStatus("");
    setIndexing(null);
    setMatchedRunCounts(new Map());
    if (selectedId && selectedId !== ALL_MATCHES_ID) {
      saveSelectedRun(selectedId);
      void loadRunImages(selectedId, 0);
    } else if (runs[0]?.id) {
      setSelectedId(runs[0].id);
    }
  }, [isNodeSearchMode, loadRunImages, selectedId, runs]);

  // 节点筛选模式：调用跨批次 /history/search。
  useEffect(() => {
    if (!isNodeSearchMode) return;
    setFolderStatus("");
    const timer = window.setTimeout(() => {
      void loadSearchImages(0);
    }, query ? 180 : 0);
    return () => window.clearTimeout(timer);
  }, [isNodeSearchMode, loadSearchImages, query]);

  // 首次对上万张历史图建索引时，后台建索引期间自动轮询刷新进度与结果。
  useEffect(() => {
    if (!isNodeSearchMode || !indexing?.running) return;
    const timer = window.setTimeout(() => {
      void loadSearchImages(0);
    }, 1500);
    return () => window.clearTimeout(timer);
  }, [indexing, isNodeSearchMode, loadSearchImages]);

  function toggleNodeFilter(node: HistoryNodeFilter) {
    setNodeFilters((current) => {
      const exists = current.some((item) => sameNodeFilter(item, node));
      const next = exists
        ? current.filter((item) => !sameNodeFilter(item, node))
        : [...current, node];
      if (next.length > 0 && current.length === 0) {
        setSelectedId(ALL_MATCHES_ID);
      } else if (next.length === 0) {
        setSelectedId(loadSelectedRun() || runs[0]?.id || "");
      }
      return next;
    });
  }

  function clearNodeFilters() {
    setNodeFilters([]);
    setSelectedId(loadSelectedRun() || runs[0]?.id || "");
  }

  const runsById = useMemo(() => new Map(runs.map((run) => [run.id, run])), [runs]);

  const visibleRuns = useMemo(() => {
    const byKind = runs.filter((run) => kind === "all"
      || run.kind === kind
      || (kind === "sequential" && run.kind === "sequential-all"));
    if (!isNodeSearchMode) return byKind;
    return byKind.filter((run) => (matchedRunCounts.get(run.id) ?? 0) > 0);
  }, [isNodeSearchMode, kind, matchedRunCounts, runs]);

  const totalMatchedAcrossRuns = useMemo(() => {
    let sum = 0;
    for (const count of matchedRunCounts.values()) sum += count;
    return sum;
  }, [matchedRunCounts]);

  const selected = selectedId !== ALL_MATCHES_ID ? (runsById.get(selectedId) ?? null) : null;
  const backends = useMemo(() => (
    isNodeSearchMode
      ? searchBackends
      : [...new Set(images.map((image) => image.info.backend).filter(Boolean) as string[])]
  ), [images, isNodeSearchMode, searchBackends]);

  const varying = useMemo(() => varyingRoles(images), [images]);
  const filtered = useMemo(() => (
    isNodeSearchMode
      ? images
      : images.filter((image) => (backend === "all" || image.info.backend === backend) && matchesQuery(image, query))
  ), [backend, images, isNodeSearchMode, query]);

  const showingAllMatches = isNodeSearchMode && selectedId === ALL_MATCHES_ID;

  // 在「全部匹配结果」模式下按批次分组展示；在单批次模式下按 group 子目录分组。
  const runSections = useMemo(() => {
    if (!showingAllMatches) return [];
    const map = new Map<string, { runId: string; runName: string; runKind?: HistoryRunKind; items: HistoryImage[] }>();
    for (const image of filtered) {
      const rid = image.run_id || "unknown";
      const existing = map.get(rid);
      if (existing) {
        existing.items.push(image);
      } else {
        const knownRun = runsById.get(rid);
        map.set(rid, {
          runId: rid,
          runName: knownRun ? runTitle(knownRun) : (image.run_name || rid),
          runKind: knownRun?.kind ?? image.run_kind,
          items: [image],
        });
      }
    }
    return [...map.values()];
  }, [filtered, runsById, showingAllMatches]);

  const groups = useMemo(() => {
    if (showingAllMatches) return [];
    const result = new Map<string, HistoryImage[]>();
    for (const image of filtered) result.set(image.group, [...(result.get(image.group) ?? []), image]);
    return [...result.entries()];
  }, [filtered, showingAllMatches]);

  const detailItems = useMemo<ImageDetailItem[]>(() => filtered.map((image) => ({
    path: image.path,
    label: imageCaption(image, varying),
    name: image.filename,
    badge: showingAllMatches
      ? (runsById.get(image.run_id ?? "")?.job?.label || image.run_name || undefined)
      : (image.group ? groupTitle(image.group) : undefined),
  })), [filtered, runsById, showingAllMatches, varying]);

  const indexOf = useMemo(() => new Map(filtered.map((image, index) => [image.path, index])), [filtered]);
  const thumb = tileSizes[tileSize].thumb;

  async function openFolder() {
    const path = images[0]?.path;
    if (!path) return;
    setFolderStatus("");
    try {
      await apiPost("/results/open-image-folder", { path });
    } catch (error) {
      setFolderStatus(errorMessage(error));
    }
  }

  function renderImageTile(image: HistoryImage, showTimeForLoose: boolean) {
    const caption = imageCaption(image, varying);
    const timing = formatImageTiming(image.info.timing ?? undefined);
    return (
      <figure className="task-tile" key={image.path}>
        <button
          aria-label={`打开 ${image.filename} 大图`}
          className="task-tile-image"
          onClick={() => setDetail({ items: detailItems, index: indexOf.get(image.path) ?? 0 })}
          type="button"
        >
          <img alt={caption} decoding="async" loading="lazy" src={thumbUrl(image.path, thumb)} />
        </button>
        <figcaption title={`${caption}\n${image.filename}`}>
          <span className="task-tile-label">{caption}</span>
          <span className="task-tile-meta">
            {image.info.seed !== null ? <span>Seed {image.info.seed}</span> : null}
            {timing ? <span>{timing}</span> : null}
            {showTimeForLoose ? <span>{formatDateTime(image.created_at).slice(11)}</span> : null}
          </span>
        </figcaption>
      </figure>
    );
  }

  return (
    <main className="history-page">
      <section className="panel history-runs" aria-label="出图批次">
        <div className="panel-title">
          <h2>出图历史</h2>
          <button
            aria-label="刷新出图历史"
            className="icon-button"
            disabled={loadingRuns}
            onClick={() => {
              void refreshRuns();
              if (isNodeSearchMode) void loadSearchImages(0, true);
              else if (selectedId) void loadRunImages(selectedId, 0);
            }}
            title="刷新"
            type="button"
          >
            <RefreshCw size={15} />
          </button>
        </div>
        <div className="history-kind-filter" role="group" aria-label="按类型筛选">
          {kindFilters.map((filter) => (
            <button
              aria-pressed={kind === filter.key}
              className={kind === filter.key ? "active" : ""}
              key={filter.key}
              onClick={() => setKind(filter.key)}
              type="button"
            >
              {filter.label}
            </button>
          ))}
        </div>
        {runsError ? <div className="alert error-alert">{runsError}</div> : null}
        <small className="field-hint">
          {isNodeSearchMode
            ? `已按节点筛选，命中 ${visibleRuns.length} 个批次。`
            : "按创建时间从新到旧；输出根目录的散图按日期归组，只读不动。"}
        </small>
        <div className="history-run-list">
          {isNodeSearchMode ? (
            <button
              aria-current={selectedId === ALL_MATCHES_ID}
              className={`history-all-matches-btn${selectedId === ALL_MATCHES_ID ? " active" : ""}`}
              onClick={() => setSelectedId(ALL_MATCHES_ID)}
              type="button"
            >
              <span className="history-all-matches-icon"><Layers size={18} /></span>
              <span className="history-run-text">
                <strong>全部匹配结果</strong>
                <small>{totalMatchedAcrossRuns} 张 · {matchedRunCounts.size} 个批次</small>
              </span>
            </button>
          ) : null}
          {visibleRuns.map((run) => {
            const matchCount = matchedRunCounts.get(run.id);
            return (
              <button
                aria-current={run.id === selectedId}
                className={run.id === selectedId ? "active" : ""}
                key={run.id}
                onClick={() => setSelectedId(run.id)}
                type="button"
              >
                {run.covers[0] ? <img alt="" decoding="async" loading="lazy" src={thumbUrl(run.covers[0], 160)} /> : <span className="history-run-cover" />}
                <span className="history-run-text">
                  <strong title={run.name}>{runTitle(run)}</strong>
                  <small>
                    <span className={`history-kind kind-${run.kind}`}>{kindLabels[run.kind]}</span>
                    {isNodeSearchMode && matchCount !== undefined
                      ? `命中 ${matchCount} / ${run.image_count} 张`
                      : `${run.image_count} 张${run.group_count > 1 ? ` · ${run.group_count} 组` : ""}`}
                  </small>
                  <small>{formatDateTime(run.created_at)}</small>
                </span>
              </button>
            );
          })}
          {!loadingRuns && !visibleRuns.length && !runsError ? (
            <div className="task-empty">{isNodeSearchMode ? "没有命中该节点筛选的批次。" : "没有出图记录。"}</div>
          ) : null}
        </div>
      </section>

      <section className="panel history-detail" aria-label="批次图片">
        <div className="history-filter-bar">
          <div className="history-filters">
            <HistoryNodeFilterPicker onToggle={toggleNodeFilter} selected={nodeFilters} />
            <label className="history-search">
              <Search size={14} />
              <input
                aria-label="筛选图片"
                onChange={(event) => setQuery(event.target.value)}
                placeholder="按节点名、seed、文件名筛选"
                value={query}
              />
              {query ? (
                <button aria-label="清空搜索" className="icon-button btn-ghost" onClick={() => setQuery("")} type="button">
                  <X size={13} />
                </button>
              ) : null}
            </label>
            {backends.length > 1 || backend !== "all" ? (
              <select aria-label="按后端筛选" onChange={(event) => setBackend(event.target.value)} value={backend}>
                <option value="all">全部后端</option>
                {backends.map((name) => <option key={name} value={name}>{name}</option>)}
              </select>
            ) : null}
            <small className="history-count-summary">
              {isNodeSearchMode
                ? `命中 ${total} 张`
                : (filtered.length === images.length ? `${images.length} 张` : `${filtered.length} / ${images.length} 张`)}
            </small>
            <div className="history-toolbar-right">
              <TileSizeToggle onChange={setTileSize} value={tileSize} />
            </div>
          </div>

          {nodeFilters.length > 0 || indexing?.running ? (
            <div className="history-active-filters" aria-label="当前节点筛选">
              {nodeFilters.map((filter) => (
                <span className={`history-node-chip role-${filter.role}`} key={nodeFilterKey(filter)} title={filter.ref || filter.name}>
                  <span className={`history-role-dot role-${filter.role}`} aria-hidden="true" />
                  <span className="history-node-chip-role">{HISTORY_ROLE_LABELS[filter.role] ?? filter.role}</span>
                  <span className="history-node-chip-name">{filter.name || filter.ref}</span>
                  <button
                    aria-label={`移除节点筛选 ${filter.name || filter.ref}`}
                    onClick={() => toggleNodeFilter(filter)}
                    type="button"
                  >
                    <X size={12} />
                  </button>
                </span>
              ))}
              {nodeFilters.length > 0 ? (
                <button className="btn-sm btn-ghost history-clear-nodes" onClick={clearNodeFilters} type="button">
                  清空节点筛选
                </button>
              ) : null}
              {indexing?.running ? (
                <span className="history-indexing-pill">
                  <LoaderCircle className="spin" size={12} />
                  正在索引 {indexing.indexed} / {indexing.total}…
                </span>
              ) : null}
            </div>
          ) : null}
        </div>

        {showingAllMatches ? (
          <>
            <div className="history-detail-header">
              <div>
                <h2>跨批次节点筛选结果</h2>
                <small>
                  共命中 {total} 张图片（分布在 {matchedRunCounts.size} 个批次），按生成时间从新到旧排列
                </small>
              </div>
              <div className="button-row">
                <button disabled={!images.length} onClick={() => void openFolder()} title="在资源管理器中打开首张图片所在位置" type="button">
                  <FolderOpen size={15} /> 打开文件夹
                </button>
              </div>
            </div>
            {folderStatus ? <div className="field-error">{folderStatus}</div> : null}
            {imagesError ? <div className="alert error-alert">{imagesError}</div> : null}
            {loadingImages && !images.length ? <div className="task-empty">加载中…</div> : null}
            {!loadingImages && !images.length && !imagesError ? (
              <div className="task-empty">没有找到同时包含这些节点的出图记录。</div>
            ) : null}
            <div className="history-groups">
              {runSections.map((section) => (
                <section className="task-group" key={section.runId}>
                  <div className="task-group-title history-run-section-title">
                    <button
                      className="history-run-section-link"
                      onClick={() => setSelectedId(section.runId)}
                      title="只看这个批次"
                      type="button"
                    >
                      {section.runKind ? <span className={`history-kind kind-${section.runKind}`}>{kindLabels[section.runKind]}</span> : null}
                      <span>{section.runName}</span>
                      <small>{section.items.length} 张</small>
                    </button>
                  </div>
                  <div className="task-tiles" style={tileGridStyle(tileSize)}>
                    {section.items.map((image) => renderImageTile(image, section.runKind === "loose"))}
                  </div>
                </section>
              ))}
            </div>
            {images.length < total ? (
              <button className="inline-button" disabled={loadingImages} onClick={() => void loadSearchImages(images.length)} type="button">
                加载更多（还有 {total - images.length} 张）
              </button>
            ) : null}
          </>
        ) : selected ? (
          <>
            <div className="history-detail-header">
              <div>
                <h2>{runTitle(selected)}</h2>
                <small>
                  {kindLabels[selected.kind]} · {formatDateTime(selected.created_at)} · {selected.image_count} 张
                  {selected.job ? ` · 任务 ${selected.job.id}` : ""}
                </small>
                <small className="history-path" title={selected.path}>{selected.path}</small>
              </div>
              <div className="button-row">
                {isNodeSearchMode ? (
                  <button className="btn-ghost" onClick={() => setSelectedId(ALL_MATCHES_ID)} type="button">
                    查看全部匹配批次
                  </button>
                ) : null}
                <button disabled={!images.length} onClick={() => void openFolder()} title="在资源管理器中打开" type="button"><FolderOpen size={15} /> 打开文件夹</button>
              </div>
            </div>
            {folderStatus ? <div className="field-error">{folderStatus}</div> : null}
            {imagesError ? <div className="alert error-alert">{imagesError}</div> : null}
            {loadingImages && !images.length ? <div className="task-empty">加载中…</div> : null}
            <div className="history-groups">
              {groups.map(([group, groupImages]) => (
                <section className="task-group" key={group || "root"}>
                  {group && groups.length > 1 ? <div className="task-group-title">{groupTitle(group)}</div> : null}
                  <div className="task-tiles" style={tileGridStyle(tileSize)}>
                    {groupImages.map((image) => renderImageTile(image, selected.kind === "loose"))}
                  </div>
                </section>
              ))}
            </div>
            {images.length < total ? (
              <button
                className="inline-button"
                disabled={loadingImages}
                onClick={() => void (isNodeSearchMode ? loadSearchImages(images.length) : loadRunImages(selected.id, images.length))}
                type="button"
              >
                加载更多（还有 {total - images.length} 张）
              </button>
            ) : null}
          </>
        ) : (
          <div className="task-empty">{loadingRuns ? "加载中…" : "选择左侧的一个批次，或点击上方「按节点筛选」跨批次查找。"}</div>
        )}
      </section>
      {detail ? <ImageDetailDialog initialIndex={detail.index} items={detail.items} onClose={() => setDetail(null)} onOpenNode={onOpenNode} /> : null}
    </main>
  );
}
