import type { TagDiffResult, TagDiffToken } from "./types";

export function tokenizePrompt(prompt: string): string[] {
  if (!prompt) return [];
  return prompt
    .split(/[,，\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function normalizeTag(tag: string): string {
  return tag
    .trim()
    .toLowerCase()
    .replace(/[\s_]+/g, " ");
}

export function computeTagDiff(basePrompt: string, variantPrompt: string): TagDiffResult {
  const baseTokens = tokenizePrompt(basePrompt);
  const variantTokens = tokenizePrompt(variantPrompt);

  const baseNormMap = new Map<string, string>();
  for (const token of baseTokens) {
    baseNormMap.set(normalizeTag(token), token);
  }

  const variantNormMap = new Map<string, string>();
  for (const token of variantTokens) {
    variantNormMap.set(normalizeTag(token), token);
  }

  const added: string[] = [];
  const unchanged: string[] = [];
  const tokens: TagDiffToken[] = [];

  for (const token of variantTokens) {
    const norm = normalizeTag(token);
    if (baseNormMap.has(norm)) {
      unchanged.push(token);
      tokens.push({ text: token, type: "unchanged" });
    } else {
      added.push(token);
      tokens.push({ text: token, type: "added" });
    }
  }

  const removed: string[] = [];
  for (const token of baseTokens) {
    const norm = normalizeTag(token);
    if (!variantNormMap.has(norm)) {
      removed.push(token);
    }
  }

  return {
    added,
    removed,
    unchanged,
    tokens,
  };
}
