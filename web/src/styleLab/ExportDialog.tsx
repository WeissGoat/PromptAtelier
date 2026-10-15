import { CircleCheck, CircleX, FolderOutput, LoaderCircle, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { errorMessage } from "../api/client";
import type { ArtistDiff, ArtistExport, ExportDefaults, ExportPreview, ExportRequest, TokenDiff } from "./api";
import { exportArtist, getExportDefaults, previewExport } from "./api";
import { formatValue } from "./format";

const NAME_RE = /^[A-Za-z0-9]+(?:_[A-Za-z0-9]+)*$/;
const PREVIEW_DELAY_MS = 300;
const LONG_LINE = 400;

type ExportDialogProps = {
  workspaceId: string;
  recipeId: string;
  onClose: () => void;
  onExported: (entry: ArtistExport) => void;
};

/** 导出前先看清楚：写到哪个目录、tags.txt 的内容、和已有画风差在哪里、读回校验是否通过。 */
export function ExportDialog({ workspaceId, recipeId, onClose, onExported }: ExportDialogProps) {
  const [defaults, setDefaults] = useState<ExportDefaults | null>(null);
  const [author, setAuthor] = useState("");
  const [name, setName] = useState("");
  const [compareRef, setCompareRef] = useState<string | null>(null);
  const [includeSource, setIncludeSource] = useState(true);
  const [preview, setPreview] = useState<ExportPreview | null>(null);
  const [previewKey, setPreviewKey] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    getExportDefaults(workspaceId, recipeId)
      .then((data) => {
        setDefaults(data);
        setAuthor(data.author ?? "");
        // 再次导出时沿用上次的画风名，后端会建并列版本。
        const last = data.exports[data.exports.length - 1];
        if (last) setName(stripAuthor(last.folder, data.author));
      })
      .catch((exc) => setError(errorMessage(exc)));
  }, [workspaceId, recipeId]);

  const request: ExportRequest = useMemo(
    () => ({ name: name.trim(), author: author.trim() || null, compare_ref: compareRef, include_source: includeSource }),
    [name, author, compareRef, includeSource],
  );
  const requestKey = JSON.stringify(request);
  const nameValid = NAME_RE.test(request.name);

  useEffect(() => {
    if (!defaults || !nameValid) {
      setPreview(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    const timer = setTimeout(async () => {
      try {
        const data = await previewExport(workspaceId, recipeId, request);
        if (cancelled) return;
        setPreview(data.preview);
        setPreviewKey(requestKey);
        setError(null);
      } catch (exc) {
        if (!cancelled) setError(errorMessage(exc));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, PREVIEW_DELAY_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // request 由 requestKey 代表。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defaults, workspaceId, recipeId, requestKey, nameValid, refresh]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  const current = preview && previewKey === requestKey && !loading;
  const submit = async () => {
    if (!preview) return;
    setBusy(true);
    setError(null);
    try {
      const data = await exportArtist(workspaceId, recipeId, request, preview.folder);
      onExported(data.export);
    } catch (exc) {
      setError(
        (exc as { status?: number }).status === 409 ? "目标目录刚被占用了，已重新预览，请确认新的目录名后再导出。" : errorMessage(exc),
      );
      setPreviewKey("");
      setRefresh((value) => value + 1);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="sl-modal-backdrop" role="presentation">
      <section aria-label="导出 artist" aria-modal="true" className="sl-modal sl-export" role="dialog">
        <header className="sl-modal-head">
          <FolderOutput size={18} aria-hidden="true" />
          <h2>导出 artist</h2>
          <span className="sl-bar-spacer" />
          <button aria-label="关闭" className="sl-icon-btn" disabled={busy} onClick={onClose} type="button">
            <X size={16} />
          </button>
        </header>

        <div className="sl-modal-body">
          <div className="sl-export-form">
            <label>
              <span>作者 id</span>
              <input onChange={(event) => setAuthor(event.target.value)} placeholder="105845157" value={author} />
            </label>
            <label className="grow">
              <span>画风名（英文，下划线分词）</span>
              <input
                aria-invalid={Boolean(name) && !nameValid}
                autoFocus
                onChange={(event) => setName(event.target.value)}
                placeholder="Crisp_Manga_Ink"
                value={name}
              />
            </label>
            <label className="sl-check">
              <input checked={includeSource} onChange={(event) => setIncludeSource(event.target.checked)} type="checkbox" />
              附带原图和原图提示词
            </label>
          </div>
          <p className="sl-hint">
            用 2～4 个描述画面的英文词，例如 Crisp_Manga_Ink、Soft_Pastel_Anime；模型、vibe、日期等写进 notes.md，不放进名字。
          </p>
          {name && !nameValid ? <p className="sl-error">画风名只能用英文字母、数字和单个下划线。</p> : null}
          {error ? <p className="sl-error">{error}</p> : null}

          {preview ? (
            <>
              <div className="sl-export-target">
                <code>
                  {defaults?.artist_root ?? preview.artist_root}\<strong>{preview.folder}</strong>
                </code>
                {preview.exists ? (
                  <span className="sl-pill warn">{preview.requested_folder} 已存在，导出为并列版本</span>
                ) : (
                  <span className="sl-pill">新目录</span>
                )}
                {preview.vibe_count ? <span className="sl-pill">vibe {preview.vibe_count} 张</span> : null}
              </div>
              <div className={`sl-export-check ${preview.roundtrip_ok ? "ok" : "bad"}`}>
                {preview.roundtrip_ok ? <CircleCheck size={15} aria-hidden="true" /> : <CircleX size={15} aria-hidden="true" />}
                {preview.roundtrip_ok
                  ? "读回校验通过：用正式读取器读回的前缀、后缀、负面、参数和配方完全一致。"
                  : `读回校验失败：${preview.problems.join("；")}。通常是某一段以 type 开头或含有 origin_uc / gen_json 字样。`}
              </div>
              {preview.warnings.map((warning) => (
                <p className="sl-hint warn" key={warning}>
                  {warning}
                </p>
              ))}

              <section className="sl-export-section">
                <header>
                  <h3>和已有画风对比</h3>
                  {preview.candidates.length ? (
                    <select
                      aria-label="对比对象"
                      onChange={(event) => setCompareRef(event.target.value || null)}
                      value={preview.compare?.ref ?? ""}
                    >
                      {preview.candidates.map((ref) => (
                        <option key={ref} value={ref}>
                          {ref}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <span className="sl-muted">这个作者还没有已导出的画风</span>
                  )}
                </header>
                {preview.compare?.error ? <p className="sl-error">{preview.compare.error}</p> : null}
                {preview.compare?.diff ? <DiffView diff={preview.compare.diff} /> : null}
              </section>

              <section className="sl-export-section">
                <header>
                  <h3>tags.txt</h3>
                  <span className="sl-muted">另写入 {preview.files.filter((file) => file !== "tags.txt").join("、")}</span>
                </header>
                <pre className="sl-export-tags">{shortenLines(preview.tags_txt)}</pre>
              </section>
            </>
          ) : !error && nameValid ? (
            <p className="sl-muted">
              <LoaderCircle className="sl-spin" size={14} /> 生成预览…
            </p>
          ) : null}
        </div>

        <footer className="sl-modal-foot">
          <button className="sl-ghost" disabled={busy} onClick={onClose} type="button">
            取消
          </button>
          <button
            className="sl-primary"
            disabled={!current || !preview?.roundtrip_ok || busy}
            onClick={() => void submit()}
            type="button"
          >
            <FolderOutput size={15} aria-hidden="true" />
            {busy ? "导出中…" : preview ? `导出到 ${preview.folder}` : "导出"}
          </button>
        </footer>
      </section>
    </div>
  );
}

function stripAuthor(folder: string, author: string | null): string {
  const name = author && folder.startsWith(`${author}_`) ? folder.slice(author.length + 1) : folder;
  return name.replace(/_v\d+$/, "");
}

/** gen_json 带 vibe 时一行几十 KB，预览里截断显示。 */
function shortenLines(text: string): string {
  return text
    .split("\n")
    .map((line) => (line.length > LONG_LINE ? `${line.slice(0, LONG_LINE)}…（共 ${line.length} 字）` : line))
    .join("\n");
}

const SECTION_LABELS: Array<[keyof ArtistDiff, string]> = [
  ["prefix", "前缀"],
  ["suffix", "后缀"],
  ["negative", "负面"],
];

export function DiffView({ diff }: { diff: ArtistDiff }) {
  const sameStyle = diff.style.same;
  const moved = !sameStyle && !diff.style.added.length && !diff.style.removed.length;
  const sections = SECTION_LABELS.filter(([key]) => !(diff[key] as TokenDiff).same);
  if (sameStyle && diff.negative.same && !diff.params.length && !diff.flags) {
    return <p className="sl-muted">完全相同。</p>;
  }
  return (
    <div className="sl-artist-diff">
      {moved ? <p className="sl-hint">画风 token 相同，只是前后缀位置或顺序不同。</p> : null}
      {sections.map(([key, label]) => {
        const part = diff[key] as TokenDiff;
        return (
          <div className="sl-artist-diff-row" key={key}>
            <span className="sl-artist-diff-label">{label}</span>
            <div className="sl-prompt-diff">
              {part.removed.map((tag, index) => (
                <span className="sl-diff-tag removed" key={`r-${index}`} title="只在已有画风">
                  − {tag}
                </span>
              ))}
              {part.added.map((tag, index) => (
                <span className="sl-diff-tag added" key={`a-${index}`} title="只在这次导出">
                  + {tag}
                </span>
              ))}
              {!part.added.length && !part.removed.length ? <span className="sl-muted">token 相同，顺序不同</span> : null}
            </div>
          </div>
        );
      })}
      {diff.params.length ? (
        <table className="sl-artist-diff-params">
          <thead>
            <tr>
              <th>参数</th>
              <th>已有</th>
              <th>这次</th>
            </tr>
          </thead>
          <tbody>
            {diff.params.map((item) => (
              <tr key={item.key}>
                <td>{item.key === "vibe" ? "vibe 张数" : item.key}</td>
                <td>{formatValue(item.before)}</td>
                <td>{formatValue(item.after)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {diff.flags ? (
        <p className="sl-hint">
          标记：{diff.flags.before.join(", ") || "无"} → {diff.flags.after.join(", ") || "无"}
        </p>
      ) : null}
    </div>
  );
}
