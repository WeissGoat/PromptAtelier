import { Lock, Sparkles } from "lucide-react";
import { Fragment, useEffect, useMemo, useState } from "react";

import type { Recipe, TagCategory } from "./api";
import {
  applyCuts,
  applySuggestions,
  commitSplit,
  cutsOf,
  setZones,
  splitStateOf,
  suggestZones,
  type SplitState,
  type Zone,
} from "./recipeModel";
import { TokenChip } from "./TokenChip";
import { useTranslations } from "./translations";

const KEY_ZONES: Record<string, Zone> = { "1": "prefix", "2": "subject", "3": "suffix", x: "dropped", X: "dropped" };

type SplitViewProps = {
  recipe: Recipe;
  categories: Record<string, TagCategory>;
  frequency: Map<string, number>;
  translateOn: boolean;
  analysisReady: boolean;
  onCommit: (recipe: Recipe) => void;
};

/**
 * 划分阶段：整段原始提示词按原顺序平铺。两种方式可以混用：
 * 点 token 之间的缝放分界线（先放前缀/主体线，再放主体/后缀线）；选中 token 后按 1/2/3/X 刷到某个区。
 */
export function SplitView({ recipe, categories, frequency, translateOn, analysisReady, onCommit }: SplitViewProps) {
  const [state, setState] = useState<SplitState>(() => splitStateOf(recipe));
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [anchor, setAnchor] = useState<number | null>(null);
  const [nextCut, setNextCut] = useState<0 | 1>(0);
  const { lookup } = useTranslations(
    state.tokens.map((token) => token.text),
    translateOn,
  );
  const suggestions = useMemo(
    () => suggestZones(state.tokens, categories, frequency),
    [state.tokens, categories, frequency],
  );
  const [cutA, cutB] = cutsOf(state);

  useEffect(() => {
    setState(splitStateOf(recipe));
    setSelected(new Set());
    // 只在切换配方时重置；同一配方的划分是本组件自己的草稿。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recipe.id]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      const zone = KEY_ZONES[event.key];
      if (zone && selected.size) {
        event.preventDefault();
        setState((current) => setZones(current, [...selected], zone));
        setSelected(new Set());
      } else if (event.key === "Escape") {
        setSelected(new Set());
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selected]);

  const placeCut = (index: number) => {
    // 先放的线是前缀/主体分界，第二条是主体/后缀分界；之后交替调整离点击位置更近的那条。
    let a = cutA;
    let b = cutB;
    if (nextCut === 0) {
      a = index;
      b = Math.max(index, cutB);
      setNextCut(1);
    } else if (Math.abs(index - cutA) < Math.abs(index - cutB)) {
      a = index;
    } else {
      b = index;
    }
    setState((current) => applyCuts(current, Math.min(a, b), Math.max(a, b)));
  };

  const clickToken = (index: number, id: string, event: React.MouseEvent) => {
    setSelected((current) => {
      if (event.shiftKey && anchor !== null) {
        const [from, to] = anchor < index ? [anchor, index] : [index, anchor];
        return new Set([...current, ...state.tokens.slice(from, to + 1).map((token) => token.id)]);
      }
      const next = new Set(event.ctrlKey || event.metaKey ? current : []);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    setAnchor(index);
  };

  const counts = { prefix: 0, subject: 0, suffix: 0, dropped: 0 } as Record<Zone, number>;
  state.tokens.forEach((token) => {
    counts[state.zones[token.id]] += 1;
  });
  const unsure = state.tokens.filter((token) => suggestions[token.id]?.zone === null).length;
  const review = state.tokens.filter((token) => suggestions[token.id]?.review).length;

  return (
    <section className="sl-split">
      <header className="sl-split-bar">
        <div className="sl-split-legend">
          <span className="sl-legend prefix">前缀 {counts.prefix}</span>
          <span className="sl-legend subject">主体 {counts.subject}</span>
          <span className="sl-legend suffix">后缀 {counts.suffix}</span>
          <span className="sl-legend dropped">丢弃 {counts.dropped}</span>
        </div>
        <span className="sl-bar-spacer" />
        <button
          className="sl-ghost"
          disabled={!analysisReady}
          onClick={() => setState((current) => applySuggestions(current, suggestions))}
          title={analysisReady ? `按类别和同组出现率建议；${unsure} 个拿不准的保持不变` : "tag 分类还没完成"}
          type="button"
        >
          <Sparkles size={14} aria-hidden="true" />
          采用建议
        </button>
        <button className="sl-primary small" onClick={() => onCommit(commitSplit(recipe, state))} type="button">
          <Lock size={14} aria-hidden="true" />
          锁定画风
        </button>
      </header>
      <p className="sl-hint">
        点 token 之间的缝放分界线；或选中 token（Shift 连选、Ctrl 多选）后按 1 前缀 / 2 主体 / 3 后缀 / X 丢弃。虚线框是建议的区，
        琥珀色框是同组高频但拿不准是画风还是内容的{review ? `（${review} 个）` : ""}，鼠标悬停看原因。
      </p>
      <div className="sl-split-stream">
        {state.tokens.map((token, index) => (
          <Fragment key={token.id}>
            <Gap active={index === cutA || index === cutB} label={gapLabel(index, cutA, cutB)} onClick={() => placeCut(index)} />
            <TokenChip
              hint={suggestions[token.id]?.reason}
              onClick={(event) => clickToken(index, token.id, event)}
              selected={selected.has(token.id)}
              review={suggestions[token.id]?.review}
              suggested={suggestions[token.id]?.zone !== state.zones[token.id] ? suggestions[token.id]?.zone : null}
              token={token}
              zh={lookup(token.text)}
              zone={state.zones[token.id]}
            />
          </Fragment>
        ))}
        <Gap
          active={cutB === state.tokens.length && cutA !== cutB}
          label={gapLabel(state.tokens.length, cutA, cutB)}
          onClick={() => placeCut(state.tokens.length)}
        />
      </div>
    </section>
  );
}

function gapLabel(index: number, cutA: number, cutB: number): string | null {
  if (index === cutA && index === cutB) return "前缀 | 后缀";
  if (index === cutA) return "前缀 | 主体";
  if (index === cutB) return "主体 | 后缀";
  return null;
}

function Gap({ active, label, onClick }: { active: boolean; label: string | null; onClick: () => void }) {
  return (
    <button aria-label={label ? `分界线：${label}` : "在这里放分界线"} className={`sl-gap ${active && label ? "active" : ""}`} onClick={onClick} type="button">
      {active && label ? <span className="sl-gap-label">{label}</span> : null}
    </button>
  );
}
