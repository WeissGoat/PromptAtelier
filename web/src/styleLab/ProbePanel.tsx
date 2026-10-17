import { FlaskConical, LoaderCircle, Play, Repeat2, Square } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { errorMessage } from "../api/client";
import {
  defaultPieces,
  isDefaultGrouping,
  loadPieces,
  mergePieces,
  newPiece,
  pieceLabel,
  pieceSize,
  pieceValid,
  piecesToUnits,
  savePieces,
  splitPiece,
  styleSignature,
  ZONE_LABELS,
  type AblationPiece,
  type PieceMode,
  type PieceZone,
} from "./ablationPieces";
import type { ImageRecord, ProbeItem, ProbeRun, ProbeSettings, Recipe, RecipeMaterial, SeedMode } from "./api";
import { ACTIVE_RUN_STATUSES, runImageUrl, sourceImageUrl, startProbe } from "./api";
import { DuplicateNotice, duplicateOf, type DuplicateRequest } from "./DuplicateNotice";
import { formatTime, runStatusLabels } from "./format";
import { runViewerItem, sourceViewerItem, useImageViewer, type ViewerItem } from "./ImageViewer";
import { loadNode, nodeTags } from "./libraryNodes";
import { useMaterialShelf } from "./materialShelf";
import { materialsOf, materialTags } from "./recipeModel";
import { Segmented } from "./RegenPanel";

const MAX_CHARACTERS = 4;
const MAX_UNITS = 12;

type ProbePanelProps = {
  workspaceId: string;
  draft: Recipe;
  dirty: boolean;
  source: ImageRecord | null;
  runs: ProbeRun[];
  /** 出图用保存好的配方：有改动时先保存。 */
  onSave: () => Promise<Recipe | null>;
  onStarted: (run: ProbeRun) => void;
  onCancel: (run: ProbeRun) => void;
  /** 消融结果里点“从配方去掉”：把这些块挪进丢弃区（旧记录按块）。 */
  onDropTokens: (ids: string[]) => void;
  /** 同上，按 tag：块里只挪走这几个 tag。 */
  onDropTags: (tags: string[]) => void;
};

