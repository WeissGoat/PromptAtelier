import { beforeEach, describe, expect, it, vi } from "vitest";

import type { NodeDocument } from "../nodes/types";
import { createEmptySlot } from "../workspace/storage";
import { createDefaultNodePoolSpec } from "./spec";
import { resolveRandomItems } from "./resolve";

const sampleNodePool = vi.fn();

vi.mock("./api", () => ({ sampleNodePool: (...args: unknown[]) => sampleNodePool(...args) }));

function node(id: string): NodeDocument {
  return { schema: "tags-machine-core.node/v1", kind: "character", id, name: id, prompt: { positive: [], negative: [] } };
}

describe("random node resolution", () => {
  beforeEach(() => sampleNodePool.mockReset());

  it("draws once per slot and consumes a non-repeating sequence across actual tasks", async () => {
    const slot = createEmptySlot("character", "primary");
    slot.sourceKind = "random";
    slot.randomSpec = createDefaultNodePoolSpec();
    slot.randomSpec.source.value = "角色/group";
    sampleNodePool.mockResolvedValue({
      items: [
        { candidate: { role: "character", ref: "a", name: "A" }, node: node("A"), draw_index: 0, deck_cycle: 1 },
        { candidate: { role: "character", ref: "b", name: "B" }, node: node("B"), draw_index: 1, deck_cycle: 1 },
      ],
      stats: { raw_total: 2, total: 2, missing_classify: 0, invalid_classify: 0, classify_mismatch: 0, invalid_node: 0 },
    });

    const result = await resolveRandomItems([
      { value: 1, slots: { artist: null, character: slot, action: null } },
      { value: 2, slots: { artist: null, character: slot, action: null } },
    ]);

    expect(sampleNodePool).toHaveBeenCalledOnce();
    expect(sampleNodePool).toHaveBeenCalledWith("character", slot.randomSpec, 2);
    expect(result.map((item) => item.slots.character?.draftNode?.id)).toEqual(["A", "B"]);
    expect(result.map((item) => item.randomSelections[0].candidate.ref)).toEqual(["a", "b"]);
  });
});
