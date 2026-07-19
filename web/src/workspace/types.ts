import type { ComposePreviewResponse, NodeEditorDocument } from "../api/types";
import type { NodeDocument, NodeRole } from "../nodes/types";

export type SlotMode = "primary" | "compare";

export type NodeVariantSlot = {
  slotId: string;
  role: NodeRole;
  mode: SlotMode;
  sourceRef: string | null;
  sourceNode: NodeDocument | null;
  draftNode: NodeDocument | null;
  sourceEditor?: NodeEditorDocument | null;
  draftEditorValues?: Record<string, unknown> | null;
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

export type WorkspaceEditorState = {
  slotId: string | null;
  tab: "form" | "json";
  draftNode: NodeDocument | null;
  baselineNode: NodeDocument | null;
  editValues: Record<string, unknown> | null;
  baselineValues: Record<string, unknown> | null;
};

export type CustomWorkspaceState = {
  schema: "promptatelier.custom-workspace/v1";
  groups: Record<NodeRole, RoleNodeGroup>;
  params: RenderWorkspaceParams;
  editor: WorkspaceEditorState;
  preview: ComposePreviewResponse | null;
  revision: number;
};
