import { FlaskConical, LoaderCircle, Play, Repeat2, Square } from "lucide-react";
import { useMemo, useState } from "react";

import { errorMessage } from "../api/client";
import type { AblationUnit, ImageRecord, ProbeItem, ProbeRun, ProbeSettings, Recipe, RecipeMaterial, SeedMode } from "./api";
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
  /** 消融结果里点“从配方去掉”：把这些 token 挪进丢弃区。 */
  onDropTokens: (ids: string[]) => void;
};

export function ProbePanel({ workspaceId, draft, dirty, source, runs, onSave, onStarted, onCancel, onDropTokens }: ProbePanelProps) {
  const [mode, setMode] = useState<ProbeSettings["kind"]>("swap");
  const [seedMode, setSeedMode] = useState<SeedMode>(source?.seed != null ? "source" : "random");
  const [seed, setSeed] = useState<number | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [replaceClothing, setReplaceClothing] = useState(true);
  const [captionIndex, setCaptionIndex] = useState<number | null>(null);
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

  const styleTokens = useMemo(
    () => [
      ...draft.prefix.map((token) => ({ token, zone: "前缀" })),
      ...draft.suffix.map((token) => ({ token, zone: "后缀" })),
    ],
    [draft.prefix, draft.suffix],
  );
  const liveSelected = selected.filter((id) => styleTokens.some((item) => item.token.id === id));
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
        caption_index: captionIndex,
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
        settings.units = ablationUnits(current, liveSelected, together);
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
            : "画风前缀、后缀里每次去掉选中的 token，和完整配方比，看哪些 token 真的在起作用"}
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
              onChange={(event) => setCaptionIndex(event.target.value === "" ? null : Number(event.target.value))}
              value={captionIndex ?? ""}
            >
              <option value="">{captionsOn ? "自动（角色提示词 #1）" : "自动（主体）"}</option>
              {captionsOn
                ? draft.character.captions.map((_, index) => (
                    <option key={index} value={index}>
                      角色提示词 #{index + 1}
                    </option>
                  ))
                : null}
            </select>
            <label className="sl-check" title="换进主体时，原图的服装也一起去掉（换进角色提示词时整条替换）">
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
          <div className="sl-probe-tokens">
            {styleTokens.map(({ token, zone }) => (
              <button
                aria-pressed={liveSelected.includes(token.id)}
                className={`sl-probe-token ${liveSelected.includes(token.id) ? "on" : ""}`}
                key={token.id}
                onClick={() => setSelected((list) => toggle(list, token.id, together ? Infinity : MAX_UNITS))}
                title={`画风${zone}`}
                type="button"
              >
                <span className="sl-muted">{zone}</span>
                {token.text}
              </button>
            ))}
            {!styleTokens.length ? <p className="sl-muted">画风前缀、后缀是空的。</p> : null}
          </div>
          <div className="sl-form-row">
            <button className="sl-link-btn" onClick={() => setSelected(styleTokens.slice(0, MAX_UNITS).map((item) => item.token.id))} type="button">
              选前 {Math.min(MAX_UNITS, styleTokens.length)} 个
            </button>
            <button className="sl-link-btn" onClick={() => setSelected([])} type="button">
              清空
            </button>
            <label className="sl-check" title="选中的 token 作为一组一起去掉，只出一张">
              <input checked={together} onChange={(event) => setTogether(event.target.checked)} type="checkbox" />
              一起去掉
            </label>
            <span className="sl-muted">
              {together ? `去掉选中的 ${liveSelected.length} 个，出 1 张` : `选了 ${liveSelected.length} 个（最多 ${MAX_UNITS}），每个单独去掉出 1 张`}，另加 1 张完整配方作基准
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
            <ProbeRunCard draft={draft} key={run.id} onCancel={onCancel} onDropTokens={onDropTokens} run={run} source={source} workspaceId={workspaceId} />
          ))}
        </div>
      ) : null}
    </section>
  );
}

/** 选中的 token 按配方里的顺序排好；一起去掉时合成一组。 */
export function ablationUnits(recipe: Recipe, ids: string[], together: boolean): AblationUnit[] {
  const tokens = [...recipe.prefix, ...recipe.suffix].filter((token) => ids.includes(token.id));
  if (together) return tokens.length ? [{ label: tokens.map((token) => token.text).join(", "), token_ids: tokens.map((token) => token.id) }] : [];
  return tokens.map((token) => ({ label: token.text, token_ids: [token.id] }));
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
}: {
  run: ProbeRun;
  draft: Recipe;
  source: ImageRecord | null;
  workspaceId: string;
  onCancel: (run: ProbeRun) => void;
  onDropTokens: (ids: string[]) => void;
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
          const droppable = run.kind === "ablation" && item.role === "variant" && item.token_ids?.length && item.token_ids.every((id) => styleIds.has(id));
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
                <strong title={item.label}>{run.kind === "ablation" && item.role === "variant" ? `去掉 ${item.label}` : item.label}</strong>
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
                <button className="sl-ghost tiny" onClick={() => onDropTokens(item.token_ids!)} title="挪进丢弃区（不保存，保存后生效）" type="button">
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
