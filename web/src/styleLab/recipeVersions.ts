/** 配方版本对比：两个版本之间每个区域加了、删了哪些 token，参数和其他设置改了什么。 */
import type { Recipe, RecipeToken } from "./api";
import { materialsOf, tokensToText } from "./recipeModel";

export type TokenChange = { added: string[]; removed: string[] };
export type FieldChange = { label: string; before: string; after: string };

export type RecipeDiff = {
  zones: Array<{ label: string } & TokenChange>;
  fields: FieldChange[];
  /** 两个版本完全一样（只比内容，不比版本号和时间）。 */
  same: boolean;
};

/** 按文本比（同一个 tag 出现几次就算几个），不看分隔符和来源。 */
export function tokenChange(before: RecipeToken[], after: RecipeToken[]): TokenChange {
  return { added: missingFrom(after, before), removed: missingFrom(before, after) };
}

/** tokens 里在 other 中找不到的（按次数抵消）。 */
function missingFrom(tokens: RecipeToken[], other: RecipeToken[]): string[] {
  const available = new Map<string, number>();
  other.forEach((token) => available.set(token.text.trim(), (available.get(token.text.trim()) ?? 0) + 1));
  const missing: string[] = [];
  tokens.forEach((token) => {
    const text = token.text.trim();
    const count = available.get(text) ?? 0;
    if (count > 0) available.set(text, count - 1);
    else missing.push(text);
  });
  return missing;
}

function show(value: unknown): string {
  if (value === undefined || value === null || value === "") return "（无）";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

export function recipeDiff(before: Recipe, after: Recipe): RecipeDiff {
  const zones: RecipeDiff["zones"] = [
    { label: "画风前缀", ...tokenChange(before.prefix, after.prefix) },
    { label: "主体", ...tokenChange(before.subject, after.subject) },
    { label: "画风后缀", ...tokenChange(before.suffix, after.suffix) },
    { label: "丢弃", ...tokenChange(before.dropped, after.dropped) },
    { label: "画风负面", ...tokenChange(before.negative, after.negative) },
  ];
  const captionCount = Math.max(before.character.captions.length, after.character.captions.length);
  for (let index = 0; index < captionCount; index += 1) {
    const left = before.character.captions[index];
    const right = after.character.captions[index];
    zones.push({ label: `角色提示词 #${index + 1}`, ...tokenChange(left?.tokens ?? [], right?.tokens ?? []) });
    zones.push({ label: `角色负面 #${index + 1}`, ...tokenChange(left?.negative ?? [], right?.negative ?? []) });
  }

  const fields: FieldChange[] = [];
  const field = (label: string, a: unknown, b: unknown) => {
    if (JSON.stringify(a ?? null) !== JSON.stringify(b ?? null)) fields.push({ label, before: show(a), after: show(b) });
  };
  field("名字", before.name, after.name);
  field("阶段", stageLabel(before), stageLabel(after));
  field("模型", before.model, after.model);
  const keys = [...new Set([...Object.keys(before.params), ...Object.keys(after.params)])].sort();
  keys.forEach((key) => field(`参数 ${key}`, before.params[key], after.params[key]));
  field("用原图的 vibe", before.use_source_vibe, after.use_source_vibe);
  field("flags", [...before.flags].sort().join(", "), [...after.flags].sort().join(", "));
  field("启用角色提示词", before.character.enabled, after.character.enabled);
  field("按位置摆放", Boolean(before.character.use_coords), Boolean(after.character.use_coords));
  field("自动补男角色", before.character.add_male_caption, after.character.add_male_caption);
  field("素材", materialsOf(before).map((item) => item.name).join("、"), materialsOf(after).map((item) => item.name).join("、"));
  field("备注", before.notes, after.notes);

  // 只是顺序或分隔符变了：没有增删，但拼出来的文本不同。
  zones.slice(0, 3).forEach((zone, index) => {
    const key = (["prefix", "subject", "suffix"] as const)[index];
    if (!zone.added.length && !zone.removed.length && tokensToText(before[key]) !== tokensToText(after[key])) {
      fields.push({ label: zone.label, before: tokensToText(before[key]), after: tokensToText(after[key]) });
    }
  });
  const changed = zones.filter((zone) => zone.added.length || zone.removed.length);
  return { zones: changed, fields, same: !changed.length && !fields.length };
}

function stageLabel(recipe: Recipe): string {
  return recipe.stage === "split" ? "划分中" : recipe.locked ? "已锁定画风" : "编辑（画风未锁定）";
}

/** 把旧版本的内容放进当前配方（id、版本号、创建时间不变），保存后成为新版本。 */
export function restoreVersion(current: Recipe, old: Recipe): Recipe {
  return { ...old, id: current.id, version: current.version, created_at: current.created_at, updated_at: current.updated_at };
}
