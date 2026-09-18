import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import type { BaseTemplate } from "./types";
import { useCompareWorkspace } from "./useCompareWorkspace";
import { CompareWorkspaceProvider } from "./CompareWorkspaceProvider";

const sampleTemplate: BaseTemplate = {
  prompt: "1girl, solo, school uniform, black hair",
  negative: "lowres, bad anatomy",
  seed: 424242,
  width: 1024,
  height: 1024,
  steps: 28,
  scale: 5.0,
  sampler: "k_euler",
};

describe("useCompareWorkspace", () => {
  beforeEach(() => localStorage.clear());

  it("initializes with default empty template and empty rounds", () => {
    const { result } = renderHook(() => useCompareWorkspace(), {
      wrapper: CompareWorkspaceProvider,
    });

    expect(result.current.state.template.prompt).toBe("");
    expect(result.current.state.rounds.length).toBe(0);
  });

  it("setBaseTemplate sets template and creates Round 1 with Variant 1", () => {
    const { result } = renderHook(() => useCompareWorkspace(), {
      wrapper: CompareWorkspaceProvider,
    });

    act(() => {
      result.current.setBaseTemplate(sampleTemplate);
    });

    expect(result.current.state.template.seed).toBe(424242);
    expect(result.current.state.rounds.length).toBe(1);

    const round1 = result.current.state.rounds[0];
    expect(round1.name).toBe("第 1 批对比");
    expect(round1.basePrompt).toBe(sampleTemplate.prompt);
    expect(round1.variants.length).toBe(1);
    expect(round1.variants[0].name).toBe("变体 1-A");
    expect(round1.variants[0].prompt).toBe(sampleTemplate.prompt);
    expect(round1.variants[0].diff.added).toEqual([]);
    expect(round1.variants[0].diff.removed).toEqual([]);
  });

  it("adds and duplicates variants with updated diff", () => {
    const { result } = renderHook(() => useCompareWorkspace(), {
      wrapper: CompareWorkspaceProvider,
    });

    act(() => {
      result.current.setBaseTemplate(sampleTemplate);
    });

    const roundId = result.current.state.rounds[0].id;

    act(() => {
      result.current.addVariant(
        roundId,
        "变体 1-B",
        "1girl, solo, school uniform, black hair, film grain",
      );
    });

    expect(result.current.state.rounds[0].variants.length).toBe(2);
    const varB = result.current.state.rounds[0].variants[1];
    expect(varB.diff.added).toEqual(["film grain"]);

    act(() => {
      result.current.duplicateVariant(roundId, varB.id);
    });

    expect(result.current.state.rounds[0].variants.length).toBe(3);
    const varC = result.current.state.rounds[0].variants[2];
    expect(varC.prompt).toBe(varB.prompt);
    expect(varC.diff.added).toEqual(["film grain"]);
  });

  it("addNewRound appends a new round below inheriting diffs from source round", () => {
    const { result } = renderHook(() => useCompareWorkspace(), {
      wrapper: CompareWorkspaceProvider,
    });

    act(() => {
      result.current.setBaseTemplate(sampleTemplate);
    });

    const round1Id = result.current.state.rounds[0].id;
    act(() => {
      result.current.addVariant(round1Id, "变体 1-B", "1girl, solo, school uniform, black hair, smile");
    });

    act(() => {
      result.current.addNewRound(round1Id, "第 2 批对比");
    });

    expect(result.current.state.rounds.length).toBe(2);
    const round2 = result.current.state.rounds[1];
    expect(round2.name).toBe("第 2 批对比");
    expect(round2.basePrompt).toBe(sampleTemplate.prompt);
    expect(round2.variants.length).toBe(2);
    // Variant 2-A has no diff
    expect(round2.variants[0].diff.added).toEqual([]);
    // Variant 2-B inherited diff: +smile
    expect(round2.variants[1].diff.added).toEqual(["smile"]);
    expect(round2.variants[1].prompt).toBe("1girl, solo, school uniform, black hair, smile");
  });

  it("addNewRound inserts directly below source round when sourceRoundId is provided", () => {
    const { result } = renderHook(() => useCompareWorkspace(), {
      wrapper: CompareWorkspaceProvider,
    });

    act(() => {
      result.current.setBaseTemplate(sampleTemplate);
    });

    const round1Id = result.current.state.rounds[0].id;
    let round2Id = "";
    act(() => {
      round2Id = result.current.addNewRound(round1Id, "第 2 批");
    });

    expect(result.current.state.rounds.length).toBe(2);
    expect(result.current.state.rounds[0].id).toBe(round1Id);
    expect(result.current.state.rounds[1].id).toBe(round2Id);

    // Derive downward from round 1 (should insert between round 1 and round 2)
    let round1DerivedId = "";
    act(() => {
      round1DerivedId = result.current.addNewRound(round1Id, "第 1 批衍生");
    });

    expect(result.current.state.rounds.length).toBe(3);
    expect(result.current.state.rounds[0].id).toBe(round1Id);
    expect(result.current.state.rounds[1].id).toBe(round1DerivedId);
    expect(result.current.state.rounds[2].id).toBe(round2Id);
  });

  it("removeRound removes a specific round and updates remaining rounds", () => {
    const { result } = renderHook(() => useCompareWorkspace(), {
      wrapper: CompareWorkspaceProvider,
    });

    act(() => {
      result.current.setBaseTemplate(sampleTemplate);
    });

    const round1Id = result.current.state.rounds[0].id;
    act(() => {
      result.current.addNewRound(round1Id, "第 2 批对比");
    });

    expect(result.current.state.rounds.length).toBe(2);
    const round2Id = result.current.state.rounds[1].id;

    // Remove round 2
    act(() => {
      result.current.removeRound(round2Id);
    });

    expect(result.current.state.rounds.length).toBe(1);
    expect(result.current.state.rounds[0].id).toBe(round1Id);

    // Attempting to remove the last remaining round should be a safe no-op
    act(() => {
      result.current.removeRound(round1Id);
    });
    expect(result.current.state.rounds.length).toBe(1);
  });

  it("reorderRounds reorders rounds and preserves full round data", () => {
    const { result } = renderHook(() => useCompareWorkspace(), {
      wrapper: CompareWorkspaceProvider,
    });

    act(() => {
      result.current.setBaseTemplate(sampleTemplate);
    });

    const round1Id = result.current.state.rounds[0].id;
    let round2Id = "";
    act(() => {
      round2Id = result.current.addNewRound(round1Id, "第 2 批对比");
    });
    let round3Id = "";
    act(() => {
      round3Id = result.current.addNewRound(round2Id, "第 3 批对比");
    });

    expect(result.current.state.rounds.length).toBe(3);
    expect(result.current.state.rounds[1].id).toBe(round2Id);
    expect(result.current.state.rounds[2].id).toBe(round3Id);

    // Move round 3 (index 2) to top (index 0)
    act(() => {
      result.current.reorderRounds(2, 0);
    });

    expect(result.current.state.rounds[0].id).toBe(round3Id);
    expect(result.current.state.rounds[1].id).toBe(round1Id);
    expect(result.current.state.rounds[2].id).toBe(round2Id);

    // Invalid index should be safe no-op
    act(() => {
      result.current.reorderRounds(-1, 0);
      result.current.reorderRounds(0, 99);
      result.current.reorderRounds(1, 1);
    });
    expect(result.current.state.rounds[0].id).toBe(round3Id);
  });

  it("switching round template synchronizes all variants to new template and clears stale result/seed", () => {
    const { result } = renderHook(() => useCompareWorkspace(), {
      wrapper: CompareWorkspaceProvider,
    });

    act(() => {
      result.current.setBaseTemplate(sampleTemplate);
    });

    const round1Id = result.current.state.rounds[0].id;
    const varAId = result.current.state.rounds[0].variants[0].id;

    // Simulate variant 1-A having a generated result image
    act(() => {
      result.current.updateVariant(round1Id, varAId, {
        resultImage: {
          url: "blob://img-1a",
          path: "output/img-1a.png",
          seed: 12345,
        },
      });
    });

    // Add variant 1-B with custom prompt, seed, and generated result image
    act(() => {
      result.current.addVariant(round1Id, "变体 1-B", "1girl, solo, school uniform, black hair, smile");
    });
    const varBId = result.current.state.rounds[0].variants[1].id;
    act(() => {
      result.current.updateVariant(round1Id, varBId, {
        seedOverride: 99999,
        resultImage: {
          url: "blob://img-1b",
          path: "output/img-1b.png",
          seed: 99999,
        },
      });
    });

    // Now user switches Base Template in Round 1
    const newCharacterTemplate: BaseTemplate = {
      ...sampleTemplate,
      prompt: "1girl, solo, madoka, pink hair",
      seed: 888888,
    };

    act(() => {
      result.current.setRoundTemplate(round1Id, newCharacterTemplate);
    });

    const updatedRound1 = result.current.state.rounds[0];
    expect(updatedRound1.template.seed).toBe(888888);
    expect(updatedRound1.basePrompt).toBe("1girl, solo, madoka, pink hair");

    // Variant 1-A has no diff, so prompt updates to new template prompt
    expect(updatedRound1.variants[0].prompt).toBe("1girl, solo, madoka, pink hair");
    expect(updatedRound1.variants[0].diff.added).toEqual([]);
    expect(updatedRound1.variants[0].resultImage).toBeUndefined();

    // Variant 1-B preserves its diff (+smile) recomputed against new template prompt
    expect(updatedRound1.variants[1].prompt).toBe("1girl, solo, madoka, pink hair, smile");
    expect(updatedRound1.variants[1].diff.added).toEqual(["smile"]);
    expect(updatedRound1.variants[1].diff.removed).toEqual([]);
    expect(updatedRound1.variants[1].resultImage).toBeUndefined();
  });

  it("syncRoundVariantsToTemplate manually re-synchronizes all variants to round template", () => {
    const { result } = renderHook(() => useCompareWorkspace(), {
      wrapper: CompareWorkspaceProvider,
    });

    act(() => {
      result.current.setBaseTemplate(sampleTemplate);
    });

    const round1Id = result.current.state.rounds[0].id;
    act(() => {
      result.current.addVariant(round1Id, "变体 1-B", "modified prompt");
    });
    const varBId = result.current.state.rounds[0].variants[1].id;
    act(() => {
      result.current.updateVariant(round1Id, varBId, {
        seedOverride: 7777,
        resultImage: { url: "blob://1b", path: "out/1b.png", seed: 7777 },
      });
    });

    act(() => {
      result.current.syncRoundVariantsToTemplate(round1Id);
    });

    const round = result.current.state.rounds[0];
    expect(round.variants[1].prompt).toBe(sampleTemplate.prompt);
    expect(round.variants[1].diff.added).toEqual([]);
    expect(round.variants[1].seedOverride).toBeNull();
    expect(round.variants[1].resultImage).toBeUndefined();
  });

  it("forkVariantToNewRound creates a new round downward based on selected variant", () => {
    const { result } = renderHook(() => useCompareWorkspace(), {
      wrapper: CompareWorkspaceProvider,
    });

    act(() => {
      result.current.setBaseTemplate(sampleTemplate);
    });

    const round1 = result.current.state.rounds[0];
    act(() => {
      result.current.addVariant(
        round1.id,
        "变体 1-B",
        "1girl, solo, school uniform, cinematic lighting",
      );
    });

    const varB = result.current.state.rounds[0].variants[1];

    act(() => {
      result.current.forkVariantToNewRound(round1.id, varB.id);
    });

    expect(result.current.state.rounds.length).toBe(2);
    const round2 = result.current.state.rounds[1];
    expect(round2.basePrompt).toBe(varB.prompt);
    expect(round2.variants[0].prompt).toBe(varB.prompt);
  });

  it("controls deep compare open, mode, and close", () => {
    const { result } = renderHook(() => useCompareWorkspace(), {
      wrapper: CompareWorkspaceProvider,
    });

    act(() => {
      result.current.openDeepCompare("var-1", "var-2", "flicker");
    });

    expect(result.current.state.deepCompare.isOpen).toBe(true);
    expect(result.current.state.deepCompare.leftVariantId).toBe("var-1");
    expect(result.current.state.deepCompare.rightVariantId).toBe("var-2");
    expect(result.current.state.deepCompare.mode).toBe("flicker");

    act(() => {
      result.current.closeDeepCompare();
    });

    expect(result.current.state.deepCompare.isOpen).toBe(false);
  });

  it("persists rounds and variants across remounts via localStorage", async () => {
    const { result, unmount } = renderHook(() => useCompareWorkspace(), {
      wrapper: CompareWorkspaceProvider,
    });

    act(() => {
      result.current.setBaseTemplate(sampleTemplate);
    });

    const roundId = result.current.state.rounds[0].id;
    act(() => {
      result.current.addVariant(roundId, "变体 1-B", "1girl, solo, school uniform, black hair, ribbon");
    });

    // Wait for 250ms debounce
    await act(async () => {
      await new Promise((r) => setTimeout(r, 300));
    });

    unmount();

    // Remount hook (simulating browser reload)
    const remounted = renderHook(() => useCompareWorkspace(), {
      wrapper: CompareWorkspaceProvider,
    });

    expect(remounted.result.current.state.rounds.length).toBe(1);
    expect(remounted.result.current.state.rounds[0].variants.length).toBe(2);
    expect(remounted.result.current.state.rounds[0].variants[1].name).toBe("变体 1-B");
    expect(remounted.result.current.state.rounds[0].variants[1].prompt).toBe(
      "1girl, solo, school uniform, black hair, ribbon",
    );
  });

  it("reorders variants moving the entire variant data together", async () => {
    const { result, unmount } = renderHook(() => useCompareWorkspace(), {
      wrapper: CompareWorkspaceProvider,
    });

    act(() => {
      result.current.setBaseTemplate(sampleTemplate);
    });

    const roundId = result.current.state.rounds[0].id;
    act(() => {
      result.current.addVariant(roundId, "变体 1-B", "prompt B");
    });
    act(() => {
      result.current.addVariant(roundId, "变体 1-C", "prompt C");
    });

    const varA = result.current.state.rounds[0].variants[0];
    const varB = result.current.state.rounds[0].variants[1];
    const varC = result.current.state.rounds[0].variants[2];

    // Move variant 1-C (index 2) to index 0
    act(() => {
      result.current.reorderVariants(roundId, 2, 0);
    });

    const reordered = result.current.state.rounds[0].variants;
    expect(reordered.length).toBe(3);
    expect(reordered[0].id).toBe(varC.id);
    expect(reordered[0].name).toBe("变体 1-C");
    expect(reordered[0].prompt).toBe("prompt C");
    expect(reordered[1].id).toBe(varA.id);
    expect(reordered[2].id).toBe(varB.id);

    // Move variant 1-C from index 0 to index 1
    act(() => {
      result.current.reorderVariants(roundId, 0, 1);
    });

    const reordered2 = result.current.state.rounds[0].variants;
    expect(reordered2[0].id).toBe(varA.id);
    expect(reordered2[1].id).toBe(varC.id);
    expect(reordered2[2].id).toBe(varB.id);

    // Wait for 250ms debounce
    await act(async () => {
      await new Promise((r) => setTimeout(r, 300));
    });

    unmount();

    // Verify localStorage persistence across remount
    const remounted = renderHook(() => useCompareWorkspace(), {
      wrapper: CompareWorkspaceProvider,
    });
    const persistedVariants = remounted.result.current.state.rounds[0].variants;
    expect(persistedVariants[0].id).toBe(varA.id);
    expect(persistedVariants[1].id).toBe(varC.id);
    expect(persistedVariants[1].name).toBe("变体 1-C");
    expect(persistedVariants[1].prompt).toBe("prompt C");
    expect(persistedVariants[2].id).toBe(varB.id);
  });
});
