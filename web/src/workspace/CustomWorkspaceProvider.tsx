import { createContext, type ReactNode, useContext, useEffect, useMemo, useRef, useState } from "react";

import type { ComposePreviewResponse, NodeEditorDocument, NodeReadResponse } from "../api/types";
import { useCompareRunController, type CompareRunController } from "../compare/useCompareRunController";
import { cloneNode, createTemporaryNode } from "../nodes/temporaryNodes";
import type { NodeDocument, NodeRole } from "../nodes/types";
import { createDefaultNodePoolSpec } from "../randomNodes/spec";
import {
  clearWorkspaceSnapshot,
  createEmptyClothingSlot,
  createEmptySlot,
  createEmptyWorkspace,
  createSlotId,
  loadWorkspaceSnapshot,
  saveWorkspaceSnapshot,
} from "./storage";
import {
  findPromptBehaviorVariant,
  PRIMARY_PROMPT_BEHAVIOR_SLOT_ID,
} from "./promptBehavior";
import type {
  CustomWorkspaceState,
  NodePoolSpec,
  NodeVariantSlot,
  PromptBehaviorParams,
  PromptBehaviorVariant,
  RenderWorkspaceParams,
} from "./types";

type CustomWorkspaceContextValue = {
  state: CustomWorkspaceState;
  storageWarning: string;
  compareRun: CompareRunController;
  findSlot(slotId: string): NodeVariantSlot | null;
  selectNode(slotId: string, ref: string, node: NodeDocument, editor?: NodeEditorDocument | null): void;
  applySavedNode(slotId: string, response: NodeReadResponse): void;
  createBlank(slotId: string): void;
  createRandom(slotId: string): void;
  updateRandomSpec(slotId: string, spec: NodePoolSpec): void;
  updateDraft(slotId: string, node: NodeDocument): void;
  restoreSlot(slotId: string): void;
  clearSlot(slotId: string): void;
  addCompare(role: NodeRole): string;
  removeCompare(slotId: string): void;
  addClothingCompare(characterSlotId: string): string;
  removeClothingCompare(characterSlotId: string, clothingSlotId: string): void;
  openEditor(slotId: string, response?: NodeReadResponse): void;
  openRandomEditor(slotId: string): void;
  closeEditor(): void;
  setEditorTab(tab: "form" | "json"): void;
  setEditorDraft(node: NodeDocument): void;
  setEditorValues(values: Record<string, unknown>): void;
  setParams(patch: Partial<RenderWorkspaceParams>): void;
  setClothingForSlot(slotId: string, clothingRef: string | null, clothingNode?: NodeDocument | null): void;
  findPromptBehavior(slotId: string): PromptBehaviorVariant | null;
  selectPromptBehavior(slotId: string): void;
  addPromptBehaviorCompare(): string;
  removePromptBehaviorCompare(slotId: string): void;
  renamePromptBehavior(slotId: string, label: string): void;
  setPromptBehavior(value: PromptBehaviorParams): void;
  setPreview(preview: ComposePreviewResponse | null): void;
  resetWorkspace(): void;
};

const CustomWorkspaceContext = createContext<CustomWorkspaceContextValue | null>(null);

function updateSlotOrClothing(
  slot: NodeVariantSlot,
  targetSlotId: string,
  update: (s: NodeVariantSlot) => NodeVariantSlot,
): { updated: NodeVariantSlot; matched: boolean } {
  if (slot.slotId === targetSlotId) {
    return { updated: update(slot), matched: true };
  }
  if (slot.clothingSlots && slot.clothingSlots.length > 0) {
    const cIndex = slot.clothingSlots.findIndex((cs) => cs.slotId === targetSlotId);
    if (cIndex >= 0) {
      const newClothingSlots = [...slot.clothingSlots];
      newClothingSlots[cIndex] = update(newClothingSlots[cIndex]);
      return {
        updated: {
          ...slot,
          clothingSlots: newClothingSlots,
          clothingRef: newClothingSlots[0]?.sourceRef ?? null,
          clothingNode: newClothingSlots[0]?.draftNode ? cloneNode(newClothingSlots[0].draftNode) : null,
        },
        matched: true,
      };
    }
  }
  return { updated: slot, matched: false };
}

