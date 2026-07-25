import { describe, expect, it } from "vitest";

import type { NodeDocument, NodeRole } from "../nodes/types";
import { createDefaultPromptBehaviorGroup } from "../workspace/promptBehavior";
import type { NodeVariantSlot, PromptBehaviorGroup, RoleNodeGroup } from "../workspace/types";
import { buildCompareMatrix, compareCount, selectedSlots } from "./matrix";

function slot(role: NodeRole, slotId: string, selected = true): NodeVariantSlot {
  const node: NodeDocument = { schema: "tags-machine-core.node/v1", kind: role, id: slotId, prompt: { positive: [], negative: [] } };
  return { slotId, role, mode: slotId.startsWith("primary") ? "primary" : "compare", sourceRef: selected ? slotId : null, sourceNode: selected ? node : null, draftNode: selected ? node : null };
}

function group(role: NodeRole, count: number): RoleNodeGroup {
  return { primary: slot(role, `primary-${role}`, count > 0), compares: Array.from({ length: Math.max(0, count - 1) }, (_, index) => slot(role, `${role}-${index}`)) };
}

function behaviorGroup(count = 1): PromptBehaviorGroup {
  const group = createDefaultPromptBehaviorGroup();
  group.compares = Array.from({ length: Math.max(0, count - 1) }, (_, index) => ({
    slotId: `behavior-${index + 1}`,
    label: `Behavior ${index + 1}`,
    mode: "compare",
    value: structuredClone(group.primary.value),
  }));
  return group;
}

describe("compare matrix", () => {
  it("expands the exact Cartesian product", () => {
    const groups = { artist: group("artist", 2), character: group("character", 3), action: group("action", 2) };
    expect(compareCount(groups, behaviorGroup())).toBe(12);
    expect(buildCompareMatrix(groups, behaviorGroup())).toHaveLength(12);
  });

  it("expands complete prompt behavior profiles as a matrix dimension", () => {
    const groups = { artist: group("artist", 2), character: group("character", 1), action: group("action", 2) };
    const behaviors = behaviorGroup(3);
    const matrix = buildCompareMatrix(groups, behaviors);

    expect(compareCount(groups, behaviors)).toBe(12);
    expect(matrix).toHaveLength(12);
    expect(new Set(matrix.map((item) => item.promptBehavior.slotId))).toEqual(new Set([
      "primary-prompt-behavior",
      "behavior-1",
      "behavior-2",
    ]));
    expect(matrix.every((item) => item.combinationId.endsWith(item.promptBehavior.slotId))).toBe(true);
  });

  it("uses a null factor when a role has no selected node", () => {
    const groups = { artist: group("artist", 0), character: group("character", 1), action: group("action", 2) };
    const matrix = buildCompareMatrix(groups, behaviorGroup());
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
    const behaviors = behaviorGroup();
    const matrix = buildCompareMatrix({ artist, character: group("character", 1), action: group("action", 1) }, behaviors);
    expect(matrix).toHaveLength(2);
    expect(matrix[0].combinationId).not.toBe(matrix[1].combinationId);
    expect(buildCompareMatrix({ artist, character: group("character", 1), action: group("action", 1) }, behaviors).map((item) => item.combinationId)).toEqual(matrix.map((item) => item.combinationId));
  });

  it("counts a configured random slot as one matrix item", () => {
    const character = group("character", 0);
    character.primary.sourceKind = "random";
    character.primary.randomSpec = {
      source: { type: "folder", value: "角色/group", recursive: false, include_names: [], exclude_names: [] },
      filters: { classify: { phase: [], species: [], cast: [], domain: [], subtype: [], pose: [], environment: [], tone: [], flags: [], clothing: [] } },
    };

    expect(selectedSlots(character)).toHaveLength(1);
    expect(buildCompareMatrix({ artist: group("artist", 1), character, action: group("action", 1) }, behaviorGroup())).toHaveLength(1);
  });
});
