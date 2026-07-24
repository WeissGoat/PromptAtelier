import type { NodeRole } from "../nodes/types";
import type {
  CustomWorkspaceState,
  NodeVariantSlot,
  PromptBehaviorParams,
  RoleNodeGroup,
} from "./types";

export const CUSTOM_WORKSPACE_STORAGE_KEY = "promptatelier.custom-workspace/v1";

const roles: NodeRole[] = ["artist", "character", "action"];
let fallbackCounter = 0;

export type WorkspaceLoadResult =
  | { status: "empty"; state: CustomWorkspaceState }
  | { status: "loaded"; state: CustomWorkspaceState }
  | { status: "invalid"; state: CustomWorkspaceState; message: string };

export function createSlotId(prefix = "slot"): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  fallbackCounter += 1;
  return `${prefix}-${Date.now()}-${fallbackCounter}`;
}

export function createEmptySlot(role: NodeRole, mode: "primary" | "compare"): NodeVariantSlot {
  return {
    slotId: mode === "primary" ? `primary-${role}` : createSlotId(`compare-${role}`),
    role,
    mode,
    sourceRef: null,
    sourceNode: null,
    draftNode: null,
    sourceEditor: null,
    draftEditorValues: null,
  };
}

function createEmptyGroup(role: NodeRole): RoleNodeGroup {
  return { primary: createEmptySlot(role, "primary"), compares: [] };
}

export function createDefaultPromptBehavior(): PromptBehaviorParams {
  return {
    identityMinimal: { mode: "inherit", sections: [] },
    characterPrompts: { mode: "auto", addMaleCaption: true },
    policyRules: {},
  };
}

export function createEmptyWorkspace(): CustomWorkspaceState {
  return {
    schema: CUSTOM_WORKSPACE_STORAGE_KEY,
    groups: {
      artist: createEmptyGroup("artist"),
      character: createEmptyGroup("character"),
      action: createEmptyGroup("action"),
    },
    params: { negative: "", width: 1024, height: 1024, nt: 1, seed: "-1" },
    promptBehavior: createDefaultPromptBehavior(),
    editor: { slotId: null, tab: "form", draftNode: null, baselineNode: null, editValues: null, baselineValues: null },
    preview: null,
    revision: 0,
  };
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isSlot(value: unknown, role: NodeRole, mode: "primary" | "compare"): value is NodeVariantSlot {
  if (!isObject(value)) return false;
  return value.role === role
    && value.mode === mode
    && typeof value.slotId === "string"
    && (value.sourceRef === null || typeof value.sourceRef === "string")
    && (value.sourceNode === null || isObject(value.sourceNode))
    && (value.draftNode === null || isObject(value.draftNode))
    && (value.sourceEditor === undefined || value.sourceEditor === null || isObject(value.sourceEditor))
    && (value.draftEditorValues === undefined || value.draftEditorValues === null || isObject(value.draftEditorValues));
}

function normalizePromptBehavior(value: unknown): PromptBehaviorParams {
  if (!isObject(value)) return createDefaultPromptBehavior();

  const identity = isObject(value.identityMinimal) ? value.identityMinimal : {};
  const identityMode = identity.mode === "override" ? "override" : "inherit";
  const identitySections = Array.isArray(identity.sections)
    ? [...new Set(identity.sections.map((item) => String(item).trim()).filter(Boolean))]
    : [];

  const character = isObject(value.characterPrompts) ? value.characterPrompts : {};
  const characterMode = character.mode === "off" ? "off" : "auto";
  const addMaleCaption = typeof character.addMaleCaption === "boolean"
    ? character.addMaleCaption
    : true;

  const policyRules: PromptBehaviorParams["policyRules"] = {};
  if (isObject(value.policyRules)) {
    for (const [ruleId, rawRule] of Object.entries(value.policyRules)) {
      if (!isObject(rawRule)) continue;
      if (rawRule.state !== "inherit" && rawRule.state !== "enabled" && rawRule.state !== "disabled") continue;
      const options = isObject(rawRule.options) ? structuredClone(rawRule.options) : undefined;
      policyRules[ruleId] = options ? { state: rawRule.state, options } : { state: rawRule.state };
    }
  }

  return {
    identityMinimal: { mode: identityMode, sections: identitySections },
    characterPrompts: { mode: characterMode, addMaleCaption },
    policyRules,
  };
}

function isPromptBehavior(value: unknown): value is PromptBehaviorParams {
  if (!isObject(value)) return false;
  const identity = value.identityMinimal;
  const character = value.characterPrompts;
  return isObject(identity)
    && (identity.mode === "inherit" || identity.mode === "override")
    && Array.isArray(identity.sections)
    && identity.sections.every((item) => typeof item === "string")
    && isObject(character)
    && (character.mode === "auto" || character.mode === "off")
    && typeof character.addMaleCaption === "boolean"
    && isObject(value.policyRules);
}

function isWorkspace(value: unknown): value is CustomWorkspaceState {
  if (!isObject(value) || value.schema !== CUSTOM_WORKSPACE_STORAGE_KEY) return false;
  if (!isObject(value.groups) || !isObject(value.params) || !isObject(value.editor)) return false;
  for (const role of roles) {
    const group = value.groups[role];
    if (!isObject(group) || !isSlot(group.primary, role, "primary") || !Array.isArray(group.compares)) return false;
    if (!group.compares.every((slot) => isSlot(slot, role, "compare"))) return false;
  }
  return typeof value.params.negative === "string"
    && typeof value.params.width === "number"
    && typeof value.params.height === "number"
    && typeof value.params.nt === "number"
    && typeof value.params.seed === "string"
    && (value.editor.slotId === null || typeof value.editor.slotId === "string")
    && (value.editor.tab === "form" || value.editor.tab === "json")
    && typeof value.revision === "number"
    && isPromptBehavior(value.promptBehavior);
}

export function loadWorkspaceSnapshot(storage: Storage): WorkspaceLoadResult {
  const raw = storage.getItem(CUSTOM_WORKSPACE_STORAGE_KEY);
  if (!raw) return { status: "empty", state: createEmptyWorkspace() };
  try {
    const parsed: unknown = JSON.parse(raw);
    const migrated = isObject(parsed)
      ? { ...parsed, promptBehavior: normalizePromptBehavior(parsed.promptBehavior) }
      : parsed;
    if (!isWorkspace(migrated)) {
      return { status: "invalid", state: createEmptyWorkspace(), message: "工作台缓存格式不兼容，请重置工作台。" };
    }
    const state = structuredClone(migrated);
    const editorValues = state.editor.editValues;
    if (state.editor.slotId && editorValues) {
      for (const role of roles) {
        const group = state.groups[role];
        const slot = [group.primary, ...group.compares]
          .find((candidate) => candidate.slotId === state.editor.slotId);
        if (slot) {
          slot.draftEditorValues = structuredClone(editorValues);
          break;
        }
      }
    }
    return { status: "loaded", state };
  } catch {
    return { status: "invalid", state: createEmptyWorkspace(), message: "工作台缓存无法解析，请重置工作台。" };
  }
}

export function saveWorkspaceSnapshot(storage: Storage, state: CustomWorkspaceState): void {
  storage.setItem(CUSTOM_WORKSPACE_STORAGE_KEY, JSON.stringify({
    schema: state.schema,
    groups: state.groups,
    params: state.params,
    promptBehavior: state.promptBehavior,
    editor: state.editor,
    preview: state.preview,
    revision: state.revision,
  }));
}

export function clearWorkspaceSnapshot(storage: Storage): void {
  storage.removeItem(CUSTOM_WORKSPACE_STORAGE_KEY);
}
