import { useMemo, useReducer } from "react";
import {
  cloneNode,
  createTemporaryNode,
  serializeNodeSlot,
} from "./temporaryNodes";
import type {
  ComposeNodeInput,
  GroupRole,
  NodeDocument,
  NodeRole,
  NodeSlotState,
} from "./types";

const NODE_ROLES: GroupRole[] = ["artist", "character", "action"];

type State = {
  slots: Record<GroupRole, NodeSlotState>;
  revision: number;
};

type Action =
  | { type: "replace"; slot: NodeSlotState }
  | { type: "clear"; role: GroupRole };

function emptySlots(): Record<GroupRole, NodeSlotState> {
  return {
    artist: { role: "artist", sourceRef: null, sourceNode: null, draftNode: null },
    character: { role: "character", sourceRef: null, sourceNode: null, draftNode: null },
    action: { role: "action", sourceRef: null, sourceNode: null, draftNode: null },
  };
}

function sortKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, entry]) => [key, sortKeys(entry)]),
    );
  }
  return value;
}

function sameValue(left: unknown, right: unknown): boolean {
  return JSON.stringify(sortKeys(left)) === JSON.stringify(sortKeys(right));
}

function reduceState(state: State, action: Action): State {
  const nextSlot = action.type === "clear"
    ? { role: action.role, sourceRef: null, sourceNode: null, draftNode: null }
    : action.slot;
  const previousSlot = state.slots[nextSlot.role as GroupRole];
  if (sameValue(previousSlot, nextSlot)) return state;
  return {
    slots: { ...state.slots, [nextSlot.role as GroupRole]: nextSlot },
    revision: state.revision + 1,
  };
}

export function useTemporaryNodes(): {
  slots: Record<GroupRole, NodeSlotState>;
  selectNode(role: GroupRole, ref: string, node: NodeDocument): void;
  createBlank(role: GroupRole): void;
  updateDraft(role: GroupRole, node: NodeDocument): void;
  restore(role: GroupRole): void;
  clear(role: GroupRole): void;
  composeNodes: ComposeNodeInput[];
  revision: number;
} {
  const [{ slots, revision }, dispatch] = useReducer(reduceState, {
    slots: emptySlots(),
    revision: 0,
  });

  const selectNode = (role: GroupRole, ref: string, node: NodeDocument): void => {
    const sourceNode = cloneNode(node);
    dispatch({ type: "replace", slot: { role, sourceRef: ref, sourceNode, draftNode: cloneNode(sourceNode) } });
  };

  const createBlank = (role: GroupRole): void => {
    dispatch({ type: "replace", slot: {
      role,
      sourceRef: null,
      sourceNode: null,
      draftNode: createTemporaryNode(role),
    } });
  };

  const updateDraft = (role: GroupRole, node: NodeDocument): void => {
    const current = slots[role];
    dispatch({ type: "replace", slot: { ...current, draftNode: cloneNode(node) } });
  };

  const restore = (role: GroupRole): void => {
    const current = slots[role];
    dispatch({ type: "replace", slot: {
      ...current,
      draftNode: current.sourceNode ? cloneNode(current.sourceNode) : null,
    } });
  };

  const clear = (role: GroupRole): void => {
    dispatch({ type: "clear", role });
  };

  const composeNodes = useMemo(
    () => NODE_ROLES.flatMap((role) => {
      const serialized = serializeNodeSlot(slots[role]);
      return serialized ? [serialized] : [];
    }),
    [slots],
  );

  return { slots, selectNode, createBlank, updateDraft, restore, clear, composeNodes, revision };
}
