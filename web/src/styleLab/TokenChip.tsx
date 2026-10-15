import type { RecipeToken } from "./api";
import type { Zone } from "./recipeModel";

export function originKind(origin: string): "character" | "action" | "manual" | "source" {
  if (origin.startsWith("character:")) return "character";
  if (origin.startsWith("action:")) return "action";
  if (origin === "manual") return "manual";
  return "source";
}

/** 来源色条只看第一个非原图来源：卡片加的块一眼能看出来自哪类卡。 */
function originClass(token: RecipeToken): string {
  const extra = token.origins.find((origin) => origin !== "source");
  return extra ? `origin-${originKind(extra)}` : "";
}

/** 块所在的地方：配方的四个区，或角色提示词。 */
export type ChipZone = Zone | "character" | "unassigned";

type TokenChipProps = {
  token: RecipeToken;
  zone: ChipZone;
  zh?: string;
  hint?: string;
  selected?: boolean;
  /** 右上角留出删除按钮的位置（按钮在外面，按钮里不能套按钮）。 */
  removable?: boolean;
  draggable?: boolean;
  onClick?: (event: React.MouseEvent) => void;
  onDoubleClick?: (event: React.MouseEvent) => void;
  onDragStart?: (event: React.DragEvent) => void;
};

export function TokenChip({ token, zone, zh, hint, selected, removable, draggable, onClick, onDoubleClick, onDragStart }: TokenChipProps) {
  const title = [token.text, hint, token.origins.filter((origin) => origin !== "source").join("、")].filter(Boolean).join("\n");
  return (
    <button
      aria-pressed={selected}
      className={`sl-chip zone-${zone} ${originClass(token)} ${selected ? "selected" : ""} ${removable ? "removable" : ""}`}
      data-token-id={token.id}
      draggable={draggable}
      onClick={onClick}
      onDoubleClick={onDoubleClick}
      onDragStart={onDragStart}
      title={title}
      type="button"
    >
      <span className="sl-chip-en">{token.text}</span>
      {zh ? <span className="sl-chip-zh">{zh}</span> : null}
    </button>
  );
}
