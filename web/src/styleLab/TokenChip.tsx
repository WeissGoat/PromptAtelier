import type { RecipeToken } from "./api";
import type { Zone } from "./recipeModel";

export function originKind(origin: string): "character" | "action" | "manual" | "source" {
  if (origin.startsWith("character:")) return "character";
  if (origin.startsWith("action:")) return "action";
  if (origin === "manual") return "manual";
  return "source";
}

/** 来源色条只看第一个非原图来源：卡片加的 token 一眼能看出来自哪类卡。 */
function originClass(token: RecipeToken): string {
  const extra = token.origins.find((origin) => origin !== "source");
  return extra ? `origin-${originKind(extra)}` : "";
}

type TokenChipProps = {
  token: RecipeToken;
  zone: Zone | "unassigned";
  zh?: string;
  hint?: string;
  selected?: boolean;
  suggested?: Zone | null;
  review?: boolean;
  draggable?: boolean;
  onClick?: (event: React.MouseEvent) => void;
  onDragStart?: (event: React.DragEvent) => void;
};

export function TokenChip({ token, zone, zh, hint, selected, suggested, review, draggable, onClick, onDragStart }: TokenChipProps) {
  const title = [token.text, hint, token.origins.filter((origin) => origin !== "source").join("、")]
    .filter(Boolean)
    .join("\n");
  return (
    <button
      aria-pressed={selected}
      className={`sl-chip zone-${zone} ${originClass(token)} ${selected ? "selected" : ""} ${suggested ? `suggest-${suggested}` : ""} ${review ? "review" : ""}`}
      data-token-id={token.id}
      draggable={draggable}
      onClick={onClick}
      onDragStart={onDragStart}
      title={title}
      type="button"
    >
      <span className="sl-chip-en">{token.text}</span>
      {zh ? <span className="sl-chip-zh">{zh}</span> : null}
    </button>
  );
}
