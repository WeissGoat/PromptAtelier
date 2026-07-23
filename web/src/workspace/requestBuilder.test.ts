import { describe, expect, it } from "vitest";

import type { NodeDocument } from "../nodes/types";
import type { NodeVariantSlot, PromptBehaviorParams, RenderWorkspaceParams } from "./types";
import { buildComposeRenderRequest } from "./requestBuilder";

const params: RenderWorkspaceParams = { negative: "", width: 832, height: 1216, nt: 3, seed: "-1" };
const artistNode: NodeDocument = { schema: "tags-machine-core.node/v1", kind: "artist", id: "artist-a", prompt: { positive: [], negative: [] } };
const promptBehavior: PromptBehaviorParams = {
  identityMinimal: { mode: "override", sections: ["character", "role"] },
  characterPrompts: { mode: "auto", addMaleCaption: true },
  policyRules: { visibility_policy: { state: "disabled" } },
};

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

  it("serializes prompt behavior overrides", () => {
    const request = buildComposeRenderRequest(
      { artist: artistSlot(), character: null, action: null },
      params,
      { compare: false, promptBehavior },
    );

    expect(request.compose.identity_minimal_sections).toEqual(["character", "role"]);
    expect(request.compose.prompt_policy?.rules.visibility_policy).toEqual({ enabled: false });
    expect(request.render.params.character_prompts).toEqual({ mode: "auto", add_male_caption: true });
  });

  it("omits inherited prompt behavior", () => {
    const request = buildComposeRenderRequest(
      { artist: artistSlot(), character: null, action: null },
      params,
      {
        compare: false,
        promptBehavior: {
          identityMinimal: { mode: "inherit", sections: [] },
          characterPrompts: { mode: "off", addMaleCaption: true },
          policyRules: { visibility_policy: { state: "inherit" } },
        },
      },
    );

    expect(request.compose).not.toHaveProperty("identity_minimal_sections");
    expect(request.compose).not.toHaveProperty("prompt_policy");
    expect(request.render.params).not.toHaveProperty("character_prompts");
  });

  it("rejects an empty identity override", () => {
    expect(() => buildComposeRenderRequest(
      { artist: artistSlot(), character: null, action: null },
      params,
      {
        compare: false,
        promptBehavior: {
          ...promptBehavior,
          identityMinimal: { mode: "override", sections: [] },
        },
      },
    )).toThrow("identity_minimal_sections");
  });
});
