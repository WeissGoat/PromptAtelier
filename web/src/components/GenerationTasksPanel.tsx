import { AlertTriangle, ChevronDown, ChevronRight, CircleStop, FolderOpen, Loader2, Play, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { apiGet, apiPost, errorMessage, thumbUrl } from "../api/client";
import { describeJobProgress } from "../comfyui/jobProgress";
import { formatDuration, formatImageTiming } from "../generation/timing";
import {
  BACKGROUND_BATCH_JOB,
  BACKGROUND_RUNS_CHANGED,
  itemProgressJob,
  resumeBackgroundBatch,
  type BackgroundBatchItem,
  type BackgroundBatchJob,
} from "../generation/backgroundRun";
import { loadTileSize, tileGridStyle, tileSizes, type TileSize } from "../generation/tileSize";
import type { ImageDetailItem } from "./ImageDetailDialog";
import { TileSizeToggle } from "./TileSizeToggle";

const activeStatuses = new Set(["queued", "running", "cancelling"]);
const statusLabels: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  cancelling: "正在停止",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已停止",
  interrupted: "已中断",
};
const kindLabels: Record<string, string> = {
  primary: "Primary",
  random: "Random",
  sequential: "Sequential",
  compare: "Compare",
};
const labelKeys = ["artist", "character", "clothing", "action", "behavior"] as const;
// 排队项只画这么多个占位格，剩下的折成一行文字，几千项的任务也不会撑爆页面。
const QUEUED_PLACEHOLDERS = 4;
const PAGE_SIZE = 8;

export type OpenImages = (selection: { items: ImageDetailItem[]; index: number }) => void;

type Props = {
  onOpenImage: OpenImages;
  pollIntervalMs?: number;
};

function formatClock(seconds: number | undefined): string {
  if (!seconds) return "";
  const date = new Date(seconds * 1000);
  const today = new Date();
  const time = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return date.toDateString() === today.toDateString() ? time : `${date.getMonth() + 1}/${date.getDate()} ${time}`;
}

/** Compare 任务里各项之间真正不同的维度；图下只显示这些，相同的维度放到任务标题里不重复。 */
function varyingLabelKeys(items: BackgroundBatchItem[]): string[] {
  return labelKeys.filter((key) => new Set(items.map((item) => item.labels?.[key] ?? "")).size > 1);
}

function itemCaption(item: BackgroundBatchItem, varying: string[]): string {
  if (item.labels && varying.length) return varying.map((key) => item.labels?.[key]).filter(Boolean).join(" · ");
  return item.label ?? `#${item.index + 1}`;
}

function imageSeed(item: BackgroundBatchItem, meta: Record<string, unknown> | undefined): string | null {
  const seed = meta?.seed ?? item.seed;
  return typeof seed === "number" || typeof seed === "string" ? String(seed) : null;
}

function unfinishedCount(job: BackgroundBatchJob): number {
  return (job.result?.items ?? []).filter((item) => item.status !== "succeeded").length;
}

type TileProps = {
  job: BackgroundBatchJob;
  item: BackgroundBatchItem;
  caption: string;
  thumbSize: number;
  imageIndexes: Map<string, number>;
  onOpen(index: number): void;
};

