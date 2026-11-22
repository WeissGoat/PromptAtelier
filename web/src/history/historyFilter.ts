import type { HistoryNodeFilter } from "../api/types";

export type OpenHistoryForNode = (node: HistoryNodeFilter) => void;

export const HISTORY_ROLE_LABELS: Record<string, string> = {
  artist: "画风",
  character: "角色",
  action: "动作",
  clothing: "服装",
  background: "背景",
};

export function normalizeNodeRef(value: string | null | undefined): string {
  return (value ?? "").trim().replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
}

export function nodeFilterKey(filter: HistoryNodeFilter): string {
  const role = filter.role.trim().toLowerCase();
  const refNorm = normalizeNodeRef(filter.ref);
  const name = filter.name.trim().toLowerCase();
  return `${role}\u0000${refNorm || name}`;
}

export function sameNodeFilter(left: HistoryNodeFilter, right: HistoryNodeFilter): boolean {
  const leftRole = left.role.trim().toLowerCase();
  const rightRole = right.role.trim().toLowerCase();
  if (leftRole !== rightRole) return false;
  const leftRef = normalizeNodeRef(left.ref);
  const rightRef = normalizeNodeRef(right.ref);
  if (leftRef && rightRef) return leftRef === rightRef;
  return left.name.trim().toLowerCase() === right.name.trim().toLowerCase();
}

export function buildHistoryHash(nodes: HistoryNodeFilter[]): string {
  if (!nodes.length) return "#/results";
  const compact = nodes.map((node) => ({
    role: node.role.trim().toLowerCase(),
    name: node.name.trim(),
    ...(node.ref?.trim() ? { ref: node.ref.trim() } : {}),
  }));
  const params = new URLSearchParams({ nodes: JSON.stringify(compact) });
  return `#/results?${params.toString()}`;
}

export function parseHistoryHashNodes(hash: string): HistoryNodeFilter[] {
  const queryIndex = hash.indexOf("?");
  if (queryIndex < 0) return [];
  const params = new URLSearchParams(hash.slice(queryIndex + 1));
  const raw = params.get("nodes");
  if (raw) {
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        return parsed
          .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
          .map((item) => ({
            role: String(item.role ?? "").trim().toLowerCase(),
            name: String(item.name ?? "").trim(),
            ref: typeof item.ref === "string" && item.ref.trim() ? item.ref.trim() : null,
          }))
          .filter((item) => Boolean(item.name || item.ref));
      }
    } catch {
      return [];
    }
  }
  const role = (params.get("node_role") ?? "").trim().toLowerCase();
  const name = (params.get("node_name") ?? "").trim();
  const ref = (params.get("node_ref") ?? "").trim() || null;
  if (name || ref) return [{ role, name, ref }];
  return [];
}
