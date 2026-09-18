import {
  ArrowLeftRight,
  ChevronLeft,
  ChevronRight,
  Columns,
  Eye,
  FolderOpen,
  MoveHorizontal,
  Sparkles,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type MouseEvent } from "react";

import { apiGet, apiPost, apiUrl, errorMessage } from "../api/client";
import type {
  ImageMetadataResponse,
  ImageParameterDiffItem,
  ImageParameterDiffResponse,
} from "../api/types";

export type ImageDetailItem = {
  path: string;
  label?: string;
  name?: string;
  badge?: string;
  isControlGroup?: boolean;
};

type ImageDetailDialogProps = {
  paths?: string[];
  items?: ImageDetailItem[];
  initialIndex: number;
  onClose(): void;
};

type DiffCategory = "changed" | "added" | "removed";

const missingValue = "<missing>";

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function parameter(metadata: ImageMetadataResponse | null, key: string): unknown {
  return metadata?.parameters?.[key];
}

function diffCategory(item: ImageParameterDiffItem): DiffCategory {
  if (item.left === missingValue) return "added";
  if (item.right === missingValue) return "removed";
  return "changed";
}

function diffLabel(path: string): string {
  if (path === "$.input" || path === "$.parameters.prompt") return "Prompt";
  if (path === "$.parameters.uc" || path === "$.parameters.negative_prompt") return "Negative";
  if (path === "$.model" || path === "$.parameters.model") return "Model";
  return path
    .replace(/^\$\.parameters\./, "")
    .replace(/^\$\./, "")
    .replace(/_/g, " ");
}

function summarizeValue(value: unknown): string {
  if (value === missingValue || value === undefined) return "未设置";
  if (value === null) return "null";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const record = value as Record<string, unknown>;
    if (typeof record.sha256 === "string") {
      const size = typeof record.bytes === "number" ? ` · ${formatBytes(record.bytes)}` : "";
      return `${String(record.type ?? "image")} · ${record.sha256.slice(0, 12)}…${size}`;
    }
  }
  return JSON.stringify(value, null, 2);
}

type PromptDiffSummary = {
  removed: string[];
  added: string[];
};

function isPromptDiff(item: ImageParameterDiffItem): boolean {
  const path = item.path.toLowerCase();
  return path.includes("prompt") || path === "$.input" || path.endsWith(".uc");
}

function promptTags(value: unknown): string[] | null {
  if (value === missingValue) return [];
  if (typeof value !== "string") return null;
  return value.split(",").map((tag) => tag.trim()).filter(Boolean);
}

function promptDiffSummary(item: ImageParameterDiffItem): PromptDiffSummary | null {
  if (!isPromptDiff(item)) return null;
  const left = promptTags(item.left);
  const right = promptTags(item.right);
  if (!left || !right) return null;

  const lengths = Array.from({ length: left.length + 1 }, () => Array<number>(right.length + 1).fill(0));
  for (let leftIndex = left.length - 1; leftIndex >= 0; leftIndex -= 1) {
    for (let rightIndex = right.length - 1; rightIndex >= 0; rightIndex -= 1) {
      lengths[leftIndex][rightIndex] = left[leftIndex] === right[rightIndex]
        ? lengths[leftIndex + 1][rightIndex + 1] + 1
        : Math.max(lengths[leftIndex + 1][rightIndex], lengths[leftIndex][rightIndex + 1]);
    }
  }

  const removed: string[] = [];
  const added: string[] = [];
  let leftIndex = 0;
  let rightIndex = 0;
  while (leftIndex < left.length && rightIndex < right.length) {
    if (left[leftIndex] === right[rightIndex]) {
      leftIndex += 1;
      rightIndex += 1;
    } else if (lengths[leftIndex + 1][rightIndex] >= lengths[leftIndex][rightIndex + 1]) {
      removed.push(left[leftIndex]);
      leftIndex += 1;
    } else {
      added.push(right[rightIndex]);
      rightIndex += 1;
    }
  }
  removed.push(...left.slice(leftIndex));
  added.push(...right.slice(rightIndex));
  return { removed, added };
}

