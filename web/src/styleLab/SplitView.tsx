import { Eraser, Flame, Lock, Sparkles } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { Recipe, TagCategory } from "./api";
import {
  commitTextSplit,
  markRange,
  markTokens,
  snapRange,
  suggestTextMarks,
  textSegments,
  textSplitOf,
  tokenFrequency,
  tokenSpans,
  tokensToText,
  type TextSplit,
  type Zone,
} from "./recipeModel";
import { useTranslations } from "./translations";

const KEY_ZONES: Record<string, Zone> = {
  "1": "prefix",
  s: "prefix",
  "2": "subject",
  "3": "suffix",
  S: "suffix",
  x: "dropped",
  X: "dropped",
  Delete: "dropped",
};

const ZONE_ACTIONS: Array<{ zone: Zone; label: string; key: string }> = [
  { zone: "prefix", label: "前缀", key: "1" },
  { zone: "suffix", label: "后缀", key: "3" },
  { zone: "subject", label: "主体", key: "2" },
  { zone: "dropped", label: "丢弃", key: "X" },
];

type SplitViewProps = {
  recipe: Recipe;
  sourcePrompt: string | null;
  categories: Record<string, TagCategory>;
  frequency: Map<string, number>;
  /** 热力图：tag 在整个工作区的投稿里出现的比例，posts 是投稿数。 */
  heat?: { frequency: Map<string, number>; posts: number };
  analysisReady: boolean;
  translateOn: boolean;
  onCommit: (recipe: Recipe) => void;
};

/** 选区端点换算成整段原文里的字符位置：容器里只有原文文字，数前面的字数就行。 */
function textOffset(root: HTMLElement, node: Node, offset: number): number {
  const range = document.createRange();
  range.selectNodeContents(root);
  range.setEnd(node, offset);
  return range.toString().length;
}

/**
 * 划分阶段：原图提示词整段按原文显示。在文字上拖选一段，标成前缀或后缀（也可以丢弃），
 * 没标的都是主体。点已标的一段可以改标或清掉。
 */
