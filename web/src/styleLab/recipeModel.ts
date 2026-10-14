/**
 * 配方编辑的纯函数：划分、建议、移动、按来源增删、文本编辑。
 * 配方里的一个 token 是一块（一整组提示词：划分时标出的原文、一块素材），不按 tag 分词；
 * 要按 tag 拆开时由用户显式操作（splitToken）。所有函数都返回新对象，不改动传入的配方。
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

// ---- 划分阶段：在原文上拖选标记 ----

/** 标出来的一段原文，锁定后整段是一块（内部不再分词）。没标的是主体，两段标记之间的主体也是一块。 */
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
 * 拖选的范围按字符算，只去掉两头的空格和逗号，不按分词补全：
 * "1girl-1::,Chibi character::" 这种分词切不准的地方可以从中间切开。
 */
export function snapRange(text: string, start: number, end: number): [number, number] | null {
  let s = Math.max(0, Math.min(start, end));
  let e = Math.min(text.length, Math.max(start, end));
  while (s < e && EDGE_CHAR.test(text[s])) s += 1;
  while (e > s && EDGE_CHAR.test(text[e - 1])) e -= 1;
  return s < e ? [s, e] : null;
}

/** 去掉标记两头的空格和逗号（拆开一段标记后剩下的边）。 */
function trimMark(text: string, mark: TextMark): TextMark {
  let { start, end } = mark;
  while (start < end && EDGE_CHAR.test(text[start])) start += 1;
  while (end > start && EDGE_CHAR.test(text[end - 1])) end -= 1;
  return { ...mark, start, end };
}

/** 把 [start, end) 标成某个区；标成主体就是清掉这段的标记。每段标记各自成块，相邻的不合并。 */
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
  const marks = pieces
    .map((mark) => trimMark(split.text, mark))
    .filter((mark) => mark.start < mark.end)
    .sort((a, b) => a.start - b.start);
  return { ...split, marks };
}

