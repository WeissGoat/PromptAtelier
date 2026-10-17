/**
 * 消融测试的分组：画风前缀、后缀按 tag（或按块）分好，可以合成一组、拆开、新增。
 * 只在这次测试里用，不改配方；按配方存在浏览器里，配方的画风变了就重新分。
 */
import type { AblationUnit, Recipe } from "./api";
import { tokensToText } from "./recipeModel";
import { tokenize } from "./tokens";

export type PieceZone = "prefix" | "suffix" | "new";
export type PieceMode = "tag" | "block";

export type AblationPiece = {
  id: string;
  zone: PieceZone;
  /** 去掉的 tag（画风里原有的）。 */
  remove: string[];
  /** 加上的 tag（配方里没有的，加在后缀末尾）。 */
  add: string[];
};

export const ZONE_LABELS: Record<PieceZone, string> = { prefix: "前缀", suffix: "后缀", new: "新增" };

let counter = 0;
function pieceId(): string {
  counter += 1;
  return `p${Date.now().toString(36)}${counter}`;
}

/** 和后端一致：tag 比较时只把连续空白当成一个空格。 */
export function tagKey(text: string): string {
  return text.trim().split(/\s+/).join(" ");
}

function blockTags(text: string): string[] {
  return tokenize(text).tokens.map((token) => token.text);
}

/** 默认分组：按 tag 每个 tag 一组，按块每块一组。 */
export function defaultPieces(recipe: Recipe, mode: PieceMode): AblationPiece[] {
  return (["prefix", "suffix"] as const).flatMap((zone) =>
    recipe[zone].flatMap((block) => {
      const tags = blockTags(block.text);
      if (!tags.length) return [];
      return mode === "block"
        ? [{ id: pieceId(), zone, remove: tags, add: [] }]
        : tags.map((tag) => ({ id: pieceId(), zone, remove: [tag], add: [] }));
    }),
  );
}

/** 画风前缀、后缀里每个 tag 出现几次。 */
function styleTagCounts(recipe: Recipe): Map<string, number> {
  const counts = new Map<string, number>();
  [...recipe.prefix, ...recipe.suffix].forEach((block) =>
    blockTags(block.text).forEach((tag) => counts.set(tagKey(tag), (counts.get(tagKey(tag)) ?? 0) + 1)),
  );
  return counts;
}

/** 要去掉的 tag 配方里都还在（配方改过以后旧分组可能失效）。 */
export function pieceValid(piece: AblationPiece, recipe: Recipe): boolean {
  const counts = styleTagCounts(recipe);
  return piece.remove.every((tag) => {
    const left = counts.get(tagKey(tag)) ?? 0;
    counts.set(tagKey(tag), left - 1);
    return left > 0;
  });
}

export function pieceLabel(piece: AblationPiece): string {
  return [...piece.remove, ...piece.add.map((tag) => `+ ${tag}`)].join(", ");
}

export function pieceSize(piece: AblationPiece): number {
  return piece.remove.length + piece.add.length;
}

/** 选中的几组合成一组，放在第一组的位置。 */
export function mergePieces(pieces: AblationPiece[], ids: string[]): { pieces: AblationPiece[]; merged: string | null } {
  const chosen = pieces.filter((piece) => ids.includes(piece.id));
  if (chosen.length < 2) return { pieces, merged: null };
  const zones = new Set(chosen.map((piece) => piece.zone));
  const merged: AblationPiece = {
    id: pieceId(),
    zone: zones.size === 1 ? chosen[0].zone : chosen.find((piece) => piece.zone !== "new")?.zone ?? "new",
    remove: chosen.flatMap((piece) => piece.remove),
    add: chosen.flatMap((piece) => piece.add),
  };
  const first = pieces.indexOf(chosen[0]);
  const rest = pieces.filter((piece) => !ids.includes(piece.id));
  rest.splice(pieces.slice(0, first).filter((piece) => !ids.includes(piece.id)).length, 0, merged);
  return { pieces: rest, merged: merged.id };
}

/** 一组拆回每个 tag 一组。 */
export function splitPiece(pieces: AblationPiece[], id: string): AblationPiece[] {
  return pieces.flatMap((piece) =>
    piece.id !== id || pieceSize(piece) < 2
      ? [piece]
      : [
          ...piece.remove.map((tag) => ({ id: pieceId(), zone: piece.zone, remove: [tag], add: [] })),
          ...piece.add.map((tag) => ({ id: pieceId(), zone: "new" as const, remove: [], add: [tag] })),
        ],
  );
}

/** 手动新增一组：输入的 tag 画风里有的算去掉，没有的算加上。 */
export function newPiece(text: string, recipe: Recipe): AblationPiece | null {
  const tags = blockTags(text);
  if (!tags.length) return null;
  const counts = styleTagCounts(recipe);
  const remove: string[] = [];
  const add: string[] = [];
  tags.forEach((tag) => {
    const left = counts.get(tagKey(tag)) ?? 0;
    if (left > 0) {
      counts.set(tagKey(tag), left - 1);
      remove.push(tag);
    } else {
      add.push(tag);
    }
  });
  return { id: pieceId(), zone: "new", remove, add };
}

/** 选中的组变成出图的改动：每组一张，或合成一张。 */
export function piecesToUnits(pieces: AblationPiece[], ids: string[], together: boolean): AblationUnit[] {
  const chosen = pieces.filter((piece) => ids.includes(piece.id));
  if (!chosen.length) return [];
  const unit = (list: AblationPiece[]): AblationUnit => {
    const remove = list.flatMap((piece) => piece.remove);
    const add = list.flatMap((piece) => piece.add);
    return { label: list.map(pieceLabel).join(", "), token_ids: [], remove, add };
  };
  return together ? [unit(chosen)] : chosen.map((piece) => unit([piece]));
}

/** 画风前缀、后缀的文字：存下来的分组对应的是哪一版画风。 */
export function styleSignature(recipe: Recipe): string {
  return `${tokensToText(recipe.prefix)}\n${tokensToText(recipe.suffix)}`;
}

type Stored = { signature: string; mode: PieceMode; pieces: AblationPiece[] };

const storageKey = (recipeId: string) => `promptatelier.style-lab.ablation.${recipeId}`;

/** 读回这个配方上次的分组；画风变了就按默认重分，手动新增的、还有效的组留着。 */
export function loadPieces(recipe: Recipe): { mode: PieceMode; pieces: AblationPiece[] } {
  let stored: Stored | null = null;
  try {
    stored = JSON.parse(localStorage.getItem(storageKey(recipe.id)) ?? "null") as Stored | null;
  } catch {
    stored = null;
  }
  if (!stored || !Array.isArray(stored.pieces)) return { mode: "tag", pieces: defaultPieces(recipe, "tag") };
  if (stored.signature === styleSignature(recipe)) return { mode: stored.mode, pieces: stored.pieces };
  const kept = stored.pieces.filter((piece) => piece.zone === "new" && pieceValid(piece, recipe));
  return { mode: stored.mode, pieces: [...defaultPieces(recipe, stored.mode), ...kept] };
}

export function savePieces(recipe: Recipe, mode: PieceMode, pieces: AblationPiece[]): void {
  try {
    const value: Stored = { signature: styleSignature(recipe), mode, pieces };
    localStorage.setItem(storageKey(recipe.id), JSON.stringify(value));
  } catch {
    // 浏览器不让存就算了，只是下次要重新分。
  }
}
