import { CircleCheck, CircleX, LoaderCircle, Square, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";

import { computeTagDiff } from "../compare/tagDiff";
import type { CompareVerdict, ParamDiff, RunItem, StyleLabRun } from "./api";
import { ACTIVE_RUN_STATUSES, runImageUrl, sourceImageUrl } from "./api";
import { formatTime, formatValue, runStatusLabels, verdictLabels } from "./format";

type RunPanelProps = {
  workspaceId: string;
  imageId: string;
  runs: StyleLabRun[];
  onCancel: (run: StyleLabRun) => void;
};

export function RunPanel({ workspaceId, imageId, runs, onCancel }: RunPanelProps) {
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

      <CompareView imageId={imageId} item={item} run={run} workspaceId={workspaceId} />
    </section>
  );
}

function describeSettings(run: StyleLabRun): string {
  const parts = [`${run.settings.count} 张`];
  parts.push(
    run.settings.seed_mode === "source" ? "原图种子" : run.settings.seed_mode === "random" ? "随机种子" : `种子 ${run.settings.seed}`,
  );
  if (run.settings.size_mode === "custom") {
    parts.push(`${run.settings.width}×${run.settings.height}`);
  }
  const overrides = Object.keys(run.settings.overrides);
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
  imageId,
  run,
  item,
}: {
  workspaceId: string;
  imageId: string;
  run: StyleLabRun;
  item: RunItem;
}) {
  const [mode, setMode] = useState<"side" | "slider">("side");
  const [split, setSplit] = useState(50);
  const [showExpected, setShowExpected] = useState(false);
  const compare = item.compare;
  const sourceUrl = sourceImageUrl(workspaceId, imageId, 640);
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
            <img alt="原图" src={sourceUrl} />
            <figcaption>原图</figcaption>
          </figure>
          <figure>
            {generatedUrl ? <img alt="重生" src={generatedUrl} /> : <div className="sl-compare-empty">{statusText(item)}</div>}
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
                显示可忽略的差异（主动改动、等价写法）
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
              {visibleDiffs(compare.diffs, showExpected).map((diff) => (
                <tr className={diff.expected ? "expected" : ""} key={diff.path}>
                  <td title={diff.note ?? diff.path}>
                    {diff.path.replace(/^\$\.(parameters\.)?/, "")}
                    {diff.note ? <span className="sl-diff-note">{diff.note}</span> : null}
                  </td>
                  {isPromptDiff(diff) ? (
                    <td colSpan={2}>
                      <PromptDiff left={String(diff.left)} right={String(diff.right)} />
                    </td>
                  ) : (
                    <>
                      <td>{formatValue(diff.left)}</td>
                      <td>{formatValue(diff.right)}</td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
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
