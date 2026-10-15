import { CircleCheck, CircleX, LoaderCircle, Square, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";

import { computeTagDiff } from "../compare/tagDiff";
import type { CompareVerdict, ImageRecord, ParamDiff, RunItem, StyleLabRun } from "./api";
import { ACTIVE_RUN_STATUSES, runImageUrl, sourceImageUrl } from "./api";
import { formatTime, formatValue, runStatusLabels, verdictLabels } from "./format";
import { runViewerItem, sourceViewerItem, useImageViewer } from "./ImageViewer";

type RunPanelProps = {
  workspaceId: string;
  image: ImageRecord;
  runs: StyleLabRun[];
  onCancel: (run: StyleLabRun) => void;
};

export function RunPanel({ workspaceId, image, runs, onCancel }: RunPanelProps) {
  const [selected, setSelected] = useState<{ runId: string; index: number } | null>(null);

  // 切换图片或新提交一次重生时，自动选中最新一次的第一张。
  const latestId = runs[0]?.id ?? null;
  useEffect(() => {
    setSelected(latestId ? { runId: latestId, index: 0 } : null);
  }, [latestId]);

  if (!runs.length) {
    return (
      <section className="sl-section">
        <header className="sl-section-head">
          <span className="sl-section-label">对照</span>
        </header>
        <p className="sl-muted">还没有重生记录。</p>
      </section>
    );
  }

  const run = runs.find((item) => item.id === selected?.runId) ?? runs[0];
  const item = run.items[selected?.runId === run.id ? selected.index : 0] ?? run.items[0];

  return (
    <section className="sl-section">
      <header className="sl-section-head">
        <span className="sl-section-label">对照</span>
        <span className="sl-muted">{runs.length} 次重生</span>
      </header>

      <div className="sl-runs">
        {runs.map((entry) => (
          <div className={`sl-run ${entry.id === run.id ? "on" : ""}`} key={entry.id}>
            <div className="sl-run-head">
              <span>{formatTime(entry.created_at)}</span>
              <span className={`sl-run-status ${entry.status}`}>
                {ACTIVE_RUN_STATUSES.has(entry.status) ? <LoaderCircle className="sl-spin" size={12} /> : null}
                {runStatusLabels[entry.status]}
              </span>
              <span className="sl-muted">{describeSettings(entry)}</span>
              {ACTIVE_RUN_STATUSES.has(entry.status) && entry.job_id ? (
                <button aria-label="停止" className="sl-icon-btn" onClick={() => onCancel(entry)} title="停止剩余张数" type="button">
                  <Square size={12} />
                </button>
              ) : null}
            </div>
            <div className="sl-run-items">
              {entry.items.map((runItem) => (
                <button
                  aria-label={`第 ${runItem.index + 1} 张，种子 ${runItem.seed}`}
                  className={`sl-run-thumb ${entry.id === run.id && runItem.index === item.index ? "on" : ""}`}
                  key={runItem.index}
                  onClick={() => setSelected({ runId: entry.id, index: runItem.index })}
                  type="button"
                >
                  {runItem.image_path ? (
                    <img alt="" loading="lazy" src={runImageUrl(workspaceId, runItem.image_path, 160)} />
                  ) : (
                    <span className="sl-run-thumb-state">
                      {runItem.status === "running" ? <LoaderCircle className="sl-spin" size={14} /> : runStatusLabels[runItem.status]}
                    </span>
                  )}
                  {runItem.compare ? <VerdictDot verdict={runItem.compare.verdict} /> : null}
                </button>
              ))}
            </div>
            {entry.warnings.map((warning) => (
              <p className="sl-hint warn" key={warning}>
                {warning}
              </p>
            ))}
          </div>
        ))}
      </div>

      <CompareView image={image} item={item} run={run} workspaceId={workspaceId} />
    </section>
  );
}

/**
 * 一次出图的设置摘要。探针（替换角色、消融）、画师测试的记录也会出现在原图的记录里，
 * 它们的 settings 不是重生的格式（没有 count、overrides），每一项都要容错。
 */
export function describeSettings(run: StyleLabRun): string {
  const settings = (run.settings ?? {}) as Partial<StyleLabRun["settings"]> & {
    kind?: string;
    characters?: unknown[];
    units?: unknown[];
  };
  const parts: string[] = [];
  if (run.recipe) parts.push(`配方 v${run.recipe.version}`);
  if (settings.kind === "swap") parts.push(`替换角色 ${settings.characters?.length ?? 0} 个`);
  else if (settings.kind === "ablation") parts.push(`消融 ${settings.units?.length ?? 0} 组`);
  parts.push(`${settings.count ?? run.items?.length ?? 0} 张`);
  if (settings.seed_mode) {
    parts.push(settings.seed_mode === "source" ? "原图种子" : settings.seed_mode === "random" ? "随机种子" : `种子 ${settings.seed}`);
  }
  if (settings.size_mode === "custom") {
    parts.push(`${settings.width}×${settings.height}`);
  }
  const overrides = Object.keys(settings.overrides ?? {});
  if (overrides.length) {
    parts.push(`覆盖 ${overrides.join("/")}`);
  }
  return parts.join(" · ");
}

function VerdictDot({ verdict }: { verdict: CompareVerdict }) {
  return <span className={`sl-verdict-dot ${verdict}`} title={verdictLabels[verdict]} />;
}

function CompareView({
  workspaceId,
  image,
  run,
  item,
}: {
  workspaceId: string;
  image: ImageRecord;
  run: StyleLabRun;
  item: RunItem;
}) {
  const [mode, setMode] = useState<"side" | "slider">("side");
  const [split, setSplit] = useState(50);
  const [showExpected, setShowExpected] = useState(false);
  const viewer = useImageViewer();
  const compare = item.compare;
  const sourceUrl = sourceImageUrl(workspaceId, image.id, 640);
  const viewerItems = [
    sourceViewerItem(image),
    ...(item.image_path ? [runViewerItem(item.image_path, `重生 · 第 ${item.index + 1} 张`, item.seed)] : []),
  ];
  const generatedUrl = item.image_path ? runImageUrl(workspaceId, item.image_path, 640) : null;

  return (
    <div className="sl-compare">
      <div className="sl-compare-bar">
        {compare ? <VerdictBadge compare={compare} /> : <span className="sl-muted">{statusText(item)}</span>}
        <span className="sl-bar-spacer" />
        <div className="sl-segmented small" role="radiogroup">
          <button aria-checked={mode === "side"} className={mode === "side" ? "on" : ""} onClick={() => setMode("side")} role="radio" type="button">
            并排
          </button>
          <button aria-checked={mode === "slider"} className={mode === "slider" ? "on" : ""} onClick={() => setMode("slider")} role="radio" type="button">
            滑块
          </button>
        </div>
      </div>

      {mode === "side" || !generatedUrl ? (
        <div className="sl-compare-side">
          <figure>
            <button className="sl-zoomable" onClick={() => viewer.open(viewerItems, 0)} title="查看大图和文件位置" type="button">
              <img alt="原图" src={sourceUrl} />
            </button>
            <figcaption>原图</figcaption>
          </figure>
          <figure>
            {generatedUrl ? (
              <button className="sl-zoomable" onClick={() => viewer.open(viewerItems, 1)} title="查看大图和文件位置" type="button">
                <img alt="重生" src={generatedUrl} />
              </button>
            ) : (
              <div className="sl-compare-empty">{statusText(item)}</div>
            )}
            <figcaption>重生 · 种子 {item.seed}</figcaption>
          </figure>
        </div>
      ) : (
        <div className="sl-compare-slider">
          <img alt="原图" src={sourceUrl} />
          <img alt="重生" src={generatedUrl} style={{ clipPath: `inset(0 0 0 ${split}%)` }} />
          <span className="sl-slider-line" style={{ left: `${split}%` }} />
          <input aria-label="分割位置" max={100} min={0} onChange={(event) => setSplit(Number(event.target.value))} type="range" value={split} />
          <span className="sl-slider-label left">原图</span>
          <span className="sl-slider-label right">重生</span>
        </div>
      )}

      {compare?.verdict === "drift" ? (
        <p className="sl-hint warn">
          同参数重生是确定性的。参数一致但画面不同，通常是原图经过后期修改或局部重绘，或者 NovelAI 服务端有过变化；用本项目生成的图做原参重生可以确认链路本身。
        </p>
      ) : null}
      {item.error ? (
        <p className="sl-error" title={item.error_detail ?? item.error}>
          {item.error}
        </p>
      ) : null}
      {run.error ? <p className="sl-error">{run.error}</p> : null}

      {compare && compare.diffs.length ? (
        <div className="sl-diffs">
          <div className="sl-diffs-head">
            <span>参数差异</span>
            {compare.diffs.some((diff) => diff.expected) ? (
              <label className="sl-check">
                <input checked={showExpected} onChange={(event) => setShowExpected(event.target.checked)} type="checkbox" />
                显示可忽略的差异（{compare.diffs.filter((diff) => diff.expected).length} 项：主动改动、等价写法、客户端多记的字段）
              </label>
            ) : null}
          </div>
          <table>
            <thead>
              <tr>
                <th>参数</th>
                <th>原图</th>
                <th>重生</th>
              </tr>
            </thead>
            <tbody>
              {noteGroups(visibleDiffs(compare.diffs, showExpected)).map((entry) =>
                "group" in entry ? (
                  <tr className="expected" key={`group-${entry.note}`}>
                    <td>
                      {entry.group.length} 项
                      <span className="sl-diff-note">{entry.note}</span>
                    </td>
                    <td colSpan={2}>
                      <span className="sl-diff-keys">
                        {entry.group.map((diff) => (
                          <span className="sl-diff-key" key={diff.path} title={`原图：${formatValue(diff.left)}
重生：${missingLabel(diff.right)}`}>
                            {diffName(diff)}
                          </span>
                        ))}
                      </span>
                    </td>
                  </tr>
                ) : (
                <tr className={entry.expected ? "expected" : ""} key={entry.path}>
                  <td title={entry.note ?? entry.path}>
                    {diffName(entry)}
                    {entry.note ? <span className="sl-diff-note">{entry.note}</span> : null}
                  </td>
                  {isPromptDiff(entry) ? (
                    <td colSpan={2}>
                      <PromptDiff left={String(entry.left)} right={String(entry.right)} />
                    </td>
                  ) : (
                    <>
                      <td>{missingLabel(entry.left)}</td>
                      <td>{missingLabel(entry.right)}</td>
                    </>
                  )}
                </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

const MISSING = "<missing>";

/** 比对结果里 "<missing>" 表示这一边没有这个字段。 */
function missingLabel(value: unknown): string {
  return value === MISSING ? "（没有这个字段）" : formatValue(value);
}

function diffName(diff: ParamDiff): string {
  return diff.path.replace(/^\$\.(parameters\.)?/, "");
}

/** 同一原因的可忽略差异超过一项时合并成一行，只列字段名，悬停看两边的值。 */
type NoteGroup = { note: string; group: ParamDiff[] };

function noteGroups(diffs: ParamDiff[]): Array<ParamDiff | NoteGroup> {
  const byNote = new Map<string, ParamDiff[]>();
  diffs.forEach((diff) => {
    if (diff.expected && diff.note) byNote.set(diff.note, [...(byNote.get(diff.note) ?? []), diff]);
  });
  const emitted = new Set<string>();
  return diffs.flatMap<ParamDiff | NoteGroup>((diff) => {
    const group = diff.expected && diff.note ? byNote.get(diff.note)! : null;
    if (!group || group.length < 2) return [diff];
    if (emitted.has(diff.note!)) return [];
    emitted.add(diff.note!);
    return [{ note: diff.note!, group }];
  });
}

const PROMPT_PATH_RE = /(^\$\.input$|\.prompt$|\.uc$|\.negative_prompt$|base_caption$|char_caption$)/;

function isPromptDiff(diff: ParamDiff): boolean {
  return typeof diff.left === "string" && typeof diff.right === "string" && PROMPT_PATH_RE.test(diff.path);
}

/** input 和 parameters.prompt 是同一段提示词，内容相同只显示一行。 */
function visibleDiffs(diffs: ParamDiff[], showExpected: boolean): ParamDiff[] {
  const prompt = diffs.find((diff) => diff.path === "$.parameters.prompt");
  return diffs.filter(
    (diff) =>
      (showExpected || !diff.expected) &&
      !(diff.path === "$.input" && prompt && prompt.left === diff.left && prompt.right === diff.right),
  );
}

function PromptDiff({ left, right }: { left: string; right: string }) {
  const diff = computeTagDiff(left, right);
  return (
    <div className="sl-prompt-diff">
      {diff.removed.map((tag, index) => (
        <span className="sl-diff-tag removed" key={`r-${tag}-${index}`} title="只在原图">
          − {tag}
        </span>
      ))}
      {diff.added.map((tag, index) => (
        <span className="sl-diff-tag added" key={`a-${tag}-${index}`} title="只在重生">
          + {tag}
        </span>
      ))}
      <span className="sl-muted">
        {diff.removed.length || diff.added.length ? `其余 ${diff.unchanged.length} 个相同` : "tag 相同，只有顺序或空格不同"}
      </span>
    </div>
  );
}

function statusText(item: RunItem): string {
  return item.status === "running" ? "生成中…" : runStatusLabels[item.status];
}

function VerdictBadge({ compare }: { compare: NonNullable<RunItem["compare"]> }) {
  const Icon = compare.verdict === "match" ? CircleCheck : compare.verdict === "drift" ? TriangleAlert : CircleX;
  return (
    <span className={`sl-verdict ${compare.verdict}`}>
      <Icon size={15} aria-hidden="true" />
      {verdictLabels[compare.verdict]}
      {compare.similarity !== null ? <span className="sl-verdict-num">相似度 {(compare.similarity * 100).toFixed(1)}%</span> : null}
      {compare.dhash_distance !== null ? <span className="sl-verdict-num">dHash {compare.dhash_distance}</span> : null}
      {compare.param_diff_count ? <span className="sl-verdict-num">差异 {compare.param_diff_count} 项</span> : null}
    </span>
  );
}
