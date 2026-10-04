import { describe, expect, it } from "vitest";

import type { JobEvent, JobRecord } from "../api/types";
import { describeJobProgress } from "./jobProgress";

function job(events: JobEvent[], status: JobRecord["status"] = "running"): JobRecord {
  return { id: "job-1", name: "generate", status, events: [{ type: "started" }, ...events] };
}

describe("describeJobProgress", () => {
  it("follows the ComfyUI phases with the time spent in the current one", () => {
    expect(describeJobProgress(job([{ type: "comfyui_starting", at: 100 }]), 112.4)).toBe("正在启动 ComfyUI · 已 12 秒");
    expect(describeJobProgress(job([{ type: "comfyui_ready", at: 125, waited_seconds: 25 }]), 125)).toBe("ComfyUI 已就绪，正在提交");
    expect(describeJobProgress(job([{ type: "comfyui_queued", at: 200 }]), 275)).toBe("生成中 · 已 1 分 15 秒");
    expect(describeJobProgress(job([{ type: "comfyui_queued", at: 200 }, { type: "comfyui_downloading", at: 230 }]), 231))
      .toBe("正在下载图片");
  });

  it("warns that the first image after a cold start also loads the model", () => {
    const cold = job([
      { type: "comfyui_starting", at: 100 },
      { type: "comfyui_ready", at: 124, waited_seconds: 24 },
      { type: "comfyui_queued", at: 125 },
    ]);
    const warm = job([
      { type: "comfyui_starting", at: 100 },
      { type: "comfyui_ready", at: 100.3, waited_seconds: 0.3 },
      { type: "comfyui_queued", at: 101 },
    ]);

    expect(describeJobProgress(cold, 135)).toBe("生成中（刚启动，首张要先加载模型） · 已 10 秒");
    expect(describeJobProgress(warm, 111)).toBe("生成中 · 已 10 秒");
  });

  it("numbers the samples of a split ComfyUI job", () => {
    const record = job([
      { type: "comfyui_queued", at: 10, sample_index: 0, sample_count: 3 },
      { type: "comfyui_downloading", at: 40, sample_index: 0, sample_count: 3 },
      { type: "comfyui_queued", at: 41, sample_index: 1, sample_count: 3 },
    ]);

    expect(describeJobProgress(record, 46)).toBe("第 2/3 张 · 生成中 · 已 5 秒");
  });

  it("stays quiet for finished jobs and jobs without ComfyUI phases", () => {
    expect(describeJobProgress(job([{ type: "comfyui_queued", at: 1 }], "succeeded"), 5)).toBeNull();
    expect(describeJobProgress(job([{ type: "generation_started" }]), 5)).toBeNull();
    expect(describeJobProgress({ id: "job-2", name: "generate", status: "running" }, 5)).toBeNull();
  });
});
