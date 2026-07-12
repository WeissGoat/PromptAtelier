import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ComposePreviewResponse, JobRecord } from "../api/types";
import type { NodeDocument, NodeRole } from "../nodes/types";
import type { RenderWorkspaceParams, RoleNodeGroup } from "../workspace/types";
import { useCompareRunController } from "./useCompareRunController";

const params: RenderWorkspaceParams = { negative: "", width: 1024, height: 1024, nt: 4, seed: "-1" };

function group(role: NodeRole, count: number): RoleNodeGroup {
  const makeSlot = (slotId: string, mode: "primary" | "compare") => {
    const node: NodeDocument = { schema: "tags-machine-core.node/v1", kind: role, id: slotId, prompt: { positive: [{ text: slotId }], negative: [] } };
    return { slotId, role, mode, sourceRef: slotId, sourceNode: node, draftNode: node };
  };
  return {
    primary: count ? makeSlot(`primary-${role}`, "primary") : { slotId: `primary-${role}`, role, mode: "primary", sourceRef: null, sourceNode: null, draftNode: null },
    compares: Array.from({ length: Math.max(0, count - 1) }, (_, index) => makeSlot(`${role}-${index}`, "compare")),
  };
}

describe("useCompareRunController", () => {
  it("runs NovelAI combinations serially and previews before generate", async () => {
    let activePreviews = 0;
    let maxActivePreviews = 0;
    const previewed = new Set<string>();
    const generated: string[] = [];
    const seeds = new Set<number>();
    const post = vi.fn(async (path: string, body: unknown): Promise<unknown> => {
      if (path === "/compose-preview") {
        const request = body as { compose: { nodes: Array<{ ref: string }> } };
        seeds.add((body as { render: { seed: number } }).render.seed);
        const marker = request.compose.nodes.map((item) => item.ref).join("|");
        activePreviews += 1;
        maxActivePreviews = Math.max(maxActivePreviews, activePreviews);
        await new Promise((resolve) => window.setTimeout(resolve, 10));
        activePreviews -= 1;
        previewed.add(marker);
        return { status: "ready", render_request: { marker } };
      }
      const marker = String((body as { render_request: { marker: string } }).render_request.marker);
      expect(previewed.has(marker)).toBe(true);
      generated.push(marker);
      return { id: `job-${generated.length}`, name: "generate", status: "succeeded", result: { images: [] } };
    });
    const randomSeed = vi.fn(() => 123456789);
    const { result } = renderHook(() => useCompareRunController({ post, pollIntervalMs: 1, randomSeed }));
    const groups = { artist: group("artist", 2), character: group("character", 1), action: group("action", 2) };

    await act(async () => { await result.current.start(groups, params); });

    expect(maxActivePreviews).toBe(1);
    expect(result.current.summary.succeeded).toBe(4);
    expect(generated).toHaveLength(4);
    expect(randomSeed).toHaveBeenCalledTimes(1);
    expect([...seeds]).toEqual([123456789]);
  });

  it("reuses an explicit seed without generating a random one", async () => {
    const seeds: number[] = [];
    const post = vi.fn(async (path: string, body: unknown): Promise<unknown> => {
      if (path === "/compose-preview") {
        seeds.push((body as { render: { seed: number } }).render.seed);
        return { status: "ready", render_request: {} };
      }
      return { id: `job-${seeds.length}`, name: "generate", status: "succeeded" };
    });
    const randomSeed = vi.fn(() => 999);
    const { result } = renderHook(() => useCompareRunController({ post, randomSeed }));
    await act(async () => {
      await result.current.start(
        { artist: group("artist", 2), character: group("character", 1), action: group("action", 1) },
        { ...params, seed: "42" },
      );
    });
    expect(seeds).toEqual([42, 42]);
    expect(randomSeed).not.toHaveBeenCalled();
  });

  it("polls jobs and continues when one combination fails", async () => {
    let previewCount = 0;
    const post = vi.fn(async (path: string): Promise<unknown> => {
      if (path === "/compose-preview") {
        previewCount += 1;
        if (previewCount === 1) throw new Error("first failed");
        return { status: "ready", render_request: { prompt: "ready" } };
      }
      return { id: `job-${previewCount}`, name: "generate", status: "queued" };
    });
    const get = vi.fn(async (): Promise<unknown> => ({ id: "job-2", name: "generate", status: "succeeded", result: { images: [] } }));
    const { result } = renderHook(() => useCompareRunController({ post, get, pollIntervalMs: 1 }));
    const groups = { artist: group("artist", 1), character: group("character", 1), action: group("action", 2) };

    await act(async () => { await result.current.start(groups, params); });

    expect(result.current.summary.failed).toBe(1);
    expect(result.current.summary.succeeded).toBe(1);
    expect(get).toHaveBeenCalled();
    expect(result.current.results[0].labels.character).toBe("primary-character");
  });

  it("keeps runtime results outside localStorage", async () => {
    localStorage.clear();
    const post = vi.fn(async (path: string): Promise<unknown> => path === "/compose-preview"
      ? { status: "ready", render_request: {} }
      : { id: "job", name: "generate", status: "succeeded" });
    const { result } = renderHook(() => useCompareRunController({ post }));
    await act(async () => { await result.current.start({ artist: group("artist", 1), character: group("character", 1), action: group("action", 1) }, params); });
    await waitFor(() => expect(result.current.summary.succeeded).toBe(1));
    expect(JSON.stringify(localStorage)).not.toContain("job");
  });
});
