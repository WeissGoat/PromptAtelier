import type { JobEvent, JobRecord } from "../api/types";

const PHASE_EVENTS = new Set(["comfyui_starting", "comfyui_ready", "comfyui_queued", "comfyui_downloading"]);
// 就绪前等了这么久，说明 ComfyUI 刚冷启动，接下来的第一张还要加载模型。
const COLD_START_SECONDS = 5;

function numberField(event: JobEvent, key: string): number | null {
  const value = event[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds} 秒`;
  return `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
}

/**
 * 进行中的 ComfyUI 任务停在哪一步：启动 ComfyUI、生成、下载图片。
 * nowSeconds 是当前 Unix 时间（秒），用来算这一步已经等了多久；不是进行中的 ComfyUI 任务时返回 null。
 */
export function describeJobProgress(job: JobRecord, nowSeconds: number): string | null {
  if (job.status !== "running") return null;
  const phases = (job.events ?? []).filter((event) => PHASE_EVENTS.has(event.type));
  const last = phases[phases.length - 1];
  if (!last) return null;

  const sampleIndex = numberField(last, "sample_index");
  const sampleCount = numberField(last, "sample_count");
  const prefix = sampleIndex !== null && sampleCount !== null && sampleCount > 1
    ? `第 ${sampleIndex + 1}/${sampleCount} 张 · `
    : "";
  const at = numberField(last, "at");
  const elapsed = at === null ? "" : ` · 已 ${formatElapsed(Math.max(0, Math.round(nowSeconds - at)))}`;

  switch (last.type) {
    case "comfyui_starting":
      return `${prefix}正在启动 ComfyUI${elapsed}`;
    case "comfyui_ready":
      return `${prefix}ComfyUI 已就绪，正在提交`;
    case "comfyui_queued": {
      const previous = phases[phases.length - 2];
      const waited = previous?.type === "comfyui_ready" ? numberField(previous, "waited_seconds") : null;
      const coldStart = waited !== null && waited >= COLD_START_SECONDS;
      return `${prefix}${coldStart ? "生成中（刚启动，首张要先加载模型）" : "生成中"}${elapsed}`;
    }
    default:
      return `${prefix}正在下载图片`;
  }
}
