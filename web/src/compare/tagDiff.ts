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

  // Count frequencies in base
  const baseCounts = new Map<string, number>();
  for (const token of baseTokens) {
    const norm = normalizeTag(token);
    baseCounts.set(norm, (baseCounts.get(norm) || 0) + 1);
  }

  // Count frequencies in variant
  const variantCounts = new Map<string, number>();
  for (const token of variantTokens) {
    const norm = normalizeTag(token);
    variantCounts.set(norm, (variantCounts.get(norm) || 0) + 1);
  }

  // Match variant tokens against available base tokens
  const matchedFromBase = new Map<string, number>();
  const added: string[] = [];
  const unchanged: string[] = [];
  const tokens: TagDiffToken[] = [];

  for (const token of variantTokens) {
    const norm = normalizeTag(token);
    const inBaseCount = baseCounts.get(norm) || 0;
    const currentMatched = matchedFromBase.get(norm) || 0;

    if (currentMatched < inBaseCount) {
      matchedFromBase.set(norm, currentMatched + 1);
      unchanged.push(token);
      tokens.push({ text: token, type: "unchanged" });
    } else {
      added.push(token);
      tokens.push({ text: token, type: "added" });
    }
  }

  // Find removed tokens from base that were not matched by variant
  const matchedFromVariant = new Map<string, number>();
  const removed: string[] = [];

  for (const token of baseTokens) {
    const norm = normalizeTag(token);
    const inVariantCount = variantCounts.get(norm) || 0;
    const currentMatched = matchedFromVariant.get(norm) || 0;

    if (currentMatched < inVariantCount) {
      matchedFromVariant.set(norm, currentMatched + 1);
    } else {
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

export function applyTagDiff(
  basePrompt: string,
  diff?: { added?: string[]; removed?: string[] },
): string {
  if (!diff || ((!diff.added || diff.added.length === 0) && (!diff.removed || diff.removed.length === 0))) {
    return basePrompt;
  }
  const baseTokens = tokenizePrompt(basePrompt);

  // Count how many times each normalized tag should be removed
  const toRemoveCounts = new Map<string, number>();
  for (const tag of diff.removed || []) {
    const norm = normalizeTag(tag);
    toRemoveCounts.set(norm, (toRemoveCounts.get(norm) || 0) + 1);
  }

  // Remove matching tokens based on count
  const kept: string[] = [];
  for (const token of baseTokens) {
    const norm = normalizeTag(token);
    const count = toRemoveCounts.get(norm) || 0;
    if (count > 0) {
      toRemoveCounts.set(norm, count - 1);
    } else {
      kept.push(token);
    }
  }

  // Count existing tokens in kept
  const keptCounts = new Map<string, number>();
  for (const token of kept) {
    const norm = normalizeTag(token);
    keptCounts.set(norm, (keptCounts.get(norm) || 0) + 1);
  }

  // Count desired additions
  const desiredAddCounts = new Map<string, number>();
  for (const tag of diff.added || []) {
    const trimmed = tag.trim();
    if (!trimmed) continue;
    const norm = normalizeTag(trimmed);
    desiredAddCounts.set(norm, (desiredAddCounts.get(norm) || 0) + 1);
  }

  // Add added tags when needed
  const addedSoFar = new Map<string, number>();
  for (const tag of diff.added || []) {
    const trimmed = tag.trim();
    if (!trimmed) continue;
    const norm = normalizeTag(trimmed);
    const currentInKept = keptCounts.get(norm) || 0;
    const currentAdded = addedSoFar.get(norm) || 0;
    const maxDesired = desiredAddCounts.get(norm) || 1;

    if (currentInKept + currentAdded < maxDesired) {
      kept.push(trimmed);
      addedSoFar.set(norm, currentAdded + 1);
    }
  }

  return kept.join(", ");
}

