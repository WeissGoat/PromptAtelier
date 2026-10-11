import { History, LoaderCircle, RotateCcw, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { errorMessage } from "../api/client";
import type { AnyRun, ArtistExport, Recipe } from "./api";
import { getRecipeVersion } from "./api";
import { formatTime } from "./format";
import { recipeDiff, restoreVersion } from "./recipeVersions";

export type HistoryEntry = { version: number; updated_at: number };

type RecipeHistoryProps = {
  workspaceId: string;
  saved: Recipe;
  dirty: boolean;
  history: HistoryEntry[];
  runs: AnyRun[];
  exports: ArtistExport[];
  onRestore: (recipe: Recipe) => void;
};

const RUN_KIND_LABELS: Record<string, string> = {
  recipe: "出图",
  regression: "回归",
  matrix: "矩阵",
  swap: "换角色",
  ablation: "消融",
};

/** 每个版本出过的图和导出：看结果时能对上是哪一版配方。 */
function versionMarks(version: number, runs: AnyRun[], exports: ArtistExport[]): string[] {
  const counts = new Map<string, number>();
  runs
    .filter((run) => run.recipe?.version === version)
    .forEach((run) => counts.set(run.kind, (counts.get(run.kind) ?? 0) + 1));
  const marks = [...counts].map(([kind, count]) => `${RUN_KIND_LABELS[kind] ?? kind} ${count}`);
  exports.filter((item) => item.recipe_version === version).forEach((item) => marks.push(`导出 ${item.folder}`));
  return marks;
}

export function RecipeHistory({ workspaceId, saved, dirty, history, runs, exports, onRestore }: RecipeHistoryProps) {
  const [open, setOpen] = useState<number | null>(null);
  const entries: HistoryEntry[] = useMemo(
    () => [{ version: saved.version, updated_at: saved.updated_at }, ...history.filter((item) => item.version !== saved.version)],
    [saved.version, saved.updated_at, history],
  );
  if (saved.version <= 0) return null;

  return (
    <section className="sl-recipe-group sl-history">
      <h3>
        <History size={13} aria-hidden="true" /> 版本 <span className="sl-count">{entries.length}</span>
      </h3>
      {entries.map((entry) => {
        const marks = versionMarks(entry.version, runs, exports);
        return (
          <button
            className="sl-history-row"
            key={entry.version}
            onClick={() => setOpen(entry.version)}
            title={entry.version > 1 ? "看这一版改了什么，可以恢复" : "第一版"}
            type="button"
          >
            <span className="sl-history-version">v{entry.version}</span>
            <span className="sl-muted">{entry.version === saved.version ? "当前" : formatTime(entry.updated_at)}</span>
            {marks.length ? <span className="sl-history-marks">{marks.join(" · ")}</span> : null}
          </button>
        );
      })}
      {open !== null ? (
        <VersionDialog
          dirty={dirty}
          onClose={() => setOpen(null)}
          onRestore={(recipe) => {
            onRestore(restoreVersion(saved, recipe));
            setOpen(null);
          }}
          saved={saved}
          version={open}
          workspaceId={workspaceId}
        />
      ) : null}
    </section>
  );
}

function VersionDialog({
  workspaceId,
  saved,
  version,
  dirty,
  onClose,
  onRestore,
}: {
  workspaceId: string;
  saved: Recipe;
  version: number;
  dirty: boolean;
  onClose: () => void;
  onRestore: (recipe: Recipe) => void;
}) {
  // 默认看这一版保存时改了什么（和上一版比）；也可以看它和当前版本差在哪。
  const [against, setAgainst] = useState<"previous" | "current">(version > 1 ? "previous" : "current");
  const [loaded, setLoaded] = useState<Record<number, Recipe>>({ [saved.version]: saved });
  const [error, setError] = useState<string | null>(null);
  const otherVersion = against === "previous" ? version - 1 : saved.version;
  const [before, after] = against === "previous" ? [otherVersion, version] : [version, saved.version];

  useEffect(() => {
    const missing = [version, otherVersion].filter((item) => item >= 1 && !loaded[item]);
    if (!missing.length) return;
    let cancelled = false;
    Promise.all(missing.map((item) => getRecipeVersion(workspaceId, saved.id, item)))
      .then((results) => {
        if (cancelled) return;
        setLoaded((current) => ({ ...current, ...Object.fromEntries(results.map((data, index) => [missing[index], data.recipe])) }));
      })
      .catch((exc) => !cancelled && setError(errorMessage(exc)));
    return () => {
      cancelled = true;
    };
  }, [workspaceId, saved.id, version, otherVersion, loaded]);

  const left = loaded[before];
  const right = loaded[after];
  const diff = left && right && before !== after ? recipeDiff(left, right) : null;
  const target = loaded[version];

  return (
    <div className="sl-modal-backdrop" role="presentation">
      <section aria-label={`配方 v${version}`} aria-modal="true" className="sl-modal sl-history-dialog" role="dialog">
        <header className="sl-modal-head">
          <History size={18} aria-hidden="true" />
          <h2>
            v{version}
            {version === saved.version ? "（当前）" : ""}
          </h2>
          <span className="sl-bar-spacer" />
          <button aria-label="关闭" className="sl-icon-btn" onClick={onClose} type="button">
            <X size={16} />
          </button>
        </header>
        <div className="sl-modal-body">
          <div className="sl-segmented small" role="radiogroup">
            <button
              aria-checked={against === "previous"}
              className={against === "previous" ? "on" : ""}
              disabled={version <= 1}
              onClick={() => setAgainst("previous")}
              role="radio"
              type="button"
            >
              这一版改了什么（v{version - 1} → v{version}）
            </button>
            <button
              aria-checked={against === "current"}
              className={against === "current" ? "on" : ""}
              disabled={version === saved.version}
              onClick={() => setAgainst("current")}
              role="radio"
              type="button"
            >
              和当前比（v{version} → v{saved.version}）
            </button>
          </div>
          {error ? <p className="sl-error">{error}</p> : null}
          {before === after ? (
            <p className="sl-muted">{version <= 1 ? "这是第一版。" : "选一个对比方式。"}</p>
          ) : !diff ? (
            <p className="sl-muted">
              <LoaderCircle className="sl-spin" size={14} /> 读取版本…
            </p>
          ) : diff.same ? (
            <p className="sl-muted">两个版本内容一样。</p>
          ) : (
            <DiffView diff={diff} />
          )}
        </div>
        <footer className="sl-modal-foot">
          {dirty && version !== saved.version ? <span className="sl-muted">当前有没保存的修改，恢复后会被替换。</span> : null}
          <span className="sl-bar-spacer" />
          <button className="sl-ghost" onClick={onClose} type="button">
            关闭
          </button>
          <button
            className="sl-primary"
            disabled={!target || version === saved.version}
            onClick={() => target && onRestore(target)}
            title="把这一版的内容放进编辑区，保存后成为新版本，历史不会丢"
            type="button"
          >
            <RotateCcw size={15} aria-hidden="true" />
            恢复成 v{version}
          </button>
        </footer>
      </section>
    </div>
  );
}

function DiffView({ diff }: { diff: ReturnType<typeof recipeDiff> }) {
  return (
    <div className="sl-history-diff">
      {diff.zones.map((zone) => (
        <div className="sl-history-zone" key={zone.label}>
          <span className="sl-history-label">{zone.label}</span>
          <div className="sl-prompt-diff">
            {zone.removed.map((tag, index) => (
              <span className="sl-diff-tag removed" key={`r-${tag}-${index}`}>
                − {tag}
              </span>
            ))}
            {zone.added.map((tag, index) => (
              <span className="sl-diff-tag added" key={`a-${tag}-${index}`}>
                + {tag}
              </span>
            ))}
          </div>
        </div>
      ))}
      {diff.fields.length ? (
        <table className="sl-history-fields">
          <thead>
            <tr>
              <th>设置</th>
              <th>之前</th>
              <th>之后</th>
            </tr>
          </thead>
          <tbody>
            {diff.fields.map((field) => (
              <tr key={field.label}>
                <td>{field.label}</td>
                <td>{field.before}</td>
                <td>{field.after}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </div>
  );
}
