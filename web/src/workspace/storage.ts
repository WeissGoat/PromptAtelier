import { errorMessage } from "../api/client";
import type { GroupRole, NodeRole } from "../nodes/types";
import type {
  CustomWorkspaceState,
  NodeVariantSlot,
  RoleNodeGroup,
} from "./types";
import {
  createDefaultPromptBehaviorGroup,
  findPromptBehaviorVariant,
  normalizePromptBehavior,
  normalizePromptBehaviorGroup,
  PRIMARY_PROMPT_BEHAVIOR_SLOT_ID,
} from "./promptBehavior";

export { createDefaultPromptBehavior } from "./promptBehavior";

export const CUSTOM_WORKSPACE_STORAGE_KEY = "promptatelier.custom-workspace/v1";
export const CUSTOM_WORKSPACE_SCHEMA = "promptatelier.custom-workspace/v2";
const LEGACY_CUSTOM_WORKSPACE_SCHEMA = "promptatelier.custom-workspace/v1";

const roles: GroupRole[] = ["artist", "character", "action"];
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

export function createEmptyClothingSlot(mode: "primary" | "compare" = "primary", parentSlotId = ""): NodeVariantSlot {
  return {
    slotId: mode === "primary" ? `clothing-primary-${parentSlotId || Date.now()}` : createSlotId(`clothing-compare`),
    role: "clothing",
    mode,
    sourceKind: "fixed",
    randomSpec: null,
    sourceRef: null,
    sourceNode: null,
    draftNode: null,
    sourceEditor: null,
    draftEditorValues: null,
  };
}

export function createEmptySlot(role: NodeRole, mode: "primary" | "compare"): NodeVariantSlot {
  const slot: NodeVariantSlot = {
    slotId: mode === "primary" ? `primary-${role}` : createSlotId(`compare-${role}`),
    role,
    mode,
    sourceKind: "fixed",
    randomSpec: null,
    sourceRef: null,
    sourceNode: null,
    draftNode: null,
    sourceEditor: null,
    draftEditorValues: null,
  };
  if (role === "character") {
    slot.clothingSlots = [createEmptyClothingSlot("primary", slot.slotId)];
  }
  return slot;
}

function createEmptyGroup(role: GroupRole): RoleNodeGroup {
  return { primary: createEmptySlot(role, "primary"), compares: [] };
}

