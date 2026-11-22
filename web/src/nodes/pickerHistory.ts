import type { NodeSummary } from "../api/types";

export const NODE_PICKER_HISTORY_STORAGE_KEY = "promptatelier.node-picker-history/v1";
const NODE_PICKER_HISTORY_SCHEMA = "promptatelier.node-picker-history/v1";
const MAX_HISTORY_PER_ROLE = 50;

type StoredNodePickerHistory = {
  schema: typeof NODE_PICKER_HISTORY_SCHEMA;
  byRole: Record<string, NodeSummary[]>;
};

function resolveStorage(storage?: Storage | null): Storage | null {
  if (storage !== undefined) return storage;
  try {
    return typeof window !== "undefined" ? window.localStorage ?? null : null;
  } catch {
    return null;
  }
}

function sanitizeNode(value: unknown, fallbackRole: string): NodeSummary | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const raw = value as Record<string, unknown>;
  const name = typeof raw.name === "string" ? raw.name.trim() : "";
  const ref = typeof raw.ref === "string" ? raw.ref.trim() : "";
  if (!name || !ref) return null;
  const node: NodeSummary = {
    role: typeof raw.role === "string" && raw.role.trim() ? raw.role : fallbackRole,
    name,
    ref,
  };
  if (typeof raw.relative === "string") node.relative = raw.relative;
  if (Array.isArray(raw.backends)) {
    node.backends = raw.backends.filter((item): item is string => typeof item === "string");
  }
  if (typeof raw.has_preview === "boolean") node.has_preview = raw.has_preview;
  if (typeof raw.updated_at === "number" && Number.isFinite(raw.updated_at)) {
    node.updated_at = raw.updated_at;
  }
  return node;
}

function readStore(storage: Storage | null): StoredNodePickerHistory {
  const empty: StoredNodePickerHistory = { schema: NODE_PICKER_HISTORY_SCHEMA, byRole: {} };
  if (!storage) return empty;
  try {
    const raw = storage.getItem(NODE_PICKER_HISTORY_STORAGE_KEY);
    if (!raw) return empty;
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return empty;
    const record = parsed as Record<string, unknown>;
    if (record.schema !== NODE_PICKER_HISTORY_SCHEMA || !record.byRole || typeof record.byRole !== "object" || Array.isArray(record.byRole)) {
      return empty;
    }
    const byRole: Record<string, NodeSummary[]> = {};
    for (const [role, entries] of Object.entries(record.byRole as Record<string, unknown>)) {
      if (!Array.isArray(entries)) continue;
      const seen = new Set<string>();
      const cleaned: NodeSummary[] = [];
      for (const item of entries) {
        const node = sanitizeNode(item, role);
        if (!node || seen.has(node.ref)) continue;
        seen.add(node.ref);
        cleaned.push(node);
        if (cleaned.length >= MAX_HISTORY_PER_ROLE) break;
      }
      if (cleaned.length > 0) byRole[role] = cleaned;
    }
    return { schema: NODE_PICKER_HISTORY_SCHEMA, byRole };
  } catch {
    return empty;
  }
}

function writeStore(storage: Storage | null, store: StoredNodePickerHistory): void {
  if (!storage) return;
  try {
    storage.setItem(NODE_PICKER_HISTORY_STORAGE_KEY, JSON.stringify(store));
  } catch {
    // 隐私模式或配额不足时静默降级，不影响选择节点。
  }
}

export function loadNodePickerHistory(role: string, storage?: Storage | null): NodeSummary[] {
  const store = readStore(resolveStorage(storage));
  return store.byRole[role] ?? [];
}

export function recordNodePickerSelection(role: string, node: NodeSummary, storage?: Storage | null): NodeSummary[] {
  const clean = sanitizeNode(node, role);
  const targetStorage = resolveStorage(storage);
  const store = readStore(targetStorage);
  const current = store.byRole[role] ?? [];
  if (!clean) return current;
  const next = [clean, ...current.filter((item) => item.ref !== clean.ref)].slice(0, MAX_HISTORY_PER_ROLE);
  store.byRole[role] = next;
  writeStore(targetStorage, store);
  return next;
}

export function filterNodePickerHistory(history: NodeSummary[], query: string): NodeSummary[] {
  const needles = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (needles.length === 0) return history;
  return history.filter((node) => {
    const searchable = `${node.name} ${node.relative ?? ""}`.toLowerCase();
    return needles.every((needle) => searchable.includes(needle));
  });
}

export function mergeHistoryAndResults(history: NodeSummary[], results: NodeSummary[]): NodeSummary[] {
  if (history.length === 0) return results;
  const resultByRef = new Map(results.map((node) => [node.ref, node]));
  const historyRefs = new Set<string>();
  const pinned: NodeSummary[] = [];
  for (const item of history) {
    if (historyRefs.has(item.ref)) continue;
    historyRefs.add(item.ref);
    pinned.push(resultByRef.get(item.ref) ?? item);
  }
  const rest = results.filter((node) => !historyRefs.has(node.ref));
  return [...pinned, ...rest];
}