function ItemTiles({ job, item, caption, thumbSize, imageIndexes, onOpen }: TileProps) {
  if (item.status === "succeeded" && item.images.length) {
    return (
      <>
        {item.images.map((image, index) => {
          const seed = imageSeed(item, image.meta);
          const timing = formatImageTiming(image.meta);
          const name = item.images.length > 1 ? `${caption} (${index + 1})` : caption;
          return (
            <figure className="task-tile" key={`${image.path}-${index}`}>
              <button
                aria-label={`打开 ${name} 大图`}
                className="task-tile-image"
                onClick={() => onOpen(imageIndexes.get(image.path) ?? 0)}
                type="button"
              >
                <img alt={name} decoding="async" loading="lazy" src={thumbUrl(image.path, thumbSize)} />
              </button>
              <figcaption title={item.label ?? caption}>
                <span className="task-tile-label">{name}</span>
                <span className="task-tile-meta">
                  {seed ? <span>Seed {seed}</span> : null}
                  {timing ? <span>{timing}</span> : null}
                </span>
              </figcaption>
            </figure>
          );
        })}
      </>
    );
  }
  const progress = item.status === "running"
    ? describeJobProgress(itemProgressJob(job, item), Date.now() / 1000) ?? "出图中"
    : null;
  const text = {
    running: progress,
    queued: "排队中",
    failed: item.error || "失败",
    cancelled: "已跳过",
    succeeded: "没有返回图片",
  }[item.status];
  return (
    <figure className={`task-tile task-tile-placeholder ${item.status}`} title={item.error ?? item.label ?? ""}>
      <div className="task-tile-image">
        {item.status === "running" ? <Loader2 className="spin" size={22} /> : null}
        {item.status === "failed" ? <AlertTriangle size={20} /> : null}
        <small>{text}</small>
      </div>
      <figcaption>
        <span className="task-tile-label">{caption}</span>
        {item.seed !== undefined ? <span className="task-tile-meta"><span>Seed {item.seed}</span></span> : null}
      </figcaption>
    </figure>
  );
}

