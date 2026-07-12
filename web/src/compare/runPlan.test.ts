import { describe, expect, it, vi } from "vitest";

import type { CompareCombination } from "./matrix";
import { buildCompareRunPlan, compareRunCount } from "./runPlan";

const matrix = [
  { combinationId: "a", artist: null, character: null, action: null },
  { combinationId: "b", artist: null, character: null, action: null },
] satisfies CompareCombination[];

describe("buildCompareRunPlan", () => {
  it("expands complete matrix groups in group-first order with explicit seeds", () => {
    const plan = buildCompareRunPlan(matrix, { nt: 3, seed: "42", randomSeed: vi.fn() });

    expect(plan.groups.map((group) => group.seed)).toEqual([42, 43, 44]);
    expect(plan.items.map((item) => item.runId)).toEqual([
      "group-001::a",
      "group-001::b",
      "group-002::a",
      "group-002::b",
      "group-003::a",
      "group-003::b",
    ]);
  });

  it("creates a distinct random seed for every group", () => {
    const randomSeed = vi.fn()
      .mockReturnValueOnce(100)
      .mockReturnValueOnce(100)
      .mockReturnValueOnce(200);
    const plan = buildCompareRunPlan(matrix, { nt: 3, seed: "-1", randomSeed });

    expect(plan.groups.map((group) => group.seed)).toEqual([100, 101, 200]);
    expect(randomSeed).toHaveBeenCalledTimes(3);
  });

  it.each([0, -1, 1.5, Number.NaN])("rejects invalid nt %s", (nt) => {
    expect(() => buildCompareRunPlan(matrix, { nt, seed: "-1", randomSeed: () => 1 }))
      .toThrow("Compare NT 必须是大于等于 1 的整数");
  });

  it("calculates the total number of run items", () => {
    expect(compareRunCount(12, 4)).toBe(48);
    expect(compareRunCount(12, 0)).toBe(0);
  });
});
