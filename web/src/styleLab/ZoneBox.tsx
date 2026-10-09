import { Lock, Pencil, Type } from "lucide-react";
import { useState } from "react";

import type { RecipeToken } from "./api";
import { tokensToText, type Zone } from "./recipeModel";
import { TokenChip } from "./TokenChip";

type ZoneBoxProps = {
  zone: Zone;
  title: string;
  hint?: string;
  tokens: RecipeToken[];
  locked: boolean;
  selected: Set<string>;
  lookup: (text: string) => string | undefined;
  hints?: Record<string, string>;
  actions?: React.ReactNode;
  allowText: boolean;
  onSelect: (id: string, event: React.MouseEvent) => void;
  onDropToken: (id: string, zone: Zone, index: number) => void;
  onTextChange?: (text: string) => void;
};

/** 配方的一个区：小块可拖动（跨区或区内调序），可以切到文本视图直接编辑。 */
export function ZoneBox({
  zone,
  title,
  hint,
  tokens,
  locked,
  selected,
  lookup,
  hints,
  actions,
  allowText,
  onSelect,
  onDropToken,
  onTextChange,
}: ZoneBoxProps) {
  const [textMode, setTextMode] = useState(false);
  const [draft, setDraft] = useState("");
  const [dropIndex, setDropIndex] = useState<number | null>(null);

  const openText = () => {
    setDraft(tokensToText(tokens));
    setTextMode(true);
  };

  const indexFromEvent = (event: React.DragEvent) => {
    const chip = (event.target as HTMLElement).closest("[data-token-id]") as HTMLElement | null;
    if (!chip) return tokens.length;
    const index = tokens.findIndex((token) => token.id === chip.dataset.tokenId);
    const rect = chip.getBoundingClientRect();
    return event.clientX > rect.left + rect.width / 2 ? index + 1 : index;
  };

  return (
    <section
      className={`sl-zone zone-${zone} ${dropIndex !== null ? "drop-target" : ""}`}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node)) setDropIndex(null);
      }}
      onDragOver={(event) => {
        if (textMode) return;
        event.preventDefault();
        setDropIndex(indexFromEvent(event));
      }}
      onDrop={(event) => {
        event.preventDefault();
        const id = event.dataTransfer.getData("text/x-token-id");
        if (id) onDropToken(id, zone, indexFromEvent(event));
        setDropIndex(null);
      }}
    >
      <header className="sl-zone-head">
        <span className="sl-zone-title">
          {locked ? <Lock size={13} aria-hidden="true" /> : null}
          {title}
          <span className="sl-count">{tokens.length}</span>
        </span>
        {hint ? <span className="sl-muted">{hint}</span> : null}
        <span className="sl-bar-spacer" />
        {actions}
        {allowText && onTextChange ? (
          <button
            aria-label={textMode ? "切回小块" : "文本编辑"}
            className="sl-icon-btn"
            onClick={() => (textMode ? setTextMode(false) : openText())}
            title={textMode ? "切回小块" : "文本编辑"}
            type="button"
          >
            {textMode ? <Type size={14} /> : <Pencil size={14} />}
          </button>
        ) : null}
      </header>
      {textMode && onTextChange ? (
        <div className="sl-zone-text">
          <textarea
            aria-label={`${title}文本`}
            onChange={(event) => setDraft(event.target.value)}
            rows={Math.min(8, Math.max(2, Math.ceil(draft.length / 70)))}
            value={draft}
          />
          <div className="sl-zone-text-actions">
            <span className="sl-muted">文字没变的 tag 保留原来的来源，新写的记为手打。</span>
            <button className="sl-ghost" onClick={() => setTextMode(false)} type="button">
              取消
            </button>
            <button
              className="sl-primary small"
              onClick={() => {
                onTextChange(draft);
                setTextMode(false);
              }}
              type="button"
            >
              应用
            </button>
          </div>
        </div>
      ) : (
        <div className="sl-zone-chips">
          {tokens.length === 0 ? <span className="sl-muted">（空，可以把 token 拖到这里）</span> : null}
          {tokens.map((token, index) => (
            <span className={`sl-chip-slot ${dropIndex === index ? "drop-before" : ""}`} key={token.id}>
              <TokenChip
                draggable
                hint={hints?.[token.id]}
                onClick={(event) => onSelect(token.id, event)}
                onDragStart={(event) => {
                  event.dataTransfer.setData("text/x-token-id", token.id);
                  event.dataTransfer.effectAllowed = "move";
                }}
                selected={selected.has(token.id)}
                token={token}
                zh={lookup(token.text)}
                zone={zone}
              />
            </span>
          ))}
          {dropIndex === tokens.length && tokens.length ? <span className="sl-drop-end" /> : null}
        </div>
      )}
    </section>
  );
}
