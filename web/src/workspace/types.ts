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
  /** 组内勾选的成员（节点目录的绝对路径）；为空表示整组都参与随机/顺序。 */
  selection?: { refs: string[] };
};

/** 节点组成员的临时修改：抽到这个成员时用 draftNode 出图，不改源文件。 */
export type MemberDraft = {
  name: string;
  sourceNode: NodeDocument;
  draftNode: NodeDocument;
  sourceEditor?: NodeEditorDocument | null;
  draftEditorValues?: Record<string, unknown> | null;
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
  /** 节点组成员的临时修改，按成员 ref 存。 */
  memberDrafts?: Record<string, MemberDraft>;
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
  n: number;
  seed: string;
  /** ComfyUI 画风在哪个运行位置出图（comfyui.targets 的名字）；空表示用后端默认。 */
  comfyuiTarget?: string;
  /** 尺寸选择：random 从画风的竖横方预设里抽，portrait/landscape/square 用画风对应的那个，custom 用 width/height；空等同 random。 */
  size?: SizeChoice;
};

export type SizeOrientation = "portrait" | "landscape" | "square";
export type SizeChoice = "random" | SizeOrientation | "custom";

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

export type EditorTab = "form" | "json" | "source";

export type WorkspaceEditorState = {
  slotId: string | null;
  kind?: "node" | "random" | null;
  /** 正在编辑节点组里的某个成员时是它的 ref；编辑槽位自己的节点时为空。 */
  memberRef?: string | null;
  tab: EditorTab;
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
