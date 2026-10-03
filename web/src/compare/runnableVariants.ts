import type { BaseTemplate, PromptVariant } from "./types";

/**
 * Normalizes prompt tags by trimming and removing empty items.
 */
export function normalizePromptTags(prompt?: string): string {
  if (!prompt) return "";
  return prompt
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean)
    .join(", ");
}

/**
 * Computes a unique signature for a variant given the batch template.
 */
export function getVariantSignature(
  variant: PromptVariant,
  template: BaseTemplate,
): {
  prompt: string;
  seed: number;
  key: string;
} {
  const normPrompt = normalizePromptTags(variant.prompt);
  const effectiveSeed =
    variant.seedOverride !== null && variant.seedOverride !== undefined
      ? variant.seedOverride
      : (template.seed ?? 0);
  return {
    prompt: normPrompt,
    seed: effectiveSeed,
    key: `${normPrompt}:::${effectiveSeed}`,
  };
}

/**
 * Checks if a variant is completely identical to the base template (same prompt & same seed).
 */
export function isVariantIdenticalToBase(
  variant: PromptVariant,
  template: BaseTemplate,
): boolean {
  const baseSeed = template.seed ?? 0;
  const variantSeed =
    variant.seedOverride !== null && variant.seedOverride !== undefined
      ? variant.seedOverride
      : baseSeed;

  // If seeds differ, it is not identical to base
  if (variantSeed !== baseSeed) {
    return false;
  }

  // If diff is explicitly empty (0 added and 0 removed), it is identical to base
  if (
    variant.diff &&
    variant.diff.added.length === 0 &&
    variant.diff.removed.length === 0
  ) {
    return true;
  }

  // Fallback: compare normalized prompt text
  const normBase = normalizePromptTags(template.prompt);
  const normVariant = normalizePromptTags(variant.prompt);
  return normVariant === normBase;
}

export type VariantIdentityStatus = {
  isIdenticalToBase: boolean;
  isControlGroup: boolean;
  isDuplicate: boolean;
  isRunnable: boolean;
  duplicateOfVariantId?: string;
};

/**
 * Inspects all variants in a round and maps each variant ID to its identity status.
 *
 * Rules:
 * 1. The first variant in the batch that is identical to the base template is treated as the Control Group (对照组)
 *    and is NOT skipped (it is runnable).
 * 2. Any subsequent variant identical to the base template is treated as a duplicate of the control group and is skipped.
 * 3. Any duplicate variant sharing prompt and seed with an earlier variant in the batch is skipped.
 */
export function getVariantIdentityMap(
  variants: PromptVariant[],
  template: BaseTemplate,
): Map<string, VariantIdentityStatus> {
  const map = new Map<string, VariantIdentityStatus>();
  const seenKeys = new Map<string, string>(); // signatureKey -> firstVariantId
  let hasControlGroup = false;

  for (let i = 0; i < variants.length; i++) {
    const variant = variants[i];
    const identicalToBase = isVariantIdenticalToBase(variant, template);
    const sig = getVariantSignature(variant, template);

    let isControlGroup = false;
    let isDuplicate = false;
    let duplicateOfVariantId: string | undefined;

    if (identicalToBase) {
      if (!hasControlGroup) {
        // First base-identical variant acts as the Control Group (对照组)
        isControlGroup = true;
        hasControlGroup = true;
        seenKeys.set(sig.key, variant.id);
      } else {
        // Subsequent base-identical variants are duplicates of the control group
        isDuplicate = true;
        duplicateOfVariantId = seenKeys.get(sig.key);
      }
    } else {
      if (seenKeys.has(sig.key)) {
        isDuplicate = true;
        duplicateOfVariantId = seenKeys.get(sig.key);
      } else {
        seenKeys.set(sig.key, variant.id);
      }
    }

    const isRunnable = isControlGroup || (!identicalToBase && !isDuplicate);

    map.set(variant.id, {
      isIdenticalToBase: identicalToBase,
      isControlGroup,
      isDuplicate,
      isRunnable,
      duplicateOfVariantId,
    });
  }

  return map;
}

/**
 * Returns only the runnable variants for a round batch, skipping:
 * 1. Variants that are identical to the base template (与本轮基准一致)
 * 2. Duplicate variants within the batch that share the same prompt and seed
 */
export function getRunnableVariants(
  variants: PromptVariant[],
  template: BaseTemplate,
): PromptVariant[] {
  const identityMap = getVariantIdentityMap(variants, template);
  return variants.filter((v) => identityMap.get(v.id)?.isRunnable ?? false);
}

/**
 * Checks if a variant has already completed generation with a valid result image.
 */
export function isVariantCompleted(variant: PromptVariant): boolean {
  return variant.status === "succeeded" && !!variant.resultImage?.url;
}

/**
 * Returns only runnable variants that have not yet completed successfully
 * (i.e. idle, failed, or missing result image).
 */
export function getPendingRunnableVariants(
  variants: PromptVariant[],
  template: BaseTemplate,
): PromptVariant[] {
  const runnable = getRunnableVariants(variants, template);
  return runnable.filter((v) => !isVariantCompleted(v));
}
