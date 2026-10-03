import type { ComposePreviewResponse, NodeEditorDocument } from "../api/types";
import type { GroupRole, NodeDocument, NodeRole } from "../nodes/types";

export type SlotMode = "primary" | "compare";

export type NodePoolSourceType = "folder" | "collection" | "glob";

export type DrawMode = "random" | "sequential";

export type ClassifyFilter = {
  phase: string[];
  species: string[];
  cast: string[];
  domain: string[];
  subtype: string[];
  pose: string[];
  environment: string[];
  tone: string[];
  flags: string[];
  clothing: string[];
};

export type NodePoolSpec = {
  source: {
    type: NodePoolSourceType;
    value: string;
    recursive: boolean;
    include_names: string[];
    exclude_names: string[];
  };
  filters: { classify: ClassifyFilter };
  drawMode?: DrawMode;
};

export type NodeVariantSlot = {
  slotId: string;
  role: NodeRole;
  mode: SlotMode;
  sourceKind?: "fixed" | "random";
  randomSpec?: NodePoolSpec | null;
  sourceRef: string | null;
  sourceNode: NodeDocument | null;
  draftNode: NodeDocument | null;
  sourceEditor?: NodeEditorDocument | null;
  draftEditorValues?: Record<string, unknown> | null;
  clothingRef?: string | null;
  clothingNode?: NodeDocument | null;
  clothingSlots?: NodeVariantSlot[];
  poolCursor?: number;
};

export type RoleNodeGroup = {
  primary: NodeVariantSlot;
  compares: NodeVariantSlot[];
};

export type RenderWorkspaceParams = {
  negative: string;
  width: number;
  height: number;
  nt: number;
  seed: string;
};

export type PolicyRuleState = "inherit" | "enabled" | "disabled";

export type PromptBehaviorParams = {
  identityMinimal: {
    mode: "inherit" | "override";
    sections: string[];
  };
  characterPrompts: {
    mode: "auto" | "off";
    addMaleCaption: boolean;
  };
  policyRules: Record<string, {
    state: PolicyRuleState;
    options?: Record<string, unknown>;
  }>;
};

export type PromptBehaviorVariant = {
  slotId: string;
  label: string;
  mode: SlotMode;
  value: PromptBehaviorParams;
};

export type PromptBehaviorGroup = {
  primary: PromptBehaviorVariant;
  compares: PromptBehaviorVariant[];
};

export type WorkspaceEditorState = {
  slotId: string | null;
  kind?: "node" | "random" | null;
  tab: "form" | "json";
  draftNode: NodeDocument | null;
  baselineNode: NodeDocument | null;
  editValues: Record<string, unknown> | null;
  baselineValues: Record<string, unknown> | null;
};

export type CustomWorkspaceState = {
  schema: "promptatelier.custom-workspace/v2";
  groups: Record<GroupRole, RoleNodeGroup>;
  params: RenderWorkspaceParams;
  promptBehaviorGroup: PromptBehaviorGroup;
  activePromptBehaviorSlotId: string;
  editor: WorkspaceEditorState;
  preview: ComposePreviewResponse | null;
  revision: number;
};