function TaskCard({ job, open, tileSize, onToggle, onCancel, onResume, onOpenImage }: {
  job: BackgroundBatchJob;
  open: boolean;
  tileSize: TileSize;
  onToggle(): void;
  onCancel(id: string): void;
  onResume(id: string): void;
  onOpenImage: OpenImages;
}) {
  const [folderError, setFolderError] = useState("");
  const result = job.result;
  const items = useMemo(() => result?.items ?? [], [result]);
  const counts = result?.counts;
  const total = result?.total ?? items.length;
  const active = activeStatuses.has(job.status);
  const varying = useMemo(() => varyingLabelKeys(items), [items]);
  const shared = useMemo(() => {
    const first = items[0]?.labels;
    if (!first || !varying.length) return "";
    return labelKeys.filter((key) => !varying.includes(key) && first[key]).map((key) => first[key]).join(" · ");
  }, [items, varying]);
  const images = useMemo(() => items.flatMap((item) => item.status === "succeeded"
    ? item.images.map((image, index) => ({ item, image, index }))
    : []), [items]);
  const detailItems = useMemo<ImageDetailItem[]>(() => images.map(({ item, image, index }) => {
    const caption = itemCaption(item, varying);
    return {
      path: image.path,
      label: item.images.length > 1 ? `${caption} (${index + 1})` : caption,
      name: item.label ?? caption,
      badge: item.group !== undefined ? `Group ${item.group}` : undefined,
    };
  }), [images, varying]);
  const imageIndexes = useMemo(() => new Map(images.map(({ image }, index) => [image.path, index])), [images]);
  const done = (counts?.succeeded ?? 0) + (counts?.failed ?? 0) + (counts?.cancelled ?? 0);
  const percent = total ? Math.round((done / total) * 100) : 0;
  const leftover = unfinishedCount(job);
  const canResume = !active && leftover > 0 && Boolean(result);
  const running = items.find((item) => item.status === "running");
  const duration = !active && job.created_at && job.updated_at ? job.updated_at - job.created_at : null;
  const thumb = tileSizes[tileSize].thumb;
  const openAt = (index: number) => onOpenImage({ items: detailItems, index });

  async function openFolder() {
    const path = images[0]?.image.path;
    if (!path) return;
    setFolderError("");
    try {
      await apiPost("/results/open-image-folder", { path });
    } catch (requestError) {
      setFolderError(errorMessage(requestError));
    }
  }

  // Compare 按 Group（同一 seed）分行，其他任务按顺序平铺。
  const sections = useMemo(() => {
    const visible: BackgroundBatchItem[] = [];
    let queuedShown = 0;
    let hiddenQueued = 0;
    for (const item of items) {
      if (item.status === "queued") {
        if (queuedShown >= QUEUED_PLACEHOLDERS) {
          hiddenQueued += 1;
          continue;
        }
        queuedShown += 1;
      }
      visible.push(item);
    }
    const grouped = result?.kind === "compare" && items.some((item) => item.group !== undefined);
    if (!grouped) return { groups: [{ key: "all", title: "", items: visible }], hiddenQueued };
    const groups = new Map<number, BackgroundBatchItem[]>();
    for (const item of visible) {
      const key = item.group ?? 0;
      groups.set(key, [...(groups.get(key) ?? []), item]);
    }
    return {
      groups: [...groups.entries()].map(([group, groupItems]) => ({
        key: String(group),
        title: `Group ${group}${groupItems[0]?.seed !== undefined ? ` · Seed ${groupItems[0].seed}` : ""}`,
        items: groupItems,
      })),
      hiddenQueued,
    };
  }, [items, result?.kind]);

  return (
    <article className={`task-card status-${job.status}`}>
      <header className="task-card-header">
        <button aria-expanded={open} className="task-card-toggle" onClick={onToggle} type="button">
          {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          {result?.kind && kindLabels[result.kind] ? <span className="task-kind">{kindLabels[result.kind]}</span> : null}
          <strong>{result?.label ?? job.id}</strong>
        </button>
        <span className={`status-pill task-status-${job.status}`}>{statusLabels[job.status] ?? job.status}</span>
        <small className="task-card-time">
          {formatClock(job.created_at)}
          {duration && duration > 0 ? ` · 用时 ${formatDuration(duration)}` : ""}
        </small>
        <div className="task-card-actions">
          {active ? (
            <button disabled={job.status === "cancelling"} onClick={() => onCancel(job.id)} title="跑完当前这张后停止，剩下的跳过" type="button">
              <CircleStop size={15} /> 停止
            </button>
          ) : null}
          {canResume ? (
            <button onClick={() => onResume(job.id)} title="在原任务里继续没成功的项，图片写回原目录" type="button">
              <Play size={15} /> 继续剩余 {leftover} 项
            </button>
          ) : null}
          {images.length ? (
            <button aria-label="打开输出文件夹" onClick={() => void openFolder()} title={result?.output_dir ?? "打开输出文件夹"} type="button">
              <FolderOpen size={15} />
            </button>
          ) : null}
        </div>
      </header>
      {counts ? (
        <div className="task-progress" title={`${done} / ${total}`}>
          <div className="task-progress-bar"><span style={{ width: `${percent}%` }} /></div>
          <small>
            成功 {counts.succeeded} / {total}
            {counts.failed ? ` · 失败 ${counts.failed}` : ""}
            {counts.cancelled ? ` · 跳过 ${counts.cancelled}` : ""}
            {running ? ` · 正在跑第 ${running.index + 1} 项` : ""}
          </small>
        </div>
      ) : null}
      {job.status === "interrupted" ? (
        <div className="task-notice">Web 后端重启时这个任务还没跑完；已出的图都在，点「继续剩余」接着跑。</div>
      ) : null}
      {job.status === "failed" && job.error && !items.some((item) => item.status === "failed") ? <div className="field-error">{job.error}</div> : null}
      {folderError ? <div className="field-error">{folderError}</div> : null}
      {open ? (
        <div className="task-card-body">
          {shared ? <small className="task-shared">共同：{shared}</small> : null}
          {sections.groups.map((section) => (
            <section className="task-group" key={section.key}>
              {section.title ? <div className="task-group-title">{section.title}</div> : null}
              <div className="task-tiles" style={tileGridStyle(tileSize)}>
                {section.items.map((item) => (
                  <ItemTiles
                    caption={itemCaption(item, varying)}
                    imageIndexes={imageIndexes}
                    item={item}
                    job={job}
                    key={item.index}
                    onOpen={openAt}
                    thumbSize={thumb}
                  />
                ))}
              </div>
            </section>
          ))}
          {sections.hiddenQueued ? <small className="field-hint">还有 {sections.hiddenQueued} 项排队中</small> : null}
        </div>
      ) : images.length ? (
        <div className="task-strip">
          {images.slice(0, 8).map(({ item, image }, index) => (
            <button aria-label={`打开 ${itemCaption(item, varying)} 大图`} key={`${image.path}-${index}`} onClick={() => openAt(index)} type="button">
              <img alt="" decoding="async" loading="lazy" src={thumbUrl(image.path, 160)} />
            </button>
          ))}
          {images.length > 8 ? <span>+{images.length - 8}</span> : null}
        </div>
      ) : null}
    </article>
  );
}

/**
 * 出图任务：所有出图都交给 Web 后端排队跑，这里只看任务。
 * 任务记录存在后端（outputs/.web/jobs），刷新网页、关掉网页、重启后端都还在。
 */
export function GenerationTasksPanel({ onOpenImage, pollIntervalMs = 1500 }: Props) {
  const [jobs, setJobs] = useState<BackgroundBatchJob[]>([]);
  const [error, setError] = useState("");
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [tileSize, setTileSize] = useState<TileSize>(loadTileSize);
  // 用户手动展开 / 收起过的任务；没动过的按默认（最新一个和正在跑的展开）。
  const [toggled, setToggled] = useState<Record<string, boolean>>({});
  const [loaded, setLoaded] = useState(false);
  const timer = useRef<number | null>(null);
  const mounted = useRef(true);

  const refresh = useCallback(async () => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
    try {
      const response = await apiGet<{ jobs: BackgroundBatchJob[] }>(`/jobs?name=${BACKGROUND_BATCH_JOB}&limit=${limit + 1}`);
      if (!mounted.current) return;
      setJobs(response.jobs);
      setError("");
      if (response.jobs.some((job) => activeStatuses.has(job.status))) {
        timer.current = window.setTimeout(() => void refresh(), pollIntervalMs);
      }
    } catch (requestError) {
      if (mounted.current) setError(errorMessage(requestError));
    } finally {
      if (mounted.current) setLoaded(true);
    }
  }, [limit, pollIntervalMs]);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    const onChanged = () => void refresh();
    window.addEventListener(BACKGROUND_RUNS_CHANGED, onChanged);
    return () => {
      mounted.current = false;
      window.removeEventListener(BACKGROUND_RUNS_CHANGED, onChanged);
      if (timer.current !== null) window.clearTimeout(timer.current);
    };
  }, [refresh]);

  async function act(request: () => Promise<unknown>) {
    try {
      await request();
    } catch (requestError) {
      setError(errorMessage(requestError));
    }
    void refresh();
  }

  const shown = jobs.slice(0, limit);
  return (
    <section className="generation-tasks" aria-label="出图任务">
      <div className="section-title-row">
        <div>
          <h3>出图任务</h3>
          <small>在 Web 后端排队逐张跑；刷新、关掉网页或重启后端都不会丢，全部图片也在「出图历史」里。</small>
        </div>
        <div className="button-row task-toolbar">
          <TileSizeToggle onChange={setTileSize} value={tileSize} />
          <button aria-label="刷新任务" onClick={() => void refresh()} title="刷新" type="button"><RefreshCw size={15} /></button>
        </div>
      </div>
      {error ? <div className="alert error-alert">{error}</div> : null}
      {loaded && !shown.length && !error ? <div className="task-empty">还没有出图任务。点上面的 Generate 或 Compare Generate 开始。</div> : null}
      {shown.map((job, index) => (
        <TaskCard
          job={job}
          key={job.id}
          onCancel={(id) => void act(() => apiPost(`/jobs/${encodeURIComponent(id)}/cancel`, {}))}
          onOpenImage={onOpenImage}
          onResume={(id) => void act(() => resumeBackgroundBatch(id))}
          onToggle={() => setToggled((current) => ({
            ...current,
            [job.id]: !(current[job.id] ?? (index === 0 || activeStatuses.has(job.status))),
          }))}
          open={toggled[job.id] ?? (index === 0 || activeStatuses.has(job.status))}
          tileSize={tileSize}
        />
      ))}
      {jobs.length > limit ? (
        <button className="inline-button task-more" onClick={() => setLimit((current) => current + PAGE_SIZE)} type="button">显示更早的任务</button>
      ) : null}
    </section>
  );
}