function visibleDiffs(diffs: ImageParameterDiffItem[]): ImageParameterDiffItem[] {
  const paths = new Set(diffs.map((item) => item.path));
  const seenPromptValues = new Set<string>();
  return diffs.filter((item) => {
    if (item.path === "$.parameters.prompt" && paths.has("$.input")) return false;
    if (item.path === "$.parameters.model" && paths.has("$.model")) return false;
    if (isPromptDiff(item)) {
      const signature = JSON.stringify([item.left, item.right]);
      if (seenPromptValues.has(signature)) return false;
      seenPromptValues.add(signature);
    }
    return true;
  });
}

function PromptSummary({ summary }: { summary: PromptDiffSummary }) {
  return (
    <div className="prompt-diff-summary">
      {summary.removed.length ? (
        <div className="prompt-diff-tags removed"><span>移除</span><div>{summary.removed.map((tag, index) => <code key={`removed-${index}-${tag}`}>{tag}</code>)}</div></div>
      ) : null}
      {summary.added.length ? (
        <div className="prompt-diff-tags added"><span>新增</span><div>{summary.added.map((tag, index) => <code key={`added-${index}-${tag}`}>{tag}</code>)}</div></div>
      ) : null}
    </div>
  );
}

function DiffGroup({
  category,
  items,
  referenceLabel,
  currentLabel,
}: {
  category: DiffCategory;
  items: ImageParameterDiffItem[];
  referenceLabel?: string;
  currentLabel?: string;
}) {
  if (!items.length) return null;
  const labels: Record<DiffCategory, string> = { changed: "变更", added: "新增", removed: "移除" };
  return (
    <section className={`parameter-diff-group ${category}`}>
      <h4>{labels[category]} <span>{items.length}</span></h4>
      <div className="parameter-diff-list">
        {items.map((item) => {
          const promptSummary = promptDiffSummary(item);
          return (
            <article className={`parameter-diff-item ${isPromptDiff(item) ? "wide" : ""}`} key={`${item.path}-${item.kind}`}>
              <strong>{diffLabel(item.path)}</strong>
              {promptSummary ? <PromptSummary summary={promptSummary} /> : (
                <div className="parameter-diff-values">
                  {category !== "added" ? (
                    <div className="diff-before">
                      <span>{referenceLabel ? `基准 (${referenceLabel})` : "上一张"}</span>
                      <pre>{summarizeValue(item.left)}</pre>
                    </div>
                  ) : null}
                  {category !== "removed" ? (
                    <div className="diff-after">
                      <span>{currentLabel ? `当前 (${currentLabel})` : "当前"}</span>
                      <pre>{summarizeValue(item.right)}</pre>
                    </div>
                  ) : null}
                </div>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}

export function ImageDetailDialog({ paths, items, initialIndex, onClose }: ImageDetailDialogProps) {
  const resolvedItems: ImageDetailItem[] = useMemo(() => {
    if (items && items.length > 0) return items;
    if (paths && paths.length > 0) {
      return paths.map((p, idx) => ({
        path: p,
        label: `第 ${idx + 1} 张`,
        name: `第 ${idx + 1} 张`,
      }));
    }
    return [];
  }, [items, paths]);

  const safeInitialIndex = Math.min(Math.max(initialIndex, 0), Math.max(resolvedItems.length - 1, 0));
  const [currentIndex, setCurrentIndex] = useState(safeInitialIndex);

  // Initialize reference index: if safeInitialIndex > 0, default to control group or 0; if at 0, default to null
  const [referenceIndex, setReferenceIndex] = useState<number | null>(() => {
    if (resolvedItems.length <= 1) return null;
    if (safeInitialIndex > 0) {
      const ctrlIdx = resolvedItems.findIndex((item) => item.isControlGroup);
      if (ctrlIdx >= 0 && ctrlIdx !== safeInitialIndex) return ctrlIdx;
      return 0;
    }
    return null;
  });

  const [compareMode, setCompareMode] = useState<"single" | "split" | "flicker">("single");
  const [sliderPos, setSliderPos] = useState(50);
  const [isDraggingSlider, setIsDraggingSlider] = useState(false);
  const [flickerTarget, setFlickerTarget] = useState<"current" | "reference">("current");
  const stageRef = useRef<HTMLDivElement | null>(null);

  const [metadata, setMetadata] = useState<ImageMetadataResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [diff, setDiff] = useState<ImageParameterDiffResponse | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [diffError, setDiffError] = useState("");
  const [diffExpanded, setDiffExpanded] = useState(false);
  const [folderStatus, setFolderStatus] = useState("");
  const [openingFolder, setOpeningFolder] = useState(false);

  const currentItem = resolvedItems[currentIndex];
  const currentPath = currentItem?.path ?? "";

  const referenceItem =
    referenceIndex !== null &&
    referenceIndex >= 0 &&
    referenceIndex < resolvedItems.length &&
    referenceIndex !== currentIndex
      ? resolvedItems[referenceIndex]
      : null;
  const referencePath = referenceItem?.path ?? null;

  const hasPrevious = currentIndex > 0;
  const hasNext = currentIndex < resolvedItems.length - 1;

  function handleSelectCurrent(newIndex: number) {
    setCurrentIndex(newIndex);
    if (referenceIndex === null && newIndex > 0) {
      const ctrlIdx = resolvedItems.findIndex((item) => item.isControlGroup);
      setReferenceIndex(ctrlIdx >= 0 && ctrlIdx !== newIndex ? ctrlIdx : 0);
    } else if (referenceIndex === newIndex) {
      // If user chooses current to be the same as reference, pick an alternative reference
      setReferenceIndex(newIndex === 0 ? (resolvedItems.length > 1 ? 1 : null) : 0);
    }
  }

  // Fetch metadata for currently viewed image
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    setMetadata(null);
    setFolderStatus("");
    if (!currentPath) {
      setLoading(false);
      return () => { active = false; };
    }
    void apiGet<ImageMetadataResponse>(`/results/image-metadata?${new URLSearchParams({ path: currentPath })}`)
      .then((result) => {
        if (active) setMetadata(result);
      })
      .catch((requestError) => {
        if (active) setError(errorMessage(requestError));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [currentPath]);

  // Fetch parameter diff against reference
  useEffect(() => {
    let active = true;
    setDiffExpanded(false);
    setDiff(null);
    setDiffError("");
    if (!referencePath || !currentPath) {
      setDiffLoading(false);
      return () => { active = false; };
    }
    setDiffLoading(true);
    const search = new URLSearchParams({ previous_path: referencePath, current_path: currentPath });
    void apiGet<ImageParameterDiffResponse>(`/results/image-parameter-diff?${search}`)
      .then((result) => {
        if (active) setDiff(result);
      })
      .catch((requestError) => {
        if (active) setDiffError(errorMessage(requestError));
      })
      .finally(() => {
        if (active) setDiffLoading(false);
      });
    return () => { active = false; };
  }, [currentPath, referencePath]);

  // Split slider mouse tracking
  useEffect(() => {
    if (!isDraggingSlider) return;

    function handleMouseMove(e: globalThis.MouseEvent) {
      if (!stageRef.current) return;
      const rect = stageRef.current.getBoundingClientRect();
      const rawX = e.clientX - rect.left;
      const pct = Math.max(0, Math.min(100, (rawX / rect.width) * 100));
      setSliderPos(pct);
    }

    function handleMouseUp() {
      setIsDraggingSlider(false);
    }

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isDraggingSlider]);

  // Keyboard navigation
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
        return;
      }
      const target = event.target;
      if (target instanceof Element && target.matches("input, textarea, select")) return;

      if (compareMode === "flicker") {
        if (event.key === " " || event.key === "ArrowLeft" || event.key === "ArrowRight") {
          event.preventDefault();
          setFlickerTarget((prev) => (prev === "current" ? "reference" : "current"));
          return;
        }
      }

      if (event.key === "ArrowLeft") handleSelectCurrent(Math.max(0, currentIndex - 1));
      if (event.key === "ArrowRight") handleSelectCurrent(Math.min(resolvedItems.length - 1, currentIndex + 1));
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [compareMode, currentIndex, onClose, resolvedItems.length, referenceIndex]);

  const commonParameters = useMemo(() => {
    const rows: Array<[string, unknown]> = [
      ["Seed", parameter(metadata, "seed")],
      ["Model", metadata?.model ?? parameter(metadata, "model")],
      ["Sampler", parameter(metadata, "sampler")],
      ["Steps", parameter(metadata, "steps")],
      ["Scale", parameter(metadata, "scale")],
      ["Noise schedule", parameter(metadata, "noise_schedule")],
    ];
    return rows.filter((row) => row[1] !== undefined && row[1] !== null);
  }, [metadata]);

  const groupedDiffs = useMemo(() => {
    const grouped: Record<DiffCategory, ImageParameterDiffItem[]> = { changed: [], added: [], removed: [] };
    for (const item of visibleDiffs(diff?.diffs ?? [])) grouped[diffCategory(item)].push(item);
    return grouped;
  }, [diff]);

  async function openFolder() {
    setOpeningFolder(true);
    setFolderStatus("");
    try {
      await apiPost("/results/open-image-folder", { path: currentPath });
      setFolderStatus("已在资源管理器中定位图片");
    } catch (requestError) {
      setFolderStatus(errorMessage(requestError));
    } finally {
      setOpeningFolder(false);
    }
  }

  const prompt = parameter(metadata, "prompt");
  const negative = parameter(metadata, "uc") ?? parameter(metadata, "negative_prompt");
  const visibleDiffCount = groupedDiffs.changed.length + groupedDiffs.added.length + groupedDiffs.removed.length;

  return (
    <div className="image-detail-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }} role="presentation">
      <section aria-label="图片详情" aria-modal="true" className="image-detail-dialog" role="dialog">
        <header className="image-detail-header">
          <div>
            <div className="image-detail-title-row">
              <h2>{metadata?.filename ?? currentItem?.name ?? currentItem?.label ?? "图片详情"}</h2>
              {currentItem?.label && currentItem.label !== metadata?.filename ? (
                <span className="image-detail-variant-name">{currentItem.label}</span>
              ) : null}
              {currentItem?.badge ? (
                <span className="image-detail-badge">{currentItem.badge}</span>
              ) : null}
              <span>{currentIndex + 1} / {resolvedItems.length}</span>
            </div>
            <small>{metadata?.path ?? currentPath}</small>
          </div>
          <button aria-label="关闭图片详情" className="icon-button" onClick={onClose} title="关闭" type="button"><X size={18} /></button>
        </header>

        <div className="image-detail-content">
          <div className="image-detail-left-pane">
            {/* Top comparison mode and reference bar */}
            <div className="image-detail-mode-bar" role="toolbar">
              <div className="mode-pill-group">
                <button
                  className={`mode-pill-btn ${compareMode === "single" ? "active" : ""}`}
                  onClick={() => setCompareMode("single")}
                  type="button"
                >
                  <Eye size={13} /> 单图查看
                </button>
                <button
                  className={`mode-pill-btn ${compareMode === "split" ? "active" : ""}`}
                  disabled={!referencePath}
                  onClick={() => setCompareMode("split")}
                  title={!referencePath ? "请先选择有效的对比基准" : "左右卷帘滑动对比"}
                  type="button"
                >
                  <Columns size={13} /> 卷帘对比
                </button>
                <button
                  className={`mode-pill-btn ${compareMode === "flicker" ? "active" : ""}`}
                  disabled={!referencePath}
                  onClick={() => setCompareMode("flicker")}
                  title={!referencePath ? "请先选择有效的对比基准" : "按空格键或点击快速闪烁比对"}
                  type="button"
                >
                  <Sparkles size={13} /> 瞬切闪烁
                </button>
              </div>

              {resolvedItems.length > 1 ? (
                <div className="reference-select-group">
                  <label htmlFor="ref-select">对比基准:</label>
                  <select
                    aria-label="选择对比基准"
                    className="reference-select"
                    id="ref-select"
                    onChange={(e) => {
                      const val = e.target.value;
                      setReferenceIndex(val === "" ? null : Number(val));
                    }}
                    value={referenceIndex ?? ""}
                  >
                    <option value="" disabled>-- 请选择基准 --</option>
                    {resolvedItems.map((item, idx) => (
                      <option disabled={idx === currentIndex} key={`${item.path}-${idx}`} value={idx}>
                        {idx === currentIndex
                          ? `${item.label || item.name || `第 ${idx + 1} 张`} (当前查看中)`
                          : `${item.label || item.name || `第 ${idx + 1} 张`}${item.badge ? ` [${item.badge}]` : ""}`}
                      </option>
                    ))}
                  </select>

                  {referenceIndex !== null && referenceIndex !== currentIndex ? (
                    <button
                      className="reference-swap-btn"
                      onClick={() => {
                        const oldRef = referenceIndex;
                        setReferenceIndex(currentIndex);
                        setCurrentIndex(oldRef);
                      }}
                      title="对调当前图与对比基准图"
                      type="button"
                    >
                      <ArrowLeftRight size={12} /> 对调
                    </button>
                  ) : null}
                </div>
              ) : null}
            </div>

            {/* Canvas Area */}
            <div className={`image-detail-canvas mode-${compareMode}`}>
              {compareMode === "single" ? (
                <>
                  <button
                    aria-label="上一张图片"
                    className="image-nav-button previous"
                    disabled={!hasPrevious}
                    onClick={() => handleSelectCurrent(Math.max(0, currentIndex - 1))}
                    title="上一张 (← 键)"
                    type="button"
                  >
                    <ChevronLeft size={24} />
                  </button>
                  <img
                    alt={metadata?.filename ?? currentItem?.label ?? "生成大图"}
                    src={apiUrl(`/results/image?path=${encodeURIComponent(currentPath)}`)}
                  />
                  <button
                    aria-label="下一张图片"
                    className="image-nav-button next"
                    disabled={!hasNext}
                    onClick={() => handleSelectCurrent(Math.min(resolvedItems.length - 1, currentIndex + 1))}
                    title="下一张 (→ 键)"
                    type="button"
                  >
                    <ChevronRight size={24} />
                  </button>
                </>
              ) : null}

              {compareMode === "split" && referencePath ? (
                <div
                  className="split-slider-stage"
                  onMouseDown={(e) => {
                    if (e.target === e.currentTarget) {
                      const rect = e.currentTarget.getBoundingClientRect();
                      const pct = Math.max(0, Math.min(100, ((e.clientX - rect.left) / rect.width) * 100));
                      setSliderPos(pct);
                    }
                  }}
                  ref={stageRef}
                >
                  <img
                    alt={referenceItem?.label ?? "基准图"}
                    className="split-stage-img left-img"
                    draggable={false}
                    src={apiUrl(`/results/image?path=${encodeURIComponent(referencePath)}`)}
                  />
                  <span className="image-layer-label left">
                    基准: {referenceItem?.label ?? "基准图"}
                  </span>

                  <div className="split-overlay-container" style={{ clipPath: `inset(0 0 0 ${sliderPos}%)` }}>
                    <img
                      alt={currentItem?.label ?? "当前图"}
                      className="split-stage-img right-img"
                      draggable={false}
                      src={apiUrl(`/results/image?path=${encodeURIComponent(currentPath)}`)}
                    />
                    <span className="image-layer-label right">
                      当前: {currentItem?.label ?? "当前图"}
                    </span>
                  </div>

                  <div
                    className="split-slider-line"
                    onMouseDown={(e) => {
                      e.stopPropagation();
                      e.preventDefault();
                      setIsDraggingSlider(true);
                    }}
                    style={{ left: `${sliderPos}%` }}
                  >
                    <div className="split-slider-handle" title="按住左右拖拽对比">
                      <MoveHorizontal size={14} />
                    </div>
                  </div>
                </div>
              ) : null}

              {compareMode === "flicker" && referencePath ? (
                <div
                  className="flicker-stage"
                  onClick={() => setFlickerTarget((prev) => (prev === "current" ? "reference" : "current"))}
                  title="点击或按空格键切换当前图与基准图"
                >
                  <img
                    alt={flickerTarget === "current" ? (currentItem?.label ?? "当前图") : (referenceItem?.label ?? "基准图")}
                    className="flicker-image"
                    draggable={false}
                    src={apiUrl(`/results/image?path=${encodeURIComponent(flickerTarget === "current" ? currentPath : referencePath)}`)}
                  />
                  <div className="flicker-badge">
                    <span>
                      正在显示：<strong>{flickerTarget === "current" ? `当前图 · ${currentItem?.label ?? ""}` : `基准图 · ${referenceItem?.label ?? ""}`}</strong>
                    </span>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setFlickerTarget((prev) => (prev === "current" ? "reference" : "current"));
                      }}
                      type="button"
                    >
                      切换 (空格键)
                    </button>
                  </div>
                </div>
              ) : null}
            </div>

            {/* Batch Filmstrip Navigation */}
            {resolvedItems.length > 1 ? (
              <div aria-label="同批图片缩略图列表" className="image-detail-filmstrip" role="region">
                {resolvedItems.map((item, idx) => {
                  const isCurrent = idx === currentIndex;
                  const isRef = idx === referenceIndex;
                  return (
                    <div
                      className={`filmstrip-card ${isCurrent ? "active" : ""} ${isRef ? "is-reference" : ""}`}
                      key={`${item.path}-${idx}`}
                      onClick={() => handleSelectCurrent(idx)}
                      role="button"
                      tabIndex={0}
                      title={`${item.label || item.name || `第 ${idx + 1} 张`} (点击切换查看)`}
                    >
                      <img
                        alt={item.label || `图片 ${idx + 1}`}
                        src={apiUrl(`/results/image?path=${encodeURIComponent(item.path)}`)}
                      />
                      <div className="filmstrip-info">
                        {item.label || item.name || `第 ${idx + 1} 张`}
                      </div>
                      {isCurrent ? <span className="filmstrip-pill current">当前</span> : null}
                      {isRef ? <span className="filmstrip-pill reference">基准</span> : null}
                      {item.badge && !isRef && !isCurrent ? (
                        <span className="filmstrip-pill badge">{item.badge}</span>
                      ) : null}
                      {!isRef && idx !== currentIndex ? (
                        <button
                          className="set-ref-btn"
                          onClick={(e) => {
                            e.stopPropagation();
                            setReferenceIndex(idx);
                          }}
                          title="设为此图为对比基准"
                          type="button"
                        >
                          设基准
                        </button>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            ) : null}
          </div>

          <aside className="image-metadata-panel">
            {loading ? <div className="image-metadata-message">正在从 PNG 读取元数据...</div> : null}
            {error ? <div className="alert error-alert" role="alert">{error}</div> : null}
            {metadata ? (
              <>
                <dl className="image-file-summary">
                  <div><dt>尺寸</dt><dd>{metadata.dimensions ? `${metadata.dimensions.width} × ${metadata.dimensions.height}` : "未知"}</dd></div>
                  <div><dt>文件大小</dt><dd>{formatBytes(metadata.size_bytes)}</dd></div>
                  <div><dt>修改时间</dt><dd>{new Date(metadata.modified_at).toLocaleString()}</dd></div>
                </dl>
                {metadata.metadata_error ? <div className="alert error-alert">{metadata.metadata_error}</div> : null}
                <dl className="image-parameter-summary">
                  {commonParameters.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{String(value)}</dd></div>)}
                </dl>

                {prompt !== undefined ? <label className="field"><span>Prompt</span><textarea readOnly value={String(prompt)} /></label> : null}
                {negative !== undefined ? <label className="field compact"><span>Negative</span><textarea readOnly value={String(negative)} /></label> : null}
                <details>
                  <summary>完整 PNG Parameters</summary>
                  <pre className="json-preview">{JSON.stringify(metadata.parameters, null, 2)}</pre>
                </details>
                <details>
                  <summary>全部 PNG Text</summary>
                  <pre className="json-preview">{JSON.stringify(metadata.png_text, null, 2)}</pre>
                </details>

                <section className={`parameter-diff-panel ${diffExpanded ? "expanded" : ""}`}>
                  <button aria-expanded={diffExpanded} className="parameter-diff-title" onClick={() => {
                    setDiffExpanded((expanded) => !expanded);
                  }} type="button">
                    <div>
                      <h3>参数 Diff</h3>
                      <small>
                        {referenceItem
                          ? `与【${referenceItem.label || referenceItem.name || `第 ${referenceIndex! + 1} 张`}】比较`
                          : "选择对比基准以查看差异"}
                      </small>
                    </div>
                    {referencePath && !diffLoading && !diffError ? <span className={visibleDiffCount ? "changed" : "matched"}>{visibleDiffCount} 项</span> : null}
                  </button>
                  {diffExpanded ? (
                    <div className="parameter-diff-summary-content">
                      {resolvedItems.length > 1 ? (
                        <div className="parameter-diff-reference-bar">
                          <span>对比基准：</span>
                          <select
                            aria-label="参数Diff对比基准"
                            className="parameter-diff-ref-select"
                            onChange={(e) => {
                              const val = e.target.value;
                              setReferenceIndex(val === "" ? null : Number(val));
                            }}
                            value={referenceIndex ?? ""}
                          >
                            <option value="" disabled>-- 请选择基准 --</option>
                            {resolvedItems.map((item, idx) => (
                              <option disabled={idx === currentIndex} key={`diff-ref-${item.path}-${idx}`} value={idx}>
                                {idx === currentIndex
                                  ? `${item.label || item.name} (当前正在查看)`
                                  : `${item.label || item.name}${item.badge ? ` [${item.badge}]` : ""}`}
                              </option>
                            ))}
                          </select>
                        </div>
                      ) : null}

                      {!referencePath ? (
                        <div className="parameter-diff-empty">
                          {resolvedItems.length <= 1 ? "这是序列中的第一张，没有上一张可比较。" : "请在上方选择对比基准以查看参数差异。"}
                        </div>
                      ) : null}
                      {diffLoading ? <div className="parameter-diff-empty">正在读取两张 PNG 的参数差异...</div> : null}
                      {diffError ? <div className="alert error-alert">{diffError}</div> : null}
                      {diff && !visibleDiffCount ? <div className="parameter-diff-match">生成参数一致</div> : null}
                      {diff ? (
                        <>
                          <div className="parameter-diff-overview">
                            <DiffGroup category="changed" currentLabel={currentItem?.label} items={groupedDiffs.changed} referenceLabel={referenceItem?.label} />
                            <DiffGroup category="added" currentLabel={currentItem?.label} items={groupedDiffs.added} referenceLabel={referenceItem?.label} />
                            <DiffGroup category="removed" currentLabel={currentItem?.label} items={groupedDiffs.removed} referenceLabel={referenceItem?.label} />
                          </div>
                          <details className="raw-parameter-diff"><summary>完整参数 Diff</summary><pre className="json-preview">{JSON.stringify(diff.diffs, null, 2)}</pre></details>
                        </>
                      ) : null}
                    </div>
                  ) : null}
                </section>
              </>
            ) : null}
          </aside>
        </div>

        <footer className="image-detail-footer">
          <span aria-live="polite">{folderStatus}</span>
          <button disabled={openingFolder} onClick={() => void openFolder()} type="button"><FolderOpen size={16} /> 打开所在文件夹</button>
        </footer>
      </section>
    </div>
  );
}

