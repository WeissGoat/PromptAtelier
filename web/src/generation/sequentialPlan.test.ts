import { describe, expect, it } from "vitest";

import { planSequentialRun, sequentialCursors, sequentialIndex } from "./sequentialPlan";

describe("sequential plan", () => {
  it("behaves like the old single action cursor", () => {
    const next = planSequentialRun([5], [2], 2);
    expect(next.combos).toEqual([[2], [3]]);
    expect(next.nextCursors).toEqual([4]);
    const all = planSequentialRun([5], [2], null);
    expect(all.combos).toEqual([[2], [3], [4]]);
    expect(all.nextCursors).toEqual([5]);
    expect(() => planSequentialRun([5], [5], 1)).toThrow("跑到末尾");
  });

  it("crosses several groups like an odometer, last group fastest", () => {
    // 服装 2 套 × 动作 3 个，从第 1 套的第 2 个动作开始。
    const run = planSequentialRun([2, 3], [0, 1], null);
    expect(run.total).toBe(6);
    expect(run.startIndex).toBe(1);
    expect(run.combos).toEqual([[0, 1], [0, 2], [1, 0], [1, 1], [1, 2]]);
    expect(run.nextCursors).toEqual([2, 0]);

    const step = planSequentialRun([2, 3], [0, 2], 2);
    expect(step.combos).toEqual([[0, 2], [1, 0]]);
    expect(step.nextCursors).toEqual([1, 1]);
  });

  it("carries an inner cursor that ran past its own group", () => {
    // 动作之前单独跑完停在 3，再加上服装一起按顺序：等于第 2 套的第 1 个动作。
    expect(sequentialIndex([2, 3], [0, 3])).toBe(3);
    expect(planSequentialRun([2, 3], [0, 3], 1).combos).toEqual([[1, 0]]);
    expect(sequentialCursors([2, 3], 6)).toEqual([2, 0]);
    expect(() => planSequentialRun([2, 0], [0, 0], 1)).toThrow("没有可用成员");
  });
});
