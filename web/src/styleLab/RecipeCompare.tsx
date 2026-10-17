import { ArrowLeftRight, GitCompareArrows, LoaderCircle, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { errorMessage } from "../api/client";
import type { Recipe, RecipeSummary } from "./api";
import { getRecipe, getRecipeVersion, sourceImageUrl } from "./api";
import { formatTime } from "./format";
import { compareRecipes, zoneCounts, type CompareChip, type CompareZone, type RecipeComparison } from "./recipeComparison";

function chipTitle(chip: CompareChip, side: "left" | "right", labels: [string, string]): string {
  const [self, other] = side === "left" ? labels : [labels[1], labels[0]];
  if (chip.status === "same") return "两边一样";
  if (chip.status === "weight") return chip.note ?? "权重不同";
  if (chip.status === "moved") return `${other} 里有，在${chip.movedTo}`;
  return `只在 ${self}`;
}

/** 逐区并排：左 A 右 B；只看不同时隐藏没变的区，变了的区里相同的 tag 收起来只显示个数。 */
export function ComparisonView({
  comparison,
  leftLabel,
  rightLabel,
  onlyDiff = true,
}: {
  comparison: RecipeComparison;
  leftLabel: string;
  rightLabel: string;
  onlyDiff?: boolean;
}) {
  const zones = onlyDiff ? comparison.zones.filter((zone) => zone.changed || zone.reordered) : comparison.zones;
  return (
    <div className="sl-cmp">
      <div className="sl-cmp-legend">
        <span className="sl-cmp-chip only left">只在 {leftLabel}</span>
        <span className="sl-cmp-chip only right">只在 {rightLabel}</span>
        <span className="sl-cmp-chip weight">权重不同</span>
        <span className="sl-cmp-chip moved">换了区</span>
        <span className={`sl-pill ${comparison.styleSame ? "ok" : "warn"}`}>{comparison.styleSame ? "画风相同" : "画风不同"}</span>
      </div>
      {zones.length ? (
        <div className="sl-cmp-grid">
          <span className="sl-cmp-head" />
          <span className="sl-cmp-head">{leftLabel}</span>
          <span className="sl-cmp-head">{rightLabel}</span>
          {zones.map((zone) => (
            <ZoneRow key={zone.id} labels={[leftLabel, rightLabel]} onlyDiff={onlyDiff} zone={zone} />
          ))}
        </div>
      ) : (
        <p className="sl-muted">提示词各区完全一样。</p>
      )}
      {comparison.fields.length ? (
        <table className="sl-history-fields">
          <thead>
            <tr>
              <th>设置</th>
              <th>{leftLabel}</th>
              <th>{rightLabel}</th>
            </tr>
          </thead>
          <tbody>
            {comparison.fields.map((field) => (
              <tr key={field.label}>
                <td>{field.label}</td>
                <td>{field.before}</td>
                <td>{field.after}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="sl-muted">模型、参数和其他设置一样。</p>
      )}
    </div>
  );
}

function ZoneRow({ zone, onlyDiff, labels }: { zone: CompareZone; onlyDiff: boolean; labels: [string, string] }) {
  const counts = zoneCounts(zone);
  const summary = [
    counts.onlyLeft ? `${labels[0]} 独有 ${counts.onlyLeft}` : "",
    counts.onlyRight ? `${labels[1]} 独有 ${counts.onlyRight}` : "",
    counts.weight ? `权重 ${counts.weight}` : "",
    counts.moved ? `换区 ${counts.moved}` : "",
    zone.reordered ? "顺序不同" : "",
  ].filter(Boolean);
  return (
    <>
      <span className={`sl-cmp-label ${zone.style ? "style" : ""}`}>
        {zone.label}
        {summary.length ? <small>{summary.join(" · ")}</small> : <small>一样</small>}
      </span>
      <Chips chips={zone.left} labels={labels} onlyDiff={onlyDiff} side="left" />
      <Chips chips={zone.right} labels={labels} onlyDiff={onlyDiff} side="right" />
    </>
  );
}

function Chips({
  chips,
  side,
  onlyDiff,
  labels,
}: {
  chips: CompareChip[];
  side: "left" | "right";
  onlyDiff: boolean;
  labels: [string, string];
}) {
  const shown = onlyDiff ? chips.filter((chip) => chip.status !== "same") : chips;
  const hidden = chips.length - shown.length;
  return (
    <div className="sl-cmp-cell">
      {!chips.length ? <span className="sl-muted">（空）</span> : null}
      {shown.map((chip, index) => (
        <span
          className={`sl-cmp-chip ${chip.status} ${side}`}
          key={`${chip.text}-${index}`}
          title={chipTitle(chip, side, labels)}
        >
          {chip.text}
          {chip.status === "weight" ? <small>{chip.note}</small> : null}
          {chip.status === "moved" ? <small>→ {chip.movedTo}</small> : null}
        </span>
      ))}
      {hidden ? <span className="sl-muted">另有 {hidden} 个相同</span> : null}
    </div>
  );
}

type Side = { id: string; version: number | null };
type History = Array<{ version: number; updated_at: number }>;

/**
 * 配方对比：左右各选一个配方和版本，逐区对比 tag，下面是设置差异。
 * initial 没给版本时用当前版本。
 */
export function RecipeCompareDialog({
  workspaceId,
  recipes,
  initial,
  onClose,
}: {
  workspaceId: string;
  recipes: RecipeSummary[];
  initial: { left: Side; right: Side };
  onClose: () => void;
}) {
  const [left, setLeft] = useState<Side>(initial.left);
  const [right, setRight] = useState<Side>(initial.right);
  const [onlyDiff, setOnlyDiff] = useState(true);
  const [current, setCurrent] = useState<Record<string, { recipe: Recipe; history: History }>>({});
  const [versions, setVersions] = useState<Record<string, Recipe>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // 每个配方读一次当前版本和历史；旧版本按需读。
  useEffect(() => {
    const missing = [...new Set([left.id, right.id])].filter((id) => id && !current[id]);
    if (!missing.length) return;
    let cancelled = false;
    Promise.all(missing.map((id) => getRecipe(workspaceId, id)))
      .then((results) => {
        if (cancelled) return;
        setCurrent((state) => ({ ...state, ...Object.fromEntries(results.map((data, index) => [missing[index], data])) }));
      })
      .catch((exc) => !cancelled && setError(errorMessage(exc)));
    return () => {
      cancelled = true;
    };
  }, [workspaceId, left.id, right.id, current]);

  const resolve = (side: Side): Recipe | null => {
    const entry = current[side.id];
    if (!entry) return null;
    if (side.version === null || side.version === entry.recipe.version) return entry.recipe;
    return versions[`${side.id}@${side.version}`] ?? null;
  };

  useEffect(() => {
    const wanted = [left, right].filter(
      (side) => current[side.id] && side.version !== null && side.version !== current[side.id].recipe.version && !versions[`${side.id}@${side.version}`],
    );
    if (!wanted.length) return;
    let cancelled = false;
    Promise.all(wanted.map((side) => getRecipeVersion(workspaceId, side.id, side.version!)))
      .then((results) => {
        if (cancelled) return;
        setVersions((state) => ({
          ...state,
          ...Object.fromEntries(results.map((data, index) => [`${wanted[index].id}@${wanted[index].version}`, data.recipe])),
        }));
      })
      .catch((exc) => !cancelled && setError(errorMessage(exc)));
    return () => {
      cancelled = true;
    };
  }, [workspaceId, left, right, current, versions]);

  const a = resolve(left);
  const b = resolve(right);
  const comparison = useMemo(() => (a && b ? compareRecipes(a, b) : null), [a, b]);

  return (
    <div className="sl-modal-backdrop" role="presentation">
      <section aria-label="配方对比" aria-modal="true" className="sl-modal sl-compare-dialog" role="dialog">
        <header className="sl-modal-head">
          <GitCompareArrows size={18} aria-hidden="true" />
          <h2>配方对比</h2>
          <span className="sl-bar-spacer" />
          <label className="sl-check">
            <input checked={onlyDiff} onChange={(event) => setOnlyDiff(event.target.checked)} type="checkbox" />
            只看不同
          </label>
          <button aria-label="关闭" className="sl-icon-btn" onClick={onClose} type="button">
            <X size={16} />
          </button>
        </header>
        <div className="sl-modal-body">
          <div className="sl-cmp-pickers">
            <SidePicker
              current={current[left.id]}
              label="A"
              onChange={setLeft}
              recipe={a}
              recipes={recipes}
              side={left}
              workspaceId={workspaceId}
            />
            <button
              aria-label="左右互换"
              className="sl-icon-btn"
              onClick={() => {
                setLeft(right);
                setRight(left);
              }}
              title="左右互换"
              type="button"
            >
              <ArrowLeftRight size={16} />
            </button>
            <SidePicker
              current={current[right.id]}
              label="B"
              onChange={setRight}
              recipe={b}
              recipes={recipes}
              side={right}
              workspaceId={workspaceId}
            />
          </div>
          {error ? <p className="sl-error">{error}</p> : null}
          {!comparison ? (
            <p className="sl-muted">
              <LoaderCircle className="sl-spin" size={14} /> 读取配方…
            </p>
          ) : a === b ? (
            <p className="sl-muted">两边是同一个配方的同一版，换一个对比。</p>
          ) : comparison.same ? (
            <p className="sl-muted">两边内容完全一样。</p>
          ) : (
            <ComparisonView comparison={comparison} leftLabel="A" onlyDiff={onlyDiff} rightLabel="B" />
          )}
        </div>
      </section>
    </div>
  );
}

function SidePicker({
  workspaceId,
  label,
  side,
  recipes,
  current,
  recipe,
  onChange,
}: {
  workspaceId: string;
  label: string;
  side: Side;
  recipes: RecipeSummary[];
  current: { recipe: Recipe; history: History } | undefined;
  recipe: Recipe | null;
  onChange: (side: Side) => void;
}) {
  const versions = current
    ? [
        { version: current.recipe.version, updated_at: current.recipe.updated_at },
        ...current.history.filter((item) => item.version !== current.recipe.version),
      ].sort((x, y) => y.version - x.version)
    : [];
  const activeVersion = side.version ?? current?.recipe.version ?? null;
  return (
    <div className="sl-cmp-side">
      <span className="sl-cmp-side-label">{label}</span>
      {recipe?.source_image_id ? (
        <img alt="" className="sl-cmp-thumb" src={sourceImageUrl(workspaceId, recipe.source_image_id, 160)} />
      ) : (
        <span className="sl-cmp-thumb empty" />
      )}
      <div className="sl-cmp-side-fields">
        <select aria-label={`配方 ${label}`} onChange={(event) => onChange({ id: event.target.value, version: null })} value={side.id}>
          {recipes.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
        <select
          aria-label={`配方 ${label} 的版本`}
          disabled={!versions.length}
          onChange={(event) => onChange({ id: side.id, version: Number(event.target.value) })}
          value={activeVersion ?? ""}
        >
          {versions.map((item) => (
            <option key={item.version} value={item.version}>
              v{item.version}
              {item.version === current?.recipe.version ? "（当前）" : ` · ${formatTime(item.updated_at)}`}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
