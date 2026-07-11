import { describe, expect, it } from "vitest";
import {
  createTemporaryNode,
  hasUsablePositivePrompt,
  nodeSlotStatus,
  serializeNodeSlot,
} from "./temporaryNodes";

describe("temporary node slots", () => {
  it("serializes an unchanged library node as a ref only", () => {
    const node = createTemporaryNode("character", "homura");
    const slot = { role: "character" as const, sourceRef: "F:/design/homura", sourceNode: node, draftNode: node };
    expect(nodeSlotStatus(slot)).toBe("original");
    expect(serializeNodeSlot(slot)).toEqual({ role: "character", ref: "F:/design/homura" });
  });

  it("serializes modified content inline", () => {
    const source = createTemporaryNode("action", "standing");
    const draft = structuredClone(source);
    draft.prompt.positive = [{ text: "standing, looking_at_viewer" }];
    const slot = { role: "action" as const, sourceRef: "F:/design/standing", sourceNode: source, draftNode: draft };
    expect(nodeSlotStatus(slot)).toBe("modified");
    expect(serializeNodeSlot(slot)).toEqual({ role: "action", ref: "F:/design/standing", node: draft });
  });

  it("does not treat object key order as a modification", () => {
    const source = createTemporaryNode("action", "standing");
    const draft = structuredClone(source);
    draft.prompt = { negative: [], positive: [] };
    const slot = { role: "action" as const, sourceRef: "standing", sourceNode: source, draftNode: draft };
    expect(nodeSlotStatus(slot)).toBe("original");
  });

  it("serializes a blank-origin draft with a web temporary ref", () => {
    const draft = createTemporaryNode("character", "temporary-character");
    draft.prompt.positive = [{ text: "1girl, black_hair" }];
    const slot = { role: "character" as const, sourceRef: null, sourceNode: null, draftNode: draft };
    expect(nodeSlotStatus(slot)).toBe("temporary");
    expect(serializeNodeSlot(slot)?.ref).toBe("web-temporary:character:temporary-character");
  });

  it("requires non-empty positive prompt before generation", () => {
    const node = createTemporaryNode("character", "draft");
    expect(hasUsablePositivePrompt(node)).toBe(false);
    node.prompt.positive = [{ text: "  " }, { text: "1girl" }];
    expect(hasUsablePositivePrompt(node)).toBe(true);
  });

  it("returns null for an empty slot and clones inline content", () => {
    const empty = { role: "artist" as const, sourceRef: null, sourceNode: null, draftNode: null };
    expect(serializeNodeSlot(empty)).toBeNull();

    const node = createTemporaryNode("artist", "draft");
    const slot = { ...empty, draftNode: node };
    const serialized = serializeNodeSlot(slot);
    expect(serialized?.node).not.toBe(node);
    expect(serialized?.node).toEqual(node);
  });
});
