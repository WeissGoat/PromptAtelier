/**
 * NovelAI 提示词的无损分词，和后端 style_lab/tokens.py 同一套规则，
 * 两边共用 tests/fixtures/prompt_tokens.json 的用例。
 */

export type Token = { text: string; sep: string };
export type TokenList = { leading: string; tokens: Token[]; trailing: string };

const SEPARATORS = new Set([",", "，", "|", "\n"]);
const OPENERS: Record<string, string> = { "{": "}", "[": "]", "(": ")" };
const CLOSERS = new Set(Object.values(OPENERS));
const WEIGHT_OPEN_RE = /-?\d+(?:\.\d+)?::/y;
const WEIGHT_OPEN_GLOBAL_RE = /-?\d+(?:\.\d+)?::/g;
const NUMBER_AT_END_RE = /-?\d+(?:\.\d+)?$/;
const SD_WEIGHT_RE = /:-?\d+(?:\.\d+)?$/;
export const DEFAULT_SEP = ", ";

export function tokenize(text: string): TokenList {
  const source = text ?? "";
  const isProtected = protectedMask(source);
  const segments: Array<[number, number]> = [];
  let start = 0;
  for (let index = 0; index < source.length; index += 1) {
    if (SEPARATORS.has(source[index]) && !isProtected[index]) {
      segments.push([start, index]);
      start = index + 1;
    }
  }
  segments.push([start, source.length]);

  const result: TokenList = { leading: "", tokens: [], trailing: "" };
  let cursor = 0;
  for (const [segStart, segEnd] of segments) {
    const raw = source.slice(segStart, segEnd);
    const stripped = raw.trim();
    if (!stripped) {
      continue;
    }
    const tokenStart = segStart + (raw.length - raw.trimStart().length);
    const gap = source.slice(cursor, tokenStart);
    if (result.tokens.length) {
      result.tokens.push({ text: stripped, sep: gap });
    } else {
      result.leading = gap;
      result.tokens.push({ text: stripped, sep: "" });
    }
    cursor = tokenStart + stripped.length;
  }
  if (result.tokens.length) {
    result.trailing = source.slice(cursor);
  } else {
    result.leading = source;
  }
  return result;
}

export function hasSeparator(sep: string): boolean {
  return [...sep].some((char) => SEPARATORS.has(char));
}

/** 拼回字符串。第一个 token 不带分隔符；新加或挪动后没有分隔符的 token 用 ", "。 */
export function serialize(list: TokenList): string {
  if (!list.tokens.length) {
    return list.leading + list.trailing;
  }
  let out = list.leading + list.tokens[0].text;
  for (const token of list.tokens.slice(1)) {
    out += (hasSeparator(token.sep) ? token.sep : DEFAULT_SEP) + token.text;
  }
  return out + list.trailing;
}

/** 只关心 token 顺序的场合（配方各区）：用各自的分隔符拼接，不带首尾。 */
export function joinTokens(tokens: Token[]): string {
  return serialize({ leading: "", tokens, trailing: "" });
}

/** 把一个 token（可能是权重组或括号组）拆成用于统计和翻译的普通 tag，已规范化。 */
export function innerTags(tokenText: string): string[] {
  let text = tokenText.replace(WEIGHT_OPEN_GLOBAL_RE, ",").split("::").join(",");
  text = text.replace(/[{}[\]]/g, ",");
  const tags: string[] = [];
  for (const part of text.split(/[,，|\n]/)) {
    let tag = part.trim();
    if (tag.startsWith("(") && !tag.includes(")")) {
      tag = tag.slice(1).trim();
    }
    if (tag.endsWith(")") && !tag.includes("(")) {
      tag = tag.slice(0, -1).trim();
    }
    tag = tag.replace(SD_WEIGHT_RE, "").trim();
    tag = tag.replace(/_/g, " ").replace(/\s+/g, " ").trim().toLowerCase();
    tag = tag.replace(/^artist:\s*/, "");
    if (tag && !tag.endsWith(":")) {
      tags.push(tag);
    }
  }
  return tags;
}

/** 括号组、权重组的范围（[start, end)）：组内的逗号不分词，划分时也不能从中间切开。 */
export function protectedRanges(text: string): Array<[number, number]> {
  return [...bracketRanges(text), ...weightRanges(text)];
}

function protectedMask(text: string): boolean[] {
  const mask = new Array<boolean>(text.length).fill(false);
  for (const [start, end] of protectedRanges(text)) {
    for (let index = start; index < end; index += 1) {
      mask[index] = true;
    }
  }
  return mask;
}

function bracketRanges(text: string): Array<[number, number]> {
  const ranges: Array<[number, number]> = [];
  const stack: Array<[string, number]> = [];
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (char in OPENERS) {
      stack.push([char, index]);
    } else if (CLOSERS.has(char)) {
      for (let depth = stack.length - 1; depth >= 0; depth -= 1) {
        if (OPENERS[stack[depth][0]] === char) {
          ranges.push([stack[depth][1], index + 1]);
          stack.length = depth;
          break;
        }
      }
    }
  }
  return ranges;
}

function weightRanges(text: string): Array<[number, number]> {
  const ranges: Array<[number, number]> = [];
  let index = 0;
  while (index < text.length) {
    WEIGHT_OPEN_RE.lastIndex = index;
    // 紧跟在上一个权重组后面（只隔空格）的也算组的开头："1.2::a,:: -2::b, c,::"。
    const afterGroup = ranges.length > 0 && !text.slice(ranges[ranges.length - 1][1], index).replace(/[ \t]/g, "");
    const match = afterGroup || isTokenStart(text, index) ? WEIGHT_OPEN_RE.exec(text) : null;
    if (!match) {
      index += 1;
      continue;
    }
    const openEnd = index + match[0].length;
    const end = weightClose(text, openEnd);
    if (end === null) {
      index = openEnd;
      continue;
    }
    ranges.push([index, end]);
    index = end;
  }
  return ranges;
}

function weightClose(text: string, position: number): number | null {
  let depth = 1;
  let index = position;
  while (index < text.length - 1) {
    if (text.startsWith("::", index)) {
      if (NUMBER_AT_END_RE.test(text.slice(0, index))) {
        depth += 1;
      } else {
        depth -= 1;
        if (depth === 0) {
          return index + 2;
        }
      }
      index += 2;
      continue;
    }
    index += 1;
  }
  return null;
}

function isTokenStart(text: string, index: number): boolean {
  const before = text.slice(0, index).replace(/[ \t]+$/, "");
  if (!before) {
    return true;
  }
  const last = before[before.length - 1];
  return SEPARATORS.has(last) || last === "{" || last === "[" || last === "(";
}
