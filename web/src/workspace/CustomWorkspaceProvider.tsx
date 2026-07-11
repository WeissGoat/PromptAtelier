import { createContext, type ReactNode, useContext, useEffect, useMemo, useRef, useState } from "react";

import type { ComposePreviewResponse } from "../api/types";
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
import type { CustomWorkspaceState, NodeVariantSlot, RenderWorkspaceParams } from "./types";

type CustomWorkspaceContextValue = {
  state: CustomWorkspaceState;
  storageWarning: string;
  compareRun: CompareRunController;
  findSlot(slotId: string): NodeVariantSlot | null;
  selectNode(slotId: string, ref: string, node: NodeDocument): void;
  createBlank(slotId: string): void;
  updateDraft(slotId: string, node: NodeDocument): void;
  restoreSlot(slotId: string): void;
  clearSlot(slotId: string): void;
  addCompare(role: NodeRole): string;
  removeCompare(slotId: string): void;
  openEditor(slotId: string): void;
  closeEditor(): void;
  setEditorTab(tab: "form" | "json"): void;
  setEditorDraft(node: NodeDocument): void;
  setParams(patch: Partial<RenderWorkspaceParams>): void;
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
    selectNode: (slotId, ref, node) => setState((current) => mapSlot(current, slotId, (slot) => {
      const sourceNode = cloneNode(node);
      return { ...slot, sourceRef: ref, sourceNode, draftNode: cloneNode(sourceNode) };
    })),
    createBlank: (slotId) => setState((current) => mapSlot(current, slotId, (slot) => ({
      ...slot,
      sourceRef: null,
      sourceNode: null,
      draftNode: createTemporaryNode(slot.role),
    }))),
    updateDraft: (slotId, node) => setState((current) => mapSlot(current, slotId, (slot) => ({
      ...slot,
      draftNode: cloneNode(node),
    }))),
    restoreSlot: (slotId) => setState((current) => mapSlot(current, slotId, (slot) => ({
      ...slot,
      draftNode: slot.sourceNode ? cloneNode(slot.sourceNode) : null,
    }))),
    clearSlot: (slotId) => setState((current) => mapSlot(current, slotId, (slot) => ({
      ...slot,
      sourceRef: null,
      sourceNode: null,
      draftNode: null,
    }))),
    addCompare: (role) => {
      const slot = createEmptySlot(role, "compare");
      setState((current) => ({
        ...current,
        groups: { ...current.groups, [role]: {
          ...current.groups[role],
          compares: [...current.groups[role].compares, slot],
        } },
        revision: current.revision + 1,
      }));
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
              ? { slotId: null, tab: "form", draftNode: null, baselineNode: null }
              : current.editor,
            revision: current.revision + 1,
          };
        }
      }
      return current;
    }),
    openEditor: (slotId) => setState((current) => {
      const slot = findSlotInState(current, slotId);
      if (!slot?.draftNode) return current;
      return { ...current, editor: {
        slotId,
        tab: "form",
        draftNode: cloneNode(slot.draftNode),
        baselineNode: cloneNode(slot.draftNode),
      } };
    }),
    closeEditor: () => setState((current) => ({
      ...current,
      editor: { slotId: null, tab: "form", draftNode: null, baselineNode: null },
    })),
    setEditorTab: (tab) => setState((current) => ({ ...current, editor: { ...current.editor, tab } })),
    setEditorDraft: (node) => setState((current) => ({
      ...current,
      editor: { ...current.editor, draftNode: cloneNode(node) },
    })),
    setParams: (patch) => setState((current) => ({
      ...current,
      params: { ...current.params, ...patch },
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
