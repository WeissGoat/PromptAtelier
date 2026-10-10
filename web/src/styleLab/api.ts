import { apiDelete, apiGet, apiPost, apiPut, apiUrl, ApiClientError } from "../api/client";

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
  analysis_job_id?: string | null;
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
  note?: string;
};

export type CompareVerdict = "match" | "drift" | "param_diff" | "reference";

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
  kind: "regenerate" | "recipe";
  recipe?: { id: string; version: number; name: string };
  status: RunStatus;
  created_at: number;
  finished_at: number | null;
  job_id: string | null;
  source: { image_id: string; path: string; rel_path: string } | null;
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
  force = false,
): Promise<{ run: StyleLabRun }> {
  return apiPost(`${base}/workspaces/${encodeURIComponent(workspaceId)}/regenerate`, {
    image_id: imageId,
    settings,
    force,
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

// ---- P2：分析、分组、配方、素材 ----

export type TagCategory =
  | "artist"
  | "style"
  | "quality"
  | "meta"
  | "count"
  | "character"
  | "appearance"
  | "clothing"
  | "action"
  | "expression"
  | "scene"
  | "camera"
  | "nsfw"
  | "other";

export type GroupChild = {
  id: string;
  variant: string;
  vibe: string;
  model: string | null;
  post_count: number;
  image_count: number;
  date_from: string | null;
  date_to: string | null;
  image_ids: string[];
};

export type StyleGroup = {
  id: string;
  name: string;
  signature: Array<{ tag: string; posts: number }>;
  signature_kind: "artist" | "style";
  post_count: number;
  image_count: number;
  date_from: string | null;
  date_to: string | null;
  image_ids: string[];
  children: GroupChild[];
};

export type Analysis = {
  categories: Record<string, TagCategory>;
  classified: number;
  total_tags: number;
  job_id: string | null;
  groups: StyleGroup[];
};

export type RecipeToken = { id: string; text: string; sep: string; origins: string[] };

export type MaterialRole = "character" | "action";
/** 素材架上的一块；excluded 是在卡片里筛掉不要的 tag。 */
export type RecipeMaterial = { role: MaterialRole; ref: string; name: string; excluded: string[] };

export type Recipe = {
  schema: string;
  id: string;
  name: string;
  version: number;
  created_at: number;
  updated_at: number;
  source_image_id: string | null;
  group_id: string | null;
  stage: "split" | "edit";
  locked: boolean;
  prefix: RecipeToken[];
  subject: RecipeToken[];
  suffix: RecipeToken[];
  dropped: RecipeToken[];
  character: { enabled: boolean; tokens: RecipeToken[]; negative: RecipeToken[]; add_male_caption: boolean };
  /** 旧版本的配方和浏览器里的草稿备份没有这一项。 */
  materials?: RecipeMaterial[];
  negative: RecipeToken[];
  model: string | null;
  params: Record<string, unknown>;
  use_source_vibe: boolean;
  flags: string[];
  notes: string;
};

export type RecipeSummary = Pick<
  Recipe,
  "id" | "name" | "version" | "stage" | "locked" | "source_image_id" | "group_id" | "updated_at"
>;

export type RecipePreview = {
  prompt: string;
  negative_prompt: string;
  char_captions: string[];
  negative_char_captions: string[];
  character_prompts: { mode: string; count?: number; male_caption_added?: boolean; status?: string } | null;
  model: string | null;
  size: { width: number; height: number } | null;
  params: Record<string, unknown>;
  vibe_count: number;
};

export type LibraryNodeSummary = { role: string; name: string; ref: string; relative?: string; has_preview?: boolean };
export type LibraryNode = {
  ref: string;
  role: "character" | "action";
  name: string;
  sections: Array<{ name: string; tags: string[] }>;
  has_preview: boolean;
};

const ws = (id: string) => `${base}/workspaces/${encodeURIComponent(id)}`;

export function getAnalysis(workspaceId: string): Promise<Analysis> {
  return apiGet(`${ws(workspaceId)}/analysis`);
}

export function listRecipes(workspaceId: string): Promise<{ recipes: RecipeSummary[] }> {
  return apiGet(`${ws(workspaceId)}/recipes`);
}

export function createRecipe(
  workspaceId: string,
  imageId: string,
  options: { name?: string; groupId?: string | null } = {},
): Promise<{ recipe: Recipe }> {
  return apiPost(`${ws(workspaceId)}/recipes`, { image_id: imageId, name: options.name, group_id: options.groupId });
}

export function getRecipe(
  workspaceId: string,
  recipeId: string,
): Promise<{ recipe: Recipe; history: Array<{ version: number; updated_at: number }> }> {
  return apiGet(`${ws(workspaceId)}/recipes/${encodeURIComponent(recipeId)}`);
}

export function saveRecipe(workspaceId: string, recipe: Recipe, baseVersion: number): Promise<{ recipe: Recipe }> {
  return apiPut(`${ws(workspaceId)}/recipes/${encodeURIComponent(recipe.id)}`, { recipe, base_version: baseVersion });
}

export function deleteRecipe(workspaceId: string, recipeId: string): Promise<unknown> {
  return apiDelete(`${ws(workspaceId)}/recipes/${encodeURIComponent(recipeId)}`);
}

export function previewRecipe(workspaceId: string, recipe: Recipe): Promise<{ preview: RecipePreview }> {
  return apiPost(`${ws(workspaceId)}/recipes/preview`, { recipe });
}

export function generateRecipe(
  workspaceId: string,
  recipeId: string,
  settings: RegenSettings,
  force = false,
): Promise<{ run: StyleLabRun }> {
  return apiPost(`${ws(workspaceId)}/recipes/${encodeURIComponent(recipeId)}/generate`, { settings, force });
}

export type FacetOption = { value: string; count: number };
export type MaterialNode = LibraryNodeSummary & {
  copies: number;
  copy_paths: string[];
  facets: Record<string, string[]>;
};
export type MaterialSearchResult = {
  nodes: MaterialNode[];
  total: number;
  has_more: boolean;
  facet_options: Record<string, FacetOption[]>;
};

/** 去重后的素材搜索：内容相同的副本目录合并；动作可以按 classify.yaml 分面筛选。 */
export function searchMaterials(
  role: MaterialRole,
  query: string,
  facets: Record<string, string> = {},
  options: { offset?: number; limit?: number } = {},
): Promise<MaterialSearchResult> {
  const params = new URLSearchParams({ role, offset: String(options.offset ?? 0), limit: String(options.limit ?? 30) });
  if (query.trim()) params.set("q", query.trim());
  Object.entries(facets).forEach(([name, value]) => value && params.append("facet", `${name}:${value}`));
  return apiGet(`${base}/library/search?${params}`);
}

export function getLibraryNode(ref: string, role: "character" | "action"): Promise<LibraryNode> {
  return apiGet(`${base}/library/node?${new URLSearchParams({ ref, role })}`);
}

export function analyzeWorkspace(workspaceId: string): Promise<{ job_id: string | null }> {
  return apiPost(`${ws(workspaceId)}/analyze`, {});
}

// ---- 导出 artist 与测试 ----

export type ArtistExport = {
  folder: string;
  path: string;
  recipe_id: string;
  recipe_version: number;
  recipe_name: string;
  exported_at: number;
  files: string[];
  exists: boolean;
};

export type ExportDefaults = {
  author: string | null;
  artist_root: string;
  exports: ArtistExport[];
  candidates: string[];
};

export type ExportRequest = {
  name: string;
  author: string | null;
  compare_ref?: string | null;
  include_source?: boolean;
};

export type TokenDiff = { added: string[]; removed: string[]; same: boolean };

export type ArtistDiff = {
  prefix: TokenDiff;
  suffix: TokenDiff;
  negative: TokenDiff;
  style: TokenDiff;
  params: Array<{ key: string; before: unknown; after: unknown }>;
  flags: { before: string[]; after: string[] } | null;
};

export type ExportPreview = {
  folder: string;
  requested_folder: string;
  exists: boolean;
  artist_root: string;
  tags_txt: string;
  files: string[];
  vibe_count: number;
  roundtrip_ok: boolean;
  problems: string[];
  warnings: string[];
  candidates: string[];
  compare: { ref: string; diff?: ArtistDiff; error?: string } | null;
};

export type ArtistTestSettings = {
  kind: "regression" | "matrix";
  artist: string;
  image_ids: string[];
  characters: string[];
  actions: string[];
  seed_mode: SeedMode;
  seed: number | null;
  width: number | null;
  height: number | null;
};

export type ArtistTestItem = RunItem & {
  label?: string;
  source?: { image_id: string; path: string; rel_path: string };
  subject?: string;
  removed?: string[];
  character?: string | null;
  action?: string | null;
};

export type ArtistTestRun = Omit<StyleLabRun, "kind" | "settings" | "items"> & {
  kind: "regression" | "matrix";
  settings: ArtistTestSettings;
  artist: { folder: string };
  items: ArtistTestItem[];
};

export type AnyRun = StyleLabRun | ArtistTestRun;

export function isArtistTestRun(run: AnyRun): run is ArtistTestRun {
  return run.kind === "regression" || run.kind === "matrix";
}

function recipeUrl(workspaceId: string, recipeId: string): string {
  return `${ws(workspaceId)}/recipes/${encodeURIComponent(recipeId)}`;
}

export function listRecipeRuns(workspaceId: string, recipeId: string): Promise<{ runs: AnyRun[] }> {
  return apiGet(`${ws(workspaceId)}/runs?${new URLSearchParams({ recipe_id: recipeId })}`);
}

export function getExportDefaults(workspaceId: string, recipeId: string): Promise<ExportDefaults> {
  return apiGet(`${recipeUrl(workspaceId, recipeId)}/exports`);
}

export function previewExport(workspaceId: string, recipeId: string, request: ExportRequest): Promise<{ preview: ExportPreview }> {
  return apiPost(`${recipeUrl(workspaceId, recipeId)}/export/preview`, request);
}

export function exportArtist(
  workspaceId: string,
  recipeId: string,
  request: ExportRequest,
  expectedFolder: string,
): Promise<{ export: ArtistExport }> {
  return apiPost(`${recipeUrl(workspaceId, recipeId)}/export`, { ...request, expected_folder: expectedFolder });
}

export function startArtistTest(
  workspaceId: string,
  recipeId: string,
  settings: ArtistTestSettings,
  force = false,
): Promise<{ run: ArtistTestRun }> {
  return apiPost(`${recipeUrl(workspaceId, recipeId)}/artist-test`, { settings, force });
}
