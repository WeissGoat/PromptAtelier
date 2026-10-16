import type { NodeRole } from "../nodes/types";

/**
 * 多个节点组都按顺序时两两交叉（笛卡尔积），像里程表一样推进：
 * 排在后面的位置变化最快，跑完一轮再进位到前一个位置。
 * 次序是 画风 → 角色 → 服装 → 动作，所以"每套服装把这些动作都跑一遍"。
 */
export const SEQUENTIAL_ROLE_ORDER: NodeRole[] = ["artist", "character", "clothing", "action"];

export type SequentialRun = {
  /** 每一项是各位置在自己（勾选后）列表里的位置，顺序同 totals。 */
  combos: number[][];
  /** 交出去之后各位置的游标；全部跑完时第一个位置等于它的总数，其余为 0。 */
  nextCursors: number[];
  /** 本次第一项在全部组合里的序号（从 0 开始）。 */
  startIndex: number;
  /** 全部组合数。 */
  total: number;
};

function weights(totals: number[]): number[] {
  const result = new Array<number>(totals.length).fill(1);
  for (let index = totals.length - 2; index >= 0; index -= 1) {
    result[index] = result[index + 1] * totals[index + 1];
  }
  return result;
}

/** 各位置的游标折算成组合序号；后面位置的游标超出自己列表时自然进位。 */
export function sequentialIndex(totals: number[], cursors: number[]): number {
  const w = weights(totals);
  return totals.reduce((sum, _, index) => sum + Math.max(0, Math.trunc(cursors[index] ?? 0)) * w[index], 0);
}

/** 组合序号拆回各位置的游标；序号等于总数时第一个位置停在末尾之后。 */
export function sequentialCursors(totals: number[], index: number): number[] {
  const digits = new Array<number>(totals.length).fill(0);
  let rest = index;
  for (let position = totals.length - 1; position > 0; position -= 1) {
    digits[position] = rest % totals[position];
    rest = Math.floor(rest / totals[position]);
  }
  if (totals.length) digits[0] = rest;
  return digits;
}

/**
 * 从当前游标开始规划这次要跑的组合。
 * count 为 null 表示一直跑到最后一组（Run All）；否则最多跑 count 组。
 */
export function planSequentialRun(totals: number[], cursors: number[], count: number | null): SequentialRun {
  if (!totals.length) throw new Error("没有按顺序的节点组。");
  const empty = totals.findIndex((value) => value <= 0);
  if (empty >= 0) throw new Error("按顺序的节点组里没有可用成员。");
  const total = totals.reduce((product, value) => product * value, 1);
  const startIndex = Math.min(sequentialIndex(totals, cursors), total);
  if (startIndex >= total) throw new Error("顺序节点组已经跑到末尾，请先重置位置。");
  const size = count === null ? total - startIndex : Math.min(Math.max(1, Math.trunc(count)), total - startIndex);
  const combos = Array.from({ length: size }, (_, offset) => sequentialCursors(totals, startIndex + offset));
  return { combos, nextCursors: sequentialCursors(totals, startIndex + size), startIndex, total };
}
