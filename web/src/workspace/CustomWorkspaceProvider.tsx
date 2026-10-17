import { createContext, type ReactNode, useContext, useEffect, useMemo, useRef, useState } from "react";

import type { ComposePreviewResponse, NodeEditorDocument, NodeReadResponse } from "../api/types";
import { cloneNode, createTemporaryNode } from "../nodes/temporaryNodes";
import type { GroupRole, NodeDocument, NodeRole } from "../nodes/types";
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
  EditorTab,
  MemberDraft,
  NodePoolSpec,
  NodeVariantSlot,
  PromptBehaviorParams,
  PromptBehaviorVariant,
  RenderWorkspaceParams,
} from "./types";

/** 编辑器当前编辑的对象：槽位自己的节点，或节点组里的某个成员。 */
export type EditorTarget = {
  slot: NodeVariantSlot;
  memberRef: string | null;
  role: NodeRole;
  name: string;
  sourceRef: string | null;
  sourceNode: NodeDocument | null;
  draftNode: NodeDocument | null;
  sourceEditor: NodeEditorDocument | null;
  draftEditorValues: Record<string, unknown> | null;
};

type CustomWorkspaceContextValue = {
  state: CustomWorkspaceState;
  storageWarning: string;
  editorTarget: EditorTarget | null;
  findSlot(slotId: string): NodeVariantSlot | null;
  /** 打开节点组成员的编辑器；第一次编辑时用读到的节点建立成员草稿。 */
  openMemberEditor(slotId: string, ref: string, name: string, response?: NodeReadResponse): void;
  /** 改编辑对象的运行时节点（JSON / 通用表单 / 表单预览结果）。 */
  updateEditorTargetDraft(node: NodeDocument): void;
  restoreEditorTarget(): void;
  applySavedToEditorTarget(response: NodeReadResponse): void;
  discardMemberDraft(slotId: string, ref: string): void;
  /** null：整组都参与；数组：只在这些成员里随机/按序（空数组表示一个都没选）。 */
  setGroupSelection(slotId: string, refs: string[] | null): void;
  selectNode(slotId: string, ref: string, node: NodeDocument, editor?: NodeEditorDocument | null): void;
  applySavedNode(slotId: string, response: NodeReadResponse): void;
  createBlank(slotId: string): void;
  createRandom(slotId: string): void;
  updateRandomSpec(slotId: string, spec: NodePoolSpec): void;
  updateDraft(slotId: string, node: NodeDocument): void;
  restoreSlot(slotId: string): void;
  clearSlot(slotId: string): void;
  addCompare(role: GroupRole): string;
  removeCompare(slotId: string): void;
  addClothingCompare(characterSlotId: string): string;
  removeClothingCompare(characterSlotId: string, clothingSlotId: string): void;
  openEditor(slotId: string, response?: NodeReadResponse): void;
  openRandomEditor(slotId: string): void;
  closeEditor(): void;
  setEditorTab(tab: EditorTab): void;
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
  advancePoolCursor(slotId: string): void;
  resetPoolCursor(slotId: string): void;
  setPoolCursor(slotId: string, cursor: number): void;
  resetWorkspace(): void;
};

const CustomWorkspaceContext = createContext<CustomWorkspaceContextValue | null>(null);

const EMPTY_EDITOR: CustomWorkspaceState["editor"] = {
  slotId: null,
  kind: null,
  memberRef: null,
  tab: "form",
  draftNode: null,
  baselineNode: null,
  editValues: null,
  baselineValues: null,
};

function emptyEditor(): CustomWorkspaceState["editor"] {
  return { ...EMPTY_EDITOR };
}

function mapMember(
  state: CustomWorkspaceState,
  slotId: string,
  ref: string,
  update: (draft: MemberDraft) => MemberDraft | null,
  incrementRevision = true,
): CustomWorkspaceState {
  return mapSlot(state, slotId, (slot) => {
    const current = slot.memberDrafts?.[ref];
    if (!current) return slot;
    const next = update(current);
    const memberDrafts = { ...(slot.memberDrafts ?? {}) };
    if (next) memberDrafts[ref] = next;
    else delete memberDrafts[ref];
    return { ...slot, memberDrafts };
  }, incrementRevision);
}

