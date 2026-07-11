import { nodeSlotStatus, serializeNodeSlot } from "../nodes/temporaryNodes";
import type { NodeVariantSlot, RenderWorkspaceParams } from "./types";

export type SelectedNodes = {
  artist: NodeVariantSlot | null;
  character: NodeVariantSlot | null;
  action: NodeVariantSlot | null;
};

export type ComposeRenderRequest = {
  compose: {
    nodes: NonNullable<ReturnType<typeof serializeNodeSlot>>[];
    negative: string;
  };
  render: {
    backend: "novelai";
    artist?: string;
    width: number;
    height: number;
    seed?: number;
    params: { n_samples: number };
  };
};

export function buildComposeRenderRequest(
  selected: SelectedNodes,
  params: RenderWorkspaceParams,
  options: { compare: boolean },
): ComposeRenderRequest {
  const ordered = [selected.artist, selected.character, selected.action];
  const nodes = ordered
    .map((slot) => slot ? serializeNodeSlot(slot) : null)
    .filter((node): node is NonNullable<typeof node> => Boolean(node));
  const artistIsInline = Boolean(selected.artist?.draftNode) && nodeSlotStatus(selected.artist!) !== "original";
  const parsedSeed = Number(params.seed);
  return {
    compose: { nodes, negative: params.negative || "" },
    render: {
      backend: "novelai",
      artist: !artistIsInline ? selected.artist?.sourceRef ?? undefined : undefined,
      width: params.width,
      height: params.height,
      seed: Number.isFinite(parsedSeed) && parsedSeed >= 0 ? parsedSeed : undefined,
      params: { n_samples: options.compare ? 1 : params.nt },
    },
  };
}
