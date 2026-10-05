import { apiPost } from "../api/client";
import type { GenerationImage, JobRecord } from "../api/types";
import type { RandomSelectionRecord } from "../randomNodes/resolve";
import type { ComposeRenderRequest } from "../workspace/requestBuilder";
import type { RenderWorkspaceParams } from "../workspace/types";

/** 后台批量任务在 /api/jobs 里的名字（对应后端 /generate/batch）。 */
export const BACKGROUND_BATCH_JOB = "generate-batch";
export const BACKGROUND_RUNS_CHANGED = "promptatelier:background-runs-changed";
const PREFERENCE_KEY = "promptatelier.background-run/v1";

export type BackgroundItemStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export type BackgroundRequestItem = {
  label: string;
  group?: number;
  seed?: number;
  labels?: Record<string, string>;
  compose_request: ComposeRenderRequest;
  generate: {
    output_dir?: string;
    comfyui_target?: string;
    random_selections?: RandomSelectionRecord[];
  };
};

export type BackgroundBatchRequest = {
  label: string;
  kind: "primary" | "random" | "sequential" | "compare";
  output_dir?: string;
  items: BackgroundRequestItem[];
};

export type BackgroundBatchItem = {
  index: number;
  label?: string;
  group?: number;
  seed?: number;
  labels?: Record<string, string>;
  status: BackgroundItemStatus;
  images: GenerationImage[];
  error: string | null;
  started_at?: number;
  finished_at?: number;
};

export type BackgroundBatchResult = {
  label: string;
  kind: string;
  output_dir?: string | null;
  total: number;
  counts: Record<BackgroundItemStatus, number>;
  items: BackgroundBatchItem[];
};

export type BackgroundBatchJob = Omit<JobRecord, "result"> & { result?: BackgroundBatchResult | null };

export function loadBackgroundPreference(): boolean {
  try {
    return window.localStorage.getItem(PREFERENCE_KEY) === "1";
  } catch {
    return false;
  }
}

export function saveBackgroundPreference(enabled: boolean): void {
  try {
    window.localStorage.setItem(PREFERENCE_KEY, enabled ? "1" : "0");
  } catch {
    // 浏览器禁用存储时只在当前页面生效。
  }
}

/** 每一项出图时附带的选项；运行位置只对 ComfyUI 画风生效，后端按实际 backend 决定用不用。 */
export function backgroundGenerateOptions(
  params: RenderWorkspaceParams,
  extra: Omit<BackgroundRequestItem["generate"], "comfyui_target"> = {},
): BackgroundRequestItem["generate"] {
  return params.comfyuiTarget ? { ...extra, comfyui_target: params.comfyuiTarget } : { ...extra };
}

export function randomSelectionLabel(selections: RandomSelectionRecord[]): string {
  return selections
    .map((selection) => selection.candidate?.name || selection.candidate?.ref)
    .filter(Boolean)
    .join(" · ");
}

export async function submitBackgroundBatch(request: BackgroundBatchRequest): Promise<JobRecord> {
  const job = await apiPost<JobRecord>("/generate/batch", request);
  window.dispatchEvent(new Event(BACKGROUND_RUNS_CHANGED));
  return job;
}

/** 只含某一项事件的伪任务，用来复用单张任务的进度文案（启动 ComfyUI / 生成中 / 下载）。 */
export function itemProgressJob(job: BackgroundBatchJob, item: BackgroundBatchItem): JobRecord {
  return {
    id: `${job.id}:${item.index}`,
    name: job.name,
    status: item.status === "running" ? "running" : "queued",
    events: (job.events ?? []).filter((event) => event.item_index === item.index),
  };
}
