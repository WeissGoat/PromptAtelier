import { nodeSlotStatus, serializeNodeSlot } from "../nodes/temporaryNodes";
import type { NodeVariantSlot, PromptBehaviorParams, RenderWorkspaceParams } from "./types";

export type SelectedNodes = {
  artist: NodeVariantSlot | null;
  character: NodeVariantSlot | null;
  action: NodeVariantSlot | null;
};

export type ComposeRenderRequest = {
  compose: {
    nodes: NonNullable<ReturnType<typeof serializeNodeSlot>>[];
    negative: string;
    identity_minimal_sections?: string[];
    prompt_policy?: {
      rules: Record<string, { enabled: boolean; options?: Record<string, unknown> }>;
    };
  };
  render: {
    backend: "novelai";
    artist?: string;
    width: number;
    height: number;
    seed?: number;
    params: Record<string, unknown>;
  };
};

export function buildComposeRenderRequest(
  selected: SelectedNodes,
  params: RenderWorkspaceParams,
  options: { compare: boolean; promptBehavior?: PromptBehaviorParams },
): ComposeRenderRequest {
  const ordered = [selected.artist, selected.character, selected.action];
  const nodes = ordered
    .map((slot) => slot ? serializeNodeSlot(slot) : null)
    .filter((node): node is NonNullable<typeof node> => Boolean(node));
  const artistIsInline = Boolean(selected.artist?.draftNode) && nodeSlotStatus(selected.artist!) !== "original";
  const parsedSeed = Number(params.seed);
  const promptBehavior = options.promptBehavior;
  const compose: ComposeRenderRequest["compose"] = {
    nodes,
    negative: params.negative || "",
  };
  if (promptBehavior?.identityMinimal.mode === "override") {
    if (!promptBehavior.identityMinimal.sections.length) {
      throw new Error("identity_minimal_sections must contain at least one section");
    }
    compose.identity_minimal_sections = [...promptBehavior.identityMinimal.sections];
  }
  if (promptBehavior) {
    const rules: NonNullable<ComposeRenderRequest["compose"]["prompt_policy"]>["rules"] = {};
    for (const [ruleId, rule] of Object.entries(promptBehavior.policyRules)) {
      if (rule.state === "inherit") continue;
      rules[ruleId] = {
        enabled: rule.state === "enabled",
        ...(rule.state === "enabled" && rule.options
          ? { options: structuredClone(rule.options) }
          : {}),
      };
    }
    if (Object.keys(rules).length) compose.prompt_policy = { rules };
  }
  const renderParams: Record<string, unknown> = {
    n_samples: options.compare ? 1 : params.nt,
  };
  if (promptBehavior?.characterPrompts.mode === "auto") {
    renderParams.character_prompts = {
      mode: "auto",
      add_male_caption: promptBehavior.characterPrompts.addMaleCaption,
    };
  }
  return {
    compose,
    render: {
      backend: "novelai",
      artist: !artistIsInline ? selected.artist?.sourceRef ?? undefined : undefined,
      width: params.width,
      height: params.height,
      seed: Number.isFinite(parsedSeed) && parsedSeed >= 0 ? parsedSeed : undefined,
      params: renderParams,
    },
  };
}
