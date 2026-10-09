import { apiGet, apiPost, apiUrl, ApiClientError } from "../api/client";

export type PostInfo = {
  dir_name: string;
  date: string | null;
  post_id: string | null;
  title: string | null;
};

export type CharCaption = {
  positive: string;
  negative: string;
  centers: Array<{ x: number; y: number }>;
};

export type VibeInfo = {
  count: number;
  hashes: string[];
  strengths: number[];
  information_extracted: number[];
};

export type ImageFlag = "no_metadata" | "inpaint" | "img2img" | "add_original" | "vibe_missing" | "director_ref";

export type ImageRecord = {
  id: string;
  path: string;
  rel_path: string;
  size_bytes: number;
  mtime_ns: number;
  post: PostInfo | null;
  width: number | null;
  height: number | null;
  has_metadata: boolean;
  source_label: string | null;
  model: string | null;
  request_type: string | null;
  prompt: string;
  negative_prompt: string;
  char_captions: CharCaption[];
  seed: number | null;
  steps: number | null;
  scale: number | null;
  cfg_rescale: number | null;
  sampler: string | null;
  noise_schedule: string | null;
  vibe: VibeInfo;
  flags: ImageFlag[];
};

export type WorkspaceInfo = {
  id: string;
  name: string;
  kind: "folder" | "files";
  root: string;
  data_dir: string;
  scan_dirs: string[];
  files: string[];
  created_at: number;
  last_opened_at: number;
};

export type ScanStats = { total: number; reused: number; read: number; failed: number };

export type WorkspacePayload = {
  workspace: WorkspaceInfo;
  scanned_at: number | null;
  images: ImageRecord[];
  scan?: ScanStats | null;
  pretranslate_job_id?: string | null;
};

export type ImageDetail = {
  image: ImageRecord;
  raw_parameters: Record<string, unknown>;
  png_text_keys: string[];
};

export type SeedMode = "source" | "random" | "fixed";
export type SizeMode = "source" | "custom";

export type RegenOverrides = Partial<{
  model: string;
  steps: number;
  scale: number;
  cfg_rescale: number;
  sampler: string;
  noise_schedule: string;
}>;

export type RegenSettings = {
  count: number;
  seed_mode: SeedMode;
  seed: number | null;
  size_mode: SizeMode;
  width: number | null;
  height: number | null;
  overrides: RegenOverrides;
};

export type ParamDiff = {
  path: string;
  key: string;
  kind: string;
  left: unknown;
  right: unknown;
  expected: boolean;
};

export type CompareVerdict = "match" | "drift" | "param_diff";

export type CompareResult = {
  verdict: CompareVerdict;
  similarity: number | null;
  dhash_distance: number | null;
  param_diff_count: number;
  param_diff_no_resolution_count: number;
  diffs: ParamDiff[];
  error?: string;
};

export type RunItemStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled" | "interrupted";
export type RunStatus = RunItemStatus | "partial";

export type RunItem = {
  index: number;
  seed: number;
  status: RunItemStatus;
  image_path?: string;
  error?: string;
  error_detail?: string;
  compare?: CompareResult;
};

export type StyleLabRun = {
  id: string;
  kind: "regenerate";
  status: RunStatus;
  created_at: number;
  finished_at: number | null;
  job_id: string | null;
  source: { image_id: string; path: string; rel_path: string };
  settings: RegenSettings;
  expected_diff_keys: string[];
  warnings: string[];
  items: RunItem[];
  error?: string;
};

export type LLMStatus = {
  available: boolean;
  base_url: string | null;
  models: Record<string, string | null>;
};

const base = "/style-lab";

export function listWorkspaces(): Promise<{ workspaces: WorkspaceInfo[] }> {
  return apiGet(`${base}/workspaces`);
}

export function openFolder(root: string): Promise<WorkspacePayload> {
  return apiPost(`${base}/workspaces`, { root });
}

export function createImageGroup(files: string[], name?: string): Promise<WorkspacePayload> {
  return apiPost(`${base}/workspaces`, { files, name });
}

export function getWorkspace(id: string): Promise<WorkspacePayload> {
  return apiGet(`${base}/workspaces/${encodeURIComponent(id)}`);
}

export function rescanWorkspace(id: string): Promise<WorkspacePayload> {
  return apiPost(`${base}/workspaces/${encodeURIComponent(id)}/scan`, {});
}

export async function uploadImages(id: string, files: File[]): Promise<WorkspacePayload> {
  const form = new FormData();
  for (const file of files) {
    form.append("files", file, file.name);
  }
  const response = await fetch(apiUrl(`${base}/workspaces/${encodeURIComponent(id)}/upload`), {
    method: "POST",
    body: form,
  });
  if (!response.ok) {
    const text = await response.text();
    let message = text || response.statusText;
    try {
      message = (JSON.parse(text) as { error?: { message?: string } }).error?.message ?? message;
    } catch {
      // 保留原始文本。
    }
    throw new ApiClientError(message, { status: response.status });
  }
  return response.json() as Promise<WorkspacePayload>;
}

export function getImageDetail(workspaceId: string, imageId: string): Promise<ImageDetail> {
  return apiGet(`${base}/workspaces/${encodeURIComponent(workspaceId)}/images/${encodeURIComponent(imageId)}`);
}

export function sourceImageUrl(workspaceId: string, imageId: string, size = 0): string {
  const params = new URLSearchParams({ image_id: imageId, size: String(size) });
  return apiUrl(`${base}/workspaces/${encodeURIComponent(workspaceId)}/file?${params}`);
}

export function runImageUrl(workspaceId: string, path: string, size = 0): string {
  const params = new URLSearchParams({ path, size: String(size) });
  return apiUrl(`${base}/workspaces/${encodeURIComponent(workspaceId)}/file?${params}`);
}

export function startRegenerate(
  workspaceId: string,
  imageId: string,
  settings: RegenSettings,
): Promise<{ run: StyleLabRun }> {
  return apiPost(`${base}/workspaces/${encodeURIComponent(workspaceId)}/regenerate`, {
    image_id: imageId,
    settings,
  });
}

export function listRuns(workspaceId: string, imageId?: string): Promise<{ runs: StyleLabRun[] }> {
  const query = imageId ? `?${new URLSearchParams({ image_id: imageId })}` : "";
  return apiGet(`${base}/workspaces/${encodeURIComponent(workspaceId)}/runs${query}`);
}

export function getRun(workspaceId: string, runId: string): Promise<{ run: StyleLabRun }> {
  return apiGet(`${base}/workspaces/${encodeURIComponent(workspaceId)}/runs/${encodeURIComponent(runId)}`);
}

export function cancelJob(jobId: string): Promise<unknown> {
  return apiPost(`/jobs/${encodeURIComponent(jobId)}/cancel`, {});
}

export function getLLMStatus(): Promise<LLMStatus> {
  return apiGet(`${base}/llm/status`);
}

export function translateTexts(texts: string[]): Promise<{ available: boolean; translations: Record<string, string> }> {
  return apiPost(`${base}/translate`, { texts });
}

export const ACTIVE_RUN_STATUSES: ReadonlySet<RunStatus> = new Set(["queued", "running"]);
