import { Lock, Plus, X } from "lucide-react";
import { useRef, useState } from "react";

import type { RecipeToken } from "./api";
import { MATERIAL_DRAG_TYPE, type MaterialDrag, type Zone } from "./recipeModel";
import { originKind, TokenChip, type ChipZone } from "./TokenChip";

/** 主体里素材块的显示：label 返回素材名（不是素材块的来源返回 null），onRemove 一键移出。 */
export type BlockOptions = { label: (origin: string) => string | null; onRemove: (origin: string) => void };

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
  /** 双击改一块、加一块；锁定的画风区不能改。 */
  editable: boolean;
  onSelect: (id: string, event: React.MouseEvent) => void;
  onDropToken: (id: string, zone: Zone, index: number) => void;
  onEdit?: (id: string, text: string) => void;
  onAdd?: (text: string) => void;
  /** 删除一块；不给时跟 editable 一样（锁定的画风区没有删除按钮）。 */
  removable?: boolean;
  /** 接受从素材架拖来的整块素材。 */
  onDropMaterial?: (drag: MaterialDrag, index: number) => void;
  blocks?: BlockOptions;
};

/** 配方的一个区：每块可拖动（跨区或区内调序），双击改文字，"+" 加一块。 */
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
  editable,
  onSelect,
  onDropToken,
  onEdit,
  onAdd,
  removable = editable,
  onDropMaterial,
  blocks,
}: ZoneBoxProps) {
  const [dropIndex, setDropIndex] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);

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
        if (event.dataTransfer.types.includes(MATERIAL_DRAG_TYPE) && !onDropMaterial) return;
        event.preventDefault();
        setDropIndex(indexFromEvent(event));
      }}
      onDrop={(event) => {
        event.preventDefault();
        const material = event.dataTransfer.getData(MATERIAL_DRAG_TYPE);
        const id = event.dataTransfer.getData("text/x-token-id");
        if (material && onDropMaterial) onDropMaterial(JSON.parse(material) as MaterialDrag, indexFromEvent(event));
        else if (id) onDropToken(id, zone, indexFromEvent(event));
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
        {editable && onAdd ? (
          <button aria-label={`${title}加一块`} className="sl-icon-btn" onClick={() => setAdding(true)} title="加一块（整段是一块，不分词）" type="button">
            <Plus size={14} />
          </button>
        ) : null}
      </header>
      <BlockChips
        adding={adding}
        blocks={blocks}
        draggable
        dropIndex={dropIndex}
        editable={editable}
        empty={onDropMaterial ? "（空，可以把块或素材拖到这里，或点 + 加一块）" : "（空，可以把块拖到这里）"}
        hints={hints}
        label={title}
        lookup={lookup}
        onAdd={onAdd}
        onAddDone={() => setAdding(false)}
        onEdit={onEdit}
        onSelect={onSelect}
        removable={removable}
        selected={selected}
        tokens={tokens}
        zone={zone}
      />
    </section>
  );
}

type BlockChipsProps = {
  tokens: RecipeToken[];
  zone: ChipZone;
  label: string;
  selected: Set<string>;
  lookup: (text: string) => string | undefined;
  hints?: Record<string, string>;
  blocks?: BlockOptions;
  editable: boolean;
  /** 每块右上角带 × 删除（通过 onEdit 改成空文字）；默认跟 editable 一样。 */
  removable?: boolean;
  draggable?: boolean;
  dropIndex?: number | null;
  adding: boolean;
  empty: string;
  onSelect?: (id: string, event: React.MouseEvent) => void;
  onEdit?: (id: string, text: string) => void;
  onAdd?: (text: string) => void;
  onAddDone: () => void;
};

