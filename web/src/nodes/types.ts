export type NodeRole = "artist" | "character" | "action" | "clothing";
export type GroupRole = "artist" | "character" | "action";

export type PromptFragment = {
  text: string;
  role?: string | null;
  weight?: number | null;
  include_scopes?: string[];
  exclude_scopes?: string[];
  notes?: string[];
};

export type NodeDocument = {
  schema: "tags-machine-core.node/v1";
  kind: NodeRole | "background" | "clothing" | "vibe" | "story" | "unknown";
  id: string;
  name?: string | null;
  description?: string | null;
  prompt: {
    positive: PromptFragment[];
    negative: PromptFragment[];
  };
  [key: string]: unknown;
};

export type NodeSlotState = {
  role: NodeRole;
  sourceKind?: "fixed" | "random";
  sourceRef: string | null;
  sourceNode: NodeDocument | null;
  draftNode: NodeDocument | null;
  clothingRef?: string | null;
  clothingNode?: NodeDocument | null;
};

export type NodeSlotStatus = "empty" | "original" | "modified" | "temporary" | "random";

export type ComposeNodeInput = {
  role: NodeRole;
  ref: string;
  node?: NodeDocument;
  clothing_ref?: string;
  clothing?: NodeDocument;
};
