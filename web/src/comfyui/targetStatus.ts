import type { ComfyUITarget } from "../api/types";

export type TargetStatusTone = "ok" | "busy" | "idle" | "warn";

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds} 秒`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return rest ? `${minutes} 分 ${rest} 秒` : `${minutes} 分钟`;
}

/** 运行位置的状态文案；elapsedSeconds 是距上次拉取状态过去的秒数，用来让关机倒计时往下走。 */
export function describeTargetStatus(target: ComfyUITarget, elapsedSeconds = 0): string {
  const cloud = target.location === "cloud";
  if (target.active_jobs > 0) return cloud ? "云端生成中（冷启动时先启动再生成）" : `${target.label} 生成中`;
  switch (target.status.state) {
    case "online":
      return `${target.label} 在线`;
    case "offline":
      return cloud ? "云端无法连接" : `${target.label} 未启动`;
    case "running": {
      const remaining = target.status.shutdown_in_seconds;
      if (typeof remaining !== "number") return "云端运行中";
      const left = Math.max(0, remaining - elapsedSeconds);
      return left > 0 ? `云端运行中 · 约 ${formatDuration(left)}后自动关机` : "云端运行中 · 即将自动关机";
    }
    case "stopped":
      return "云端已关机 · 下次生成需先启动（约 1–2 分钟）";
    default:
      return "状态未知";
  }
}

export function targetStatusTone(target: ComfyUITarget): TargetStatusTone {
  if (target.active_jobs > 0) return "busy";
  switch (target.status.state) {
    case "online":
    case "running":
      return "ok";
    case "offline":
      return "warn";
    default:
      return "idle";
  }
}

const TARGETS_CHANGED_EVENT = "promptatelier:comfyui-targets-changed";

/** ComfyUI 任务提交或结束后通知运行位置面板立刻刷新状态，而不是等下一次定时刷新。 */
export function notifyComfyTargetsChanged(renderRequest: Record<string, unknown> | undefined): void {
  if (renderRequest?.backend !== "comfyui") return;
  window.dispatchEvent(new Event(TARGETS_CHANGED_EVENT));
}

export function onComfyTargetsChanged(listener: () => void): () => void {
  window.addEventListener(TARGETS_CHANGED_EVENT, listener);
  return () => window.removeEventListener(TARGETS_CHANGED_EVENT, listener);
}
