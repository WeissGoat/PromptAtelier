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
  randomScope?: string;
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

export function hasSequentialSlot(slots: ResolvedSlotSet): boolean {
  return (Object.keys(slots) as NodeRole[]).some(
    (role) => slots[role]?.sourceKind === "random" && slots[role]?.randomSpec?.drawMode === "sequential",
  );
}

export function isSequentialSlot(slot: NodeVariantSlot | null | undefined): boolean {
  return isRandomSlot(slot) && slot.randomSpec?.drawMode === "sequential";
}

/** 勾选记录为空数组表示一个都没选；后端把空勾选当整组，所以前端先拦下。 */
export function assertGroupHasSelection(slot: NodeVariantSlot): void {
  if (slot.randomSpec?.selection && slot.randomSpec.selection.refs.length === 0) {
    throw new Error("节点组一个成员都没勾选，请至少勾选一个，或点“恢复整组”。");
  }
}

export async function resolveRandomItems<T>(items: Array<SlotSetItem<T>>): Promise<Array<ResolvedRandomItem<T>>> {
  const occurrences = new Map<string, {
    slot: NodeVariantSlot & { randomSpec: NodePoolSpec };
    selectionKeys: string[];
    seenSelectionKeys: Set<string>;
  }>();
  for (const [itemIndex, item] of items.entries()) {
    for (const role of Object.keys(item.slots) as NodeRole[]) {
      const slot = item.slots[role];
      if (!isRandomSlot(slot)) continue;
      assertGroupHasSelection(slot);
      const selectionKey = randomSelectionKey(item, itemIndex, slot.slotId);
      const current = occurrences.get(slot.slotId) ?? {
        slot,
        selectionKeys: [],
        seenSelectionKeys: new Set<string>(),
      };
      if (!current.seenSelectionKeys.has(selectionKey)) {
        current.selectionKeys.push(selectionKey);
        current.seenSelectionKeys.add(selectionKey);
      }
      occurrences.set(slot.slotId, current);
    }
  }

  const draws = new Map<string, { draw: SampledNode; stats: NodePoolStats }>();
  await Promise.all([...occurrences.values()].map(async (entry) => {
    const response = await sampleNodePool(entry.slot.role, entry.slot.randomSpec, entry.selectionKeys.length);
    entry.selectionKeys.forEach((selectionKey, index) => {
      const draw = response.items[index];
      if (draw) draws.set(selectionKey, { draw, stats: response.stats });
    });
  }));

  return items.map((item, itemIndex) => {
    const slots = { ...item.slots };
    const randomSelections: RandomSelectionRecord[] = [];
    for (const role of Object.keys(slots) as NodeRole[]) {
      const slot = slots[role];
      if (!isRandomSlot(slot)) continue;
      const resolved = draws.get(randomSelectionKey(item, itemIndex, slot.slotId));
      if (!resolved) throw new Error(`随机节点抽取数量不足：${slot.slotId}`);
      const { draw, stats } = resolved;
      slots[role] = resolvedSlot(slot, draw.node, draw.candidate.ref);
      randomSelections.push({
        slot_id: slot.slotId,
        role,
        source: structuredClone(slot.randomSpec.source),
        filters: structuredClone(slot.randomSpec.filters),
        candidate: structuredClone(draw.candidate),
        draw_index: draw.draw_index,
        deck_cycle: draw.deck_cycle,
        pool_stats: structuredClone(stats),
      });
    }
    return { value: item.value, slots, randomScope: item.randomScope, randomSelections };
  });
}

function randomSelectionKey<T>(item: SlotSetItem<T>, itemIndex: number, slotId: string): string {
  const scope = item.randomScope?.trim();
  return scope ? `${scope}\u0000${slotId}` : `${itemIndex}\u0000${slotId}`;
}

/**
 * 抽到的成员变成一个普通槽位；成员有临时修改时用修改后的节点出图（按临时节点内联发给后端）。
 * 顺序模式也走这里，保证随机和顺序对同一成员的修改效果一致。
 */
export function resolvedSlot(slot: NodeVariantSlot, node: NodeDocument, ref: string): NodeVariantSlot {
  const draft = slot.memberDrafts?.[ref];
  return {
    ...slot,
    sourceKind: "fixed",
    randomSpec: null,
    sourceRef: ref,
    sourceNode: structuredClone(node),
    draftNode: structuredClone(draft ? draft.draftNode : node),
    sourceEditor: null,
    draftEditorValues: null,
    memberDrafts: undefined,
  };
}

/** 浏览成员时要看到整组（含没勾选的），所以去掉勾选条件再扫描。 */
export function withoutSelection(spec: NodePoolSpec): NodePoolSpec {
  const { selection: _selection, ...rest } = spec;
  return rest;
}

export function selectedRefs(spec: NodePoolSpec | null | undefined): string[] {
  return spec?.selection?.refs ?? [];
}
