import { describe, expect, it } from "vitest";

import type { StyleLabRun } from "./api";
import { describeSettings } from "./RunPanel";

function run(settings: unknown, extra: Partial<StyleLabRun> = {}): StyleLabRun {
  return {
    id: "r",
    kind: "regenerate",
    status: "succeeded",
    created_at: 0,
    finished_at: 0,
    job_id: null,
    source: null,
    settings: settings as StyleLabRun["settings"],
    expected_diff_keys: [],
    warnings: [],
    items: [
      { index: 0, seed: 1, status: "succeeded" },
      { index: 1, seed: 1, status: "succeeded" },
    ] as StyleLabRun["items"],
    ...extra,
  };
}

describe("run settings summary", () => {
  it("describes regenerate runs", () => {
    const text = describeSettings(
      run({ count: 2, seed_mode: "source", size_mode: "custom", width: 832, height: 1216, overrides: { steps: 28 } }),
    );
    expect(text).toBe("2 张 · 原图种子 · 832×1216 · 覆盖 steps");
  });

  it("does not crash on probe runs, whose settings have no count or overrides", () => {
    const recipe = { id: "x", version: 3, name: "配方" };
    expect(describeSettings(run({ kind: "swap", characters: [{}], seed_mode: "source" }, { recipe }))).toBe(
      "配方 v3 · 替换角色 1 个 · 2 张 · 原图种子",
    );
    expect(describeSettings(run({ kind: "ablation", units: [{}, {}, {}], seed_mode: "fixed", seed: 7 }, { recipe }))).toBe(
      "配方 v3 · 消融 3 组 · 2 张 · 种子 7",
    );
    expect(describeSettings(run(null))).toBe("2 张");
  });
});