/** 按 tag 拆开标：选中的范围里每个 token 各标一段（各自成块）。 */
export function markTokens(split: TextSplit, start: number, end: number, zone: Zone): TextSplit {
  let next = markRange(split, start, end, "subject");
  if (zone === "subject") return next;
  for (const span of tokenSpans(split.text.slice(start, end))) {
    next = markRange(next, start + span.start, start + span.end, zone);
  }
  return next;
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
export function textSplitOf(recipe: Recipe, sourcePrompt?: string | null, markUnclaimed = true): TextSplit {
  let text = sourcePrompt?.trim() ? sourcePrompt : tokensToText([...recipe.prefix, ...recipe.subject, ...recipe.suffix, ...recipe.dropped]);
  const claimed: Array<[number, number]> = [];
  const found: TextMark[] = [];
  const missing: Array<{ text: string; zone: MarkZone }> = [];
  const free = (at: number, length: number) => !claimed.some(([a, b]) => a < at + length && b > at);
  // 先找词边界上的（"girl" 不认 "1girl" 里的），找不到再认任意位置：按字符划分的块可能紧贴着别的字。
  const find = (piece: string, boundary: boolean): number => {
    let at = text.indexOf(piece);
    while (at >= 0 && (!free(at, piece.length) || (boundary && !isBoundary(text, at, at + piece.length)))) {
      at = text.indexOf(piece, at + 1);
    }
    return at;
  };
  const claim = (piece: string): number => {
    let at = find(piece, true);
    if (at < 0) at = find(piece, false);
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
  const resplit = markUnclaimed && (recipe.stage === "edit" || recipe.prefix.length + recipe.suffix.length + recipe.dropped.length > 0);
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

/**
 * 按类别和同组出现率给原文里的每个 token 建议区，拿不准的保持原样。
 * 连着的同区 token 标成一块；perTag 时每个 token 各成一块。
 */
export function suggestTextMarks(
  split: TextSplit,
  categories: Record<string, TagCategory>,
  frequency: Map<string, number>,
  perTag = false,
): { split: TextSplit; unsure: number } {
  const spans = tokenSpans(split.text);
  const suggestions = suggestZones(
    spans.map((span, index) => ({ id: `t${index}`, text: span.text, sep: "", origins: [] })),
    categories,
    frequency,
  );
  const runs: Array<{ start: number; end: number; zone: Zone; last: number }> = [];
  let unsure = 0;
  spans.forEach((span, index) => {
    const zone = suggestions[`t${index}`]?.zone;
    if (!zone) {
      unsure += 1;
      return;
    }
    const run = runs[runs.length - 1];
    if (!perTag && run && run.zone === zone && run.last === index - 1) {
      run.end = span.end;
      run.last = index;
    } else {
      runs.push({ start: span.start, end: span.end, zone, last: index });
    }
  });
  const next = runs.reduce((current, run) => markRange(current, run.start, run.end, run.zone), split);
  return { split: next, unsure };
}

/**
 * 把标记写回配方（保持原文顺序），进入编辑阶段并锁定画风。每段都整段成一块，不分词（两头的逗号空格去掉）。
 * 文字相同的块沿用原来的 id 和来源；主体里原图之外的块（素材、手打的）留在主体末尾。
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
  // 每个区上一块在原文里的结尾：同区的两块之间只隔着分隔符时（如 "a|b" 分开标），沿用原文的分隔符。
  const lastEnd: Partial<Record<Zone, number>> = {};
  for (const segment of textSegments(split)) {
    const range = snapRange(split.text, segment.start, segment.end);
    if (!range) continue;
    const [start, end] = range;
    const text = split.text.slice(start, end);
    const before = lastEnd[segment.zone];
    const gap = before === undefined ? "" : split.text.slice(before, start);
    const sep = gap && isEdgeOnly(gap) ? gap : "";
    lastEnd[segment.zone] = end;
    const reuse = pool.get(text)?.shift();
    const next = reuse ? { ...reuse, sep } : { id: newTokenId(), text, sep, origins: [SOURCE_ORIGIN] };
    used.add(next.id);
    zones[segment.zone].push(next);
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

/** 去掉某个来源：只属于它的块删掉，共有的（旧版按 tag 去重存的）只去掉这个来源。 */
function removeFromList(list: RecipeToken[], origin: string): RecipeToken[] {
  const tokens: RecipeToken[] = [];
  for (const token of list) {
    if (!token.origins.includes(origin)) {
      tokens.push(token);
      continue;
    }
    const rest = token.origins.filter((item) => item !== origin);
    if (rest.length) tokens.push({ ...token, origins: rest });
  }
  return tokens;
}

/** 一组 tag 拼成一块的文字。 */
export function joinTags(texts: string[]): string {
  return texts.map((text) => text.trim()).filter(Boolean).join(DEFAULT_SEP);
}

/** 整段文字作为一块；空文字没有块。 */
export function textBlock(text: string, origin: string = MANUAL_ORIGIN): RecipeToken[] {
  const clean = text.trim();
  return clean ? [{ id: newTokenId(), text: clean, sep: "", origins: [origin] }] : [];
}

/**
 * 某个来源（素材块）在一串块里的那一块换成 text：原来有就在原位置换掉（旧版按 tag 存的几块合成一块），
 * 没有就插在 at 处（默认末尾）；text 为空时去掉。
 */
export function setOriginBlock(list: RecipeToken[], origin: string, text: string, at?: number): RecipeToken[] {
  const first = list.findIndex((token) => token.origins.includes(origin));
  const kept = removeFromList(list, origin);
  const clean = text.trim();
  if (!clean) return kept;
  const keptIds = new Set(kept.map((token) => token.id));
  const position =
    first >= 0
      ? list.slice(0, first).filter((token) => keptIds.has(token.id)).length
      : Math.max(0, Math.min(at ?? kept.length, kept.length));
  const id = first >= 0 && !keptIds.has(list[first].id) ? list[first].id : newTokenId();
  const block: RecipeToken = { id, text: clean, sep: "", origins: [origin] };
  return [...kept.slice(0, position), block, ...kept.slice(position)];
}

/**
 * 素材块加进主体：整块是一块，不拆成 tag。已经加过就在原位置换成新的内容。
 * at 是插入位置（拖进主体时），默认追加到末尾。返回新配方和新增的块数。
 */
export function addTokens(recipe: Recipe, texts: string[], origin: string, at?: number): { recipe: Recipe; added: number } {
  const existed = recipe.subject.some((token) => token.origins.includes(origin));
  const subject = setOriginBlock(recipe.subject, origin, joinTags(texts), at);
  return { recipe: { ...recipe, subject }, added: existed || subject.length === recipe.subject.length ? 0 : 1 };
}

/** 一键移除某张卡片：只删只属于这张卡的 token；共有的 token 只去掉这个来源。 */
export function removeOrigin(recipe: Recipe, origin: string): Recipe {
  return { ...recipe, subject: removeFromList(recipe.subject, origin) };
}

export function originCount(recipe: Recipe, origin: string): number {
  return recipe.subject.filter((token) => token.origins.includes(origin)).length;
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

/** 恢复原图主体：原图里不属于前缀、后缀、丢弃的几段各成一块（画风区不动，锁定保护的就是这个）。 */
export function restoreSourceSubject(recipe: Recipe, sourcePrompt: string): Recipe {
  const split = textSplitOf({ ...recipe, subject: [] }, sourcePrompt, false);
  const subject = textSegments(split).flatMap((segment) => {
    const range = segment.zone === "subject" ? snapRange(split.text, segment.start, segment.end) : null;
    return range ? textBlock(split.text.slice(range[0], range[1]), SOURCE_ORIGIN) : [];
  });
  return { ...recipe, subject };
}

// ---- 块的编辑：双击改文字、加一块、合并、按 tag 拆开（四个区和每条角色提示词用同一套） ----

/** 对配方里的每一串块（四个区、每条角色提示词的正向）做同一个变换。 */
function mapLists(recipe: Recipe, fn: (list: RecipeToken[]) => RecipeToken[]): Recipe {
  const next = { ...recipe } as Recipe;
  for (const zone of ZONES) next[zone] = fn(recipe[zone]);
  next.character = {
    ...recipe.character,
    captions: recipe.character.captions.map((caption) => ({ ...caption, tokens: fn(caption.tokens) })),
  };
  return next;
}

export function findToken(recipe: Recipe, id: string): RecipeToken | null {
  for (const list of [...ZONES.map((zone) => recipe[zone]), ...recipe.character.captions.map((caption) => caption.tokens)]) {
    const token = list.find((item) => item.id === id);
    if (token) return token;
  }
  return null;
}

/** 改一块的文字；改成空的就删掉。改过的原图块记为手打（重新划分时不会当成原文）。 */
export function editInList(list: RecipeToken[], id: string, text: string): RecipeToken[] {
  const clean = text.trim();
  return list.flatMap((token) => {
    if (token.id !== id) return [token];
    if (!clean) return [];
    if (clean === token.text) return [token];
    const origins = [...new Set([...token.origins.filter((origin) => origin !== SOURCE_ORIGIN), MANUAL_ORIGIN])];
    return [{ ...token, text: clean, origins }];
  });
}

export function editToken(recipe: Recipe, id: string, text: string): Recipe {
  return mapLists(recipe, (list) => editInList(list, id, text));
}

export function addBlock(recipe: Recipe, zone: Zone, text: string): Recipe {
  return { ...recipe, [zone]: [...recipe[zone], ...textBlock(text)] };
}

/** 同一串里选中的几块合成一块，放在第一块的位置，原来的分隔符照留。 */
export function mergeInList(list: RecipeToken[], ids: Set<string>): RecipeToken[] {
  const picked = list.filter((token) => ids.has(token.id));
  if (picked.length < 2) return list;
  const merged: RecipeToken = {
    ...picked[0],
    text: tokensToText(picked),
    origins: [...new Set(picked.flatMap((token) => token.origins))],
  };
  return list.flatMap((token) => (token === picked[0] ? [merged] : ids.has(token.id) ? [] : [token]));
}

export function mergeTokens(recipe: Recipe, ids: string[]): Recipe {
  const set = new Set(ids);
  return mapLists(recipe, (list) => mergeInList(list, set));
}

/** 一块按 tag 拆开（用户显式要求时才分词），拼回去文字不变。 */
export function splitInList(list: RecipeToken[], id: string): RecipeToken[] {
  return list.flatMap((token) => {
    if (token.id !== id) return [token];
    const parts = tokenize(token.text).tokens;
    if (parts.length <= 1) return [token];
    return parts.map((part, index) => ({
      id: index === 0 ? token.id : newTokenId(),
      text: part.text,
      sep: index === 0 ? token.sep : part.sep,
      origins: [...token.origins],
    }));
  });
}

export function splitToken(recipe: Recipe, id: string): Recipe {
  return mapLists(recipe, (list) => splitInList(list, id));
}

export function canSplit(token: RecipeToken | null): boolean {
  return Boolean(token && tokenize(token.text).tokens.length > 1);
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

/** 角色卡作角色提示词时没有 girl/boy 就补 girl。 */
function captionTags(role: RecipeMaterial["role"], tags: string[]): string[] {
  return role === "character" && tags.length && !tags.some((tag) => GENDER_TAG.test(tag.trim())) ? ["girl", ...tags] : tags;
}

/** 放进第 index 条角色提示词（没有就新加一条）：角色卡替换整条（没有 girl/boy 时补 girl），动作卡作为一块追加到后面。 */
export function applyToCharacter(recipe: Recipe, drag: MaterialDrag, index = 0): Recipe {
  const captions = [...recipe.character.captions];
  const at = Math.min(index, captions.length);
  const caption = captions[at] ?? { tokens: [], negative: [] };
  const text = joinTags(captionTags(drag.role, drag.tags));
  const tokens = drag.role === "character" ? textBlock(text, drag.origin) : setOriginBlock(caption.tokens, drag.origin, text);
  captions[at] = { ...caption, tokens };
  return { ...recipe, character: { ...recipe.character, enabled: true, captions } };
}

/** 素材块筛的 tag 变了：主体和用到它的角色提示词里那一块按新的筛选重写。 */
function setMaterialExcluded(recipe: Recipe, origin: string, allTags: string[], excluded: string[]): Recipe {
  const material = materialsOf(recipe).find((item) => materialOrigin(item) === origin);
  if (!material) return recipe;
  const materials = materialsOf(recipe).map((item) => (item === material ? { ...item, excluded } : item));
  const tags = allTags.filter((tag) => !excluded.includes(tag));
  const subject = originCount(recipe, origin) ? setOriginBlock(recipe.subject, origin, joinTags(tags)) : recipe.subject;
  const captions = recipe.character.captions.map((caption) =>
    caption.tokens.some((token) => token.origins.includes(origin))
      ? { ...caption, tokens: setOriginBlock(caption.tokens, origin, joinTags(captionTags(material.role, tags))) }
      : caption,
  );
  return { ...recipe, materials, subject, character: { ...recipe.character, captions } };
}

/** 卡片上点一个 tag：切换筛选；这块素材已经加进主体或角色提示词时同步重写那一块。 */
export function toggleMaterialTag(recipe: Recipe, origin: string, tag: string, allTags: string[]): Recipe {
  const material = materialsOf(recipe).find((item) => materialOrigin(item) === origin);
  if (!material) return recipe;
  const excluded = material.excluded.includes(tag)
    ? material.excluded.filter((value) => value !== tag)
    : [...material.excluded, tag];
  return setMaterialExcluded(recipe, origin, allTags, excluded);
}

/** 全选 / 全不选。 */
export function setMaterialTags(recipe: Recipe, origin: string, allTags: string[], include: boolean): Recipe {
  return setMaterialExcluded(recipe, origin, allTags, include ? [] : [...allTags]);
}

/** 只从角色提示词里去掉这块素材的 tag。 */
export function removeFromCharacter(recipe: Recipe, origin: string): Recipe {
  const captions = recipe.character.captions.map((caption) => ({ ...caption, tokens: removeFromList(caption.tokens, origin) }));
  return { ...recipe, character: { ...recipe.character, captions } };
}