export function SplitView({ recipe, sourcePrompt, categories, frequency, heat, analysisReady, translateOn, onCommit }: SplitViewProps) {
  const [split, setSplit] = useState<TextSplit>(() => textSplitOf(recipe, sourcePrompt));
  const [pending, setPending] = useState<[number, number] | null>(null);
  const [note, setNote] = useState<string | null>(null);
  // 默认选中的一段整体成块；勾上时按 tag 拆开，每个 tag 各成一块。
  const [perTag, setPerTag] = useState(false);
  const [showHeat, setShowHeat] = useState(true);
  const markSelection = perTag ? markTokens : markRange;
  const textRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setSplit(textSplitOf(recipe, sourcePrompt));
    setPending(null);
    // 只在切换配方时重置；同一配方的划分是本组件自己的草稿。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recipe.id]);

  const apply = (zone: Zone) => {
    if (!pending) return;
    setSplit((current) => markSelection(current, pending[0], pending[1], zone));
    setPending(null);
  };

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      if (event.key === "Escape") {
        setPending(null);
        return;
      }
      const zone = KEY_ZONES[event.key];
      if (!zone || !pending || event.ctrlKey || event.metaKey || event.altKey) return;
      event.preventDefault();
      setSplit((current) => markSelection(current, pending[0], pending[1], zone));
      setPending(null);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pending, markSelection]);

  const onMouseUp = () => {
    const root = textRef.current;
    const selection = window.getSelection();
    if (!root || !selection || !selection.rangeCount) return;
    const range = selection.getRangeAt(0);
    if (!root.contains(range.startContainer) || !root.contains(range.endContainer)) return;
    const start = textOffset(root, range.startContainer, range.startOffset);
    const end = textOffset(root, range.endContainer, range.endOffset);
    if (start === end) {
      // 单击：选中点到的那一段标记，方便改标或清掉。
      const mark = split.marks.find((item) => item.start <= start && start < item.end);
      setPending(mark ? [mark.start, mark.end] : null);
      return;
    }
    setPending(snapRange(split.text, start, end));
    selection.removeAllRanges();
  };

  const segments = useMemo(() => textSegments(split), [split]);
  const result = useMemo(() => commitTextSplit(recipe, split), [recipe, split]);
  const spans = useMemo(() => tokenSpans(split.text), [split.text]);
  const { lookup } = useTranslations(
    spans.map((span) => span.text),
    translateOn,
  );
  // 译文挂在每个 token 的末尾（CSS 伪元素显示，不算原文，拖选也选不到）。
  const zhAt = useMemo(() => {
    const map = new Map<number, string>();
    spans.forEach((span) => {
      const zh = lookup(span.text);
      if (zh) map.set(span.end, zh);
    });
    return map;
  }, [spans, lookup]);
  // 热力图：每个 token 在工作区投稿里的出现率。
  const heatSpans = useMemo(
    () => (heat && showHeat ? spans.map((span) => ({ ...span, value: tokenFrequency(span.text, heat.frequency) })) : []),
    [spans, heat, showHeat],
  );
  // 显示用：标记段按待标的选区、有译文的 token 末尾和（热力图时）每个 token 的边界切开，选区单独高亮。
  const pieces = useMemo(() => {
    const cuts = [
      ...(pending ? [pending[0], pending[1]] : []),
      ...zhAt.keys(),
      ...heatSpans.flatMap((span) => [span.start, span.end]),
    ];
    return segments.flatMap((segment) => {
      const inner = [...new Set(cuts.filter((cut) => cut > segment.start && cut < segment.end))].sort((a, b) => a - b);
      const points = [segment.start, ...inner, segment.end];
      return points.slice(1).map((end, index) => {
        const start = points[index];
        return {
          start,
          end,
          zone: segment.zone,
          zh: zhAt.get(end),
          heat: heatSpans.find((span) => span.start <= start && end <= span.end)?.value ?? null,
          pending: Boolean(pending && start >= pending[0] && end <= pending[1]),
        };
      });
    });
  }, [segments, pending, zhAt, heatSpans]);

  const adopt = () => {
    const suggested = suggestTextMarks(split, categories, frequency);
    setSplit(suggested.split);
    setPending(null);
    setNote(suggested.unsure ? `${suggested.unsure} 个拿不准的保持原样` : null);
  };

  const excerpt = pending ? split.text.slice(pending[0], pending[1]) : "";

  return (
    <section className="sl-split">
      <header className="sl-split-bar">
        <div className="sl-split-legend">
          <span className="sl-legend prefix">前缀 {result.prefix.length}</span>
          <span className="sl-legend subject">主体 {result.subject.length}</span>
          <span className="sl-legend suffix">后缀 {result.suffix.length}</span>
          <span className="sl-legend dropped">丢弃 {result.dropped.length}</span>
        </div>
        <span className="sl-bar-spacer" />
        {heat ? (
          <button
            aria-pressed={showHeat}
            className={`sl-ghost ${showHeat ? "on" : ""}`}
            onClick={() => setShowHeat(!showHeat)}
            title={`底色越深，这个 tag 在工作区 ${heat.posts} 个投稿里出现得越多`}
            type="button"
          >
            <Flame size={14} aria-hidden="true" />
            热力图
          </button>
        ) : null}
        <button
          className="sl-ghost"
          disabled={!analysisReady}
          onClick={adopt}
          title={analysisReady ? "按 tag 类别和同组出现率自动标一遍，标完还可以再改" : "tag 分类还没完成"}
          type="button"
        >
          <Sparkles size={14} aria-hidden="true" />
          采用建议
        </button>
        <button
          className="sl-ghost"
          disabled={!split.marks.length}
          onClick={() => {
            setSplit((current) => ({ ...current, marks: [] }));
            setPending(null);
          }}
          type="button"
        >
          <Eraser size={14} aria-hidden="true" />
          清空标记
        </button>
        <button className="sl-primary small" onClick={() => onCommit(result)} type="button">
          <Lock size={14} aria-hidden="true" />
          锁定画风
        </button>
      </header>
      <div className="sl-mark-bar" role="toolbar" aria-label="标记选中的文字">
        {pending ? (
          <>
            <span className="sl-mark-excerpt" title={excerpt}>
              已选「{excerpt}」
            </span>
            {ZONE_ACTIONS.map((action) => (
              <button className={`sl-mark-btn zone-${action.zone}`} key={action.zone} onClick={() => apply(action.zone)} type="button">
                {action.zone === "subject" ? "清除标记（回主体）" : `标为${action.label}`}
                <kbd>{action.key}</kbd>
              </button>
            ))}
          </>
        ) : (
          <span className="sl-muted">
            在下面的提示词上按字符拖选一段，标成前缀或后缀，标出的一段整体是一块，里面不再分词；没标的都是主体。点已标的一段可以改。
            {note ? `（${note}）` : ""}
          </span>
        )}
        <label className="sl-check sl-mark-pertag" title="勾上后，选中的一段按 tag 拆开，每个 tag 各成一块">
          <input checked={perTag} onChange={(event) => setPerTag(event.target.checked)} type="checkbox" />
          按 tag 拆开
        </label>
      </div>
      <div className={`sl-mark-text ${heatSpans.length ? "heat" : ""}`} data-testid="split-text" onMouseUp={onMouseUp} ref={textRef}>
        {pieces.map((piece) => (
          <span
            className={`sl-mark zone-${piece.zone} ${piece.pending ? "pending" : ""}`}
            data-start={piece.start}
            data-zh={piece.zh}
            key={`${piece.start}-${piece.end}`}
            style={piece.heat ? ({ "--heat": piece.heat.toFixed(3) } as React.CSSProperties) : undefined}
            title={piece.heat !== null && heat ? `工作区 ${Math.round(piece.heat * 100)}% 的投稿有（共 ${heat.posts} 个）` : undefined}
          >
            {split.text.slice(piece.start, piece.end)}
          </span>
        ))}
      </div>
      <dl className="sl-split-result">
        <dt>前缀</dt>
        <dd>{tokensToText(result.prefix) || <span className="sl-muted">（空）</span>}</dd>
        <dt>后缀</dt>
        <dd>{tokensToText(result.suffix) || <span className="sl-muted">（空）</span>}</dd>
      </dl>
    </section>
  );
}
