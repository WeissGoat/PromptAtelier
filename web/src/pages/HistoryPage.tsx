import { FolderOpen, RefreshCw, Search } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { apiGet, apiPost, errorMessage, thumbUrl } from "../api/client";
import type { HistoryImage, HistoryRun, HistoryRunImagesResponse, HistoryRunKind } from "../api/types";
import { ImageDetailDialog, type ImageDetailItem } from "../components/ImageDetailDialog";
import { TileSizeToggle } from "../components/TileSizeToggle";
import { formatImageTiming } from "../generation/timing";
import { loadTileSize, tileGridStyle, tileSizes, type TileSize } from "../generation/tileSize";

const PAGE_SIZE = 300;
const SELECTED_RUN_KEY = "promptatelier.history-run/v1";
const kindLabels: Record<HistoryRunKind, string> = {
  compare: "Compare",
  random: "Random",
  sequential: "Sequential",
  "sequential-all": "Sequential",
  primary: "Primary",
  loose: "散图",
  other: "其他",
};
const kindFilters: Array<{ key: string; label: string }> = [
  { key: "all", label: "全部" },
  { key: "compare", label: "Compare" },
  { key: "random", label: "Random" },
  { key: "sequential", label: "Sequential" },
  { key: "primary", label: "Primary" },
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

export function HistoryPage() {
  const [runs, setRuns] = useState<HistoryRun[]>([]);
  const [runsError, setRunsError] = useState("");
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [kind, setKind] = useState("all");
  const [selectedId, setSelectedId] = useState(loadSelectedRun);
  const [images, setImages] = useState<HistoryImage[]>([]);
  const [total, setTotal] = useState(0);
  const [imagesError, setImagesError] = useState("");
  const [loadingImages, setLoadingImages] = useState(false);
  const [query, setQuery] = useState("");
  const [backend, setBackend] = useState("all");
  const [tileSize, setTileSize] = useState<TileSize>(loadTileSize);
  const [detail, setDetail] = useState<{ items: ImageDetailItem[]; index: number } | null>(null);
  const [folderStatus, setFolderStatus] = useState("");

  const refreshRuns = useCallback(async () => {
    setLoadingRuns(true);
    setRunsError("");
    try {
      const response = await apiGet<{ runs: HistoryRun[] }>("/history/runs");
      setRuns(response.runs);
      setSelectedId((current) => response.runs.some((run) => run.id === current) ? current : response.runs[0]?.id ?? "");
    } catch (error) {
      setRunsError(errorMessage(error));
    } finally {
      setLoadingRuns(false);
    }
  }, []);

  const loadImages = useCallback(async (runId: string, offset: number) => {
    if (!runId) return;
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

  useEffect(() => {
    void refreshRuns();
  }, [refreshRuns]);

  useEffect(() => {
    setImages([]);
    setTotal(0);
    setQuery("");
    setBackend("all");
    setFolderStatus("");
    if (selectedId) {
      saveSelectedRun(selectedId);
      void loadImages(selectedId, 0);
    }
  }, [loadImages, selectedId]);

  const visibleRuns = useMemo(() => runs.filter((run) => kind === "all"
    || run.kind === kind
    || (kind === "sequential" && run.kind === "sequential-all")), [kind, runs]);
  const selected = runs.find((run) => run.id === selectedId) ?? null;
  const backends = useMemo(() => [...new Set(images.map((image) => image.info.backend).filter(Boolean) as string[])], [images]);
  const varying = useMemo(() => varyingRoles(images), [images]);
  const filtered = useMemo(() => images.filter((image) => (backend === "all" || image.info.backend === backend) && matchesQuery(image, query)), [backend, images, query]);
  const groups = useMemo(() => {
    const result = new Map<string, HistoryImage[]>();
    for (const image of filtered) result.set(image.group, [...(result.get(image.group) ?? []), image]);
    return [...result.entries()];
  }, [filtered]);
  const detailItems = useMemo<ImageDetailItem[]>(() => filtered.map((image) => ({
    path: image.path,
    label: imageCaption(image, varying),
    name: image.filename,
    badge: image.group ? groupTitle(image.group) : undefined,
  })), [filtered, varying]);
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

  return (
    <main className="history-page">
      <section className="panel history-runs" aria-label="出图批次">
        <div className="panel-title">
          <h2>出图历史</h2>
          <button aria-label="刷新出图历史" className="icon-button" disabled={loadingRuns} onClick={() => {
            void refreshRuns();
            void loadImages(selectedId, 0);
          }} title="刷新" type="button">
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
        <small className="field-hint">按创建时间从新到旧；outputs 根目录的散图按日期归组，只读不动。</small>
        <div className="history-run-list">
          {visibleRuns.map((run) => (
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
                  {run.image_count} 张{run.group_count > 1 ? ` · ${run.group_count} 组` : ""}
                </small>
                <small>{formatDateTime(run.created_at)}</small>
              </span>
            </button>
          ))}
          {!loadingRuns && !visibleRuns.length && !runsError ? <div className="task-empty">没有出图记录。</div> : null}
        </div>
      </section>

      <section className="panel history-detail" aria-label="批次图片">
        {selected ? (
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
                <TileSizeToggle onChange={setTileSize} value={tileSize} />
                <button disabled={!images.length} onClick={() => void openFolder()} title="在资源管理器中打开" type="button"><FolderOpen size={15} /> 打开文件夹</button>
              </div>
            </div>
            <div className="history-filters">
              <label className="history-search">
                <Search size={14} />
                <input
                  aria-label="筛选图片"
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="按节点名、seed、文件名筛选"
                  value={query}
                />
              </label>
              {backends.length > 1 ? (
                <select aria-label="按后端筛选" onChange={(event) => setBackend(event.target.value)} value={backend}>
                  <option value="all">全部后端</option>
                  {backends.map((name) => <option key={name} value={name}>{name}</option>)}
                </select>
              ) : null}
              <small>{filtered.length === images.length ? `${images.length} 张` : `${filtered.length} / ${images.length} 张`}</small>
            </div>
            {folderStatus ? <div className="field-error">{folderStatus}</div> : null}
            {imagesError ? <div className="alert error-alert">{imagesError}</div> : null}
            {loadingImages && !images.length ? <div className="task-empty">加载中…</div> : null}
            <div className="history-groups">
              {groups.map(([group, groupImages]) => (
                <section className="task-group" key={group || "root"}>
                  {group && groups.length > 1 ? <div className="task-group-title">{groupTitle(group)}</div> : null}
                  <div className="task-tiles" style={tileGridStyle(tileSize)}>
                    {groupImages.map((image) => {
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
                              {selected.kind === "loose" ? <span>{formatDateTime(image.created_at).slice(11)}</span> : null}
                            </span>
                          </figcaption>
                        </figure>
                      );
                    })}
                  </div>
                </section>
              ))}
            </div>
            {images.length < total ? (
              <button className="inline-button" disabled={loadingImages} onClick={() => void loadImages(selected.id, images.length)} type="button">
                加载更多（还有 {total - images.length} 张）
              </button>
            ) : null}
          </>
        ) : (
          <div className="task-empty">{loadingRuns ? "加载中…" : "选择左侧的一个批次。"}</div>
        )}
      </section>
      {detail ? <ImageDetailDialog initialIndex={detail.index} items={detail.items} onClose={() => setDetail(null)} /> : null}
    </main>
  );
}
