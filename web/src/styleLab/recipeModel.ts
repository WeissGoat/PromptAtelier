/**
 * 配方编辑的纯函数：划分、建议、移动、按来源增删、文本编辑。
 * 所有函数都返回新对象，不改动传入的配方。
 */
import type { ImageRecord, Recipe, RecipeMaterial, RecipeToken, TagCategory } from "./api";
import { DEFAULT_SEP, hasSeparator, innerTags, tokenize } from "./tokens";

export type Zone = "prefix" | "subject" | "suffix" | "dropped";
export const ZONES: Zone[] = ["prefix", "subject", "suffix", "dropped"];
export const STYLE_CATEGORIES: TagCategory[] = ["artist", "style", "quality", "meta"];
export const SUBJECT_CATEGORIES: TagCategory[] = [
  "count",
  "character",
  "appearance",
  "clothing",
  "action",
  "expression",
  "scene",
  "camera",
  "nsfw",
];

export const SOURCE_ORIGIN = "source";
export const MANUAL_ORIGIN = "manual";

let counter = 0;
export function newTokenId(): string {
  counter += 1;
  return `t${Date.now().toString(36)}${counter.toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

/**
 * 去重用的规范形式：忽略 {} [] 和大小写空格；但数字权重要保留，
 * "0.0::loli::"（去掉这个元素）和 "loli" 意思相反，不能当成同一个 tag。
 */
export function normalizeText(text: string): string {
  const weight = /^\s*(-?\d+(?:\.\d+)?)::/.exec(text)?.[1];
  const base = innerTags(text).join(", ") || text.trim().toLowerCase();
  return weight !== undefined && Number(weight) !== 1 ? `${Number(weight)}::${base}` : base;
}

// ---- 划分阶段 ----

export type SplitState = { tokens: RecipeToken[]; zones: Record<string, Zone> };

/** 当前配方摊平成原始顺序的一条 token 流（前缀、主体、后缀、丢弃），并记住各自的区。 */
export function splitStateOf(recipe: Recipe): SplitState {
  const zones: Record<string, Zone> = {};
  const tokens: RecipeToken[] = [];
  for (const zone of ZONES) {
    for (const token of recipe[zone]) {
      tokens.push(token);
      zones[token.id] = zone;
    }
  }
  return { tokens, zones };
}

/** 两条分界线：index 之前的是前缀，cutB 之后的是后缀；丢弃的 token 不受影响。 */
export function applyCuts(state: SplitState, cutA: number, cutB: number): SplitState {
  const [a, b] = cutA <= cutB ? [cutA, cutB] : [cutB, cutA];
  const zones = { ...state.zones };
  state.tokens.forEach((token, index) => {
    if (zones[token.id] === "dropped") {
      return;
    }
    zones[token.id] = index < a ? "prefix" : index < b ? "subject" : "suffix";
  });
  return { ...state, zones };
}

/** 从当前划分推回两条分界线的位置（前缀末尾、后缀开头），用于在界面上画线。 */
export function cutsOf(state: SplitState): [number, number] {
  let cutA = 0;
  let cutB = state.tokens.length;
  state.tokens.forEach((token, index) => {
    const zone = state.zones[token.id];
    if (zone === "prefix") {
      cutA = Math.max(cutA, index + 1);
    }
  });
  for (let index = state.tokens.length - 1; index >= 0; index -= 1) {
    const zone = state.zones[state.tokens[index].id];
    if (zone === "suffix") {
      cutB = index;
    } else if (zone !== "dropped") {
      break;
    }
  }
  return [cutA, Math.max(cutA, cutB)];
}

export function setZones(state: SplitState, ids: string[], zone: Zone): SplitState {
  const zones = { ...state.zones };
  ids.forEach((id) => {
    zones[id] = zone;
  });
  return { ...state, zones };
}

/** 把划分结果写回配方（保持原始顺序），进入编辑阶段并锁定画风。 */
export function commitSplit(recipe: Recipe, state: SplitState): Recipe {
  const pick = (zone: Zone) => state.tokens.filter((token) => state.zones[token.id] === zone);
  return {
    ...recipe,
    prefix: pick("prefix"),
    subject: pick("subject"),
    suffix: pick("suffix"),
    dropped: pick("dropped"),
    stage: "edit",
    locked: true,
  };
}

/** 一个 token 的类别：artist: 前缀算画师；组里有画师算画师，否则取多数。和后端 token_category 一致。 */
export function tokenCategory(text: string, categories: Record<string, TagCategory>): TagCategory | null {
  if (/^[{[(\-0-9.:]*artist:/i.test(text)) {
    return "artist";
  }
  const found = innerTags(text)
    .map((tag) => categories[tag])
    .filter((category): category is TagCategory => Boolean(category));
  if (!found.length) {
    return null;
  }
  if (found.includes("artist")) {
    return "artist";
  }
  const counts = new Map<TagCategory, number>();
  found.forEach((category) => counts.set(category, (counts.get(category) ?? 0) + 1));
  return [...counts.entries()].sort((a, b) => b[1] - a[1])[0][0];
}

/** 投稿级 tag 出现率：一个投稿算一次，多图投稿不会放大权重。 */
export function postFrequency(images: ImageRecord[]): Map<string, number> {
  const posts = new Map<string, Set<string>>();
  for (const image of images) {
    const key = image.post?.dir_name ?? image.id;
    const tags = posts.get(key) ?? new Set<string>();
    tokenize(image.prompt).tokens.forEach((token) => innerTags(token.text).forEach((tag) => tags.add(tag)));
    posts.set(key, tags);
  }
  const counts = new Map<string, number>();
  posts.forEach((tags) => tags.forEach((tag) => counts.set(tag, (counts.get(tag) ?? 0) + 1)));
  const total = Math.max(1, posts.size);
  const frequency = new Map<string, number>();
  counts.forEach((count, tag) => frequency.set(tag, count / total));
  return frequency;
}

export function tokenFrequency(text: string, frequency: Map<string, number>): number {
  const tags = innerTags(text);
  if (!tags.length) {
    return 0;
  }
  return Math.max(...tags.map((tag) => frequency.get(tag) ?? 0));
}

export type Suggestion = { zone: Zone | null; reason: string; review?: boolean };

const STYLE_FREQUENCY = 0.5;
/** 同组几乎每个投稿都有的场景/其他类词，通常是画风调味（如 Particles of Light）。 */
const SEASONING_FREQUENCY = 0.8;
const SEASONING_CATEGORIES: TagCategory[] = ["scene", "other"];
/** 高频的镜头、外貌、作品/角色名可能是画风（shallow depth of field）也可能是内容（face focus），交给人判断。 */
const REVIEW_WHEN_FREQUENT: TagCategory[] = ["camera", "appearance", "character"];
/** 这些永远是画面内容，出现率再高也不进画风（skill 的规则：1girl、solo 这类不算画风）。 */
const ALWAYS_SUBJECT: TagCategory[] = ["count", "clothing", "action", "expression", "nsfw"];

/**
 * 建议每个 token 的区：
 * - 画风类（画师、风格、质量、元信息）：画师总是画风，其余在同组出现率 >= 50% 才算；
 * - 同组出现率 >= 80% 的场景/其他类词算画风调味；高频的镜头、外貌、作品/角色名标为待判断；
 * - 人数、服装、动作、表情、NSFW 永远是主体。
 * 画风 token 后面的主体 token 比前面多就进前缀，否则进后缀。
 */
export function suggestZones(
  tokens: RecipeToken[],
  categories: Record<string, TagCategory>,
  frequency: Map<string, number>,
): Record<string, Suggestion> {
  const kinds = tokens.map((token) => {
    const category = tokenCategory(token.text, categories);
    const freq = tokenFrequency(token.text, frequency);
    let kind: "style" | "subject" | "unsure" = "unsure";
    let note = "";
    let review = false;
    if (category && STYLE_CATEGORIES.includes(category)) {
      kind = category === "artist" || freq >= STYLE_FREQUENCY ? "style" : "unsure";
    } else if (category && ALWAYS_SUBJECT.includes(category)) {
      kind = "subject";
    } else if (category && SEASONING_CATEGORIES.includes(category) && freq >= SEASONING_FREQUENCY) {
      kind = "style";
      note = " · 高频调味";
    } else if (category && REVIEW_WHEN_FREQUENT.includes(category) && freq >= SEASONING_FREQUENCY) {
      kind = "unsure";
      review = true;
      note = " · 同组高频，看是画风还是内容";
    } else if (category) {
      kind = "subject";
    }
    return { kind, category, freq, note, review };
  });
  const subjectBefore: number[] = [];
  let seen = 0;
  kinds.forEach((item) => {
    subjectBefore.push(seen);
    if (item.kind === "subject") seen += 1;
  });
  const result: Record<string, Suggestion> = {};
  tokens.forEach((token, index) => {
    const item = kinds[index];
    const reason = `${item.category ? categoryLabels[item.category] : "未分类"} · 同组 ${Math.round(item.freq * 100)}%${item.note}`;
    if (item.kind === "style") {
      const before = subjectBefore[index];
      const after = seen - before;
      result[token.id] = { zone: after >= before ? "prefix" : "suffix", reason };
    } else {
      result[token.id] = { zone: item.kind === "subject" ? "subject" : null, reason, review: item.review };
    }
  });
  return result;
}

export function applySuggestions(state: SplitState, suggestions: Record<string, Suggestion>): SplitState {
  const zones = { ...state.zones };
  state.tokens.forEach((token) => {
    const zone = suggestions[token.id]?.zone;
    if (zone) {
      zones[token.id] = zone;
    }
  });
  return { ...state, zones };
}

export const categoryLabels: Record<TagCategory, string> = {
  artist: "画师",
  style: "风格",
  quality: "质量",
  meta: "元信息",
  count: "人数",
  character: "角色",
  appearance: "外貌",
  clothing: "服装",
  action: "动作",
  expression: "表情",
  scene: "场景",
  camera: "镜头",
  nsfw: "NSFW",
  other: "其他",
};

// ---- 编辑阶段 ----

export type TokenZone = Exclude<Zone, "dropped"> | "dropped";

export function findZone(recipe: Recipe, id: string): Zone | null {
  return ZONES.find((zone) => recipe[zone].some((token) => token.id === id)) ?? null;
}

/** 把一批 token 挪到某个区的开头或末尾（保持它们原来的相对顺序）。 */
export function moveTokens(recipe: Recipe, ids: string[], zone: Zone, position: "start" | "end" = "end"): Recipe {
  const idSet = new Set(ids);
  const moving: RecipeToken[] = [];
  const next = { ...recipe } as Recipe;
  for (const current of ZONES) {
    const kept: RecipeToken[] = [];
    for (const token of recipe[current]) {
      (idSet.has(token.id) ? moving : kept).push(token);
    }
    next[current] = kept;
  }
  next[zone] = position === "start" ? [...moving, ...next[zone]] : [...next[zone], ...moving];
  return next;
}

/** 拖动：把 id 放到 zone 的 index 位置。 */
export function placeToken(recipe: Recipe, id: string, zone: Zone, index: number): Recipe {
  const fromZone = findZone(recipe, id);
  if (!fromZone) {
    return recipe;
  }
  const token = recipe[fromZone].find((item) => item.id === id)!;
  const next = { ...recipe, [fromZone]: recipe[fromZone].filter((item) => item.id !== id) } as Recipe;
  const target = [...next[zone]];
  const fromIndex = recipe[fromZone].findIndex((item) => item.id === id);
  const adjusted = fromZone === zone && fromIndex < index ? index - 1 : index;
  target.splice(Math.max(0, Math.min(adjusted, target.length)), 0, token);
  next[zone] = target;
  return next;
}

/**
 * 往一串 token 里加 tag：已有同一 tag 时不重复，只给它多记一个来源；新的按顺序插在 at 处（默认末尾）。
 */
function addToList(list: RecipeToken[], texts: string[], origin: string, at?: number): { tokens: RecipeToken[]; added: number } {
  const tokens = list.map((token) => ({ ...token, origins: [...token.origins] }));
  const index = new Map(tokens.map((token) => [normalizeText(token.text), token]));
  const fresh: RecipeToken[] = [];
  for (const text of texts) {
    const clean = text.trim();
    if (!clean) continue;
    const key = normalizeText(clean);
    const existing = index.get(key);
    if (existing) {
      if (!existing.origins.includes(origin)) existing.origins.push(origin);
      continue;
    }
    const token: RecipeToken = { id: newTokenId(), text: clean, sep: "", origins: [origin] };
    fresh.push(token);
    index.set(key, token);
  }
  const position = at === undefined ? tokens.length : Math.max(0, Math.min(at, tokens.length));
  tokens.splice(position, 0, ...fresh);
  return { tokens, added: fresh.length };
}

/** 去掉某个来源：只属于它的 token 删掉，共有的只去掉这个来源。text 给了时只处理这一个 tag。 */
function removeFromList(list: RecipeToken[], origin: string, text?: string): RecipeToken[] {
  const key = text === undefined ? null : normalizeText(text);
  const tokens: RecipeToken[] = [];
  for (const token of list) {
    if (!token.origins.includes(origin) || (key !== null && normalizeText(token.text) !== key)) {
      tokens.push(token);
      continue;
    }
    const rest = token.origins.filter((item) => item !== origin);
    if (rest.length) tokens.push({ ...token, origins: rest });
  }
  return tokens;
}

/**
 * 素材卡片加入 tag：主体里已有同一 tag 时不重复，只给它多记一个来源。
 * at 是插入位置（拖进主体时），默认追加到末尾。返回新配方和真正新增的数量。
 */
export function addTokens(recipe: Recipe, texts: string[], origin: string, at?: number): { recipe: Recipe; added: number } {
  const { tokens, added } = addToList(recipe.subject, texts, origin, at);
  return { recipe: { ...recipe, subject: tokens }, added };
}

/** 一键移除某张卡片：只删只属于这张卡的 token；共有的 token 只去掉这个来源。 */
export function removeOrigin(recipe: Recipe, origin: string): Recipe {
  return { ...recipe, subject: removeFromList(recipe.subject, origin) };
}

export function originCount(recipe: Recipe, origin: string): number {
  return recipe.subject.filter((token) => token.origins.includes(origin)).length;
}

/** 主体文本模式：重新分词，文字没变的 token 保留原来的 id 和来源，新出现的标为手打。 */
export function setSubjectText(recipe: Recipe, text: string): Recipe {
  return { ...recipe, subject: retokenize(recipe.subject, text) };
}

export function retokenize(previous: RecipeToken[], text: string): RecipeToken[] {
  const pool = new Map<string, RecipeToken[]>();
  previous.forEach((token) => {
    const list = pool.get(token.text) ?? [];
    list.push(token);
    pool.set(token.text, list);
  });
  return tokenize(text).tokens.map((token) => {
    const reuse = pool.get(token.text)?.shift();
    return reuse
      ? { ...reuse, sep: token.sep }
      : { id: newTokenId(), text: token.text, sep: token.sep, origins: [MANUAL_ORIGIN] };
  });
}

export function tokensToText(tokens: RecipeToken[]): string {
  if (!tokens.length) {
    return "";
  }
  let out = tokens[0].text;
  for (const token of tokens.slice(1)) {
    out += (hasSeparator(token.sep) ? token.sep : DEFAULT_SEP) + token.text;
  }
  return out;
}

/** 恢复原图主体：主体换回原图里属于主体的 token（画风区不动，锁定保护的就是这个）。 */
export function restoreSourceSubject(recipe: Recipe, sourcePrompt: string): Recipe {
  const styleTexts = new Set([...recipe.prefix, ...recipe.suffix, ...recipe.dropped].map((token) => token.text));
  const subject = tokenize(sourcePrompt)
    .tokens.filter((token) => !styleTexts.has(token.text))
    .map((token) => ({ id: newTokenId(), text: token.text, sep: token.sep, origins: [SOURCE_ORIGIN] }));
  return { ...recipe, subject };
}

/** 素材卡片上单个 tag 的开关：去掉这张卡对该 tag 的来源，没有其他来源时整个删掉。 */
export function removeOriginForText(recipe: Recipe, text: string, origin: string): Recipe {
  return { ...recipe, subject: removeFromList(recipe.subject, origin, text) };
}

/** 主体里出现过的素材卡片来源（character:<ref> / action:<ref>），按出现顺序。 */
export function cardOrigins(recipe: Recipe): string[] {
  const seen: string[] = [];
  for (const token of [...recipe.subject, ...recipe.character.tokens]) {
    for (const origin of token.origins) {
      if ((origin.startsWith("character:") || origin.startsWith("action:")) && !seen.includes(origin)) seen.push(origin);
    }
  }
  return seen;
}

// ---- 素材块 ----

/** 拖动素材块时 dataTransfer 里的类型；内容是 MaterialDrag 的 JSON。 */
export const MATERIAL_DRAG_TYPE = "application/x-sl-material";
export type MaterialDrag = { origin: string; role: RecipeMaterial["role"]; tags: string[]; material?: RecipeMaterial };

/** 素材块用进配方之前，先记进配方的 materials（已经有就不动），之后在素材架上筛 tag 才会同步。 */
export function withDragMaterial(recipe: Recipe, drag: MaterialDrag): Recipe {
  return drag.material ? addMaterial(recipe, drag.material) : recipe;
}

export function materialOrigin(material: Pick<RecipeMaterial, "role" | "ref">): string {
  return `${material.role}:${material.ref}`;
}

export function materialsOf(recipe: Recipe): RecipeMaterial[] {
  return recipe.materials ?? [];
}

export function materialTags(material: RecipeMaterial, allTags: string[]): string[] {
  const excluded = new Set(material.excluded);
  return allTags.filter((tag) => !excluded.has(tag));
}

export function addMaterial(recipe: Recipe, material: RecipeMaterial): Recipe {
  const origin = materialOrigin(material);
  if (materialsOf(recipe).some((item) => materialOrigin(item) === origin)) return recipe;
  return { ...recipe, materials: [...materialsOf(recipe), material] };
}

/** 从素材架拿掉一块：它加进主体和角色提示词的 tag 一起去掉。 */
export function removeMaterial(recipe: Recipe, origin: string): Recipe {
  return removeMaterialTokens({ ...recipe, materials: materialsOf(recipe).filter((item) => materialOrigin(item) !== origin) }, origin);
}

/** 主体和角色提示词里都去掉这块素材的 tag，素材块留在架上。 */
export function removeMaterialTokens(recipe: Recipe, origin: string): Recipe {
  return {
    ...removeOrigin(recipe, origin),
    character: { ...recipe.character, tokens: removeFromList(recipe.character.tokens, origin) },
  };
}

export function characterHasOrigin(recipe: Recipe, origin: string): boolean {
  return recipe.character.tokens.some((token) => token.origins.includes(origin));
}

const GENDER_TAG = /^(girl|boy|1girl|1boy|woman|man|other)$/i;

/** 放进角色提示词：角色卡替换整条 #1（没有 girl/boy 时补 girl），动作卡追加到后面。 */
export function applyToCharacter(recipe: Recipe, drag: MaterialDrag): Recipe {
  const character = { ...recipe.character, enabled: true };
  if (drag.role === "character") {
    const tags = drag.tags.some((tag) => GENDER_TAG.test(tag.trim())) ? drag.tags : ["girl", ...drag.tags];
    character.tokens = addToList([], tags, drag.origin).tokens;
  } else {
    character.tokens = addToList(recipe.character.tokens, drag.tags, drag.origin).tokens;
  }
  return { ...recipe, character };
}

/** 卡片上点一个 tag：切换筛选；这块素材已经加进主体或角色提示词时同步增删这个 tag。 */
export function toggleMaterialTag(recipe: Recipe, origin: string, tag: string): Recipe {
  const material = materialsOf(recipe).find((item) => materialOrigin(item) === origin);
  if (!material) return recipe;
  const excluding = !material.excluded.includes(tag);
  const materials = materialsOf(recipe).map((item) =>
    item === material
      ? { ...item, excluded: excluding ? [...item.excluded, tag] : item.excluded.filter((value) => value !== tag) }
      : item,
  );
  let subject = recipe.subject;
  let characterTokens = recipe.character.tokens;
  if (originCount(recipe, origin)) {
    subject = excluding ? removeFromList(subject, origin, tag) : addToList(subject, [tag], origin).tokens;
  }
  if (characterHasOrigin(recipe, origin)) {
    characterTokens = excluding ? removeFromList(characterTokens, origin, tag) : addToList(characterTokens, [tag], origin).tokens;
  }
  return { ...recipe, materials, subject, character: { ...recipe.character, tokens: characterTokens } };
}

/** 全选 / 全不选：同 toggleMaterialTag，一次处理整块。 */
export function setMaterialTags(recipe: Recipe, origin: string, allTags: string[], include: boolean): Recipe {
  const material = materialsOf(recipe).find((item) => materialOrigin(item) === origin);
  if (!material) return recipe;
  let next = recipe;
  for (const tag of allTags) {
    if (material.excluded.includes(tag) === include) next = toggleMaterialTag(next, origin, tag);
  }
  return next;
}

/** 只从角色提示词里去掉这块素材的 tag。 */
export function removeFromCharacter(recipe: Recipe, origin: string): Recipe {
  return { ...recipe, character: { ...recipe.character, tokens: removeFromList(recipe.character.tokens, origin) } };
}
