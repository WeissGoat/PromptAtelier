import { describe, expect, it } from "vitest";

import type { BaseTemplate, PromptVariant } from "./types";
import {
  getPendingRunnableVariants,
  getRunnableVariants,
  getVariantIdentityMap,
  isVariantCompleted,
  isVariantIdenticalToBase,
  normalizePromptTags,
} from "./runnableVariants";

const mockTemplate: BaseTemplate = {
  prompt: "1girl, solo, school uniform, black hair",
  negative: "lowres, bad anatomy",
  model: "nai-diffusion-4-5-full",
  seed: 3961922831,
  width: 832,
  height: 1216,
  steps: 28,
  scale: 6,
  sampler: "k_euler",
};

function createMockVariant(
  id: string,
  name: string,
  prompt: string,
  added: string[] = [],
  removed: string[] = [],
  seedOverride: number | null = null,
): PromptVariant {
  return {
    id,
    name,
    prompt,
    diff: { added, removed, unchanged: [], tokens: [] },
    seedOverride,
    status: "idle",
    jobId: null,
  };
}

describe("runnableVariants", () => {
  it("normalizePromptTags trims and removes empty tags", () => {
    expect(normalizePromptTags(" 1girl ,  solo, , school uniform ")).toBe(
      "1girl, solo, school uniform",
    );
  });

  it("isVariantIdenticalToBase detects exact base prompt and locked seed", () => {
    const varIdentical = createMockVariant(
      "v1",
      "变体 6-A",
      "1girl, solo, school uniform, black hair",
      [],
      [],
      null,
    );
    expect(isVariantIdenticalToBase(varIdentical, mockTemplate)).toBe(true);

    const varDiff = createMockVariant(
      "v2",
      "变体 6-G",
      "1girl, solo, school uniform, black hair, smile",
      ["smile"],
      [],
      null,
    );
    expect(isVariantIdenticalToBase(varDiff, mockTemplate)).toBe(false);

    // If seed is overridden to a different value, it's not identical even with same prompt
    const varCustomSeed = createMockVariant(
      "v3",
      "变体 6-Custom",
      "1girl, solo, school uniform, black hair",
      [],
      [],
      1234567,
    );
    expect(isVariantIdenticalToBase(varCustomSeed, mockTemplate)).toBe(false);
  });

  it("getRunnableVariants skips variants identical to base template and duplicates within batch", () => {
    const variants: PromptVariant[] = [
      // 1. Identical to base
      createMockVariant(
        "v1",
        "变体 6-A",
        "1girl, solo, school uniform, black hair",
        [],
        [],
        null,
      ),
      // 2. Also identical to base
      createMockVariant(
        "v2",
        "变体 6-F",
        "1girl, solo, school uniform, black hair",
        [],
        [],
        null,
      ),
      // 3. Different tag (-bokeh)
      createMockVariant(
        "v3",
        "变体 6-G",
        "1girl, solo, school uniform, black hair, smile",
        ["smile"],
        [],
        null,
      ),
      // 4. Another different tag
      createMockVariant(
        "v4",
        "变体 6-H",
        "1girl, solo, school uniform, red hair",
        ["red hair"],
        ["black hair"],
        null,
      ),
      // 5. Duplicate of v3 (+smile with same prompt and seed)
      createMockVariant(
        "v5",
        "变体 6-Dup",
        "1girl, solo, school uniform, black hair, smile",
        ["smile"],
        [],
        null,
      ),
      // 6. Same prompt as v3 but different seed override (should be runnable)
      createMockVariant(
        "v6",
        "变体 6-DiffSeed",
        "1girl, solo, school uniform, black hair, smile",
        ["smile"],
        [],
        99999,
      ),
      // 7. Another different tag
      createMockVariant(
        "v7",
        "变体 6-I",
        "1girl, solo, kimono",
        ["kimono"],
        ["school uniform"],
        null,
      ),
    ];

    expect(variants.length).toBe(7);

    const runnable = getRunnableVariants(variants, mockTemplate);

    // v1: kept as Control Group (对照组)
    // v2: skipped as duplicate of control group
    // v3: kept (+smile)
    // v4: kept (red hair)
    // v5: skipped (duplicate of v3)
    // v6: kept (different seed 99999)
    // v7: kept (kimono)
    expect(runnable.map((v) => v.id)).toEqual(["v1", "v3", "v4", "v6", "v7"]);
    expect(runnable.length).toBe(5);
  });

  it("getVariantIdentityMap gives accurate statuses for each variant", () => {
    const v1 = createMockVariant(
      "v1",
      "变体 6-A",
      "1girl, solo, school uniform, black hair",
      [],
      [],
      null,
    );
    const v2 = createMockVariant(
      "v2",
      "变体 6-B",
      "1girl, solo, smile",
      ["smile"],
      [],
      null,
    );
    const v3 = createMockVariant(
      "v3",
      "变体 6-C",
      "1girl, solo, smile",
      ["smile"],
      [],
      null,
    );

    const identityMap = getVariantIdentityMap([v1, v2, v3], mockTemplate);

    expect(identityMap.get("v1")).toEqual({
      isIdenticalToBase: true,
      isControlGroup: true,
      isDuplicate: false,
      isRunnable: true,
      duplicateOfVariantId: undefined,
    });

    expect(identityMap.get("v2")).toEqual({
      isIdenticalToBase: false,
      isControlGroup: false,
      isDuplicate: false,
      isRunnable: true,
      duplicateOfVariantId: undefined,
    });

    expect(identityMap.get("v3")).toEqual({
      isIdenticalToBase: false,
      isControlGroup: false,
      isDuplicate: true,
      isRunnable: false,
      duplicateOfVariantId: "v2",
    });
  });

  it("isVariantCompleted checks status and presence of resultImage", () => {
    const vIdle = createMockVariant("v1", "V1", "1girl");
    expect(isVariantCompleted(vIdle)).toBe(false);

    const vFailed: PromptVariant = {
      ...vIdle,
      status: "failed",
      error: "Timeout",
    };
    expect(isVariantCompleted(vFailed)).toBe(false);

    const vSucceededNoImg: PromptVariant = {
      ...vIdle,
      status: "succeeded",
    };
    expect(isVariantCompleted(vSucceededNoImg)).toBe(false);

    const vSucceededWithImg: PromptVariant = {
      ...vIdle,
      status: "succeeded",
      resultImage: {
        path: "outputs/sample.png",
        url: "/api/results/image?path=outputs/sample.png",
        seed: 12345,
      },
    };
    expect(isVariantCompleted(vSucceededWithImg)).toBe(true);
  });

  it("getPendingRunnableVariants filters out already completed variants from runnable list", () => {
    const v1 = createMockVariant("v1", "V1", "1girl, solo, black hair"); // Control group
    const v2 = createMockVariant("v2", "V2", "1girl, solo, smile", ["smile"]); // Runnable
    const v3 = createMockVariant("v3", "V3", "1girl, solo, smile", ["smile"]); // Duplicate, not runnable

    // Mark v1 as completed
    const v1Completed: PromptVariant = {
      ...v1,
      status: "succeeded",
      resultImage: {
        path: "outputs/v1.png",
        url: "/api/results/image?path=outputs/v1.png",
        seed: 12345,
      },
    };

    // Mark v2 as failed
    const v2Failed: PromptVariant = {
      ...v2,
      status: "failed",
      error: "504 Gateway Timeout",
    };

    const pending = getPendingRunnableVariants([v1Completed, v2Failed, v3], mockTemplate);
    // Only v2 should be returned (v1 is already completed, v3 is not runnable because duplicate)
    expect(pending.map((v) => v.id)).toEqual(["v2"]);
  });
});