export function createEmptyWorkspace(): CustomWorkspaceState {
  return {
    schema: CUSTOM_WORKSPACE_SCHEMA,
    groups: {
      artist: createEmptyGroup("artist"),
      character: createEmptyGroup("character"),
      action: createEmptyGroup("action"),
    },
    params: { negative: "", width: 1024, height: 1024, nt: 1, seed: "-1" },
    promptBehaviorGroup: createDefaultPromptBehaviorGroup(),
    activePromptBehaviorSlotId: PRIMARY_PROMPT_BEHAVIOR_SLOT_ID,
    editor: { slotId: null, kind: null, tab: "form", draftNode: null, baselineNode: null, editValues: null, baselineValues: null },
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
    && (value.sourceKind === "fixed" || value.sourceKind === "random")
    && (value.randomSpec === null || isObject(value.randomSpec))
    && (value.sourceRef === null || typeof value.sourceRef === "string")
    && (value.sourceNode === null || isObject(value.sourceNode))
    && (value.draftNode === null || isObject(value.draftNode))
    && (value.sourceEditor === undefined || value.sourceEditor === null || isObject(value.sourceEditor))
    && (value.draftEditorValues === undefined || value.draftEditorValues === null || isObject(value.draftEditorValues))
    && (value.clothingSlots === undefined || Array.isArray(value.clothingSlots));
}

function isWorkspace(value: unknown): value is CustomWorkspaceState {
  if (!isObject(value) || value.schema !== CUSTOM_WORKSPACE_SCHEMA) return false;
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
    && (value.editor.kind === null || value.editor.kind === "node" || value.editor.kind === "random")
    && (value.editor.tab === "form" || value.editor.tab === "json")
    && typeof value.revision === "number"
    && isObject(value.promptBehaviorGroup)
    && typeof value.activePromptBehaviorSlotId === "string"
    && Boolean(findPromptBehaviorVariant(
      normalizePromptBehaviorGroup(value.promptBehaviorGroup),
      value.activePromptBehaviorSlotId,
    ));
}

function migrateWorkspace(value: unknown): unknown {
  if (!isObject(value)) return value;
  if (value.schema !== LEGACY_CUSTOM_WORKSPACE_SCHEMA && value.schema !== CUSTOM_WORKSPACE_SCHEMA) return value;

  const promptBehaviorGroup = value.schema === LEGACY_CUSTOM_WORKSPACE_SCHEMA
    ? {
      ...createDefaultPromptBehaviorGroup(),
      primary: {
        ...createDefaultPromptBehaviorGroup().primary,
        value: normalizePromptBehavior(value.promptBehavior),
      },
    }
    : normalizePromptBehaviorGroup(value.promptBehaviorGroup);
  const requestedActive = typeof value.activePromptBehaviorSlotId === "string"
    ? value.activePromptBehaviorSlotId
    : PRIMARY_PROMPT_BEHAVIOR_SLOT_ID;
  const activePromptBehaviorSlotId = findPromptBehaviorVariant(promptBehaviorGroup, requestedActive)
    ? requestedActive
    : promptBehaviorGroup.primary.slotId;
  const groups = isObject(value.groups)
    ? Object.fromEntries(roles.map((role) => {
      const rawGroup = isObject(value.groups) ? value.groups[role] : null;
      if (!isObject(rawGroup)) return [role, rawGroup];
      const healRandomSpec = (rawSpec: unknown, role: NodeRole) => {
        if (!isObject(rawSpec)) return null;
        const spec = { ...rawSpec } as any;
        if (isObject(spec.source)) {
          spec.source = { ...spec.source };
          if (spec.source.type === "folder" && typeof spec.source.value === "string" && !spec.source.value.trim()) {
            spec.source.value = role === "action" ? "new" : ".";
          }
        }
        return spec;
      };

      const normalizeClothingSlot = (c: unknown, index: number, parentSlotId: string): NodeVariantSlot => {
        const slot = isObject(c) ? c : {};
        return {
          slotId: typeof slot.slotId === "string" ? slot.slotId : (index === 0 ? `clothing-primary-${parentSlotId}` : createSlotId("clothing-compare")),
          role: "clothing" as const,
          mode: index === 0 ? "primary" : "compare",
          sourceKind: slot.sourceKind === "random" ? "random" : "fixed",
          randomSpec: healRandomSpec(slot.randomSpec, "clothing"),
          sourceRef: typeof slot.sourceRef === "string" ? slot.sourceRef : null,
          sourceNode: isObject(slot.sourceNode) ? (slot.sourceNode as any) : null,
          draftNode: isObject(slot.draftNode) ? (slot.draftNode as any) : null,
          sourceEditor: isObject(slot.sourceEditor) ? (slot.sourceEditor as any) : null,
          draftEditorValues: isObject(slot.draftEditorValues) ? (slot.draftEditorValues as any) : null,
        };
      };

      const normalizeSlot = (slot: unknown) => {
        if (!isObject(slot)) return slot;
        const role = (slot.role as NodeRole) || "artist";
        const normalized = {
          ...slot,
          sourceKind: slot.sourceKind === "random" ? "random" : "fixed",
          randomSpec: healRandomSpec(slot.randomSpec, role),
        } as NodeVariantSlot;
        if (normalized.role === "character") {
          let clothingSlots: NodeVariantSlot[] = [];
          if (Array.isArray(normalized.clothingSlots) && normalized.clothingSlots.length) {
            clothingSlots = normalized.clothingSlots.map((c, idx) => normalizeClothingSlot(c, idx, normalized.slotId));
          } else {
            clothingSlots = [{
              slotId: `clothing-primary-${normalized.slotId}`,
              role: "clothing",
              mode: "primary",
              sourceKind: "fixed",
              randomSpec: null,
              sourceRef: (normalized as any).clothingRef ?? null,
              sourceNode: (normalized as any).clothingNode ?? null,
              draftNode: (normalized as any).clothingNode ?? null,
              sourceEditor: null,
              draftEditorValues: null,
            }];
          }
          normalized.clothingSlots = clothingSlots;
          (normalized as any).clothingRef = clothingSlots[0]?.sourceRef ?? null;
          (normalized as any).clothingNode = clothingSlots[0]?.draftNode ?? null;
        }
        return normalized;
      };
      return [role, {
        ...rawGroup,
        primary: normalizeSlot(rawGroup.primary),
        compares: Array.isArray(rawGroup.compares) ? rawGroup.compares.map(normalizeSlot) : rawGroup.compares,
      }];
    }))
    : value.groups;
  const editor = isObject(value.editor) ? {
    ...value.editor,
    kind: value.editor.kind === "random" ? "random" : value.editor.slotId ? "node" : null,
  } : value.editor;
  return {
    ...value,
    schema: CUSTOM_WORKSPACE_SCHEMA,
    groups,
    editor,
    promptBehaviorGroup,
    activePromptBehaviorSlotId,
  };
}

export function loadWorkspaceSnapshot(storage: Storage): WorkspaceLoadResult {
  const raw = storage.getItem(CUSTOM_WORKSPACE_STORAGE_KEY);
  if (!raw) return { status: "empty", state: createEmptyWorkspace() };
  try {
    const parsed: unknown = JSON.parse(raw);
    const migrated = migrateWorkspace(parsed);
    if (!isWorkspace(migrated)) {
      return { status: "invalid", state: createEmptyWorkspace(), message: "工作台缓存格式不兼容，请重置工作台。" };
    }
    const state = structuredClone(migrated);
    const editorValues = state.editor.editValues;
    if (state.editor.slotId && editorValues) {
      for (const role of roles) {
        const group = state.groups[role];
        const allSlots = [group.primary, ...group.compares];
        let found = false;
        for (const candidate of allSlots) {
          if (candidate.slotId === state.editor.slotId) {
            candidate.draftEditorValues = structuredClone(editorValues);
            found = true;
            break;
          }
          if (candidate.clothingSlots) {
            const clothingCandidate = candidate.clothingSlots.find((c) => c.slotId === state.editor.slotId);
            if (clothingCandidate) {
              clothingCandidate.draftEditorValues = structuredClone(editorValues);
              found = true;
              break;
            }
          }
        }
        if (found) break;
      }
    }
    return { status: "loaded", state };
  } catch (error) {
    return { status: "invalid", state: createEmptyWorkspace(), message: `读取工作台缓存失败：${errorMessage(error)}` };
  }
}

export function saveWorkspaceSnapshot(storage: Storage, state: CustomWorkspaceState): void {
  storage.setItem(CUSTOM_WORKSPACE_STORAGE_KEY, JSON.stringify({
    schema: state.schema,
    groups: state.groups,
    params: state.params,
    promptBehaviorGroup: state.promptBehaviorGroup,
    activePromptBehaviorSlotId: state.activePromptBehaviorSlotId,
    editor: state.editor,
    preview: state.preview,
    revision: state.revision,
  }));
}

export function clearWorkspaceSnapshot(storage: Storage): void {
  storage.removeItem(CUSTOM_WORKSPACE_STORAGE_KEY);
}
