import type {
  ComposeNodeInput,
  NodeDocument,
  NodeRole,
  NodeSlotState,
  NodeSlotStatus,
} from "./types";

const NODE_SCHEMA = "tags-machine-core.node/v1" as const;

export function cloneNode(node: NodeDocument): NodeDocument {
  return structuredClone(node);
}

export function createTemporaryNode(
  role: NodeRole,
  id = `temporary-${role}`,
): NodeDocument {
  return {
    schema: NODE_SCHEMA,
    kind: role,
    id,
    prompt: {
      positive: [],
      negative: [],
    },
  };
}

function sortKeys(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(sortKeys);
  }
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, entry]) => [key, sortKeys(entry)]),
    );
  }
  return value;
}

function sameNode(left: NodeDocument, right: NodeDocument): boolean {
  return JSON.stringify(sortKeys(left)) === JSON.stringify(sortKeys(right));
}

export function nodeSlotStatus(slot: NodeSlotState): NodeSlotStatus {
  if (!slot.draftNode) {
    return "empty";
  }
  if (!slot.sourceNode || !slot.sourceRef) {
    return "temporary";
  }
  return sameNode(slot.sourceNode, slot.draftNode) ? "original" : "modified";
}

export function hasUsablePositivePrompt(node: NodeDocument | null): boolean {
  return Boolean(node?.prompt.positive.some((fragment) => fragment.text.trim()));
}

export function serializeNodeSlot(slot: NodeSlotState): ComposeNodeInput | null {
  if (!slot.draftNode) {
    return null;
  }

  const status = nodeSlotStatus(slot);
  if (status === "original" && slot.sourceRef) {
    return { role: slot.role, ref: slot.sourceRef };
  }

  return {
    role: slot.role,
    ref: slot.sourceRef ?? `web-temporary:${slot.role}:${slot.draftNode.id}`,
    node: cloneNode(slot.draftNode),
  };
}
