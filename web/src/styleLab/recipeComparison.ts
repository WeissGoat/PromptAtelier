/**
 * 两个配方（或同一配方的两个版本）逐区对比。块是整段文字，对比时按 tag 拆开，
 * 同一个 tag 只是权重不同（0.6::ixy:: 和 0.8::ixy::、{tag} 和 tag）算权重变化，
 * 在另一边换了区（前缀挪到后缀）算挪动，其余是只在一边有。
 */
import type { Recipe, RecipeToken } from "./api";
import { settingChanges, type FieldChange } from "./recipeVersions";
import { tokenize } from "./tokens";

export type ChipStatus = "same" | "weight" | "only" | "moved";
/** note：权重变化（"权重 0.6 → 0.8"）；movedTo：挪到了另一边的哪个区。 */
export type CompareChip = { text: string; status: ChipStatus; note?: string; movedTo?: string };
export type CompareZone = {
  id: string;
  label: string;
  /** 画风区：导出成 artist 的部分。 */
  style: boolean;
  left: CompareChip[];
  right: CompareChip[];
  /** 有增删、权重或挪动。 */
  changed: boolean;
  /** tag 一样，只是顺序不同。 */
  reordered: boolean;
};
export type RecipeComparison = {
  zones: CompareZone[];
  fields: FieldChange[];
  /** 画风（前缀、后缀、负面）的 tag 和权重一样。 */
  styleSame: boolean;
  same: boolean;
};

type ParsedTag = { text: string; key: string; weight: number };

const WEIGHT_RE = /^(-?\d+(?:\.\d+)?)::([\s\S]*?)(?:::)?$/;

/** 一个 tag 的权重和去掉权重后的规范写法（小写、下划线当空格、组内逗号统一）。 */
export function parseTag(text: string): ParsedTag {
  const raw = text.trim();
  let body = raw;
  let weight = 1;
  const match = WEIGHT_RE.exec(body);
  if (match) {
    weight = Number(match[1]);
    body = match[2];
  }
  while (body.length > 1 && body.startsWith("{") && body.endsWith("}")) {
    weight *= 1.05;
    body = body.slice(1, -1);
  }
  while (body.length > 1 && body.startsWith("[") && body.endsWith("]")) {
    weight /= 1.05;
    body = body.slice(1, -1);
  }
  const key = body
    .toLowerCase()
    .replace(/_/g, " ")
    .split(/[,，]/)
    .map((part) => part.trim().replace(/\s+/g, " "))
    .filter(Boolean)
    .join(", ");
  return { text: raw, key: key || raw.toLowerCase(), weight: Math.round(weight * 1000) / 1000 };
}

function zoneTags(tokens: RecipeToken[]): ParsedTag[] {
  return tokens.flatMap((token) => tokenize(token.text).tokens.map((tag) => parseTag(tag.text)));
}

type ZoneSource = { id: string; label: string; style: boolean; tokens: (recipe: Recipe) => RecipeToken[] };

function zoneSources(left: Recipe, right: Recipe): ZoneSource[] {
  const zones: ZoneSource[] = [
    { id: "prefix", label: "画风前缀", style: true, tokens: (recipe) => recipe.prefix },
    { id: "subject", label: "主体", style: false, tokens: (recipe) => recipe.subject },
    { id: "suffix", label: "画风后缀", style: true, tokens: (recipe) => recipe.suffix },
    { id: "negative", label: "画风负面", style: true, tokens: (recipe) => recipe.negative },
    { id: "dropped", label: "丢弃", style: false, tokens: (recipe) => recipe.dropped },
  ];
  const captions = Math.max(left.character.captions.length, right.character.captions.length);
  for (let index = 0; index < captions; index += 1) {
    zones.push({
      id: `caption-${index}`,
      label: `角色提示词 #${index + 1}`,
      style: false,
      tokens: (recipe) => recipe.character.captions[index]?.tokens ?? [],
    });
    zones.push({
      id: `caption-negative-${index}`,
      label: `角色负面 #${index + 1}`,
      style: false,
      tokens: (recipe) => recipe.character.captions[index]?.negative ?? [],
    });
  }
  return zones;
}

