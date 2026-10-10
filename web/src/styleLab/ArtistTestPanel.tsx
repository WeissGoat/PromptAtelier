import { FolderOutput, Grid3x3, LoaderCircle, Play, Square, Rows3, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { errorMessage, nodePreviewUrl } from "../api/client";
import type {
  ArtistExport,
  ArtistTestItem,
  ArtistTestRun,
  ArtistTestSettings,
  ImageRecord,
  LibraryNodeSummary,
  SeedMode,
} from "./api";
import { ACTIVE_RUN_STATUSES, runImageUrl, sourceImageUrl, startArtistTest } from "./api";
import { DuplicateNotice, duplicateOf, type DuplicateRequest } from "./DuplicateNotice";
import { MaterialSearch } from "./MaterialSearch";
import { formatTime, runStatusLabels } from "./format";
import { runViewerItem, useImageViewer, type ViewerItem } from "./ImageViewer";
import { Segmented, SIZE_PRESETS } from "./RegenPanel";

const MAX_REGRESSION = 12;
const DEFAULT_REGRESSION = 4;
const MAX_SIDE = 4;
const PICKER_LIMIT = 24;
const SKIP_FLAGS = new Set(["no_metadata", "inpaint", "img2img"]);

type ArtistTestPanelProps = {
  workspaceId: string;
  recipeId: string;
  recipeVersion: number;
  dirty: boolean;
  images: ImageRecord[];
  groupImageIds: string[] | null;
  sourceImageId: string | null;
  exports: ArtistExport[];
  runs: ArtistTestRun[];
  onExport: () => void;
  onStarted: (run: ArtistTestRun) => void;
  onCancel: (run: ArtistTestRun) => void;
};

/** 回归对照的候选：同组、有元数据、不是局部重绘/图生图；每个投稿一张，配方原图排第一，其余按日期从新到旧。 */
export function regressionCandidates(images: ImageRecord[], groupImageIds: string[] | null, sourceImageId: string | null): ImageRecord[] {
  const allowed = groupImageIds ? new Set(groupImageIds) : null;
  const usable = images.filter(
    (image) => image.has_metadata && !image.flags.some((flag) => SKIP_FLAGS.has(flag)) && (!allowed || allowed.has(image.id)),
  );
  usable.sort((a, b) => {
    if ((a.id === sourceImageId) !== (b.id === sourceImageId)) return a.id === sourceImageId ? -1 : 1;
    return (b.post?.date ?? "").localeCompare(a.post?.date ?? "");
  });
  const seen = new Set<string>();
  return usable.filter((image) => {
    const key = image.post?.post_id ?? image.id;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function ArtistTestPanel({
  workspaceId,
  recipeId,
  recipeVersion,
  dirty,
  images,
  groupImageIds,
  sourceImageId,
  exports,
  runs,
  onExport,
  onStarted,
  onCancel,
}: ArtistTestPanelProps) {
  const available = exports.filter((item) => item.exists);
  const [artist, setArtist] = useState<string | null>(null);
  const [mode, setMode] = useState<"regression" | "matrix">("regression");
  const [selectedImages, setSelectedImages] = useState<string[]>([]);
  const [characters, setCharacters] = useState<LibraryNodeSummary[]>([]);
  const [actions, setActions] = useState<LibraryNodeSummary[]>([]);
  const [seedMode, setSeedMode] = useState<SeedMode>("source");
  const [seed, setSeed] = useState<number | null>(null);
  const [size, setSize] = useState<[number, number]>([832, 1216]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [duplicate, setDuplicate] = useState<DuplicateRequest | null>(null);

  const latest = available[available.length - 1]?.folder ?? null;
  const activeArtist = artist && available.some((item) => item.folder === artist) ? artist : latest;
  const activeExport = available.find((item) => item.folder === activeArtist) ?? null;

  const candidates = useMemo(
    () => regressionCandidates(images, groupImageIds, sourceImageId).slice(0, PICKER_LIMIT),
    [images, groupImageIds, sourceImageId],
  );
  const candidateKey = candidates.map((image) => image.id).join(",");
  useEffect(() => {
    setSelectedImages(candidates.slice(0, DEFAULT_REGRESSION).map((image) => image.id));
    // 候选列表变了才重置默认选择。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candidateKey]);

  const cells = mode === "regression" ? selectedImages.length : Math.max(1, characters.length) * Math.max(1, actions.length);
  const ready =
    Boolean(activeArtist) &&
    !submitting &&
    (seedMode !== "fixed" || seed !== null) &&
    (mode === "regression" ? selectedImages.length > 0 : characters.length + actions.length > 0);

  const start = async (force = false) => {
    if (!activeArtist) return;
    const settings: ArtistTestSettings = {
      kind: mode,
      artist: activeArtist,
      image_ids: mode === "regression" ? selectedImages : [],
      characters: mode === "matrix" ? characters.map((node) => node.ref) : [],
      actions: mode === "matrix" ? actions.map((node) => node.ref) : [],
      seed_mode: seedMode,
      seed: seedMode === "fixed" ? seed : null,
      width: mode === "matrix" ? size[0] : null,
      height: mode === "matrix" ? size[1] : null,
    };
    setSubmitting(true);
    setError(null);
    setDuplicate(null);
    try {
      const { run } = await startArtistTest(workspaceId, recipeId, settings, force);
      onStarted(run);
    } catch (exc) {
      const found = duplicateOf(exc);
      if (found) setDuplicate(found);
      else setError(errorMessage(exc));
    } finally {
      setSubmitting(false);
    }
  };

  const toggleImage = (id: string) =>
    setSelectedImages((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : current.length >= MAX_REGRESSION ? current : [...current, id],
    );

  return (
    <section className="sl-zone zone-test">
      <header className="sl-zone-head">
        <span className="sl-zone-title">导出与测试</span>
        <span className="sl-muted">导出成 design/画风 里的 artist，再按名字读回来出图</span>
        <span className="sl-bar-spacer" />
        <button className="sl-primary small" onClick={onExport} type="button">
          <FolderOutput size={14} aria-hidden="true" />
          {dirty ? "保存并导出…" : "导出 artist…"}
        </button>
      </header>

      {exports.length ? (
        <div className="sl-export-list">
          {exports
            .slice()
            .reverse()
            .map((item) => (
              <button
                className={`sl-export-chip ${item.folder === activeArtist ? "on" : ""}`}
                disabled={!item.exists}
                key={`${item.folder}-${item.exported_at}`}
                onClick={() => setArtist(item.folder)}
                title={item.exists ? item.path : "目录已被删除或改名"}
                type="button"
              >
                <span className="sl-export-chip-name">{item.folder}</span>
                <span className="sl-muted">
                  配方 v{item.recipe_version} · {formatTime(item.exported_at)}
                </span>
                {!item.exists ? <span className="sl-pill bad">已不存在</span> : null}
                {item.exists && item.recipe_version < recipeVersion ? <span className="sl-pill warn">配方已更新到 v{recipeVersion}</span> : null}
              </button>
            ))}
        </div>
      ) : (
        <p className="sl-muted">还没有导出过。导出后可以用导出的 artist 做回归对照和泛化矩阵。</p>
      )}

      {activeExport ? (
        <>
          <div className="sl-form-row">
            <Segmented
              onChange={(value) => {
                const next = value as "regression" | "matrix";
                setMode(next);
                if (next === "matrix" && seedMode === "source") setSeedMode("random");
              }}
              options={[
                ["regression", "回归对照"],
                ["matrix", "泛化矩阵"],
              ]}
              value={mode}
            />
            <span className="sl-muted">
              {mode === "regression"
                ? "同组原图去掉画风后，用导出的 artist 按原种子、原尺寸重画，和原图对照"
                : "提示词库的角色 × 动作，共用一个种子，看画风换了内容还稳不稳"}
            </span>
          </div>

          {mode === "regression" ? (
            <div className="sl-test-picker">
              <div className="sl-test-picker-head">
                <span>
                  选了 {selectedImages.length} 张（最多 {MAX_REGRESSION}）
                </span>
                <button className="sl-link-btn" onClick={() => setSelectedImages(candidates.slice(0, DEFAULT_REGRESSION).map((image) => image.id))} type="button">
                  恢复默认
                </button>
              </div>
              <div className="sl-test-thumbs">
                {candidates.map((image) => (
                  <button
                    aria-pressed={selectedImages.includes(image.id)}
                    className={`sl-test-thumb ${selectedImages.includes(image.id) ? "on" : ""}`}
                    key={image.id}
                    onClick={() => toggleImage(image.id)}
                    title={`${image.post?.post_id ?? image.rel_path}${image.id === sourceImageId ? "（配方原图）" : ""}`}
                    type="button"
                  >
                    <img alt="" loading="lazy" src={sourceImageUrl(workspaceId, image.id, 160)} />
                    {image.id === sourceImageId ? <span className="sl-test-thumb-tag">原图</span> : null}
                    {selectedImages.includes(image.id) ? <span className="sl-test-thumb-order">{selectedImages.indexOf(image.id) + 1}</span> : null}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="sl-test-matrix-pick">
              <NodePicker label="角色（行）" onChange={setCharacters} role="character" selected={characters} />
              <NodePicker label="动作（列）" onChange={setActions} role="action" selected={actions} />
            </div>
          )}

          <div className="sl-form-row">
            <span className="sl-form-label">种子</span>
            <Segmented
              onChange={(value) => setSeedMode(value as SeedMode)}
              options={[
                ["source", mode === "regression" ? "各自原图" : "配方原图"],
                ["random", mode === "regression" ? "随机（共用）" : "随机"],
                ["fixed", "指定"],
              ]}
              value={seedMode}
            />
            {seedMode === "fixed" ? (
              <input
                aria-label="指定种子"
                onChange={(event) => setSeed(event.target.value === "" ? null : Number(event.target.value))}
                type="number"
                value={seed ?? ""}
              />
            ) : null}
            {mode === "matrix" ? (
              <>
                <span className="sl-form-label">尺寸</span>
                {SIZE_PRESETS.map(([w, h]) => (
                  <button
                    className={`sl-mini-btn ${size[0] === w && size[1] === h ? "on" : ""}`}
                    key={`${w}x${h}`}
                    onClick={() => setSize([w, h])}
                    type="button"
                  >
                    {w}×{h}
                  </button>
                ))}
              </>
            ) : null}
          </div>
          {error ? <p className="sl-error">{error}</p> : null}
          {duplicate ? (
            <DuplicateNotice duplicate={duplicate} onDismiss={() => setDuplicate(null)} onForce={() => void start(true)} />
          ) : null}
          <button className="sl-primary" disabled={!ready} onClick={() => void start()} type="button">
            <Play size={15} aria-hidden="true" />
            {submitting ? "提交中…" : `用 ${activeArtist} 生成 · ${cells} 张`}
          </button>
        </>
      ) : null}

      {runs.length ? (
        <div className="sl-test-runs">
          {runs.map((run) => (
            <TestRunCard key={run.id} onCancel={onCancel} run={run} workspaceId={workspaceId} />
          ))}
        </div>
      ) : null}
    </section>
  );
}

function NodePicker({
  role,
  label,
  selected,
  onChange,
}: {
  role: "character" | "action";
  label: string;
  selected: LibraryNodeSummary[];
  onChange: (nodes: LibraryNodeSummary[]) => void;
}) {
  const add = (node: LibraryNodeSummary) => {
    if (selected.length >= MAX_SIDE || selected.some((item) => item.ref === node.ref)) return;
    onChange([...selected, node]);
  };

  return (
    <div className="sl-node-picker">
      <div className="sl-node-picker-head">
        <span className="sl-form-label">{label}</span>
        <span className="sl-muted">
          {selected.length}/{MAX_SIDE}
        </span>
      </div>
      <div className="sl-node-chips">
        {selected.map((node) => (
          <span className="sl-node-chip" key={node.ref}>
            {node.has_preview ? <img alt="" src={nodePreviewUrl(node.ref, 64)} /> : null}
            {node.name}
            <button aria-label={`移除 ${node.name}`} className="sl-icon-btn" onClick={() => onChange(selected.filter((item) => item.ref !== node.ref))} type="button">
              <X size={12} />
            </button>
          </span>
        ))}
      </div>
      <MaterialSearch
        disabled={selected.length >= MAX_SIDE}
        isPicked={(ref) => selected.some((item) => item.ref === ref)}
        onPick={add}
        placeholder={selected.length >= MAX_SIDE ? "已选满" : `搜索${label}`}
        role={role}
      />
    </div>
  );
}

function nodeName(ref: string | null | undefined): string {
  if (!ref) return "—";
  const parts = ref.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] ?? ref;
}

function similarityText(item: ArtistTestItem): string | null {
  const value = item.compare?.similarity;
  return typeof value === "number" ? `${(value * 100).toFixed(1)}%` : null;
}

export function meanSimilarity(run: ArtistTestRun): number | null {
  const values = run.items.map((item) => item.compare?.similarity).filter((value): value is number => typeof value === "number");
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
}

function TestRunCard({ run, workspaceId, onCancel }: { run: ArtistTestRun; workspaceId: string; onCancel: (run: ArtistTestRun) => void }) {
  const active = ACTIVE_RUN_STATUSES.has(run.status);
  const mean = meanSimilarity(run);
  return (
    <article className="sl-test-run">
      <header className="sl-run-head">
        {run.kind === "regression" ? <Rows3 size={14} aria-hidden="true" /> : <Grid3x3 size={14} aria-hidden="true" />}
        <strong>{run.kind === "regression" ? "回归对照" : "泛化矩阵"}</strong>
        <span className="sl-muted">{run.artist.folder}</span>
        <span>{formatTime(run.created_at)}</span>
        <span className={`sl-run-status ${run.status}`}>
          {active ? <LoaderCircle className="sl-spin" size={12} /> : null}
          {runStatusLabels[run.status]}
        </span>
        {mean !== null ? <span className="sl-verdict-num">平均相似度 {(mean * 100).toFixed(1)}%</span> : null}
        {active && run.job_id ? (
          <button aria-label="停止" className="sl-icon-btn" onClick={() => onCancel(run)} title="停止剩余张数" type="button">
            <Square size={12} />
          </button>
        ) : null}
      </header>
      {run.error ? <p className="sl-error">{run.error}</p> : null}
      {run.kind === "regression" ? <RegressionGrid run={run} workspaceId={workspaceId} /> : <MatrixGrid run={run} workspaceId={workspaceId} />}
    </article>
  );
}

/** 一次测试里所有图（回归对照含原图）按顺序排成一组，点哪张就从哪张开始看。 */
function testViewerItems(run: ArtistTestRun): ViewerItem[] {
  return run.items.flatMap((item) => {
    const label = item.label ?? [item.character, item.action].filter(Boolean).map((ref) => nodeName(ref)).join(" · ");
    return [
      ...(item.source ? [{ file: { imageId: item.source.image_id }, label: `${label} · 原图`, path: item.source.path }] : []),
      ...(item.image_path ? [runViewerItem(item.image_path, label ? `${label} · 生成` : "生成", item.seed)] : []),
    ];
  });
}

function useOpenTestImage(run: ArtistTestRun) {
  const viewer = useImageViewer();
  return (match: (file: ViewerItem["file"]) => boolean) => {
    const items = testViewerItems(run);
    viewer.open(items, Math.max(0, items.findIndex((entry) => match(entry.file))));
  };
}

function Generated({
  item,
  workspaceId,
  size,
  onOpen,
}: {
  item: ArtistTestItem;
  workspaceId: string;
  size: number;
  onOpen: (path: string) => void;
}) {
  const imagePath = item.image_path;
  if (imagePath) {
    return (
      <button className="sl-zoomable" onClick={() => onOpen(imagePath)} title="查看大图和文件位置" type="button">
        <img alt="生成" loading="lazy" src={runImageUrl(workspaceId, imagePath, size)} />
      </button>
    );
  }
  return (
    <div className="sl-test-empty" title={item.error_detail ?? item.error}>
      {item.status === "running" ? <LoaderCircle className="sl-spin" size={16} /> : item.error ?? runStatusLabels[item.status]}
    </div>
  );
}

function RegressionGrid({ run, workspaceId }: { run: ArtistTestRun; workspaceId: string }) {
  const open = useOpenTestImage(run);
  const openGenerated = (path: string) => open((file) => "path" in file && file.path === path);
  return (
    <div className="sl-regression-grid">
      {run.items.map((item) => (
        <figure className="sl-regression-pair" key={item.index}>
          <div className="sl-regression-images">
            {item.source ? (
              <button
                className="sl-zoomable"
                onClick={() => open((file) => "imageId" in file && file.imageId === item.source!.image_id)}
                title="查看大图和文件位置"
                type="button"
              >
                <img alt="原图" loading="lazy" src={sourceImageUrl(workspaceId, item.source.image_id, 320)} />
              </button>
            ) : (
              <div className="sl-test-empty">无原图</div>
            )}
            <Generated item={item} onOpen={openGenerated} size={320} workspaceId={workspaceId} />
          </div>
          <figcaption>
            <span>{item.label}</span>
            <span className="sl-muted">种子 {item.seed}</span>
            {similarityText(item) ? <span className="sl-verdict-num">{similarityText(item)}</span> : null}
          </figcaption>
          {item.subject !== undefined ? (
            <details className="sl-regression-subject">
              <summary>内容提示词</summary>
              <p>{item.subject || "（空）"}</p>
              {item.removed?.length ? <p className="sl-muted">去掉的画风：{item.removed.join(", ")}</p> : null}
            </details>
          ) : null}
        </figure>
      ))}
    </div>
  );
}

function MatrixGrid({ run, workspaceId }: { run: ArtistTestRun; workspaceId: string }) {
  const open = useOpenTestImage(run);
  const openGenerated = (path: string) => open((file) => "path" in file && file.path === path);
  const rows = run.settings.characters.length ? run.settings.characters : [null];
  const cols = run.settings.actions.length ? run.settings.actions : [null];
  const cell = (character: string | null, action: string | null) =>
    run.items.find((item) => (item.character ?? null) === character && (item.action ?? null) === action);
  return (
    <div className="sl-matrix-scroll">
      <table className="sl-matrix">
        <thead>
          <tr>
            <th />
            {cols.map((action) => (
              <th key={action ?? "none"} title={action ?? undefined}>
                <span className="sl-matrix-label">{action ? nodeName(action) : "（无动作）"}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((character) => (
            <tr key={character ?? "none"}>
              <th title={character ?? undefined}>
                <span className="sl-matrix-label">{character ? nodeName(character) : "（无角色）"}</span>
              </th>
              {cols.map((action) => {
                const item = cell(character, action);
                return <td key={action ?? "none"}>{item ? <Generated item={item} onOpen={openGenerated} size={240} workspaceId={workspaceId} /> : null}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="sl-muted">种子 {run.items[0]?.seed}</p>
    </div>
  );
}
