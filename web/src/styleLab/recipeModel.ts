/**
 * 配方编辑的纯函数：划分、建议、移动、按来源增删、文本编辑。
 * 所有函数都返回新对象，不改动传入的配方。
 */
import type { ImageRecord, Recipe, RecipeMaterial, RecipeToken, TagCategory } from "./api";
import { DEFAULT_SEP, hasSeparator, innerTags, protectedRanges, tokenize } from "./tokens";

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

// ---- 划分阶段：在原文上拖选标记 ----

/** 标出来的一段原文。没标的都是主体。 */
export type MarkZone = Exclude<Zone, "subject">;
export type TextMark = { start: number; end: number; zone: MarkZone };
export type TextSplit = { text: string; marks: TextMark[] };
export type TextSegment = { start: number; end: number; zone: Zone };

const WORD_CHAR = /[A-Za-z0-9_'-]/;
const EDGE_CHAR = /[\s,，|]/;

function isEdgeOnly(text: string): boolean {
  return [...text].every((char) => EDGE_CHAR.test(char));
}

/**
 * 拖选的范围对齐到能单独成块的边界：去掉两头的空格和逗号，半个英文词补全，
 * 切到半个括号组、权重组时整组带上。中文句子按选中的字切，不扩。
 */
export function snapRange(text: string, start: number, end: number): [number, number] | null {
  let s = Math.max(0, Math.min(start, end));
  let e = Math.min(text.length, Math.max(start, end));
  const trim = () => {
    while (s < e && EDGE_CHAR.test(text[s])) s += 1;
    while (e > s && EDGE_CHAR.test(text[e - 1])) e -= 1;
  };
  trim();
  if (s >= e) return null;
  while (s > 0 && WORD_CHAR.test(text[s - 1]) && WORD_CHAR.test(text[s])) s -= 1;
  while (e < text.length && WORD_CHAR.test(text[e - 1]) && WORD_CHAR.test(text[e])) e += 1;
  const groups = protectedRanges(text);
  let changed = true;
  while (changed) {
    changed = false;
    for (const [a, b] of groups) {
      if (a < e && b > s && (a < s || b > e)) {
        s = Math.min(s, a);
        e = Math.max(e, b);
        changed = true;
      }
    }
  }
  trim();
  return s < e ? [s, e] : null;
}

/** 去掉标记两头的空格和逗号（拆开一段标记后剩下的边）。 */
function trimMark(text: string, mark: TextMark): TextMark {
  let { start, end } = mark;
  while (start < end && EDGE_CHAR.test(text[start])) start += 1;
  while (end > start && EDGE_CHAR.test(text[end - 1])) end -= 1;
  return { ...mark, start, end };
}

/** 把 [start, end) 标成某个区；标成主体就是清掉这段的标记。相邻（只隔逗号空格）的同区标记合并。 */
export function markRange(split: TextSplit, start: number, end: number, zone: Zone): TextSplit {
  const pieces: TextMark[] = [];
  for (const mark of split.marks) {
    if (mark.end <= start || mark.start >= end) {
      pieces.push(mark);
      continue;
    }
    if (mark.start < start) pieces.push({ ...mark, end: start });
    if (mark.end > end) pieces.push({ ...mark, start: end });
  }
  if (zone !== "subject") pieces.push({ start, end, zone });
  const marks: TextMark[] = [];
  pieces
    .map((mark) => trimMark(split.text, mark))
    .filter((mark) => mark.start < mark.end)
    .sort((a, b) => a.start - b.start)
    .forEach((mark) => {
      const last = marks[marks.length - 1];
      if (last && last.zone === mark.zone && isEdgeOnly(split.text.slice(last.end, mark.start))) {
        marks[marks.length - 1] = { ...last, end: Math.max(last.end, mark.end) };
      } else {
        marks.push(mark);
      }
    });
  return { ...split, marks };
}

/** 整段原文按区切成连续的几段（没标的是主体），用于显示和写回配方。 */
export function textSegments(split: TextSplit): TextSegment[] {
  const segments: TextSegment[] = [];
  let cursor = 0;
  for (const mark of split.marks) {
    if (mark.start > cursor) segments.push({ start: cursor, end: mark.start, zone: "subject" });
    segments.push({ start: mark.start, end: mark.end, zone: mark.zone });
    cursor = mark.end;
  }
  if (cursor < split.text.length) segments.push({ start: cursor, end: split.text.length, zone: "subject" });
  return segments;
}

/** 分词后每个 token 在原文里的位置（分词是无损的，按 leading + sep 累加即可）。 */
export function tokenSpans(text: string): Array<{ start: number; end: number; text: string }> {
  const list = tokenize(text);
  let position = list.leading.length;
  return list.tokens.map((token, index) => {
    if (index > 0) position += token.sep.length;
    const start = position;
    position += token.text.length;
    return { start, end: position, text: token.text };
  });
}

function isBoundary(text: string, start: number, end: number): boolean {
  const before = start > 0 && WORD_CHAR.test(text[start - 1]) && WORD_CHAR.test(text[start]);
  const after = end < text.length && WORD_CHAR.test(text[end - 1]) && WORD_CHAR.test(text[end]);
  return !before && !after;
}

/**
 * 划分的起点：原文用原图的提示词；配方里已经在前缀、后缀、丢弃的 token 在原文里找到位置标上，
 * 原文里找不到的（解锁后手改过的）接在原文末尾再标上，重新划分不会丢。
 * 重新划分时，原文里哪个区都找不到的部分（之前从主体里删掉的）标成丢弃，不会悄悄回到主体。
 */
export function textSplitOf(recipe: Recipe, sourcePrompt?: string | null): TextSplit {
  let text = sourcePrompt?.trim() ? sourcePrompt : tokensToText([...recipe.prefix, ...recipe.subject, ...recipe.suffix, ...recipe.dropped]);
  const claimed: Array<[number, number]> = [];
  const found: TextMark[] = [];
  const missing: Array<{ text: string; zone: MarkZone }> = [];
  const claim = (piece: string): number => {
    let at = text.indexOf(piece);
    while (at >= 0 && (claimed.some(([a, b]) => a < at + piece.length && b > at) || !isBoundary(text, at, at + piece.length))) {
      at = text.indexOf(piece, at + 1);
    }
    if (at >= 0) claimed.push([at, at + piece.length]);
    return at;
  };
  for (const zone of ["prefix", "suffix", "dropped"] as MarkZone[]) {
    for (const token of recipe[zone]) {
      const at = claim(token.text);
      if (at < 0) missing.push({ text: token.text, zone });
      else found.push({ start: at, end: at + token.text.length, zone });
    }
  }
  recipe.subject.forEach((token) => claim(token.text));
  const resplit = recipe.stage === "edit" || recipe.prefix.length + recipe.suffix.length + recipe.dropped.length > 0;
  if (resplit) {
    let cursor = 0;
    for (const [a, b] of [...claimed].sort((x, y) => x[0] - y[0])) {
      if (a > cursor && !isEdgeOnly(text.slice(cursor, a))) found.push({ start: cursor, end: a, zone: "dropped" });
      cursor = Math.max(cursor, b);
    }
    if (cursor < text.length && !isEdgeOnly(text.slice(cursor))) found.push({ start: cursor, end: text.length, zone: "dropped" });
  }
  for (const item of missing) {
    if (text.trim()) text += DEFAULT_SEP;
    found.push({ start: text.length, end: text.length + item.text.length, zone: item.zone });
    text += item.text;
  }
  return found.reduce<TextSplit>((split, mark) => markRange(split, mark.start, mark.end, mark.zone), { text, marks: [] });
}

/** 按类别和同组出现率给原文里的每个 token 建议区，拿不准的保持原样。 */
export function suggestTextMarks(
  split: TextSplit,
  categories: Record<string, TagCategory>,
  frequency: Map<string, number>,
): { split: TextSplit; unsure: number } {
  const spans = tokenSpans(split.text);
  const suggestions = suggestZones(
    spans.map((span, index) => ({ id: `t${index}`, text: span.text, sep: "", origins: [] })),
    categories,
    frequency,
  );
  let next = split;
  let unsure = 0;
  spans.forEach((span, index) => {
    const zone = suggestions[`t${index}`]?.zone;
    if (zone) next = markRange(next, span.start, span.end, zone);
    else unsure += 1;
  });
  return { split: next, unsure };
}

/**
 * 把标记写回配方（保持原文顺序），进入编辑阶段并锁定画风。文字相同的 token 沿用原来的 id 和来源；
 * 主体里原图之外的 token（素材、手打的）留在主体末尾。
 */
export function commitTextSplit(recipe: Recipe, split: TextSplit): Recipe {
  const pool = new Map<string, RecipeToken[]>();
  for (const token of [...recipe.prefix, ...recipe.subject, ...recipe.suffix, ...recipe.dropped]) {
    const list = pool.get(token.text) ?? [];
    list.push(token);
    pool.set(token.text, list);
  }
  const zones: Record<Zone, RecipeToken[]> = { prefix: [], subject: [], suffix: [], dropped: [] };
  const used = new Set<string>();
  for (const segment of textSegments(split)) {
    for (const token of tokenize(split.text.slice(segment.start, segment.end)).tokens) {
      const reuse = pool.get(token.text)?.shift();
      const next = reuse
        ? { ...reuse, sep: token.sep }
        : { id: newTokenId(), text: token.text, sep: token.sep, origins: [SOURCE_ORIGIN] };
      used.add(next.id);
      zones[segment.zone].push(next);
    }
  }
  const extras = recipe.subject.filter((token) => !used.has(token.id) && token.origins.some((origin) => origin !== SOURCE_ORIGIN));
  return {
    ...recipe,
    prefix: zones.prefix,
    subject: [...zones.subject, ...extras],
    suffix: zones.suffix,
    dropped: zones.dropped,
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

/** 所有角色提示词的 token（不含负面）。 */
export function characterTokens(recipe: Recipe): RecipeToken[] {
  return recipe.character.captions.flatMap((caption) => caption.tokens);
}

/** 旧版本的配方（浏览器里的草稿备份）只有一条角色提示词，tokens / negative 直接挂在 character 上。 */
export function normalizeRecipe(recipe: Recipe): Recipe {
  const character = recipe.character as Recipe["character"] & { tokens?: RecipeToken[]; negative?: RecipeToken[] };
  if (Array.isArray(character.captions)) return recipe;
  const { tokens = [], negative = [], ...rest } = character;
  return { ...recipe, character: { ...rest, captions: tokens.length || negative.length ? [{ tokens, negative }] : [] } };
}

/** 主体里出现过的素材卡片来源（character:<ref> / action:<ref>），按出现顺序。 */
export function cardOrigins(recipe: Recipe): string[] {
  const seen: string[] = [];
  for (const token of [...recipe.subject, ...characterTokens(recipe)]) {
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
  return removeFromCharacter(removeOrigin(recipe, origin), origin);
}

export function characterHasOrigin(recipe: Recipe, origin: string): boolean {
  return characterTokens(recipe).some((token) => token.origins.includes(origin));
}

const GENDER_TAG = /^(girl|boy|1girl|1boy|woman|man|other)$/i;

/** 放进第 index 条角色提示词（没有就新加一条）：角色卡替换整条（没有 girl/boy 时补 girl），动作卡追加到后面。 */
export function applyToCharacter(recipe: Recipe, drag: MaterialDrag, index = 0): Recipe {
  const captions = [...recipe.character.captions];
  const at = Math.min(index, captions.length);
  const caption = captions[at] ?? { tokens: [], negative: [] };
  if (drag.role === "character") {
    const tags = drag.tags.some((tag) => GENDER_TAG.test(tag.trim())) ? drag.tags : ["girl", ...drag.tags];
    captions[at] = { ...caption, tokens: addToList([], tags, drag.origin).tokens };
  } else {
    captions[at] = { ...caption, tokens: addToList(caption.tokens, drag.tags, drag.origin).tokens };
  }
  return { ...recipe, character: { ...recipe.character, enabled: true, captions } };
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
  if (originCount(recipe, origin)) {
    subject = excluding ? removeFromList(subject, origin, tag) : addToList(subject, [tag], origin).tokens;
  }
  // 只改用到了这块素材的那几条角色提示词。
  const captions = recipe.character.captions.map((caption) => {
    if (!caption.tokens.some((token) => token.origins.includes(origin))) return caption;
    const tokens = excluding ? removeFromList(caption.tokens, origin, tag) : addToList(caption.tokens, [tag], origin).tokens;
    return { ...caption, tokens };
  });
  return { ...recipe, materials, subject, character: { ...recipe.character, captions } };
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
  const captions = recipe.character.captions.map((caption) => ({ ...caption, tokens: removeFromList(caption.tokens, origin) }));
  return { ...recipe, character: { ...recipe.character, captions } };
}