function mapSlot(
  state: CustomWorkspaceState,
  slotId: string,
  update: (slot: NodeVariantSlot) => NodeVariantSlot,
  incrementRevision = true,
): CustomWorkspaceState {
  let changed = false;
  const groups = { ...state.groups };
  for (const role of Object.keys(groups) as Array<keyof CustomWorkspaceState["groups"]>) {
    const group = groups[role];
    const primaryResult = updateSlotOrClothing(group.primary, slotId, update);
    if (primaryResult.matched) {
      groups[role] = { ...group, primary: primaryResult.updated };
      changed = true;
      break;
    }
    const compares = [...group.compares];
    let compareMatched = false;
    for (let i = 0; i < compares.length; i++) {
      const compareResult = updateSlotOrClothing(compares[i], slotId, update);
      if (compareResult.matched) {
        compares[i] = compareResult.updated;
        compareMatched = true;
        changed = true;
        break;
      }
    }
    if (compareMatched) {
      groups[role] = { ...group, compares };
      break;
    }
  }
  return changed ? { ...state, groups, revision: state.revision + (incrementRevision ? 1 : 0) } : state;
}

function findSlotInState(state: CustomWorkspaceState, slotId: string): NodeVariantSlot | null {
  for (const role of Object.keys(state.groups) as Array<keyof CustomWorkspaceState["groups"]>) {
    const group = state.groups[role];
    if (group.primary.slotId === slotId) return group.primary;
    if (group.primary.clothingSlots) {
      const cs = group.primary.clothingSlots.find((c) => c.slotId === slotId);
      if (cs) return cs;
    }
    for (const compare of group.compares) {
      if (compare.slotId === slotId) return compare;
      if (compare.clothingSlots) {
        const cs = compare.clothingSlots.find((c) => c.slotId === slotId);
        if (cs) return cs;
      }
    }
  }
  return null;
}

function mapPromptBehaviorVariant(
  state: CustomWorkspaceState,
  slotId: string,
  update: (variant: PromptBehaviorVariant) => PromptBehaviorVariant,
): CustomWorkspaceState {
  const group = state.promptBehaviorGroup;
  if (group.primary.slotId === slotId) {
    return {
      ...state,
      promptBehaviorGroup: { ...group, primary: update(group.primary) },
      revision: state.revision + 1,
    };
  }
  const index = group.compares.findIndex((variant) => variant.slotId === slotId);
  if (index < 0) return state;
  const compares = [...group.compares];
  compares[index] = update(compares[index]);
  return {
    ...state,
    promptBehaviorGroup: { ...group, compares },
    revision: state.revision + 1,
  };
}

function nextPromptBehaviorLabel(state: CustomWorkspaceState): string {
  const labels = new Set(state.promptBehaviorGroup.compares.map((variant) => variant.label));
  let index = 1;
  while (labels.has(`Compare ${index}`)) index += 1;
  return `Compare ${index}`;
}