/** 每个 tag 出现在这个配方的哪些区。 */
function zonesByKey(recipe: Recipe, zones: ZoneSource[]): Map<string, string[]> {
  const map = new Map<string, string[]>();
  zones.forEach((zone) =>
    zoneTags(zone.tokens(recipe)).forEach((tag) => map.set(tag.key, [...(map.get(tag.key) ?? []), zone.label])),
  );
  return map;
}

function weightText(value: number): string {
  return Number.isInteger(value) ? value.toFixed(1) : String(value);
}

function compareZone(
  zone: ZoneSource,
  left: Recipe,
  right: Recipe,
  leftWhere: Map<string, string[]>,
  rightWhere: Map<string, string[]>,
): CompareZone {
  const leftTags = zoneTags(zone.tokens(left));
  const rightTags = zoneTags(zone.tokens(right));
  const pool = new Map<string, number[]>();
  rightTags.forEach((tag, index) => pool.set(tag.key, [...(pool.get(tag.key) ?? []), index]));
  const rightChips: Array<CompareChip | null> = rightTags.map(() => null);
  const elsewhere = (where: Map<string, string[]>, key: string) => (where.get(key) ?? []).find((label) => label !== zone.label);

  const leftChips = leftTags.map<CompareChip>((tag) => {
    const candidates = pool.get(tag.key);
    const index = candidates?.shift();
    if (index === undefined) {
      const moved = elsewhere(rightWhere, tag.key);
      return moved ? { text: tag.text, status: "moved", movedTo: moved } : { text: tag.text, status: "only" };
    }
    const other = rightTags[index];
    if (other.weight === tag.weight) {
      rightChips[index] = { text: other.text, status: "same" };
      return { text: tag.text, status: "same" };
    }
    const note = `权重 ${weightText(tag.weight)} → ${weightText(other.weight)}`;
    rightChips[index] = { text: other.text, status: "weight", note };
    return { text: tag.text, status: "weight", note };
  });
  rightTags.forEach((tag, index) => {
    if (rightChips[index]) return;
    const moved = elsewhere(leftWhere, tag.key);
    rightChips[index] = moved ? { text: tag.text, status: "moved", movedTo: moved } : { text: tag.text, status: "only" };
  });

  const right_ = rightChips as CompareChip[];
  const changed = [...leftChips, ...right_].some((chip) => chip.status !== "same");
  const order = (tags: ParsedTag[]) => tags.map((tag) => tag.key).join("\n");
  return {
    id: zone.id,
    label: zone.label,
    style: zone.style,
    left: leftChips,
    right: right_,
    changed,
    reordered: !changed && order(leftTags) !== order(rightTags),
  };
}

export function compareRecipes(left: Recipe, right: Recipe): RecipeComparison {
  const sources = zoneSources(left, right);
  const leftWhere = zonesByKey(left, sources);
  const rightWhere = zonesByKey(right, sources);
  const zones = sources
    .map((zone) => compareZone(zone, left, right, leftWhere, rightWhere))
    .filter((zone) => zone.left.length || zone.right.length);
  const fields = settingChanges(left, right);
  const styleSame = zones.filter((zone) => zone.style).every((zone) => !zone.changed && !zone.reordered);
  return {
    zones,
    fields,
    styleSame,
    same: zones.every((zone) => !zone.changed && !zone.reordered) && !fields.length,
  };
}

/** 一区的变化计数：A 独有、B 独有、权重、挪动。 */
export function zoneCounts(zone: CompareZone): { onlyLeft: number; onlyRight: number; weight: number; moved: number } {
  return {
    onlyLeft: zone.left.filter((chip) => chip.status === "only").length,
    onlyRight: zone.right.filter((chip) => chip.status === "only").length,
    weight: zone.left.filter((chip) => chip.status === "weight").length,
    moved: zone.left.filter((chip) => chip.status === "moved").length + zone.right.filter((chip) => chip.status === "moved").length,
  };
}
