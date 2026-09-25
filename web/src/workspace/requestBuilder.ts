import { cloneNode, nodeSlotStatus, serializeNodeSlot } from "../nodes/temporaryNodes";
import type { NodeVariantSlot, PromptBehaviorParams, RenderWorkspaceParams } from "./types";

export type SelectedNodes = {
  artist: NodeVariantSlot | null;
  character: NodeVariantSlot | null;
  action: NodeVariantSlot | null;
  clothing?: NodeVariantSlot | null;
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
  let character = selected.character;
  if (character && selected.clothing) {
    character = {
      ...character,
      clothingRef: selected.clothing.sourceRef ?? null,
      clothingNode: selected.clothing.draftNode ? cloneNode(selected.clothing.draftNode) : null,
    };
  }
  const ordered = [selected.artist, character, selected.action];
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
      if (ruleId === "novelai_vibe" || ruleId === "novelai_vibe_artist") {
        if (rule.state === "enabled") {
          const sourceOptions = (rule.options ?? {}) as Record<string, unknown>;
          const rawSource = sourceOptions.source && typeof sourceOptions.source === "object" && !Array.isArray(sourceOptions.source)
            ? (sourceOptions.source as Record<string, unknown>)
            : null;
          const artistRef = typeof sourceOptions.artist_ref === "string" && sourceOptions.artist_ref.trim()
            ? sourceOptions.artist_ref.trim()
            : (rawSource && typeof rawSource.ref === "string" ? rawSource.ref.trim() : "");
          if (artistRef) {
            const vibeOptions: Record<string, unknown> = {
              source: { type: "artist", ref: artistRef },
            };
            if (sourceOptions.mode === "replace" || sourceOptions.mode === "merge") {
              vibeOptions.mode = sourceOptions.mode;
            }
            if (typeof sourceOptions.strength === "number" || Array.isArray(sourceOptions.strength)) {
              vibeOptions.strength = structuredClone(sourceOptions.strength);
            }
            if (typeof sourceOptions.information_extracted === "number" || Array.isArray(sourceOptions.information_extracted)) {
              vibeOptions.information_extracted = structuredClone(sourceOptions.information_extracted);
            }
            rules.novelai_vibe = { enabled: true, options: vibeOptions };
          }
        }
        continue;
      }
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
