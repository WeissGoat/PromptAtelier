import { beforeEach, describe, expect, it } from "vitest";

import type { BaseTemplate, CompareRound, CompareWorkspaceState } from "./types";
import {
  COMPARE_WORKSPACE_SCHEMA,
  COMPARE_WORKSPACE_STORAGE_KEY,
  clearCompareWorkspaceSnapshot,
  createDefaultCompareWorkspace,
  loadCompareWorkspaceSnapshot,
  saveCompareWorkspaceSnapshot,
} from "./storage";

const sampleTemplate: BaseTemplate = {
  prompt: "1girl, solo, school uniform, black hair",
  negative: "lowres, bad anatomy",
  seed: 424242,
  width: 1024,
  height: 1024,
  steps: 28,
  scale: 5.0,
  sampler: "k_euler",
  model: "nai-diffusion-4-5-full",
  sourceImage: {
    previewUrl: "http://127.0.0.1:8765/api/results/image?path=output/test.png",
    filename: "test.png",
    sourcePath: "output/test.png",
  },
};

describe("compare workspace storage", () => {
  beforeEach(() => localStorage.clear());

  it("loads empty workspace when localStorage has no snapshot", () => {
    const result = loadCompareWorkspaceSnapshot(localStorage);
    expect(result.status).toBe("empty");
    expect(result.state.template.prompt).toBe("");
    expect(result.state.rounds).toEqual([]);
    expect(result.state.deepCompare.isOpen).toBe(false);
  });

  it("round-trips rounds, variants, diffs, and resultImage", () => {
    const state: CompareWorkspaceState = {
      template: sampleTemplate,
      rounds: [
        {
          id: "round-1",
          name: "第 1 批对比",
          template: sampleTemplate,
          basePrompt: sampleTemplate.prompt,
          status: "idle",
          variants: [
            {
              id: "var-1",
              name: "变体 1-A",
              prompt: sampleTemplate.prompt,
              diff: { added: [], removed: [], unchanged: ["1girl"], tokens: [] },
              inheritedDiff: { added: [], removed: [] },
              seedOverride: null,
              status: "succeeded",
              jobId: "job-1",
              resultImage: {
                path: "output/var-1.png",
                url: "http://127.0.0.1:8765/api/results/image?path=output/var-1.png",
                seed: 424242,
              },
            },
            {
              id: "var-2",
              name: "变体 1-B",
              prompt: "1girl, solo, school uniform, black hair, smile",
              diff: { added: ["smile"], removed: [], unchanged: ["1girl"], tokens: [] },
              inheritedDiff: { added: ["smile"], removed: [] },
              seedOverride: 99999,
              status: "succeeded",
              jobId: "job-2",
              resultImage: {
                path: "output/var-2.png",
                url: "http://127.0.0.1:8765/api/results/image?path=output/var-2.png",
                seed: 99999,
              },
            },
          ],
        },
      ],
      deepCompare: {
        isOpen: true,
        leftVariantId: "var-1",
        rightVariantId: "var-2",
        mode: "split",
      },
      isBatchRunning: false,
    };

    saveCompareWorkspaceSnapshot(localStorage, state);
    const loaded = loadCompareWorkspaceSnapshot(localStorage);

    expect(loaded.status).toBe("loaded");
    expect(loaded.state.template.seed).toBe(424242);
    expect(loaded.state.rounds.length).toBe(1);

    const round1 = loaded.state.rounds[0];
    expect(round1.name).toBe("第 1 批对比");
    expect(round1.variants.length).toBe(2);
    expect(round1.variants[1].prompt).toBe("1girl, solo, school uniform, black hair, smile");
    expect(round1.variants[1].diff.added).toEqual(["smile"]);
    expect(round1.variants[1].seedOverride).toBe(99999);
    expect(round1.variants[1].resultImage?.path).toBe("output/var-2.png");
    // deepCompare should reset to closed on reload
    expect(loaded.state.deepCompare.isOpen).toBe(false);
  });

  it("converts large base64 previewUrl to image URL to protect localStorage quota", () => {
    const bigBase64 = "data:image/png;base64," + "A".repeat(10000);
    const templateWithBase64: BaseTemplate = {
      ...sampleTemplate,
      sourceImage: {
        previewUrl: bigBase64,
        filename: "test.png",
        sourcePath: "output/test.png",
      },
    };

    const state = createDefaultCompareWorkspace();
    state.template = templateWithBase64;
    state.rounds = [
      {
        id: "round-1",
        name: "第 1 批对比",
        template: templateWithBase64,
        basePrompt: templateWithBase64.prompt,
        status: "idle",
        variants: [],
      },
    ];

    saveCompareWorkspaceSnapshot(localStorage, state);
    const raw = localStorage.getItem(COMPARE_WORKSPACE_STORAGE_KEY);
    expect(raw).not.toContain(bigBase64);
    expect(raw).toContain("output%2Ftest.png");

    const loaded = loadCompareWorkspaceSnapshot(localStorage);
    expect(loaded.status).toBe("loaded");
    expect(loaded.state.template.sourceImage?.previewUrl).toContain("output%2Ftest.png");
  });

  it("handles corrupted or invalid JSON in localStorage gracefully", () => {
    localStorage.setItem(COMPARE_WORKSPACE_STORAGE_KEY, "invalid json {{{{");
    const result = loadCompareWorkspaceSnapshot(localStorage);
    expect(result.status).toBe("invalid");
    expect(result.state.rounds).toEqual([]);
  });

  it("clearCompareWorkspaceSnapshot clears the key from storage", () => {
    saveCompareWorkspaceSnapshot(localStorage, createDefaultCompareWorkspace());
    expect(localStorage.getItem(COMPARE_WORKSPACE_STORAGE_KEY)).not.toBeNull();

    clearCompareWorkspaceSnapshot(localStorage);
    expect(localStorage.getItem(COMPARE_WORKSPACE_STORAGE_KEY)).toBeNull();
  });
});