export function CustomWorkspaceProvider({ children }: { children: ReactNode }) {
  const initial = useMemo(() => loadWorkspaceSnapshot(window.localStorage), []);
  const [state, setState] = useState<CustomWorkspaceState>(initial.state);
  const [storageWarning, setStorageWarning] = useState(initial.status === "invalid" ? initial.message : "");
  const persistenceBlocked = useRef(initial.status === "invalid");
  const skipNextPersist = useRef(false);
  const compareRun = useCompareRunController();

  useEffect(() => {
    if (persistenceBlocked.current) return;
    if (skipNextPersist.current) {
      skipNextPersist.current = false;
      return;
    }
    const timer = window.setTimeout(() => {
      try {
        saveWorkspaceSnapshot(window.localStorage, state);
      } catch (error) {
        setStorageWarning(error instanceof Error ? error.message : String(error));
      }
    }, 250);
    return () => window.clearTimeout(timer);
  }, [state]);

  const value = useMemo<CustomWorkspaceContextValue>(() => ({
    state,
    storageWarning,
    compareRun,
    findSlot: (slotId) => findSlotInState(state, slotId),
    findPromptBehavior: (slotId) => findPromptBehaviorVariant(state.promptBehaviorGroup, slotId),
    selectNode: (slotId, ref, node, editor = null) => setState((current) => mapSlot(current, slotId, (slot) => {
      const sourceNode = cloneNode(node);
      return {
        ...slot,
        sourceKind: "fixed",
        randomSpec: null,
        sourceRef: ref,
        sourceNode,
        draftNode: cloneNode(sourceNode),
        sourceEditor: editor ? structuredClone(editor) : null,
        draftEditorValues: editor ? structuredClone(editor.values) : null,
      };
    })),
    applySavedNode: (slotId, response) => setState((current) => {
      const sourceNode = cloneNode(response.node);
      const sourceEditor = response.editor ? structuredClone(response.editor) : null;
      const next = mapSlot(current, slotId, (slot) => ({
        ...slot,
        sourceKind: "fixed",
        randomSpec: null,
        sourceRef: response.ref,
        sourceNode,
        draftNode: cloneNode(sourceNode),
        sourceEditor,
        draftEditorValues: sourceEditor ? structuredClone(sourceEditor.values) : null,
      }));
      if (next.editor.slotId !== slotId) return next;
      return {
        ...next,
        editor: {
          ...next.editor,
          draftNode: cloneNode(sourceNode),
          baselineNode: cloneNode(sourceNode),
          editValues: sourceEditor ? structuredClone(sourceEditor.values) : null,
          baselineValues: sourceEditor ? structuredClone(sourceEditor.values) : null,
        },
      };
    }),
    createBlank: (slotId) => setState((current) => mapSlot(current, slotId, (slot) => ({
      ...slot,
      sourceKind: "fixed",
      randomSpec: null,
      sourceRef: null,
      sourceNode: null,
      draftNode: createTemporaryNode(slot.role),
      sourceEditor: null,
      draftEditorValues: null,
    }))),
    createRandom: (slotId) => setState((current) => {
      const next = mapSlot(current, slotId, (slot) => {
        const defaultSpec = createDefaultNodePoolSpec(slot.role);
        const randomSpec = slot.randomSpec?.source?.value?.trim()
          ? structuredClone(slot.randomSpec)
          : defaultSpec;
        return {
          ...slot,
          sourceKind: "random",
          randomSpec,
          sourceRef: null,
          sourceNode: null,
          draftNode: null,
          sourceEditor: null,
          draftEditorValues: null,
        };
      });
      return {
        ...next,
        editor: {
          slotId,
          kind: "random",
          tab: "form",
          draftNode: null,
          baselineNode: null,
          editValues: null,
          baselineValues: null,
        },
      };
    }),
    updateRandomSpec: (slotId, spec) => setState((current) => mapSlot(current, slotId, (slot) => ({
      ...slot,
      sourceKind: "random",
      randomSpec: structuredClone(spec),
    }))),
    updateDraft: (slotId, node) => setState((current) => mapSlot(current, slotId, (slot) => ({
      ...slot,
      draftNode: cloneNode(node),
    }))),
    restoreSlot: (slotId) => setState((current) => mapSlot(current, slotId, (slot) => ({
      ...slot,
      draftNode: slot.sourceNode ? cloneNode(slot.sourceNode) : null,
      draftEditorValues: slot.sourceEditor ? structuredClone(slot.sourceEditor.values) : null,
    }))),
    clearSlot: (slotId) => setState((current) => mapSlot(current, slotId, (slot) => ({
      ...slot,
      sourceKind: "fixed",
      randomSpec: null,
      sourceRef: null,
      sourceNode: null,
      draftNode: null,
      sourceEditor: null,
      draftEditorValues: null,
      clothingRef: null,
      clothingNode: null,
    }))),
    setClothingForSlot: (slotId, clothingRef, clothingNode = null) => setState((current) => mapSlot(current, slotId, (slot) => {
      const primaryClothing = slot.clothingSlots?.[0] ?? createEmptyClothingSlot("primary", slot.slotId);
      const updatedPrimary: NodeVariantSlot = {
        ...primaryClothing,
        sourceKind: "fixed",
        randomSpec: null,
        sourceRef: clothingRef,
        sourceNode: clothingNode ? cloneNode(clothingNode) : null,
        draftNode: clothingNode ? cloneNode(clothingNode) : null,
        sourceEditor: null,
        draftEditorValues: null,
      };
      const otherClothing = (slot.clothingSlots || []).slice(1);
      return {
        ...slot,
        clothingRef,
        clothingNode: clothingNode ? cloneNode(clothingNode) : null,
        clothingSlots: [updatedPrimary, ...otherClothing],
      };
    })),
    addCompare: (role) => {
      const slot = createEmptySlot(role, "compare");
      setState((current) => {
        const primary = current.groups[role].primary;
        const mirrored = {
          ...slot,
          sourceKind: primary.sourceKind,
          randomSpec: primary.randomSpec ? structuredClone(primary.randomSpec) : null,
          sourceRef: primary.sourceRef,
          sourceNode: primary.sourceNode ? cloneNode(primary.sourceNode) : null,
          draftNode: primary.draftNode ? cloneNode(primary.draftNode) : null,
          sourceEditor: primary.sourceEditor ? structuredClone(primary.sourceEditor) : null,
          draftEditorValues: primary.draftEditorValues ? structuredClone(primary.draftEditorValues) : null,
          clothingRef: primary.clothingRef ?? null,
          clothingNode: primary.clothingNode ? cloneNode(primary.clothingNode) : null,
          clothingSlots: role === "character"
            ? (primary.clothingSlots?.map((cs) => ({
                ...structuredClone(cs),
                slotId: createSlotId("clothing-compare"),
                mode: "compare" as const,
              })) ?? [createEmptyClothingSlot("primary", slot.slotId)])
            : undefined,
        };
        return {
          ...current,
          groups: { ...current.groups, [role]: {
            ...current.groups[role],
            compares: [...current.groups[role].compares, mirrored],
          } },
          revision: current.revision + 1,
        };
      });
      return slot.slotId;
    },
    removeCompare: (slotId) => setState((current) => {
      for (const role of Object.keys(current.groups) as Array<keyof CustomWorkspaceState["groups"]>) {
        const group = current.groups[role];
        const removed = group.compares.find((slot) => slot.slotId === slotId);
        if (removed) {
          const removedIds = new Set([slotId, ...(removed.clothingSlots?.map((cs) => cs.slotId) ?? [])]);
          return {
            ...current,
            groups: { ...current.groups, [role]: {
              ...group,
              compares: group.compares.filter((slot) => slot.slotId !== slotId),
            } },
            editor: removedIds.has(current.editor.slotId ?? "")
              ? { slotId: null, kind: null, tab: "form", draftNode: null, baselineNode: null, editValues: null, baselineValues: null }
              : current.editor,
            revision: current.revision + 1,
          };
        }
      }
      return current;
    }),
    addClothingCompare: (characterSlotId) => {
      const clothingSlot = createEmptyClothingSlot("compare", characterSlotId);
      setState((current) => mapSlot(current, characterSlotId, (slot) => ({
        ...slot,
        clothingSlots: slot.clothingSlots ? [...slot.clothingSlots, clothingSlot] : [clothingSlot],
      })));
      return clothingSlot.slotId;
    },
    removeClothingCompare: (characterSlotId, clothingSlotId) => setState((current) => {
      let next = mapSlot(current, characterSlotId, (slot) => {
        const filtered = (slot.clothingSlots || []).filter((cs) => cs.slotId !== clothingSlotId);
        const finalClothing = filtered.length ? filtered : [createEmptyClothingSlot("primary", slot.slotId)];
        return {
          ...slot,
          clothingSlots: finalClothing,
          clothingRef: finalClothing[0]?.sourceRef ?? null,
          clothingNode: finalClothing[0]?.draftNode ? cloneNode(finalClothing[0].draftNode) : null,
        };
      });
      if (next.editor.slotId === clothingSlotId) {
        next = {
          ...next,
          editor: { slotId: null, kind: null, tab: "form", draftNode: null, baselineNode: null, editValues: null, baselineValues: null },
        };
      }
      return next;
    }),
    openEditor: (slotId, response) => setState((current) => {
      const next = response ? mapSlot(current, slotId, (slot) => {
        const sourceNode = cloneNode(response.node);
        return {
          ...slot,
          sourceKind: "fixed",
          randomSpec: null,
          sourceRef: response.ref,
          sourceNode,
          draftNode: cloneNode(sourceNode),
          sourceEditor: response.editor ? structuredClone(response.editor) : null,
          draftEditorValues: response.editor ? structuredClone(response.editor.values) : null,
        };
      }) : current;
      const slot = findSlotInState(next, slotId);
      if (!slot?.draftNode) return current;
      return { ...next, editor: {
        slotId,
        kind: "node",
        tab: "form",
        draftNode: cloneNode(slot.draftNode),
        baselineNode: cloneNode(slot.draftNode),
        editValues: slot.draftEditorValues
          ? structuredClone(slot.draftEditorValues)
          : slot.sourceEditor
            ? structuredClone(slot.sourceEditor.values)
            : null,
        baselineValues: slot.sourceEditor ? structuredClone(slot.sourceEditor.values) : null,
      } };
    }),
    openRandomEditor: (slotId) => setState((current) => {
      const slot = findSlotInState(current, slotId);
      if (!slot || slot.sourceKind !== "random" || !slot.randomSpec) return current;
      return {
        ...current,
        editor: {
          slotId,
          kind: "random",
          tab: "form",
          draftNode: null,
          baselineNode: null,
          editValues: null,
          baselineValues: null,
        },
      };
    }),
    closeEditor: () => setState((current) => ({
      ...current,
      editor: { slotId: null, kind: null, tab: "form", draftNode: null, baselineNode: null, editValues: null, baselineValues: null },
    })),
    setEditorTab: (tab) => setState((current) => ({ ...current, editor: { ...current.editor, tab } })),
    setEditorDraft: (node) => setState((current) => ({
      ...current,
      editor: { ...current.editor, draftNode: cloneNode(node) },
    })),
    setEditorValues: (values) => setState((current) => {
      const slotId = current.editor.slotId;
      const next = slotId
        ? mapSlot(current, slotId, (slot) => ({
          ...slot,
          draftEditorValues: structuredClone(values),
        }), false)
        : current;
      return {
        ...next,
        editor: { ...next.editor, editValues: structuredClone(values) },
      };
    }),
    setParams: (patch) => setState((current) => ({
      ...current,
      params: { ...current.params, ...patch },
      revision: current.revision + 1,
    })),
    selectPromptBehavior: (slotId) => setState((current) => (
      findPromptBehaviorVariant(current.promptBehaviorGroup, slotId)
        ? { ...current, activePromptBehaviorSlotId: slotId }
        : current
    )),
    addPromptBehaviorCompare: () => {
      const slotId = createSlotId("compare-prompt-behavior");
      setState((current) => {
        const variant: PromptBehaviorVariant = {
          slotId,
          label: nextPromptBehaviorLabel(current),
          mode: "compare",
          value: structuredClone(current.promptBehaviorGroup.primary.value),
        };
        return {
          ...current,
          promptBehaviorGroup: {
            ...current.promptBehaviorGroup,
            compares: [...current.promptBehaviorGroup.compares, variant],
          },
          activePromptBehaviorSlotId: slotId,
          revision: current.revision + 1,
        };
      });
      return slotId;
    },
    removePromptBehaviorCompare: (slotId) => setState((current) => {
      if (!current.promptBehaviorGroup.compares.some((variant) => variant.slotId === slotId)) return current;
      return {
        ...current,
        promptBehaviorGroup: {
          ...current.promptBehaviorGroup,
          compares: current.promptBehaviorGroup.compares.filter((variant) => variant.slotId !== slotId),
        },
        activePromptBehaviorSlotId: current.activePromptBehaviorSlotId === slotId
          ? PRIMARY_PROMPT_BEHAVIOR_SLOT_ID
          : current.activePromptBehaviorSlotId,
        revision: current.revision + 1,
      };
    }),
    renamePromptBehavior: (slotId, label) => setState((current) => {
      const normalized = label.trim();
      if (!normalized) return current;
      return mapPromptBehaviorVariant(current, slotId, (variant) => ({ ...variant, label: normalized }));
    }),
    setPromptBehavior: (promptBehavior) => setState((current) => mapPromptBehaviorVariant(
      current,
      current.activePromptBehaviorSlotId,
      (variant) => ({ ...variant, value: structuredClone(promptBehavior) }),
    )),
    setPreview: (preview) => setState((current) => ({ ...current, preview })),
    resetWorkspace: () => {
      clearWorkspaceSnapshot(window.localStorage);
      persistenceBlocked.current = false;
      skipNextPersist.current = true;
      setStorageWarning("");
      setState(createEmptyWorkspace());
    },
  }), [compareRun, state, storageWarning]);

  return <CustomWorkspaceContext.Provider value={value}>{children}</CustomWorkspaceContext.Provider>;
}

export function useCustomWorkspace(): CustomWorkspaceContextValue {
  const value = useContext(CustomWorkspaceContext);
  if (!value) throw new Error("useCustomWorkspace must be used within CustomWorkspaceProvider");
  return value;
}
