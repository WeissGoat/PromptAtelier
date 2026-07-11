import { describe, expect, it } from "vitest";

import type { NodeDocument } from "../nodes/types";
import type { NodeVariantSlot, RenderWorkspaceParams } from "./types";
import { buildComposeRenderRequest } from "./requestBuilder";

const params: RenderWorkspaceParams = { negative: "", width: 832, height: 1216, nt: 3, seed: "-1" };
const artistNode: NodeDocument = { schema: "tags-machine-core.node/v1", kind: "artist", id: "artist-a", prompt: { positive: [], negative: [] } };

function artistSlot(modified = false): NodeVariantSlot {
  return {
    slotId: "primary-artist",
    role: "artist",
    mode: "primary",
    sourceRef: "F:/artists/a",
    sourceNode: artistNode,
    draftNode: modified ? { ...artistNode, name: "edited" } : artistNode,
  };
}

describe("request builder", () => {
  it("uses refs for original nodes and ordinary NT", () => {
    const request = buildComposeRenderRequest({ artist: artistSlot(), character: null, action: null }, params, { compare: false });
    expect(request.compose.nodes[0]).toEqual({ role: "artist", ref: "F:/artists/a" });
    expect(request.render.artist).toBe("F:/artists/a");
    expect(request.render.params.n_samples).toBe(3);
    expect(request.render.seed).toBeUndefined();
  });

  it("serializes modified Artist inline without duplicate render.artist", () => {
    const request = buildComposeRenderRequest({ artist: artistSlot(true), character: null, action: null }, params, { compare: false });
    expect(request.compose.nodes[0].node).toBeTruthy();
    expect(request.render.artist).toBeUndefined();
  });

  it("forces one sample for every compare combination", () => {
    const request = buildComposeRenderRequest({ artist: artistSlot(), character: null, action: null }, { ...params, seed: "42" }, { compare: true });
    expect(request.render.params.n_samples).toBe(1);
    expect(request.render.seed).toBe(42);
    expect(request.compose.negative).toBe("");
  });
});
