import type { NodePoolStats, SampledNode } from "../api/types";
import type { NodeDocument, NodeRole } from "../nodes/types";
import type { NodePoolSpec, NodeVariantSlot } from "../workspace/types";
import { sampleNodePool } from "./api";

export type RandomSelectionRecord = {
  slot_id: string;
  role: NodeRole;
  source: NodePoolSpec["source"];
  filters: NodePoolSpec["filters"];
  candidate: SampledNode["candidate"];
  draw_index: number;
  deck_cycle: number;
  pool_stats: NodePoolStats;
};

export type ResolvedSlotSet = Record<NodeRole, NodeVariantSlot | null>;

type SlotSetItem<T> = {
  value: T;
  slots: ResolvedSlotSet;
};

export type ResolvedRandomItem<T> = SlotSetItem<T> & {
  randomSelections: RandomSelectionRecord[];
};

export function isRandomSlot(slot: NodeVariantSlot | null | undefined): slot is NodeVariantSlot & { randomSpec: NodePoolSpec } {
  return Boolean(slot?.sourceKind === "random" && slot.randomSpec?.source.value.trim());
}

export function hasRandomSlots(slots: ResolvedSlotSet): boolean {
  return (Object.keys(slots) as NodeRole[]).some((role) => slots[role]?.sourceKind === "random");
}

export async function resolveRandomItems<T>(items: Array<SlotSetItem<T>>): Promise<Array<ResolvedRandomItem<T>>> {
  const occurrences = new Map<string, { slot: NodeVariantSlot & { randomSpec: NodePoolSpec }; count: number }>();
  for (const item of items) {
    for (const role of Object.keys(item.slots) as NodeRole[]) {
      const slot = item.slots[role];
      if (!isRandomSlot(slot)) continue;
      const current = occurrences.get(slot.slotId);
      occurrences.set(slot.slotId, { slot, count: (current?.count ?? 0) + 1 });
    }
  }

  const draws = new Map<string, { items: SampledNode[]; stats: NodePoolStats; index: number }>();
  await Promise.all([...occurrences.entries()].map(async ([slotId, entry]) => {
    const response = await sampleNodePool(entry.slot.role, entry.slot.randomSpec, entry.count);
    draws.set(slotId, { items: response.items, stats: response.stats, index: 0 });
  }));

  return items.map((item) => {
    const slots = { ...item.slots };
    const randomSelections: RandomSelectionRecord[] = [];
    for (const role of Object.keys(slots) as NodeRole[]) {
      const slot = slots[role];
      if (!isRandomSlot(slot)) continue;
      const queue = draws.get(slot.slotId);
      const draw = queue?.items[queue.index++];
      if (!queue || !draw) throw new Error(`随机节点抽取数量不足：${slot.slotId}`);
      slots[role] = resolvedSlot(slot, draw.node, draw.candidate.ref);
      randomSelections.push({
        slot_id: slot.slotId,
        role,
        source: structuredClone(slot.randomSpec.source),
        filters: structuredClone(slot.randomSpec.filters),
        candidate: structuredClone(draw.candidate),
        draw_index: draw.draw_index,
        deck_cycle: draw.deck_cycle,
        pool_stats: structuredClone(queue.stats),
      });
    }
    return { value: item.value, slots, randomSelections };
  });
}

function resolvedSlot(slot: NodeVariantSlot, node: NodeDocument, ref: string): NodeVariantSlot {
  return {
    ...slot,
    sourceKind: "fixed",
    randomSpec: null,
    sourceRef: ref,
    sourceNode: structuredClone(node),
    draftNode: structuredClone(node),
    sourceEditor: null,
    draftEditorValues: null,
  };
}
