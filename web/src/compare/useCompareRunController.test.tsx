import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ComposePreviewResponse, JobRecord } from "../api/types";
import type { NodeDocument, NodeRole } from "../nodes/types";
import { createDefaultPromptBehaviorGroup } from "../workspace/promptBehavior";
import type { PromptBehaviorGroup, RenderWorkspaceParams, RoleNodeGroup } from "../workspace/types";
import { useCompareRunController } from "./useCompareRunController";

const params: RenderWorkspaceParams = { negative: "", width: 1024, height: 1024, nt: 1, seed: "-1" };

function behaviorGroup(): PromptBehaviorGroup {
  return createDefaultPromptBehaviorGroup();
}

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
    const outputDirs = new Set<string>();
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
      const generateBody = body as { render_request: { marker: string }; output_dir: string };
      const marker = String(generateBody.render_request.marker);
      outputDirs.add(generateBody.output_dir);
      expect(previewed.has(marker)).toBe(true);
      generated.push(marker);
      return { id: `job-${generated.length}`, name: "generate", status: "succeeded", result: { images: [] } };
    });
    const randomSeed = vi.fn()
      .mockReturnValueOnce(123456789)
      .mockReturnValueOnce(123456790);
    const { result } = renderHook(() => useCompareRunController({
      post,
      pollIntervalMs: 1,
      randomSeed,
      outputDirFactory: () => "outputs/compare_test",
    }));
    const groups = { artist: group("artist", 2), character: group("character", 1), action: group("action", 2) };

    await act(async () => { await result.current.start(groups, { ...params, nt: 2 }, behaviorGroup()); });

    expect(maxActivePreviews).toBe(1);
    expect(result.current.summary.succeeded).toBe(8);
    expect(generated).toHaveLength(8);
    expect(randomSeed).toHaveBeenCalledTimes(2);
    expect([...seeds]).toEqual([123456789, 123456790]);
    expect([...outputDirs]).toEqual([
      "outputs/compare_test/group_001_seed_123456789",
      "outputs/compare_test/group_002_seed_123456790",
    ]);
    expect(result.current.results.map((item) => item.runId)).toEqual([
      "group-001::primary-artist::primary-character::primary-action::primary-prompt-behavior",
      "group-001::primary-artist::primary-character::action-0::primary-prompt-behavior",
      "group-001::artist-0::primary-character::primary-action::primary-prompt-behavior",
      "group-001::artist-0::primary-character::action-0::primary-prompt-behavior",
      "group-002::primary-artist::primary-character::primary-action::primary-prompt-behavior",
      "group-002::primary-artist::primary-character::action-0::primary-prompt-behavior",
      "group-002::artist-0::primary-character::primary-action::primary-prompt-behavior",
      "group-002::artist-0::primary-character::action-0::primary-prompt-behavior",
    ]);
  });

  it("creates one output directory per compare run", async () => {
    const outputDirFactory = vi.fn()
      .mockReturnValueOnce("outputs/compare_run_1")
      .mockReturnValueOnce("outputs/compare_run_2");
    const generateDirs: string[] = [];
    const post = vi.fn(async (path: string, body: unknown): Promise<unknown> => {
      if (path === "/compose-preview") return { status: "ready", render_request: {} };
      generateDirs.push((body as { output_dir: string }).output_dir);
      return { id: `job-${generateDirs.length}`, name: "generate", status: "succeeded" };
    });
    const { result } = renderHook(() => useCompareRunController({ post, outputDirFactory }));
    const groups = { artist: group("artist", 2), character: group("character", 1), action: group("action", 1) };

    await act(async () => { await result.current.start(groups, { ...params, seed: "42" }, behaviorGroup()); });
    await act(async () => { await result.current.start(groups, { ...params, seed: "42" }, behaviorGroup()); });

    expect(outputDirFactory).toHaveBeenCalledTimes(2);
    expect(generateDirs).toEqual([
      "outputs/compare_run_1/group_001_seed_42",
      "outputs/compare_run_1/group_001_seed_42",
      "outputs/compare_run_2/group_001_seed_42",
      "outputs/compare_run_2/group_001_seed_42",
    ]);
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
        { ...params, nt: 2, seed: "42" },
        behaviorGroup(),
      );
    });
    expect(seeds).toEqual([42, 42, 43, 43]);
    expect(randomSeed).not.toHaveBeenCalled();
    expect(result.current.groupSummaries).toEqual([
      expect.objectContaining({ groupIndex: 1, seed: 42, total: 2, succeeded: 2 }),
      expect.objectContaining({ groupIndex: 2, seed: 43, total: 2, succeeded: 2 }),
    ]);
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

    await act(async () => { await result.current.start(groups, params, behaviorGroup()); });

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
    await act(async () => { await result.current.start({ artist: group("artist", 1), character: group("character", 1), action: group("action", 1) }, params, behaviorGroup()); });
    await waitFor(() => expect(result.current.summary.succeeded).toBe(1));
    expect(JSON.stringify(localStorage)).not.toContain("job");
  });

  it("uses each complete prompt behavior profile as its own compare combination", async () => {
    const composeRequests: Array<Record<string, unknown>> = [];
    const post = vi.fn(async (path: string, body: unknown): Promise<unknown> => {
      if (path === "/compose-preview") {
        composeRequests.push(body as Record<string, unknown>);
        return { status: "ready", render_request: {} };
      }
      return { id: "job", name: "generate", status: "succeeded" };
    });
    const behaviors = behaviorGroup();
    behaviors.compares.push({
      slotId: "behavior-off",
      label: "No Character Prompts",
      mode: "compare",
      value: {
        identityMinimal: { mode: "override", sections: ["character"] },
        characterPrompts: { mode: "off", addMaleCaption: false },
        policyRules: { visibility_policy: { state: "disabled" } },
      },
    });
    const { result } = renderHook(() => useCompareRunController({ post }));

    await act(async () => {
      await result.current.start(
        { artist: group("artist", 1), character: group("character", 1), action: group("action", 1) },
        params,
        behaviors,
      );
    });

    expect(composeRequests).toHaveLength(2);
    const [primaryRequest, compareRequest] = composeRequests;
    expect(((primaryRequest.render as Record<string, unknown>).params as Record<string, unknown>).character_prompts).toEqual({ mode: "auto", add_male_caption: true });
    expect(((compareRequest.render as Record<string, unknown>).params as Record<string, unknown>).character_prompts).toBeUndefined();
    expect((compareRequest.compose as Record<string, unknown>).identity_minimal_sections).toEqual(["character"]);
    expect((compareRequest.compose as Record<string, unknown>).prompt_policy).toEqual({ rules: { visibility_policy: { enabled: false } } });
    expect(result.current.results.map((item) => item.behavior.label)).toEqual(["Default", "No Character Prompts"]);
    expect(new Set(result.current.results.map((item) => item.behavior.fingerprint)).size).toBe(2);
  });
});
