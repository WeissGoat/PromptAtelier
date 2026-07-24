import { createContext, type ReactNode, useContext, useEffect, useMemo, useRef, useState } from "react";

import type { ComposePreviewResponse, NodeEditorDocument, NodeReadResponse } from "../api/types";
import { useCompareRunController, type CompareRunController } from "../compare/useCompareRunController";
import { cloneNode, createTemporaryNode } from "../nodes/temporaryNodes";
import type { NodeDocument, NodeRole } from "../nodes/types";
import {
  clearWorkspaceSnapshot,
  createEmptySlot,
  createEmptyWorkspace,
  loadWorkspaceSnapshot,
  saveWorkspaceSnapshot,
} from "./storage";
import type {
  CustomWorkspaceState,
  NodeVariantSlot,
  PromptBehaviorParams,
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
  updateDraft(slotId: string, node: NodeDocument): void;
  restoreSlot(slotId: string): void;
  clearSlot(slotId: string): void;
  addCompare(role: NodeRole): string;
  removeCompare(slotId: string): void;
  openEditor(slotId: string, response?: NodeReadResponse): void;
  closeEditor(): void;
  setEditorTab(tab: "form" | "json"): void;
  setEditorDraft(node: NodeDocument): void;
  setEditorValues(values: Record<string, unknown>): void;
  setParams(patch: Partial<RenderWorkspaceParams>): void;
  setPromptBehavior(value: PromptBehaviorParams): void;
  setPreview(preview: ComposePreviewResponse | null): void;
  resetWorkspace(): void;
};

const CustomWorkspaceContext = createContext<CustomWorkspaceContextValue | null>(null);

function mapSlot(
  state: CustomWorkspaceState,
  slotId: string,
  update: (slot: NodeVariantSlot) => NodeVariantSlot,
  incrementRevision = true,
): CustomWorkspaceState {
  let changed = false;
  const groups = { ...state.groups };
  for (const role of Object.keys(groups) as NodeRole[]) {
    const group = groups[role];
    if (group.primary.slotId === slotId) {
      groups[role] = { ...group, primary: update(group.primary) };
      changed = true;
      break;
    }
    const index = group.compares.findIndex((slot) => slot.slotId === slotId);
    if (index >= 0) {
      const compares = [...group.compares];
      compares[index] = update(compares[index]);
      groups[role] = { ...group, compares };
      changed = true;
      break;
    }
  }
  return changed ? { ...state, groups, revision: state.revision + (incrementRevision ? 1 : 0) } : state;
}

function findSlotInState(state: CustomWorkspaceState, slotId: string): NodeVariantSlot | null {
  for (const role of Object.keys(state.groups) as NodeRole[]) {
    const group = state.groups[role];
    if (group.primary.slotId === slotId) return group.primary;
    const compare = group.compares.find((slot) => slot.slotId === slotId);
    if (compare) return compare;
  }
  return null;
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
    selectNode: (slotId, ref, node, editor = null) => setState((current) => mapSlot(current, slotId, (slot) => {
      const sourceNode = cloneNode(node);
      return {
        ...slot,
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
      sourceRef: null,
      sourceNode: null,
      draftNode: createTemporaryNode(slot.role),
      sourceEditor: null,
      draftEditorValues: null,
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
      sourceRef: null,
      sourceNode: null,
      draftNode: null,
      sourceEditor: null,
      draftEditorValues: null,
    }))),
    addCompare: (role) => {
      const slot = createEmptySlot(role, "compare");
      setState((current) => {
        const primary = current.groups[role].primary;
        const mirrored = {
          ...slot,
          sourceRef: primary.sourceRef,
          sourceNode: primary.sourceNode ? cloneNode(primary.sourceNode) : null,
          draftNode: primary.draftNode ? cloneNode(primary.draftNode) : null,
          sourceEditor: primary.sourceEditor ? structuredClone(primary.sourceEditor) : null,
          draftEditorValues: primary.draftEditorValues ? structuredClone(primary.draftEditorValues) : null,
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
      for (const role of Object.keys(current.groups) as NodeRole[]) {
        const group = current.groups[role];
        if (group.compares.some((slot) => slot.slotId === slotId)) {
          return {
            ...current,
            groups: { ...current.groups, [role]: {
              ...group,
              compares: group.compares.filter((slot) => slot.slotId !== slotId),
            } },
            editor: current.editor.slotId === slotId
              ? { slotId: null, tab: "form", draftNode: null, baselineNode: null, editValues: null, baselineValues: null }
              : current.editor,
            revision: current.revision + 1,
          };
        }
      }
      return current;
    }),
    openEditor: (slotId, response) => setState((current) => {
      const next = response ? mapSlot(current, slotId, (slot) => {
        const sourceNode = cloneNode(response.node);
        return {
          ...slot,
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
    closeEditor: () => setState((current) => ({
      ...current,
      editor: { slotId: null, tab: "form", draftNode: null, baselineNode: null, editValues: null, baselineValues: null },
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
    setPromptBehavior: (promptBehavior) => setState((current) => ({
      ...current,
      promptBehavior: structuredClone(promptBehavior),
      revision: current.revision + 1,
    })),
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
