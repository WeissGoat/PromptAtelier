import { ChevronDown, ChevronRight, ExternalLink, FolderOutput, Grid3x3, LoaderCircle, Play, Square, Rows3 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { errorMessage } from "../api/client";
import type {
  ArtistExport,
  ArtistTestItem,
  ArtistTestRun,
  ArtistTestSettings,
  ImageRecord,
  MaterialRole,
  MatrixCell,
  Recipe,
  RecipeMaterial,
  SeedMode,
  SizeMode,
} from "./api";
import { ACTIVE_RUN_STATUSES, runImageUrl, sourceImageUrl, startArtistTest } from "./api";
import { DuplicateNotice, duplicateOf, type DuplicateRequest } from "./DuplicateNotice";
import { formatTime, runStatusLabels } from "./format";
import { runViewerItem, useImageViewer, type ViewerItem } from "./ImageViewer";
import { shelfMaterials } from "./LibraryPanel";
import { loadNode, nodeTags } from "./libraryNodes";
import { useMaterialShelf } from "./materialShelf";
import {
  defaultPlacement,
  materialOrigin,
  materialTags,
  matrixCellRecipe,
  tokensToText,
  type MatrixPick,
  type MatrixPlacement,
} from "./recipeModel";
import { CompareView } from "./RunPanel";
import { Segmented, SIZE_MODE_HINTS, SIZE_PRESETS } from "./RegenPanel";

const MAX_REGRESSION = 12;
const DEFAULT_REGRESSION = 4;
const PICKER_LIMIT = 24;
/** 测试记录默认显示最近几次，更早的点一下再展开。 */
const RUN_LIMIT = 5;
const SKIP_FLAGS = new Set(["no_metadata", "inpaint", "img2img"]);
const MATRIX_ROLES: MaterialRole[] = ["character", "action"];
const MATRIX_SIDE_LABELS: Record<MaterialRole, string> = { character: "角色（行）", action: "动作（列）" };

type ArtistTestPanelProps = {
  workspaceId: string;
  recipeId: string;
  recipeVersion: number;
  dirty: boolean;
  images: ImageRecord[];
  groupImageIds: string[] | null;
  sourceImageId: string | null;
  /** 编辑区当前的配方：泛化矩阵在它的主体、角色提示词上换进角色和动作。 */
  draft: Recipe;
  exports: ArtistExport[];
  runs: ArtistTestRun[];
  onExport: () => void;
  onUseInCustom: (artist: ArtistExport) => void | Promise<void>;
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
  draft,
  exports,
  runs,
  onExport,
  onUseInCustom,
  onStarted,
  onCancel,
}: ArtistTestPanelProps) {
  const available = exports.filter((item) => item.exists);
  const [artist, setArtist] = useState<string | null>(null);
  const [mode, setMode] = useState<"regression" | "matrix">("regression");
  const [selectedImages, setSelectedImages] = useState<string[]>([]);
  // 泛化矩阵直接用右边素材库的已选角色、动作；这里只记取消勾选的和改过的摆放位置。
  const { shelf } = useMaterialShelf();
  const [skipped, setSkipped] = useState<string[]>([]);
  const [placementOverride, setPlacementOverride] = useState<Partial<Record<MaterialRole, MatrixPlacement>>>({});
  const onShelf = shelfMaterials(shelf, draft);
  const pool = (role: MaterialRole) => onShelf.filter((item) => item.role === role);
  const chosenOf = (role: MaterialRole) => pool(role).filter((item) => !skipped.includes(materialOrigin(item)));
  const characters = chosenOf("character");
  const actions = chosenOf("action");
  const captionCount = draft.character.captions.length;
  const placementOf = (role: MaterialRole): MatrixPlacement => {
    const value = placementOverride[role] ?? defaultPlacement(draft, role);
    return value === "subject" ? value : Math.min(value, captionCount);
  };
  const [seedMode, setSeedMode] = useState<SeedMode>("source");
  const [seed, setSeed] = useState<number | null>(null);
  const [size, setSize] = useState<[number, number]>([832, 1216]);
  // 回归默认各自原图尺寸，矩阵默认自定义（竖图）；切换模式时各自记住。
  const [regressionSize, setRegressionSize] = useState<SizeMode>("source");
  const [matrixSize, setMatrixSize] = useState<SizeMode>("custom");
  const sizeMode = mode === "regression" ? regressionSize : matrixSize;
  const setSizeMode = mode === "regression" ? setRegressionSize : setMatrixSize;
  const [dropped, setDropped] = useState<"keep" | "strip">("keep");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openingInCustom, setOpeningInCustom] = useState<string | null>(null);
  const [openInCustomError, setOpenInCustomError] = useState<string | null>(null);
  const [duplicate, setDuplicate] = useState<DuplicateRequest | null>(null);
  // 展开看结果的那次测试；没点过时展开最新一次，其余只显示一行。
  const [openRun, setOpenRun] = useState<string | null>(null);
  const [showAllRuns, setShowAllRuns] = useState(false);
  const latestRunId = runs[0]?.id ?? null;
  useEffect(() => setOpenRun(null), [latestRunId]);
  const expandedRun = openRun ?? latestRunId;

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
    setSubmitting(true);
    setError(null);
    setDuplicate(null);
    try {
      const settings: ArtistTestSettings = {
        kind: mode,
        artist: activeArtist,
        image_ids: mode === "regression" ? selectedImages : [],
        characters: mode === "matrix" ? characters.map((item) => item.ref) : [],
        actions: mode === "matrix" ? actions.map((item) => item.ref) : [],
        seed_mode: seedMode,
        seed: seedMode === "fixed" ? seed : null,
        size_mode: sizeMode,
        width: sizeMode === "custom" ? size[0] : null,
        height: sizeMode === "custom" ? size[1] : null,
        dropped,
      };
      if (mode === "matrix") {
        const placement = { character: placementOf("character"), action: placementOf("action") };
        settings.cells = await matrixCells(draft, characters, actions, placement);
        settings.placement = Object.fromEntries(
          MATRIX_ROLES.filter((role) => (role === "character" ? characters : actions).length).map((role) => [
            role,
            placementKey(placement[role]),
          ]),
        );
      }
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

  const openInCustom = async (item: ArtistExport) => {
    setArtist(item.folder);
    setOpeningInCustom(item.folder);
    setOpenInCustomError(null);
    try {
      await onUseInCustom(item);
    } catch (exc) {
      setOpenInCustomError(errorMessage(exc));
    } finally {
      setOpeningInCustom(null);
    }
  };

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
              <div className="sl-export-item" key={`${item.folder}-${item.exported_at}`}>
                <button
                  className={`sl-export-chip ${item.folder === activeArtist ? "on" : ""}`}
                  disabled={!item.exists}
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
                <button
                  aria-label={`在 Custom 使用 ${item.folder}`}
                  className="sl-mini-btn sl-export-use"
                  disabled={!item.exists || openingInCustom !== null}
                  onClick={() => void openInCustom(item)}
                  title={item.exists ? `跳到 Custom 并选中 ${item.folder}` : "目录已被删除或改名"}
                  type="button"
                >
                  {openingInCustom === item.folder ? (
                    <LoaderCircle className="sl-spin" size={12} aria-hidden="true" />
                  ) : (
                    <ExternalLink size={12} aria-hidden="true" />
                  )}
                  {openingInCustom === item.folder ? "读取中…" : "在 Custom 使用"}
                </button>
              </div>
            ))}
        </div>
      ) : (
        <p className="sl-muted">还没有导出过。导出后可以用导出的 artist 做回归对照和泛化矩阵。</p>
      )}
      {openInCustomError ? <p className="sl-error">{openInCustomError}</p> : null}

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
                : "右边素材库已选的角色 × 动作，换进上面配方的主体、角色提示词，共用一个种子，看画风换了内容还稳不稳"}
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
              {MATRIX_ROLES.map((role) => (
                <MatrixSide
                  captions={draft.character.captions.map((caption) => tokensToText(caption.tokens).trim())}
                  chosen={role === "character" ? characters : actions}
                  defaultValue={defaultPlacement(draft, role)}
                  key={role}
                  onPlacement={(value) => setPlacementOverride((current) => ({ ...current, [role]: value }))}
                  onToggle={(item) =>
                    setSkipped((current) => {
                      const origin = materialOrigin(item);
                      return current.includes(origin) ? current.filter((value) => value !== origin) : [...current, origin];
                    })
                  }
                  placement={placementOf(role)}
                  pool={pool(role)}
                  role={role}
                />
              ))}
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
          </div>
          <div className="sl-form-row">
            <span className="sl-form-label">尺寸</span>
            <Segmented
              onChange={(value) => setSizeMode(value as SizeMode)}
              options={[
                ...(mode === "regression" ? ([["source", "各自原图"]] as Array<[string, string]>) : []),
                ["custom", "指定"],
                ["random", "随机"],
                ["loop", "轮换"],
              ]}
              value={sizeMode}
            />
            {sizeMode === "custom"
              ? SIZE_PRESETS.map(([w, h]) => (
                  <button
                    className={`sl-mini-btn ${size[0] === w && size[1] === h ? "on" : ""}`}
                    key={`${w}x${h}`}
                    onClick={() => setSize([w, h])}
                    type="button"
                  >
                    {w}×{h}
                  </button>
                ))
              : null}
            {SIZE_MODE_HINTS[sizeMode] ? <span className="sl-muted">{SIZE_MODE_HINTS[sizeMode]}</span> : null}
          </div>
          {mode === "regression" ? (
            <div className="sl-form-row">
              <span className="sl-form-label">丢弃的词</span>
              <Segmented
                onChange={(value) => setDropped(value as "keep" | "strip")}
                options={[
                  ["keep", "留在内容里"],
                  ["strip", "一起去掉"],
                ]}
                value={dropped}
              />
              <span className="sl-muted">
                {dropped === "keep"
                  ? "原图里有这些词，留着才是和原图比同一张图，只看画风还原得准不准"
                  : "去掉后看导出的画风本身能画成什么样（丢弃的词如果影响画风，会和原图差得多）"}
              </span>
            </div>
          ) : null}
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
          {(showAllRuns ? runs : runs.slice(0, RUN_LIMIT)).map((run) => (
            <TestRunCard
              key={run.id}
              onCancel={onCancel}
              onToggle={() => setOpenRun(run.id === expandedRun ? "" : run.id)}
              open={run.id === expandedRun}
              run={run}
              workspaceId={workspaceId}
            />
          ))}
          {runs.length > RUN_LIMIT ? (
            <button className="sl-link-btn" onClick={() => setShowAllRuns(!showAllRuns)} type="button">
              {showAllRuns ? "只看最近的" : `更早的 ${runs.length - RUN_LIMIT} 次`}
            </button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

/** 矩阵每一格：读出素材块筛过的 tag，在配方上换进这一格的角色和动作。 */
async function matrixCells(
  draft: Recipe,
  characters: RecipeMaterial[],
  actions: RecipeMaterial[],
  placement: Record<MaterialRole, MatrixPlacement>,
): Promise<MatrixCell[]> {
  const pick = async (material: RecipeMaterial): Promise<MatrixPick> => ({
    material,
    tags: materialTags(material, nodeTags(await loadNode(material.ref, material.role))),
  });
  const rows: Array<MatrixPick | null> = characters.length ? await Promise.all(characters.map(pick)) : [null];
  const cols: Array<MatrixPick | null> = actions.length ? await Promise.all(actions.map(pick)) : [null];
  return rows.flatMap((character) =>
    cols.map((action) => {
      const recipe = matrixCellRecipe(draft, { character, action }, placement);
      return {
        character: character?.material.ref ?? null,
        action: action?.material.ref ?? null,
        subject: recipe.subject,
        captions: recipe.character,
      };
    }),
  );
}

function placementKey(value: MatrixPlacement): string {
  return value === "subject" ? "subject" : `caption:${value}`;
}

function placementText(key: string | undefined): string | null {
  if (!key) return null;
  return key === "subject" ? "主体" : `角色提示词 #${Number(key.slice("caption:".length)) + 1}`;
}

function MatrixSide({
  role,
  pool,
  chosen,
  captions,
  placement,
  defaultValue,
  onToggle,
  onPlacement,
}: {
  role: MaterialRole;
  /** 素材架上这一类的全部块。 */
  pool: RecipeMaterial[];
  chosen: RecipeMaterial[];
  captions: string[];
  placement: MatrixPlacement;
  defaultValue: MatrixPlacement;
  onToggle: (material: RecipeMaterial) => void;
  onPlacement: (value: MatrixPlacement) => void;
}) {
  const label = MATRIX_SIDE_LABELS[role];
  const verb = role === "character" ? "替换" : "加到";
  const optionLabel = (value: MatrixPlacement) => {
    const caption = value === "subject" ? "" : captions[value] ?? "";
    const text =
      value === "subject"
        ? "主体"
        : value < captions.length
          ? `${verb}角色提示词 #${value + 1}${caption ? `：${caption.length > 16 ? `${caption.slice(0, 16)}…` : caption}` : "（空）"}`
          : `新加一条角色提示词 #${value + 1}`;
    return value === defaultValue ? `${text}（同上方）` : text;
  };
  const values: MatrixPlacement[] = ["subject", ...captions.map((_, index) => index), captions.length];
  return (
    <div className="sl-node-picker">
      <div className="sl-node-picker-head">
        <span className="sl-form-label">{label}</span>
        <span className="sl-muted">
          {chosen.length}/{pool.length}
        </span>
      </div>
      {pool.length ? (
        <div className="sl-node-chips">
          {pool.map((material) => {
            const on = chosen.includes(material);
            return (
              <button
                aria-pressed={on}
                className={`sl-mini-btn ${on ? "on" : ""}`}
                key={materialOrigin(material)}
                onClick={() => onToggle(material)}
                title={on ? "点击不用这块" : "点击用这块"}
                type="button"
              >
                {material.name}
              </button>
            );
          })}
        </div>
      ) : (
        <p className="sl-muted">右边素材库还没有已选{role === "character" ? "角色" : "动作"}。</p>
      )}
      <label className="sl-matrix-place">
        <span className="sl-muted">放到</span>
        <select
          aria-label={`${label}放到`}
          disabled={!chosen.length}
          onChange={(event) => onPlacement(event.target.value === "subject" ? "subject" : Number(event.target.value))}
          value={String(placement)}
        >
          {values.map((value) => (
            <option key={String(value)} value={String(value)}>
              {optionLabel(value)}
            </option>
          ))}
        </select>
      </label>
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

function TestRunCard({
  run,
  workspaceId,
  open,
  onToggle,
  onCancel,
}: {
  run: ArtistTestRun;
  workspaceId: string;
  /** 展开显示结果；收起时只有一行。 */
  open: boolean;
  onToggle: () => void;
  onCancel: (run: ArtistTestRun) => void;
}) {
  const active = ACTIVE_RUN_STATUSES.has(run.status);
  const mean = meanSimilarity(run);
  return (
    <article className={`sl-test-run ${open ? "open" : ""}`}>
      <header className="sl-run-head">
        <button aria-expanded={open} className="sl-test-run-toggle" onClick={onToggle} type="button">
          {open ? <ChevronDown size={14} aria-hidden="true" /> : <ChevronRight size={14} aria-hidden="true" />}
          {run.kind === "regression" ? <Rows3 size={14} aria-hidden="true" /> : <Grid3x3 size={14} aria-hidden="true" />}
          <strong>{run.kind === "regression" ? "回归对照" : "泛化矩阵"}</strong>
          <span className="sl-muted">{run.artist.folder}</span>
          <span>{formatTime(run.created_at)}</span>
          <span className="sl-muted">{run.items.length} 张</span>
        </button>
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
      {open ? (
        <>
          {run.error ? <p className="sl-error">{run.error}</p> : null}
          {run.kind === "regression" ? <RegressionGrid run={run} workspaceId={workspaceId} /> : <MatrixGrid run={run} workspaceId={workspaceId} />}
        </>
      ) : null}
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
  // 下方展开对照的那一对：默认第一张出了图的，再点一次收起；没出图的（失败）不展开。
  const [selected, setSelected] = useState<number | null | undefined>(undefined);
  const firstDone = run.items.find((item) => item.image_path && item.source)?.index ?? null;
  const current = run.items.find((item) => item.index === (selected === undefined ? firstDone : selected) && item.image_path) ?? null;
  return (
    <>
    <div className="sl-regression-grid">
      {run.items.map((item) => (
        <figure className={`sl-regression-pair ${current && item.index === current.index ? "on" : ""}`} key={item.index}>
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
            {item.source && item.image_path ? (
              <button
                aria-pressed={current?.index === item.index}
                className="sl-link-btn"
                onClick={() => setSelected(current?.index === item.index ? null : item.index)}
                type="button"
              >
                {current?.index === item.index ? "收起对照" : "与原图对照"}
              </button>
            ) : null}
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
    {current?.source ? (
      <div className="sl-regression-compare">
        <h4>
          与原图对照 · {current.label}
        </h4>
        <CompareView
          generatedLabel="回归"
          item={current}
          sourceImageId={current.source.image_id}
          sourceViewer={{ file: { imageId: current.source.image_id }, label: `${current.label ?? ""} · 原图`, path: current.source.path }}
          workspaceId={workspaceId}
        />
      </div>
    ) : null}
    </>
  );
}

function matrixLabel(item: ArtistTestItem): string {
  return [
    item.character ? nodeName(item.character) : "（无角色）",
    item.action ? nodeName(item.action) : "（无动作）",
  ].join(" · ");
}

function matrixPlacementText(run: ArtistTestRun): string {
  const placement = run.settings.placement ?? {};
  return MATRIX_ROLES.map((role) => {
    const text = placementText(placement[role]);
    return text ? ` · ${role === "character" ? "角色" : "动作"}放在${text}` : "";
  }).join("");
}

function MatrixGrid({ run, workspaceId }: { run: ArtistTestRun; workspaceId: string }) {
  const open = useOpenTestImage(run);
  const openGenerated = (path: string) => open((file) => "path" in file && file.path === path);
  const rows = run.settings.characters.length ? run.settings.characters : [null];
  const cols = run.settings.actions.length ? run.settings.actions : [null];
  const cell = (character: string | null, action: string | null) =>
    run.items.find((item) => (item.character ?? null) === character && (item.action ?? null) === action);
  const firstDone = run.items.find((item) => item.image_path)?.index ?? null;
  const [selected, setSelected] = useState<number | null | undefined>(undefined);
  const current = run.items.find((item) => item.index === (selected === undefined ? firstDone : selected) && item.image_path) ?? null;
  const source = run.source;
  return (
    <>
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
                  return (
                    <td className={item && current?.index === item.index ? "on" : ""} key={action ?? "none"}>
                      {item ? (
                        <div className="sl-matrix-cell">
                          <Generated item={item} onOpen={openGenerated} size={240} workspaceId={workspaceId} />
                          {source && item.image_path ? (
                            <button
                              aria-label={`${current?.index === item.index ? "收起对照" : "与原图对照"} ${matrixLabel(item)}`}
                              aria-pressed={current?.index === item.index}
                              className="sl-link-btn"
                              onClick={() => setSelected(current?.index === item.index ? null : item.index)}
                              type="button"
                            >
                              {current?.index === item.index ? "收起对照" : "与原图对照"}
                            </button>
                          ) : null}
                        </div>
                      ) : null}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
        <p className="sl-muted">
          种子 {run.items[0]?.seed}
          {matrixPlacementText(run)}
        </p>
      </div>
      {current && source ? (
        <div className="sl-matrix-compare">
          <h4>与原图对照 · {matrixLabel(current)}</h4>
          <CompareView
            generatedLabel="泛化"
            hint={<p className="sl-muted">矩阵会换角色和动作，提示词、种子等差异是预期内的；下面的参数差异仍按源图和这张矩阵图完整对比。</p>}
            item={current}
            sourceImageId={source.image_id}
            sourceViewer={{ file: { imageId: source.image_id }, label: `${matrixLabel(current)} · 原图`, path: source.path }}
            workspaceId={workspaceId}
          />
        </div>
      ) : null}
    </>
  );
}
