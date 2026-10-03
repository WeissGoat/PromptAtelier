import { describe, expect, it } from "vitest";

import type { ComfyUITarget } from "../api/types";
import { describeTargetStatus, targetStatusTone } from "./targetStatus";

function target(overrides: Partial<ComfyUITarget>): ComfyUITarget {
  return {
    name: "modal",
    label: "Modal 云端",
    location: "cloud",
    base_url: "https://example.modal.run",
    status: { state: "unknown" },
    active_jobs: 0,
    last_used_at: null,
    ...overrides,
  };
}

describe("ComfyUI target status", () => {
  it("counts down to the cloud idle shutdown", () => {
    const running = target({ status: { state: "running", shutdown_in_seconds: 130 } });

    expect(describeTargetStatus(running)).toBe("云端运行中 · 约 2 分 10 秒后自动关机");
    expect(describeTargetStatus(running, 100)).toBe("云端运行中 · 约 30 秒后自动关机");
    expect(describeTargetStatus(running, 200)).toBe("云端运行中 · 即将自动关机");
    expect(targetStatusTone(running)).toBe("ok");
  });

  it("explains stopped, busy and unknown cloud states", () => {
    expect(describeTargetStatus(target({ status: { state: "stopped" } }))).toBe("云端已关机 · 下次生成需先启动（约 1–2 分钟）");
    expect(describeTargetStatus(target({ status: { state: "running" } }))).toBe("云端运行中");
    expect(describeTargetStatus(target({ active_jobs: 1, status: { state: "stopped" } }))).toBe("云端生成中（冷启动时先启动再生成）");
    expect(targetStatusTone(target({ active_jobs: 1 }))).toBe("busy");
    expect(describeTargetStatus(target({}))).toBe("状态未知");
  });

  it("describes the local ComfyUI by its label", () => {
    const local = target({ name: "local", label: "本机 aki", location: "local" });

    expect(describeTargetStatus({ ...local, status: { state: "online" } })).toBe("本机 aki 在线");
    expect(describeTargetStatus({ ...local, status: { state: "offline" } })).toBe("本机 aki 未启动");
    expect(targetStatusTone({ ...local, status: { state: "offline" } })).toBe("warn");
  });
});
