/**
 * 契约提示词的 Web 端分析（spec §5）：分词、来源标记、相对来源动作的 diff。
 * 分词与归一化规则和后端 compose_contracts/tokens.py 保持一致。
 */
import type { ActionMember, ContractFrame, ContractSources, SourceNode } from "./types";

export type PromptTag = {
  raw: string;
  body: string;
  key: string;
  weight: number;
  start: number;
  end: number;
  line: number;
};

const NUMERIC_OPEN = /^(-?\d+(?:\.\d+)?)::/;
const PAREN_WEIGHT = /^\((.*):\s*(-?\d+(?:\.\d+)?)\)$/s;
const NAI_BRACE_STEP = 1.05;
const SD_PAREN_STEP = 1.1;

/** 去权重后的归一化：反转义括号、小写、空白/连字符 → 下划线（同 policies.tokens.canonicalize_tag）。 */
export function normalizeTag(body: string): string {
  return body
    .trim()
    .replace(/\\([()[\]{}])/g, "$1")
    .toLowerCase()
    .replace(/\s+/g, "_")
    .replace(/-/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function round4(value: number): number {
  return Math.round(value * 10000) / 10000;
}

/** 按分隔符和换行切分；`{a, b}`、`1.2::a, b::` 这类权重可以跨多个 tag。 */
export function tokenizePrompt(text: string, separator = ","): PromptTag[] {
  const tags: PromptTag[] = [];
  let braceDepth = 0;
  let numeric: number | null = null;
  let offset = 0;
  const lines = (text ?? "").split("\n");
  lines.forEach((line, lineNo) => {
    let position = 0;
    for (const part of line.split(separator)) {
      const leading = part.length - part.trimStart().length;
      const start = offset + position + leading;
      position += part.length + separator.length;
      const raw = part.trim();
      if (!raw) continue;
      let body = raw;
      let numericHere = numeric;
      let openedNumeric = false;
      const open = NUMERIC_OPEN.exec(body);
      if (open) {
        numericHere = Number(open[1]);
        body = body.slice(open[0].length);
        openedNumeric = true;
      }
      let closesNumeric = false;
      if (body.endsWith("::") && numericHere !== null) {
        body = body.slice(0, -2);
        closesNumeric = true;
      }
      const leadOpen = body.length - body.replace(/^[{[]+/, "").length;
      const opens = body.slice(0, leadOpen);
      body = body.slice(leadOpen);
      const trailClose = body.length - body.replace(/[}\]]+$/, "").length;
      const closes = trailClose ? body.slice(body.length - trailClose) : "";
      body = trailClose ? body.slice(0, body.length - trailClose) : body;
      const count = (value: string, char: string) => value.split(char).length - 1;
      const depthHere = braceDepth + count(opens, "{") - count(opens, "[");
      let sdWeight = 1;
      const paren = PAREN_WEIGHT.exec(body);
      if (paren) {
        body = paren[1];
        sdWeight = Number(paren[2]);
      } else {
        while (body.startsWith("(") && body.endsWith(")") && !body.startsWith("\\(")) {
          body = body.slice(1, -1);
          sdWeight *= SD_PAREN_STEP;
        }
      }
      const weight = (numericHere ?? 1) * NAI_BRACE_STEP ** depthHere * sdWeight;
      body = body.trim();
      if (body) {
        tags.push({ raw, body, key: normalizeTag(body), weight: round4(weight), start, end: start + raw.length, line: lineNo });
      }
      braceDepth = depthHere - count(closes, "}") + count(closes, "]");
      if (openedNumeric && !closesNumeric) numeric = numericHere;
      else if (closesNumeric) numeric = null;
    }
    offset += line.length + 1;
  });
  return tags;
}

export type OriginKind = "character" | "action" | "clothing" | "background" | "reference";

export type Origin = {
  kind: OriginKind;
  /** 角色 id（c1/c2）或参考动作 ref；动作、服装、背景为空。 */
  id?: string;
  /** 角色等节点的分区名（hair、eyes…）。 */
  section?: string;
  raw: string;
  weight: number;
};

export type MarkedTag = PromptTag & {
  origins: Origin[];
  /** 0 个来源：Agent 新增。 */
  added: boolean;
  /** 有来源，但写法或权重和所有来源都不同。 */
  rewritten: boolean;
  /** 写错了块的角色词：值为这个词所属的角色 id（例如 c1 的发色写进了 c2 的块，或分角色时留在主提示词里）。 */
  misplaced?: string;
};

/** 代码块的键：positive / negative / positive c2 … */
export type BlockKey = { kind: "positive" | "negative"; character: string | null };

export function parseBlockKey(key: string): BlockKey {
  const [kind, character] = key.trim().split(/\s+/, 2);
  return { kind: kind === "negative" ? "negative" : "positive", character: character || null };
}

/** 块的显示顺序：主提示词 → c1 → c2 …，每组正向在前、负面在后。 */
export function orderBlockKeys(keys: string[], characterOrder: string[]): string[] {
  const rank = (key: string) => {
    const { kind, character } = parseBlockKey(key);
    const group = character == null ? -1 : characterOrder.includes(character) ? characterOrder.indexOf(character) : characterOrder.length;
    return [group, character ?? "", kind === "positive" ? 0 : 1] as const;
  };
  return [...keys].sort((a, b) => {
    const [ga, ca, ka] = rank(a);
    const [gb, cb, kb] = rank(b);
    return ga - gb || ca.localeCompare(cb) || ka - kb;
  });
}

/** 本帧写了 ```positive cN 的角色，按契约角色顺序。 */
export function blockCharacters(prompts: Record<string, string>, characterOrder: string[]): string[] {
  const ids = Object.keys(prompts)
    .map(parseBlockKey)
    .filter((block) => block.kind === "positive" && block.character)
    .map((block) => block.character as string);
  return orderBlockKeys(ids.map((id) => `positive ${id}`), characterOrder).map((key) => parseBlockKey(key).character as string);
}

// 多个角色常常共用的分区（同一部作品），不用来判断词属于哪个角色；与后端 character_blocks 校验器一致。
const SHARED_CHARACTER_SECTIONS = new Set(["copyright", "role"]);

const INLINE_CHARACTER_OPEN_RE = /::character\s*[A-Za-z0-9_]+\s*:/gi;
// 行内角色块的闭合 `::`：前面是空白或逗号、后面是逗号或串尾；`1.2::tag::` 的结尾紧贴 tag，不受影响。
const INLINE_CHARACTER_CLOSE_RE = /(^|[\s,])::(?=\s*(,|$))/gm;

/** 去掉动作库行内分角色写法 `::character A: … ::` 的外壳，只留里面的词（用于标记和 diff）。 */
export function flattenInlineCharacters(text: string): string {
  if (!/::character/i.test(text)) return text;
  return text.replace(INLINE_CHARACTER_OPEN_RE, ", ").replace(INLINE_CHARACTER_CLOSE_RE, "$1");
}

type OriginIndex = Map<string, Origin[]>;

function addOrigins(index: OriginIndex, text: string, origin: Omit<Origin, "raw" | "weight">) {
  for (const tag of tokenizePrompt(text)) {
    if (!tag.key) continue;
    const list = index.get(tag.key) ?? [];
    if (!list.some((item) => item.kind === origin.kind && item.id === origin.id && item.section === origin.section)) {
      list.push({ ...origin, raw: tag.raw, weight: tag.weight });
    }
    index.set(tag.key, list);
  }
}

function addNode(index: OriginIndex, node: SourceNode | null | undefined, kind: OriginKind, id: string | undefined, negative: boolean) {
  if (!node) return;
  if (negative) {
    addOrigins(index, node.negative.join(", "), { kind, id });
    return;
  }
  for (const [section, tags] of Object.entries(node.sections)) {
    addOrigins(index, tags.join(", "), { kind, id, section });
  }
}

/** 本帧可见的来源（§5.2）：角色、来源动作、服装、背景、参考动作。 */
export function frameMember(frame: ContractFrame, sources: ContractSources): ActionMember | null {
  if (frame.is_custom || frame.member_index == null) return null;
  return sources.action_group?.members.find((member) => member.index === frame.member_index) ?? null;
}

export function buildOriginIndex(frame: ContractFrame, sources: ContractSources, kind: "positive" | "negative" = "positive"): OriginIndex {
  const index: OriginIndex = new Map();
  const negative = kind === "negative";
  const characterIds = frame.characters.length ? frame.characters : Object.keys(sources.characters);
  for (const id of characterIds) addNode(index, sources.characters[id], "character", id, negative);
  const member = frameMember(frame, sources);
  if (member) addOrigins(index, flattenInlineCharacters(negative ? member.negative : member.positive), { kind: "action" });
  addNode(index, sources.clothing, "clothing", undefined, negative);
  addNode(index, sources.background, "background", undefined, negative);
  for (const ref of frame.inspired_by) {
    const reference = sources.references[ref];
    if (reference) addOrigins(index, flattenInlineCharacters(negative ? reference.negative : reference.positive), { kind: "reference", id: ref });
  }
  return index;
}

/**
 * 标记一个代码块里每个词的来源。
 * block 给出时检查角色词是否写对了块：cN 块里只属于其他角色的词、分角色时留在主提示词里的角色词，标为 misplaced。
 */
export function markPrompt(
  text: string,
  index: OriginIndex,
  block?: { character: string | null; splitCharacters: string[] },
): MarkedTag[] {
  return tokenizePrompt(text).map((tag) => {
    const origins = index.get(tag.key) ?? [];
    const rewritten = origins.length > 0 && origins.every((origin) => origin.raw !== tag.raw || origin.weight !== tag.weight);
    const marked: MarkedTag = { ...tag, origins, added: origins.length === 0, rewritten };
    const owners = [
      ...new Set(
        origins
          .filter((origin) => origin.kind === "character" && origin.id && !SHARED_CHARACTER_SECTIONS.has(origin.section ?? ""))
          .map((origin) => origin.id as string),
      ),
    ];
    if (block && owners.length) {
      if (block.character && !owners.includes(block.character)) marked.misplaced = owners[0];
      else if (!block.character && owners.length === 1 && block.splitCharacters.includes(owners[0])) marked.misplaced = owners[0];
    }
    return marked;
  });
}

/** 一段文本按 tag 位置切开：标记视图保留 Agent 的换行和分隔符原样显示。 */
export type MarkedSegment = { text: string; tag?: MarkedTag };

export function segmentText(text: string, tags: MarkedTag[]): MarkedSegment[] {
  const segments: MarkedSegment[] = [];
  let cursor = 0;
  for (const tag of tags) {
    if (tag.start > cursor) segments.push({ text: text.slice(cursor, tag.start) });
    segments.push({ text: text.slice(tag.start, tag.end), tag });
    cursor = tag.end;
  }
  if (cursor < text.length) segments.push({ text: text.slice(cursor) });
  return segments;
}

export type DiffEntry =
  | { type: "rewrite"; key: string; from: string; to: string; tag: PromptTag }
  | { type: "removed"; key: string; from: string }
  | { type: "added"; key: string; to: string; tag: PromptTag };

/** 本帧最终提示词 vs 来源提示词，只列改写 / 删除 / 新增（§5.3）。 */
export function diffAgainstSource(finalText: string, sourceText: string): DiffEntry[] {
  const finalTags = tokenizePrompt(finalText);
  const sourceTags = tokenizePrompt(sourceText);
  const sourceByKey = new Map<string, PromptTag>();
  for (const tag of sourceTags) if (tag.key && !sourceByKey.has(tag.key)) sourceByKey.set(tag.key, tag);
  const finalKeys = new Set(finalTags.map((tag) => tag.key));
  const entries: DiffEntry[] = [];
  const seen = new Set<string>();
  for (const tag of finalTags) {
    if (!tag.key || seen.has(tag.key)) continue;
    seen.add(tag.key);
    const source = sourceByKey.get(tag.key);
    if (!source) entries.push({ type: "added", key: tag.key, to: tag.raw, tag });
    else if (source.raw !== tag.raw || source.weight !== tag.weight) {
      entries.push({ type: "rewrite", key: tag.key, from: source.raw, to: tag.raw, tag });
    }
  }
  for (const [key, source] of sourceByKey) {
    if (!finalKeys.has(key)) entries.push({ type: "removed", key, from: source.raw });
  }
  return entries;
}

export function originLabel(origin: Origin): string {
  switch (origin.kind) {
    case "character":
      return `角色 ${origin.id ?? ""}${origin.section ? ` · ${origin.section}` : ""}`;
    case "action":
      return "来源动作";
    case "clothing":
      return `服装${origin.section ? ` · ${origin.section}` : ""}`;
    case "background":
      return `背景${origin.section ? ` · ${origin.section}` : ""}`;
    case "reference":
      return `参考 ${origin.id ?? ""}`;
  }
}

/** 标记颜色类名：角色按 c1/c2 区分色相。 */
export function originClass(origin: Origin): string {
  if (origin.kind === "character") return `origin-character origin-${(origin.id ?? "c1").replace(/[^a-z0-9]/gi, "")}`;
  return `origin-${origin.kind}`;
}