export function ProbePanel({
  workspaceId,
  draft,
  dirty,
  source,
  runs,
  onSave,
  onStarted,
  onCancel,
  onDropTokens,
  onDropTags,
}: ProbePanelProps) {
  const [mode, setMode] = useState<ProbeSettings["kind"]>("swap");
  const [seedMode, setSeedMode] = useState<SeedMode>(source?.seed != null ? "source" : "random");
  const [seed, setSeed] = useState<number | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [replaceClothing, setReplaceClothing] = useState(true);
  // "auto"、"subject" 或角色提示词的序号。
  const [swapTarget, setSwapTarget] = useState("auto");
  const [swapBaseline, setSwapBaseline] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [together, setTogether] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [duplicate, setDuplicate] = useState<DuplicateRequest | null>(null);

  // 可换的角色：素材架上的角色块（带各自的筛选），加上配方里用过、素材架上已经没有的。
  const { shelf } = useMaterialShelf();
  const characters = useMemo(() => {
    const list: RecipeMaterial[] = shelf.materials.filter((item) => item.role === "character");
    materialsOf(draft)
      .filter((item) => item.role === "character" && !list.some((other) => other.ref === item.ref))
      .forEach((item) => list.push(item));
    return list;
  }, [shelf.materials, draft]);

  // 消融的分组：只在测试里用，不改配方；按配方存在浏览器里，画风变了就重新分（手动新增的组留着）。
  const signature = styleSignature(draft);
  const [pieceMode, setPieceMode] = useState<PieceMode>(() => loadPieces(draft).mode);
  const [pieces, setPieces] = useState<AblationPiece[]>(() => loadPieces(draft).pieces);
  const [newText, setNewText] = useState("");
  useEffect(() => {
    const loaded = loadPieces(draft);
    setPieceMode(loaded.mode);
    setPieces(loaded.pieces);
    setSelected([]);
    // 只在换配方或画风文字变了时重新读。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft.id, signature]);
  useEffect(() => {
    savePieces(draft, pieceMode, pieces);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pieces, pieceMode]);
  const validIds = useMemo(() => new Set(pieces.filter((piece) => pieceValid(piece, draft)).map((piece) => piece.id)), [pieces, draft]);
  const liveSelected = selected.filter((id) => validIds.has(id));
  const selectedPieces = pieces.filter((piece) => liveSelected.includes(piece.id));
  const defaultGrouping = isDefaultGrouping(pieces, draft, pieceMode);
  const captionsOn = draft.character.enabled && draft.character.captions.some((caption) => caption.tokens.length);

  const variantCount = mode === "swap" ? picked.length : together ? Math.min(1, liveSelected.length) : liveSelected.length;
  const total = variantCount + (mode === "ablation" || swapBaseline ? 1 : 0);
  const ready =
    !submitting &&
    variantCount > 0 &&
    (seedMode !== "fixed" || seed !== null) &&
    (mode === "swap" || together || liveSelected.length <= MAX_UNITS);

  const start = async (force = false) => {
    setSubmitting(true);
    setError(null);
    setDuplicate(null);
    try {
      const current = await onSave();
      if (!current) return;
      const settings: ProbeSettings = {
        kind: mode,
        characters: [],
        replace_clothing: replaceClothing,
        target: swapTarget === "auto" || swapTarget === "subject" ? swapTarget : "caption",
        caption_index: swapTarget === "auto" || swapTarget === "subject" ? null : Number(swapTarget),
        units: [],
        include_baseline: mode === "ablation" || swapBaseline,
        seed_mode: seedMode,
        seed: seedMode === "fixed" ? seed : null,
      };
      if (mode === "swap") {
        settings.characters = await Promise.all(
          picked.map(async (ref) => {
            const material = characters.find((item) => item.ref === ref)!;
            const tags = materialTags(material, nodeTags(await loadNode(ref, "character")));
            if (!tags.length) throw new Error(`「${material.name}」的 tag 全被筛掉了`);
            return { ref, name: material.name, tags };
          }),
        );
      } else {
        settings.units = piecesToUnits(pieces, liveSelected, together);
      }
      const { run } = await startProbe(workspaceId, current.id, settings, force);
      onStarted(run);
    } catch (exc) {
      const found = duplicateOf(exc);
      if (found) setDuplicate(found);
      else setError(errorMessage(exc));
    } finally {
      setSubmitting(false);
    }
  };

  const toggle = (list: string[], id: string, limit: number) =>
    list.includes(id) ? list.filter((item) => item !== id) : list.length >= limit ? list : [...list, id];

  return (
    <section className="sl-zone zone-probe">
      <header className="sl-zone-head">
        <span className="sl-zone-title">
          <FlaskConical size={13} aria-hidden="true" />
          画风探针
        </span>
        <span className="sl-muted">配方只改一处、同一个种子出图，看画风对这处改动的反应</span>
      </header>

      <div className="sl-form-row">
        <Segmented
          onChange={(value) => setMode(value as ProbeSettings["kind"])}
          options={[
            ["swap", "替换角色"],
            ["ablation", "消融测试"],
          ]}
          value={mode}
        />
        <span className="sl-muted">
          {mode === "swap"
            ? "原图的角色换成素材架上的角色，动作、构图和画风不变，看画风换了人还稳不稳"
            : "画风前缀、后缀里每次去掉一组 tag（或加上配方里没有的 tag），和完整配方比，看哪些 tag 真的在起作用"}
        </span>
      </div>

      {mode === "swap" ? (
        <>
          {characters.length ? (
            <div className="sl-probe-picks">
              {characters.map((material) => (
                <label className={`sl-probe-pick ${picked.includes(material.ref) ? "on" : ""}`} key={material.ref}>
                  <input
                    checked={picked.includes(material.ref)}
                    disabled={!picked.includes(material.ref) && picked.length >= MAX_CHARACTERS}
                    onChange={() => setPicked((list) => toggle(list, material.ref, MAX_CHARACTERS))}
                    type="checkbox"
                  />
                  {material.name}
                  {material.excluded.length ? <span className="sl-muted">（筛掉 {material.excluded.length} 个 tag）</span> : null}
                </label>
              ))}
              <span className="sl-muted">
                {picked.length}/{MAX_CHARACTERS}
              </span>
            </div>
          ) : (
            <p className="sl-muted">右边素材架上还没有角色：先在素材架里选几个角色（可以筛掉不要的 tag），这里就能选。</p>
          )}
          <div className="sl-form-row">
            <span className="sl-form-label">换进</span>
            <select
              aria-label="换进哪里"
              onChange={(event) => setSwapTarget(event.target.value)}
              title="自动：原角色写在哪（主体或某条角色提示词）就换哪，那里的动作等其他 tag 照留"
              value={captionsOn ? swapTarget : "subject"}
            >
              {captionsOn ? <option value="auto">自动（原角色在哪就换哪）</option> : null}
              <option value="subject">主体</option>
              {captionsOn
                ? draft.character.captions.map((_, index) => (
                    <option key={index} value={index}>
                      角色提示词 #{index + 1}
                    </option>
                  ))
                : null}
            </select>
            <label className="sl-check" title="原角色的服装 tag 也一起去掉，换成新角色的">
              <input checked={replaceClothing} onChange={(event) => setReplaceClothing(event.target.checked)} type="checkbox" />
              连服装一起换
            </label>
            <label className="sl-check" title="多出一张完整配方的图，用来和替换后的图比相似度">
              <input checked={swapBaseline} onChange={(event) => setSwapBaseline(event.target.checked)} type="checkbox" />
              加一张完整配方作基准
            </label>
          </div>
        </>
      ) : (
        <>
          <div className="sl-form-row">
            <Segmented
              onChange={(value) => {
                const mode = value as PieceMode;
                setPieceMode(mode);
                setPieces([...defaultPieces(draft, mode), ...pieces.filter((piece) => piece.zone === "new")]);
                setSelected([]);
              }}
              options={[
                ["tag", "按 tag 分"],
                ["block", "按块分"],
              ]}
              value={pieceMode}
            />
            <button
              className="sl-link-btn"
              disabled={defaultGrouping}
              onClick={() => {
                setPieces(defaultPieces(draft, pieceMode));
                setSelected([]);
              }}
              title={defaultGrouping ? "现在就是默认分组" : "回到默认分组，合并、拆开、移除和新增的都撤掉"}
              type="button"
            >
              恢复默认分组
            </button>
            <span className="sl-muted">点选几组后「合成一组」，或选一组「拆开」，就是重新划分；只在测试里用，不改配方</span>
          </div>
          <div className="sl-probe-pieces">
            {(["prefix", "suffix", "new"] as PieceZone[]).map((zone) => {
              const list = pieces.filter((piece) => piece.zone === zone);
              if (!list.length) return null;
              return (
                <div className="sl-probe-piece-zone" key={zone}>
                  <span className="sl-probe-piece-zone-label">{ZONE_LABELS[zone]}</span>
                  <div className="sl-probe-tokens">
                    {list.map((piece) => {
                      const valid = validIds.has(piece.id);
                      const on = liveSelected.includes(piece.id);
                      return (
                        <button
                          aria-pressed={on}
                          className={`sl-probe-token ${on ? "on" : ""} ${valid ? "" : "invalid"} ${piece.add.length ? "adds" : ""}`}
                          disabled={!valid}
                          key={piece.id}
                          onClick={() => setSelected((list) => toggle(list, piece.id, together ? Infinity : MAX_UNITS))}
                          title={
                            valid
                              ? piece.add.length
                                ? "加上配方里没有的 tag（加在后缀末尾），看画面怎么变"
                                : "去掉这组 tag，看画面怎么变"
                              : "配方改过，画风里已经找不到这些 tag"
                          }
                          type="button"
                        >
                          {pieceLabel(piece)}
                          {pieceSize(piece) > 1 ? <span className="sl-count">{pieceSize(piece)}</span> : null}
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}
            {!pieces.length ? <p className="sl-muted">画风前缀、后缀是空的，可以在下面新增要加上试试的 tag。</p> : null}
          </div>
          <div className="sl-form-row">
            <button
              className="sl-ghost tiny"
              disabled={selectedPieces.length < 2}
              onClick={() => {
                const result = mergePieces(pieces, liveSelected);
                setPieces(result.pieces);
                setSelected(result.merged ? [result.merged] : []);
              }}
              title="选中的几组合成一组，一起去掉（或加上）出一张"
              type="button"
            >
              合成一组
            </button>
            <button
              className="sl-ghost tiny"
              disabled={!selectedPieces.some((piece) => pieceSize(piece) > 1)}
              onClick={() => {
                let next = pieces;
                selectedPieces.filter((piece) => pieceSize(piece) > 1).forEach((piece) => (next = splitPiece(next, piece.id)));
                setPieces(next);
                setSelected([]);
              }}
              title="选中的组拆回每个 tag 一组"
              type="button"
            >
              拆开
            </button>
            <button
              className="sl-ghost tiny"
              disabled={!selected.length}
              onClick={() => {
                setPieces(pieces.filter((piece) => !selected.includes(piece.id)));
                setSelected([]);
              }}
              title="从测试分组里拿掉（配方不变，恢复默认分组可以找回）"
              type="button"
            >
              移除
            </button>
            <form
              className="sl-probe-add"
              onSubmit={(event) => {
                event.preventDefault();
                const piece = newPiece(newText, draft);
                if (!piece) return;
                setPieces([...pieces, piece]);
                setSelected((list) => toggle(list, piece.id, together ? Infinity : MAX_UNITS));
                setNewText("");
              }}
            >
              <input
                aria-label="新增一组"
                onChange={(event) => setNewText(event.target.value)}
                placeholder="新增一组：输入 tag，逗号分隔"
                title="画风里有的 tag 算去掉，没有的算加上（加在后缀末尾）"
                value={newText}
              />
              <button className="sl-ghost tiny" disabled={!newText.trim()} type="submit">
                新增
              </button>
            </form>
          </div>
          <div className="sl-form-row">
            <button
              className="sl-link-btn"
              onClick={() => setSelected(pieces.filter((piece) => validIds.has(piece.id)).slice(0, MAX_UNITS).map((piece) => piece.id))}
              type="button"
            >
              选前 {Math.min(MAX_UNITS, validIds.size)} 组
            </button>
            <button className="sl-link-btn" onClick={() => setSelected([])} type="button">
              清空
            </button>
            <label className="sl-check" title="选中的组一起改，只出一张">
              <input checked={together} onChange={(event) => setTogether(event.target.checked)} type="checkbox" />
              一起改
            </label>
            <span className="sl-muted">
              {together ? `选中的 ${liveSelected.length} 组一起改，出 1 张` : `选了 ${liveSelected.length} 组（最多 ${MAX_UNITS}），每组出 1 张`}，另加 1 张完整配方作基准
            </span>
          </div>
        </>
      )}

      <div className="sl-form-row">
        <span className="sl-form-label">种子</span>
        <Segmented
          onChange={(value) => setSeedMode(value as SeedMode)}
          options={[
            ["source", "原图"],
            ["random", "随机"],
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
        <span className="sl-muted">所有图共用这一个种子</span>
      </div>
      {error ? <p className="sl-error">{error}</p> : null}
      {duplicate ? <DuplicateNotice duplicate={duplicate} onDismiss={() => setDuplicate(null)} onForce={() => void start(true)} /> : null}
      <button className="sl-primary" disabled={!ready} onClick={() => void start()} type="button">
        <Play size={15} aria-hidden="true" />
        {submitting ? "提交中…" : `${dirty ? "保存并" : ""}生成 · ${total} 张`}
      </button>

      {runs.length ? (
        <div className="sl-test-runs">
          {runs.map((run) => (
            <ProbeRunCard
              draft={draft}
              key={run.id}
              onCancel={onCancel}
              onDropTags={onDropTags}
              onDropTokens={onDropTokens}
              run={run}
              source={source}
              workspaceId={workspaceId}
            />
          ))}
        </div>
      ) : null}
    </section>
  );
}

/** 消融变体的标题：去掉了什么、加上了什么。 */
function ablationTitle(item: ProbeItem): string {
  const parts = [];
  if (item.removed?.length) parts.push(`去掉 ${item.removed.join(", ")}`);
  if (item.added?.length) parts.push(`加上 ${item.added.join(", ")}`);
  return parts.join("；") || item.label;
}

function percent(value: number | null | undefined): string | null {
  return typeof value === "number" ? `${(value * 100).toFixed(1)}%` : null;
}

/** 消融：变体按和完整配方的相似度从低到高（影响大的在前）；替换角色保持选择顺序。基准图总在最前。 */
export function orderedProbeItems(run: ProbeRun): ProbeItem[] {
  const baseline = run.items.filter((item) => item.role === "baseline");
  const variants = run.items.filter((item) => item.role !== "baseline");
  if (run.kind === "ablation") {
    variants.sort((a, b) => (a.baseline_compare?.similarity ?? 2) - (b.baseline_compare?.similarity ?? 2));
  }
  return [...baseline, ...variants];
}

function ProbeRunCard({
  run,
  draft,
  source,
  workspaceId,
  onCancel,
  onDropTokens,
  onDropTags,
}: {
  run: ProbeRun;
  draft: Recipe;
  source: ImageRecord | null;
  workspaceId: string;
  onCancel: (run: ProbeRun) => void;
  onDropTokens: (ids: string[]) => void;
  onDropTags: (tags: string[]) => void;
}) {
  const viewer = useImageViewer();
  const active = ACTIVE_RUN_STATUSES.has(run.status);
  const items = orderedProbeItems(run);
  const baseline = items.find((item) => item.role === "baseline");
  const styleIds = new Set([...draft.prefix, ...draft.suffix].map((token) => token.id));
  const viewerItems: ViewerItem[] = [
    ...(source ? [sourceViewerItem(source)] : []),
    ...items.filter((item) => item.image_path).map((item) => runViewerItem(item.image_path!, item.label, item.seed)),
  ];
  const open = (path: string) => viewer.open(viewerItems, Math.max(0, viewerItems.findIndex((entry) => "path" in entry.file && entry.file.path === path)));

  return (
    <article className="sl-test-run">
      <header className="sl-run-head">
        {run.kind === "swap" ? <Repeat2 size={14} aria-hidden="true" /> : <FlaskConical size={14} aria-hidden="true" />}
        <strong>{run.kind === "swap" ? "替换角色" : "消融测试"}</strong>
        {run.recipe ? <span className="sl-muted">配方 v{run.recipe.version}</span> : null}
        <span>{formatTime(run.created_at)}</span>
        <span className={`sl-run-status ${run.status}`}>
          {active ? <LoaderCircle className="sl-spin" size={12} /> : null}
          {runStatusLabels[run.status]}
        </span>
        <span className="sl-muted">种子 {run.items[0]?.seed}</span>
        {active && run.job_id ? (
          <button aria-label="停止" className="sl-icon-btn" onClick={() => onCancel(run)} title="停止剩余张数" type="button">
            <Square size={12} />
          </button>
        ) : null}
      </header>
      {run.error ? <p className="sl-error">{run.error}</p> : null}
      <div className="sl-probe-grid">
        {run.kind === "swap" && source ? (
          <figure className="sl-probe-cell">
            <button className="sl-zoomable" onClick={() => viewer.open(viewerItems, 0)} title="查看大图和文件位置" type="button">
              <img alt="原图" loading="lazy" src={sourceImageUrl(workspaceId, source.id, 320)} />
            </button>
            <figcaption>
              <strong>原图</strong>
            </figcaption>
          </figure>
        ) : null}
        {items.map((item) => {
          const toSource = item.compare?.similarity;
          const baselineToSource = baseline?.compare?.similarity;
          const sourceDelta = item.role !== "baseline" && typeof toSource === "number" && typeof baselineToSource === "number" ? toSource - baselineToSource : null;
          const byBlock = Boolean(item.token_ids?.length);
          // 只去掉、没加 tag 的组才能“从配方去掉”；按块的旧记录看块还在不在，按 tag 的看 tag 还在不在。
          const droppable =
            run.kind === "ablation" &&
            item.role === "variant" &&
            !item.added?.length &&
            (byBlock
              ? item.token_ids!.every((id) => styleIds.has(id))
              : Boolean(item.removed?.length) && pieceValid({ id: "", zone: "new", remove: item.removed!, add: [] }, draft));
          return (
            <figure className={`sl-probe-cell ${item.role}`} key={item.index}>
              {item.image_path ? (
                <button className="sl-zoomable" onClick={() => open(item.image_path!)} title="查看大图和文件位置" type="button">
                  <img alt={item.label} loading="lazy" src={runImageUrl(workspaceId, item.image_path, 320)} />
                </button>
              ) : (
                <div className="sl-test-empty" title={item.error_detail ?? item.error}>
                  {item.status === "running" ? <LoaderCircle className="sl-spin" size={16} /> : item.error ?? runStatusLabels[item.status]}
                </div>
              )}
              <figcaption>
                <strong title={item.label}>{run.kind === "ablation" && item.role === "variant" ? ablationTitle(item) : item.label}</strong>
                {item.target ? <span className="sl-muted">换进{item.target}</span> : null}
                {item.baseline_compare?.similarity != null ? (
                  <span className="sl-verdict-num" title="和完整配方（同一个种子）的相似度，越低说明这处改动对画面影响越大">
                    和完整配方 {percent(item.baseline_compare.similarity)}
                  </span>
                ) : null}
                {sourceDelta !== null ? (
                  <span className={`sl-probe-delta ${sourceDelta > 0 ? "up" : "down"}`} title="和原图的相似度，相对完整配方的变化">
                    离原图 {sourceDelta > 0 ? "+" : ""}
                    {(sourceDelta * 100).toFixed(1)}
                  </span>
                ) : item.role === "baseline" && percent(toSource) ? (
                  <span className="sl-muted">和原图 {percent(toSource)}</span>
                ) : null}
              </figcaption>
              {droppable ? (
                <button
                  className="sl-ghost tiny"
                  onClick={() => (byBlock ? onDropTokens(item.token_ids!) : onDropTags(item.removed!))}
                  title="挪进丢弃区（不保存，保存后生效）；tag 在一整块里时只挪走这几个"
                  type="button"
                >
                  从配方去掉
                </button>
              ) : null}
              {run.kind === "swap" && item.role === "variant" && (item.removed?.length || item.added?.length) ? (
                <details className="sl-regression-subject">
                  <summary>改了什么</summary>
                  {item.removed?.length ? <p className="sl-muted">去掉：{item.removed.join(", ")}</p> : null}
                  {item.added?.length ? <p>加入：{item.added.join(", ")}</p> : null}
                </details>
              ) : null}
            </figure>
          );
        })}
      </div>
      {run.kind === "ablation" ? (
        <p className="sl-muted">同一个种子下的灰度相似度，只能粗看：差别在 1~2% 以内的 token 多半可有可无；“离原图”为正说明去掉后反而更像原图。</p>
      ) : null}
    </article>
  );
}
