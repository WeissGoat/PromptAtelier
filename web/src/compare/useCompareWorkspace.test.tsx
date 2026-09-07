import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

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

  it("addNewRound appends a new round below", () => {
    const { result } = renderHook(() => useCompareWorkspace(), {
      wrapper: CompareWorkspaceProvider,
    });

    act(() => {
      result.current.setBaseTemplate(sampleTemplate);
    });

    act(() => {
      result.current.addNewRound("masterpiece, scenery", "第 2 批对比: 场景");
    });

    expect(result.current.state.rounds.length).toBe(2);
    const round2 = result.current.state.rounds[1];
    expect(round2.name).toBe("第 2 批对比: 场景");
    expect(round2.basePrompt).toBe("masterpiece, scenery");
    expect(round2.variants[0].prompt).toBe("masterpiece, scenery");
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
});
