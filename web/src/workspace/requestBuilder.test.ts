import { describe, expect, it } from "vitest";

import type { NodeDocument } from "../nodes/types";
import type { NodeVariantSlot, PromptBehaviorParams, RenderWorkspaceParams } from "./types";
import { artistBackend, buildComposeRenderRequest, buildGeneratePayload, workspaceMayUseComfyUI } from "./requestBuilder";

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

  it("serializes novelai_vibe policy rule with valid artist source", () => {
    const request = buildComposeRenderRequest(
      { artist: artistSlot(), character: null, action: null },
      params,
      {
        compare: false,
        promptBehavior: {
          ...promptBehavior,
          policyRules: {
            novelai_vibe: {
              state: "enabled",
              options: {
                artist_ref: "F:/artists/vibe_ref",
                mode: "merge",
                strength: [0.2, 0.3],
                information_extracted: 0.85,
              },
            },
          },
        },
      },
    );

    expect(request.compose.prompt_policy?.rules.novelai_vibe).toEqual({
      enabled: true,
      options: {
        source: { type: "artist", ref: "F:/artists/vibe_ref" },
        mode: "merge",
        strength: [0.2, 0.3],
        information_extracted: 0.85,
      },
    });
  });

  it("bridges legacy novelai_vibe_artist into novelai_vibe without leaking novelai_vibe_artist to backend", () => {
    const request = buildComposeRenderRequest(
      { artist: artistSlot(), character: null, action: null },
      params,
      {
        compare: false,
        promptBehavior: {
          ...promptBehavior,
          policyRules: {
            novelai_vibe_artist: {
              state: "enabled",
              options: {
                artist_ref: "F:/artists/vibe_ref",
                mode: "merge",
                strength: [0.2, 0.3],
                information_extracted: 0.85,
              },
            },
          },
        },
      },
    );

    expect(request.compose.prompt_policy?.rules.novelai_vibe_artist).toBeUndefined();
    expect(request.compose.prompt_policy?.rules.novelai_vibe).toEqual({
      enabled: true,
      options: {
        source: { type: "artist", ref: "F:/artists/vibe_ref" },
        mode: "merge",
        strength: [0.2, 0.3],
        information_extracted: 0.85,
      },
    });
  });

  it("omits novelai_vibe when novelai_vibe is disabled or has empty ref", () => {
    const request = buildComposeRenderRequest(
      { artist: artistSlot(), character: null, action: null },
      params,
      {
        compare: false,
        promptBehavior: {
          ...promptBehavior,
          policyRules: {
            novelai_vibe: {
              state: "disabled",
              options: { artist_ref: "F:/artists/vibe_ref" },
            },
          },
        },
      },
    );

    expect(request.compose.prompt_policy?.rules.novelai_vibe).toBeUndefined();
  });

  describe("ComfyUI artists", () => {
    const comfyNode: NodeDocument = {
      ...artistNode,
      id: "cunyfunky",
      renderers: { comfyui: { workflow: "cunyfunky" } },
    };
    const comfySlot: NodeVariantSlot = { ...artistSlot(), sourceRef: "F:/design/画风/comfyui/cunyfunky", sourceNode: comfyNode, draftNode: comfyNode };
    const vibeBehavior: PromptBehaviorParams = {
      ...promptBehavior,
      policyRules: { novelai_vibe: { state: "enabled", options: { artist_ref: "vibe-artist" } } },
    };

    it("picks the backend from the artist renderers", () => {
      expect(artistBackend(comfySlot)).toBe("comfyui");
      expect(artistBackend(artistSlot())).toBe("novelai");
      expect(artistBackend({ ...comfySlot, draftNode: { ...comfyNode, renderers: { comfyui: {}, novelai: {} } } })).toBe("novelai");
      expect(artistBackend(null)).toBe("novelai");
    });

    it("builds a comfyui render without NovelAI-only extras", () => {
      const request = buildComposeRenderRequest(
        { artist: comfySlot, character: null, action: null },
        params,
        { compare: false, promptBehavior: vibeBehavior },
      );

      expect(request.render.backend).toBe("comfyui");
      expect(request.render.artist).toBe("F:/design/画风/comfyui/cunyfunky");
      expect(request.render.params.character_prompts).toBeUndefined();
      expect(request.compose.prompt_policy?.rules.novelai_vibe).toBeUndefined();
      expect(request.render.params.n_samples).toBe(3);
    });

    it("adds the workspace run location only to comfyui generate payloads", () => {
      const withTarget = { ...params, comfyuiTarget: "modal" };

      expect(buildGeneratePayload({ backend: "comfyui" }, withTarget, { output_dir: "x" })).toEqual({
        render_request: { backend: "comfyui" },
        output_dir: "x",
        comfyui_target: "modal",
      });
      expect(buildGeneratePayload({ backend: "novelai" }, withTarget)).toEqual({ render_request: { backend: "novelai" } });
      expect(buildGeneratePayload({ backend: "comfyui" }, params)).toEqual({ render_request: { backend: "comfyui" } });
    });

    it("shows the run location for comfyui or random artists", () => {
      expect(workspaceMayUseComfyUI([artistSlot()])).toBe(false);
      expect(workspaceMayUseComfyUI([artistSlot(), comfySlot])).toBe(true);
      expect(workspaceMayUseComfyUI([{ ...artistSlot(), sourceKind: "random" }])).toBe(true);
    });
  });
});
