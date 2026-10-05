/** 出图耗时：后端写在每张图的 meta 和 PNG 的 tags_machine_core.timing 里，单位秒。 */
export type ImageTiming = {
  /** 从提交到拿回图片的总时间（含排队、云端冷启动、下载）。 */
  elapsed_seconds?: number;
  /** ComfyUI 实际执行的时间，取自 history；其他后端没有。 */
  execution_seconds?: number;
};

// 总时间比实际执行多出这么多秒才单独标出来（排队、冷启动）。
const WAIT_NOTE_THRESHOLD_SECONDS = 5;

function seconds(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : undefined;
}

export function formatDuration(value: number): string {
  if (value < 60) return `${value.toFixed(1)} 秒`;
  const total = Math.round(value);
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return rest ? `${minutes} 分 ${rest} 秒` : `${minutes} 分`;
}

/** 有实际执行时间时以它为主；总时间明显更长时在括号里补上。没有耗时记录返回 null。 */
export function formatImageTiming(timing: ImageTiming | Record<string, unknown> | null | undefined): string | null {
  if (!timing) return null;
  const elapsed = seconds(timing.elapsed_seconds);
  const execution = seconds(timing.execution_seconds);
  if (execution === undefined) return elapsed === undefined ? null : formatDuration(elapsed);
  if (elapsed !== undefined && elapsed - execution >= WAIT_NOTE_THRESHOLD_SECONDS) {
    return `${formatDuration(execution)}（含等待共 ${formatDuration(elapsed)}）`;
  }
  return formatDuration(execution);
}