function editorTargetOf(state: CustomWorkspaceState): EditorTarget | null {
  const { slotId, memberRef } = state.editor;
  if (!slotId) return null;
  const slot = findSlotInState(state, slotId);
  if (!slot) return null;
  if (memberRef) {
    const member = slot.memberDrafts?.[memberRef];
    if (!member) return null;
    return {
      slot,
      memberRef,
      role: slot.role,
      name: member.draftNode.name || member.name,
      sourceRef: memberRef,
      sourceNode: member.sourceNode,
      draftNode: member.draftNode,
      sourceEditor: member.sourceEditor ?? null,
      draftEditorValues: member.draftEditorValues ?? null,
    };
  }
  if (slot.sourceKind === "random") return null;
  return {
    slot,
    memberRef: null,
    role: slot.role,
    name: slot.draftNode?.name || slot.sourceNode?.name || slot.draftNode?.id || "",
    sourceRef: slot.sourceRef,
    sourceNode: slot.sourceNode,
    draftNode: slot.draftNode,
    sourceEditor: slot.sourceEditor ?? null,
    draftEditorValues: slot.draftEditorValues ?? null,
  };
}

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
    editorTarget: editorTargetOf(state),
    findSlot: (slotId) => findSlotInState(state, slotId),
    openMemberEditor: (slotId, ref, name, response) => setState((current) => {
      const next = mapSlot(current, slotId, (slot) => {
        if (slot.memberDrafts?.[ref] || !response) return slot;
        const sourceNode = cloneNode(response.node);
        const sourceEditor = response.editor ? structuredClone(response.editor) : null;
        return {
          ...slot,
          memberDrafts: {
            ...(slot.memberDrafts ?? {}),
            [ref]: {
              name,
              sourceNode,
              draftNode: cloneNode(sourceNode),
              sourceEditor,
              draftEditorValues: sourceEditor ? structuredClone(sourceEditor.values) : null,
            },
          },
        };
      }, false);
      const member = findSlotInState(next, slotId)?.memberDrafts?.[ref];
      if (!member) return current;
      return {
        ...next,
        editor: {
          slotId,
          kind: "node",
          memberRef: ref,
          tab: current.editor.tab,
          draftNode: cloneNode(member.draftNode),
          baselineNode: cloneNode(member.sourceNode),
          editValues: member.draftEditorValues ? structuredClone(member.draftEditorValues) : null,
          baselineValues: member.sourceEditor ? structuredClone(member.sourceEditor.values) : null,
        },
      };
    }),
    updateEditorTargetDraft: (node) => setState((current) => {
      const { slotId, memberRef } = current.editor;
      if (!slotId) return current;
      const next = memberRef
        ? mapMember(current, slotId, memberRef, (draft) => ({ ...draft, draftNode: cloneNode(node) }))
        : mapSlot(current, slotId, (slot) => ({ ...slot, draftNode: cloneNode(node) }));
      return { ...next, editor: { ...next.editor, draftNode: cloneNode(node) } };
    }),
    restoreEditorTarget: () => setState((current) => {
      const { slotId, memberRef } = current.editor;
      if (!slotId) return current;
      if (!memberRef) {
        return mapSlot(current, slotId, (slot) => ({
          ...slot,
          draftNode: slot.sourceNode ? cloneNode(slot.sourceNode) : null,
          draftEditorValues: slot.sourceEditor ? structuredClone(slot.sourceEditor.values) : null,
        }));
      }
      const next = mapMember(current, slotId, memberRef, (draft) => ({
        ...draft,
        draftNode: cloneNode(draft.sourceNode),
        draftEditorValues: draft.sourceEditor ? structuredClone(draft.sourceEditor.values) : null,
      }));
      const member = findSlotInState(next, slotId)?.memberDrafts?.[memberRef];
      return member ? {
        ...next,
        editor: {
          ...next.editor,
          draftNode: cloneNode(member.draftNode),
          editValues: member.draftEditorValues ? structuredClone(member.draftEditorValues) : null,
        },
      } : next;
    }),
    applySavedToEditorTarget: (response) => setState((current) => {
      const { slotId, memberRef } = current.editor;
      if (!slotId) return current;
      const sourceNode = cloneNode(response.node);
      const sourceEditor = response.editor ? structuredClone(response.editor) : null;
      const next = memberRef
        ? mapMember(current, slotId, memberRef, (draft) => ({
          ...draft,
          sourceNode,
          draftNode: cloneNode(sourceNode),
          sourceEditor,
          draftEditorValues: sourceEditor ? structuredClone(sourceEditor.values) : null,
        }))
        : mapSlot(current, slotId, (slot) => ({
          ...slot,
          sourceKind: "fixed",
          randomSpec: null,
          sourceRef: response.ref,
          sourceNode,
          draftNode: cloneNode(sourceNode),
          sourceEditor,
          draftEditorValues: sourceEditor ? structuredClone(sourceEditor.values) : null,
        }));
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
    discardMemberDraft: (slotId, ref) => setState((current) => {
      const next = mapMember(current, slotId, ref, () => null);
      return current.editor.slotId === slotId && current.editor.memberRef === ref
        ? { ...next, editor: emptyEditor() }
        : next;
    }),
    setGroupSelection: (slotId, refs) => setState((current) => mapSlot(current, slotId, (slot) => {
      if (!slot.randomSpec) return slot;
      const { selection: _previous, ...rest } = slot.randomSpec;
      return {
        ...slot,
        randomSpec: refs ? { ...rest, selection: { refs: [...new Set(refs)] } } : rest,
      };
    })),
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
        editor: { ...emptyEditor(), slotId, kind: "random" },
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
    addCompare: (role: GroupRole) => {
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
            ? (primary.clothingSlots?.map((cs: NodeVariantSlot) => ({
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
              ? emptyEditor()
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
          editor: emptyEditor(),
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
        memberRef: null,
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
        editor: { ...emptyEditor(), slotId, kind: "random" },
      };
    }),
    closeEditor: () => setState((current) => ({
      ...current,
      editor: emptyEditor(),
    })),
    setEditorTab: (tab) => setState((current) => ({ ...current, editor: { ...current.editor, tab } })),
    setEditorDraft: (node) => setState((current) => ({
      ...current,
      editor: { ...current.editor, draftNode: cloneNode(node) },
    })),
    setEditorValues: (values) => setState((current) => {
      const { slotId, memberRef } = current.editor;
      let next = current;
      if (slotId && memberRef) {
        next = mapMember(current, slotId, memberRef, (draft) => ({
          ...draft,
          draftEditorValues: structuredClone(values),
        }), false);
      } else if (slotId) {
        next = mapSlot(current, slotId, (slot) => ({
          ...slot,
          draftEditorValues: structuredClone(values),
        }), false);
      }
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
    advancePoolCursor: (slotId) => setState((current) => mapSlot(current, slotId, (slot) => ({
      ...slot,
      poolCursor: (slot.poolCursor ?? 0) + 1,
    }))),
    resetPoolCursor: (slotId) => setState((current) => mapSlot(current, slotId, (slot) => ({
      ...slot,
      poolCursor: 0,
    }))),
    setPoolCursor: (slotId, cursor) => setState((current) => mapSlot(current, slotId, (slot) => ({
      ...slot,
      poolCursor: Math.max(0, Math.trunc(cursor)),
    }))),
    resetWorkspace: () => {
      clearWorkspaceSnapshot(window.localStorage);
      persistenceBlocked.current = false;
      skipNextPersist.current = true;
      setStorageWarning("");
      setState(createEmptyWorkspace());
    },
  }), [state, storageWarning]);

  return <CustomWorkspaceContext.Provider value={value}>{children}</CustomWorkspaceContext.Provider>;
}

export function useCustomWorkspace(): CustomWorkspaceContextValue {
  const value = useContext(CustomWorkspaceContext);
  if (!value) throw new Error("useCustomWorkspace must be used within CustomWorkspaceProvider");
  return value;
}