/** 一串块：区和每条角色提示词共用。双击一块就地改文字（Enter 保存、Shift+Enter 换行、Esc 取消，清空即删除）。 */
export function BlockChips({
  tokens,
  zone,
  label,
  selected,
  lookup,
  hints,
  blocks,
  editable,
  removable = editable,
  draggable,
  dropIndex,
  adding,
  empty,
  onSelect,
  onEdit,
  onAdd,
  onAddDone,
}: BlockChipsProps) {
  const [editing, setEditing] = useState<string | null>(null);
  const canEdit = editable && Boolean(onEdit);

  return (
    <div className="sl-zone-chips">
      {tokens.length === 0 && !adding ? <span className="sl-muted">{empty}</span> : null}
      {groupTokens(tokens, blocks).map((group) => {
        const slots = group.items.map(({ token, index }) => (
          <span className={`sl-chip-slot ${dropIndex === index ? "drop-before" : ""} ${editing === token.id ? "editing" : ""}`} key={token.id}>
            {editing === token.id ? (
              <BlockEditor
                initial={token.text}
                label={`编辑${label}的一块`}
                onDone={(text) => {
                  setEditing(null);
                  if (text !== null && text !== token.text) onEdit?.(token.id, text);
                }}
              />
            ) : (
              <TokenChip
                draggable={draggable}
                hint={[hints?.[token.id], canEdit ? "双击修改" : editable ? null : "锁定中，解锁后可以修改"].filter(Boolean).join(" · ")}
                onClick={onSelect ? (event) => onSelect(token.id, event) : undefined}
                onDoubleClick={canEdit ? () => setEditing(token.id) : undefined}
                onDragStart={
                  draggable
                    ? (event) => {
                        event.dataTransfer.setData("text/x-token-id", token.id);
                        event.dataTransfer.effectAllowed = "move";
                      }
                    : undefined
                }
                removable={removable && Boolean(onEdit)}
                selected={selected.has(token.id)}
                token={token}
                zh={lookup(token.text)}
                zone={zone}
              />
            )}
            {removable && onEdit && editing !== token.id ? (
              <button
                aria-label={`删除 ${token.text}`}
                className="sl-chip-remove"
                onClick={() => onEdit(token.id, "")}
                title="删除这一块"
                type="button"
              >
                <X size={11} />
              </button>
            ) : null}
          </span>
        ));
        if (!group.origin || !blocks) return slots;
        return (
          <span className={`sl-chip-block origin-${originKind(group.origin)}`} key={`block-${group.items[0].token.id}`}>
            <span className="sl-chip-block-label">
              {group.label}
              <button
                aria-label={`移出 ${group.label}`}
                className="sl-icon-btn"
                onClick={() => blocks.onRemove(group.origin!)}
                title="一键移出这块素材"
                type="button"
              >
                <X size={11} />
              </button>
            </span>
            {slots}
          </span>
        );
      })}
      {dropIndex === tokens.length && tokens.length ? <span className="sl-drop-end" /> : null}
      {adding && onAdd ? (
        <BlockEditor
          initial=""
          label={`${label}新加的一块`}
          onDone={(text) => {
            onAddDone();
            if (text?.trim()) onAdd(text);
          }}
        />
      ) : null}
    </div>
  );
}

/** 就地编辑一块：失去焦点也算保存。返回 null 表示取消。 */
function BlockEditor({ initial, label, onDone }: { initial: string; label: string; onDone: (text: string | null) => void }) {
  const [text, setText] = useState(initial);
  const finished = useRef(false);
  const finish = (value: string | null) => {
    if (finished.current) return;
    finished.current = true;
    onDone(value);
  };
  return (
    <textarea
      aria-label={label}
      autoFocus
      className="sl-block-editor"
      onBlur={() => finish(text)}
      onChange={(event) => setText(event.target.value)}
      onFocus={(event) => event.target.select()}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          finish(null);
        } else if (event.key === "Enter" && !event.shiftKey) {
          event.preventDefault();
          finish(text);
        }
      }}
      rows={Math.min(6, Math.max(1, Math.ceil(text.length / 56)))}
      value={text}
    />
  );
}

type TokenGroup = { origin: string | null; label: string | null; items: Array<{ token: RecipeToken; index: number }> };

/** 连续来自同一块素材的块归成一组显示素材名（旧配方按 tag 存的素材也能归到一起）；其余各自成组。 */
function groupTokens(tokens: RecipeToken[], blocks?: BlockOptions): TokenGroup[] {
  const groups: TokenGroup[] = [];
  tokens.forEach((token, index) => {
    const origin = blocks ? token.origins.find((item) => blocks.label(item) !== null) ?? null : null;
    const last = groups[groups.length - 1];
    if (origin && last && last.origin === origin) {
      last.items.push({ token, index });
      return;
    }
    groups.push({ origin, label: origin && blocks ? blocks.label(origin) : null, items: [{ token, index }] });
  });
  return groups;
}
