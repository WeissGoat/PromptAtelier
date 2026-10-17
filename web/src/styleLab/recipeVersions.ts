/** 配方版本：设置的变化（区里的 tag 由 recipeCompare 按 tag 对比）、画风有没有变、恢复旧版本。 */
import type { Recipe } from "./api";
import { materialsOf, tokensToText } from "./recipeModel";

export type FieldChange = { label: string; before: string; after: string };

function show(value: unknown): string {
  if (value === undefined || value === null || value === "") return "（无）";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

/** 两个配方不同的设置：模型、参数、vibe、flags、角色设置、素材、备注。 */
export function settingChanges(before: Recipe, after: Recipe): FieldChange[] {
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
  return fields;
}

function stageLabel(recipe: Recipe): string {
  return recipe.stage === "split" ? "划分中" : recipe.locked ? "已锁定画风" : "编辑（画风未锁定）";
}

/** 画风（导出成 artist 的部分）有没有变：变了保存才是新版本，和后端 style_signature 一致。 */
export function styleChanged(before: Recipe, after: Recipe): boolean {
  const signature = (recipe: Recipe) =>
    JSON.stringify([
      tokensToText(recipe.prefix),
      tokensToText(recipe.suffix),
      tokensToText(recipe.negative),
      recipe.model ?? null,
      Object.keys(recipe.params)
        .sort()
        .map((key) => [key, recipe.params[key]]),
      recipe.use_source_vibe,
      [...recipe.flags].sort(),
    ]);
  return signature(before) !== signature(after);
}

/** 把旧版本的内容放进当前配方（id、版本号、创建时间不变），保存后成为新版本。 */
export function restoreVersion(current: Recipe, old: Recipe): Recipe {
  return { ...old, id: current.id, version: current.version, created_at: current.created_at, updated_at: current.updated_at };
}
