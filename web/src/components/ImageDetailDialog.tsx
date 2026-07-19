import { ChevronLeft, ChevronRight, FolderOpen, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { apiGet, apiPost, apiUrl, errorMessage } from "../api/client";
import type {
  ImageMetadataResponse,
  ImageParameterDiffItem,
  ImageParameterDiffResponse,
} from "../api/types";

type ImageDetailDialogProps = {
  paths: string[];
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

function DiffGroup({ category, items }: { category: DiffCategory; items: ImageParameterDiffItem[] }) {
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
                  {category !== "added" ? <div className="diff-before"><span>上一张</span><pre>{summarizeValue(item.left)}</pre></div> : null}
                  {category !== "removed" ? <div className="diff-after"><span>当前</span><pre>{summarizeValue(item.right)}</pre></div> : null}
                </div>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}

export function ImageDetailDialog({ paths, initialIndex, onClose }: ImageDetailDialogProps) {
  const safeInitialIndex = Math.min(Math.max(initialIndex, 0), Math.max(paths.length - 1, 0));
  const [currentIndex, setCurrentIndex] = useState(safeInitialIndex);
  const [metadata, setMetadata] = useState<ImageMetadataResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [diff, setDiff] = useState<ImageParameterDiffResponse | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [diffError, setDiffError] = useState("");
  const [diffExpanded, setDiffExpanded] = useState(false);
  const [folderStatus, setFolderStatus] = useState("");
  const [openingFolder, setOpeningFolder] = useState(false);
  const path = paths[currentIndex] ?? "";
  const previousPath = currentIndex > 0 ? paths[currentIndex - 1] : null;
  const hasPrevious = currentIndex > 0;
  const hasNext = currentIndex < paths.length - 1;

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    setMetadata(null);
    setFolderStatus("");
    void apiGet<ImageMetadataResponse>(`/results/image-metadata?${new URLSearchParams({ path })}`)
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
  }, [path]);

  useEffect(() => {
    let active = true;
    setDiffExpanded(false);
    setDiff(null);
    setDiffError("");
    if (!previousPath) {
      setDiffLoading(false);
      return () => { active = false; };
    }
    setDiffLoading(true);
    const search = new URLSearchParams({ previous_path: previousPath, current_path: path });
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
  }, [path, previousPath]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
        return;
      }
      const target = event.target;
      if (target instanceof Element && target.matches("input, textarea, select")) return;
      if (event.key === "ArrowLeft") setCurrentIndex((index) => Math.max(0, index - 1));
      if (event.key === "ArrowRight") setCurrentIndex((index) => Math.min(paths.length - 1, index + 1));
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose, paths.length]);

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
      await apiPost("/results/open-image-folder", { path });
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
              <h2>{metadata?.filename ?? "图片详情"}</h2>
              <span>{currentIndex + 1} / {paths.length}</span>
            </div>
            <small>{metadata?.path ?? path}</small>
          </div>
          <button aria-label="关闭图片详情" className="icon-button" onClick={onClose} title="关闭" type="button"><X size={18} /></button>
        </header>

        <div className="image-detail-content">
          <div className="image-detail-canvas">
            <button aria-label="上一张图片" className="image-nav-button previous" disabled={!hasPrevious} onClick={() => setCurrentIndex((index) => Math.max(0, index - 1))} title="上一张" type="button"><ChevronLeft size={24} /></button>
            <img alt={metadata?.filename ?? "生成大图"} src={apiUrl(`/results/image?path=${encodeURIComponent(path)}`)} />
            <button aria-label="下一张图片" className="image-nav-button next" disabled={!hasNext} onClick={() => setCurrentIndex((index) => Math.min(paths.length - 1, index + 1))} title="下一张" type="button"><ChevronRight size={24} /></button>
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
                    <div><h3>参数 Diff</h3><small>{hasPrevious ? `与第 ${currentIndex} 张比较` : "上一张作为比较基准"}</small></div>
                    {hasPrevious && !diffLoading && !diffError ? <span className={visibleDiffCount ? "changed" : "matched"}>{visibleDiffCount} 项</span> : null}
                  </button>
                  {diffExpanded ? <div className="parameter-diff-summary-content">
                    {!hasPrevious ? <div className="parameter-diff-empty">这是序列中的第一张，没有上一张可比较。</div> : null}
                    {diffLoading ? <div className="parameter-diff-empty">正在读取两张 PNG 的参数差异...</div> : null}
                    {diffError ? <div className="alert error-alert">{diffError}</div> : null}
                    {diff && !visibleDiffCount ? <div className="parameter-diff-match">生成参数一致</div> : null}
                    {diff ? (
                      <>
                        <div className="parameter-diff-overview">
                          <DiffGroup category="changed" items={groupedDiffs.changed} />
                          <DiffGroup category="added" items={groupedDiffs.added} />
                          <DiffGroup category="removed" items={groupedDiffs.removed} />
                        </div>
                        <details className="raw-parameter-diff"><summary>完整参数 Diff</summary><pre className="json-preview">{JSON.stringify(diff.diffs, null, 2)}</pre></details>
                      </>
                    ) : null}
                  </div> : null}
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
