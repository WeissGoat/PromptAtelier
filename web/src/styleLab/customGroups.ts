import type { CustomGroup, CustomGroups, RecipeSummary, StyleGroup } from "./api";

export const EMPTY_CUSTOM_GROUPS: CustomGroups = {
  revision: 0, groups: [], membership: {}, locked_image_ids: [], ungrouped_image_ids: [],
};
export const UNGROUPED = "custom:ungrouped";

export function customImageIds(doc: CustomGroups, id: string): string[] {
  if (id === UNGROUPED) return doc.ungrouped_image_ids;
  const ids = new Set([id, ...doc.groups.filter((group) => group.parent_id === id).map((group) => group.id)]);
  return Object.entries(doc.membership).filter(([, target]) => ids.has(target)).map(([key]) => key);
}

export function recipesInGroup(recipes: RecipeSummary[], doc: CustomGroups, id: string): RecipeSummary[] {
  const ids = new Set([id, ...doc.groups.filter((group) => group.parent_id === id).map((group) => group.id)]);
  return recipes.filter((recipe) => recipe.source_group?.kind === "custom" && ids.has(recipe.source_group.id));
}

export function cleanRepresentatives(doc: CustomGroups): CustomGroups {
  return { ...doc, groups: doc.groups.map((group) => group.representative_image_id
    && !customImageIds(doc, group.id).includes(group.representative_image_id) ? { ...group, representative_image_id: null } : group) };
}

export function newCustomGroup(name: string, parentId: string | null = null): CustomGroup {
  return {
    id: `cg_${crypto.randomUUID()}`, parent_id: parentId, name, kind: "style", notes: "", reason: "",
    evidence_strength: "limited", evidence_image_ids: [], representative_image_id: null,
    origin_auto_group_id: null, order: 0, locked: false, updated_by: "user",
    image_ids: [], image_count: 0, post_count: 0, post_share: 0, usable_count: 0,
    date_from: null, date_to: null, missing_image_ids: [],
  };
}

export function customAsStyleGroup(group: CustomGroup, doc: CustomGroups): StyleGroup {
  return {
    id: group.id, name: group.name, signature: [], signature_kind: "style",
    image_ids: customImageIds(doc, group.id), image_count: group.image_count, post_count: group.post_count,
    date_from: group.date_from, date_to: group.date_to, children: [],
  };
}

export const preparationLabels = {
  needs_review: "待检查", ready: "已准备 · 待测试", stale: "来源已变化", source_missing: "源图缺失",
};
