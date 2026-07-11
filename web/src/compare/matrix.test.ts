import { describe, expect, it } from "vitest";

import type { NodeDocument, NodeRole } from "../nodes/types";
import type { NodeVariantSlot, RoleNodeGroup } from "../workspace/types";
import { buildCompareMatrix, compareCount, selectedSlots } from "./matrix";

function slot(role: NodeRole, slotId: string, selected = true): NodeVariantSlot {
  const node: NodeDocument = { schema: "tags-machine-core.node/v1", kind: role, id: slotId, prompt: { positive: [], negative: [] } };
  return { slotId, role, mode: slotId.startsWith("primary") ? "primary" : "compare", sourceRef: selected ? slotId : null, sourceNode: selected ? node : null, draftNode: selected ? node : null };
}

function group(role: NodeRole, count: number): RoleNodeGroup {
  return { primary: slot(role, `primary-${role}`, count > 0), compares: Array.from({ length: Math.max(0, count - 1) }, (_, index) => slot(role, `${role}-${index}`)) };
}

describe("compare matrix", () => {
  it("expands the exact Cartesian product", () => {
    const groups = { artist: group("artist", 2), character: group("character", 3), action: group("action", 2) };
    expect(compareCount(groups)).toBe(12);
    expect(buildCompareMatrix(groups)).toHaveLength(12);
  });

  it("uses a null factor when a role has no selected node", () => {
    const groups = { artist: group("artist", 0), character: group("character", 1), action: group("action", 2) };
    const matrix = buildCompareMatrix(groups);
    expect(matrix).toHaveLength(2);
    expect(matrix.every((item) => item.artist === null)).toBe(true);
  });

  it("excludes empty compare slots", () => {
    const action = group("action", 1);
    action.compares.push(slot("action", "empty-action", false));
    expect(selectedSlots(action)).toHaveLength(1);
  });

  it("keeps duplicate refs in different slots as separate combinations", () => {
    const artist = group("artist", 2);
    artist.compares[0] = { ...artist.compares[0], sourceRef: artist.primary.sourceRef, sourceNode: artist.primary.sourceNode, draftNode: artist.primary.draftNode };
    const matrix = buildCompareMatrix({ artist, character: group("character", 1), action: group("action", 1) });
    expect(matrix).toHaveLength(2);
    expect(matrix[0].combinationId).not.toBe(matrix[1].combinationId);
    expect(buildCompareMatrix({ artist, character: group("character", 1), action: group("action", 1) }).map((item) => item.combinationId)).toEqual(matrix.map((item) => item.combinationId));
  });
});
