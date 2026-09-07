import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { BaseTemplate, PromptVariant } from "./types";
import { useCompareBatchRunner } from "./useCompareBatchRunner";

const sampleTemplate: BaseTemplate = {
  prompt: "1girl, solo",
  negative: "lowres",
  seed: 123456,
  width: 512,
  height: 512,
  steps: 28,
  scale: 5.0,
};

const sampleVariant: PromptVariant = {
  id: "var-1",
  name: "Variant 1",
  prompt: "1girl, solo, smiling",
  diff: { added: ["smiling"], removed: [], unchanged: ["1girl", "solo"], tokens: [] },
  seedOverride: null,
  status: "idle",
  jobId: null,
};

describe("useCompareBatchRunner", () => {
  it("executes single variant generation with mock client", async () => {
    const mockPost = vi.fn().mockResolvedValue({
      id: "job-101",
      status: "queued",
    });

    let pollCount = 0;
    const mockGet = vi.fn().mockImplementation(async () => {
      pollCount++;
      if (pollCount === 1) {
        return { id: "job-101", status: "running" };
      }
      return {
        id: "job-101",
        status: "succeeded",
        result: {
          images: [{ path: "outputs/test.png", meta: { seed: 123456 } }],
        },
      };
    });

    const { result } = renderHook(() =>
      useCompareBatchRunner({
        post: mockPost,
        get: mockGet,
        pollIntervalMs: 10,
      }),
    );

    const updates: Array<Partial<PromptVariant>> = [];
    await act(async () => {
      await result.current.runVariant(sampleVariant, sampleTemplate, (patch) => {
        updates.push(patch);
      });
    });

    expect(mockPost).toHaveBeenCalledWith(
      "/generate",
      expect.objectContaining({
        render_request: expect.objectContaining({
          parameters: expect.objectContaining({ seed: 123456 }),
        }),
      }),
    );

    const lastUpdate = updates[updates.length - 1];
    expect(lastUpdate.status).toBe("succeeded");
    expect(lastUpdate.resultImage?.path).toBe("outputs/test.png");
  });

  it("handles generation failure gracefully", async () => {
    const mockPost = vi.fn().mockResolvedValue({
      id: "job-err",
      status: "queued",
    });

    const mockGet = vi.fn().mockResolvedValue({
      id: "job-err",
      status: "failed",
      error: { message: "NovelAI rate limit exceeded" },
    });

    const { result } = renderHook(() =>
      useCompareBatchRunner({
        post: mockPost,
        get: mockGet,
        pollIntervalMs: 10,
      }),
    );

    const updates: Array<Partial<PromptVariant>> = [];
    await act(async () => {
      await result.current.runVariant(sampleVariant, sampleTemplate, (patch) => {
        updates.push(patch);
      });
    });

    const lastUpdate = updates[updates.length - 1];
    expect(lastUpdate.status).toBe("failed");
    expect(lastUpdate.error).toBe("NovelAI rate limit exceeded");
  });
});
