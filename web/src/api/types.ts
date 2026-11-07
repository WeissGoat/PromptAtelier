import type { ImageTiming } from "../generation/timing";
import type { NodeDocument } from "../nodes/types";
import type { NodePoolSpec } from "../workspace/types";

export type NodeSummary = {
  role: string;
  name: string;
  ref: string;
  relative?: string;
  backends?: string[];
  /** 节点目录里有可用的预览图（规则见后端 node_previews）。 */
  has_preview?: boolean;
};

export type ComfyUITargetState = "online" | "offline" | "running" | "stopped" | "unknown";

export type ComfyUITarget = {
  name: string;
  label: string;
  location: "local" | "cloud";
  base_url: string;
  status: {
    state: ComfyUITargetState;
    detail?: string;
    containers?: number;
    shutdown_in_seconds?: number;
  };
  active_jobs: number;
  last_used_at: number | null;
};

export type ComfyUITargetsResponse = {
  schema: "tags-machine-core.web.comfyui-targets/v1";
  default_target: string | null;
  targets: ComfyUITarget[];
};

export type NodeReadResponse = {
  schema: "tags-machine-core.web.node/v1" | "tags-machine-core.web.node/v2";
  ref: string;
  node: NodeDocument;
  form: Record<string, unknown>;
  raw?: { filename: string; text: string } | null;
  editor?: NodeEditorDocument;
};

export type NodeEditorDocument = {
  adapter: string;
  role: string;
  values: Record<string, unknown>;
  sources: Array<{ path: string; format: string; sha256: string | null; writable: boolean }>;
  capabilities: Record<string, boolean>;
};

export type NodeSavePreviewFile = {
  path: string;
  relative: string;
  format: string;
  before_sha256: string | null;
  changed: boolean;
  diff: string;
  after_text: string;
};

export type NodeSavePreviewResponse = {
  schema: "tags-machine-core.web.node-save-preview/v1";
  preview_id: string;
  node: NodeDocument;
  files: NodeSavePreviewFile[];
  warnings: string[];
  expires_at: number;
};

export type NodeSourceFile = {
  name: string;
  path: string;
  format: string;
  sha256: string | null;
  text: string;
};

export type NodeSourceFilesResponse = {
  schema: "tags-machine-core.web.node-source-files/v1";
  ref: string;
  files: NodeSourceFile[];
};

export type NodeListResponse = {
  schema: string;
  role: string;
  nodes: NodeSummary[];
  offset: number;
  limit: number;
  has_more: boolean;
};

export type NodePoolCandidate = {
  role: string;
  ref: string;
  name: string;
  relative?: string | null;
  /** 只在 /node-pools/scan 里有：在整个池里的次序（从 0 开始），搜索过滤后不变。 */
  position?: number;
  has_preview?: boolean;
};

export type NodePoolStats = {
  raw_total: number;
  total: number;
  missing_classify: number;
  invalid_classify: number;
  classify_mismatch: number;
  invalid_node: number;
  unselected?: number;
  selection_missing?: number;
};

export type NodePoolScanResponse = {
  schema: "tags-machine-core.web.node-pool-scan/v1";
  scan_id: string;
  role: string;
  total: number;
  source_total: number;
  items: NodePoolCandidate[];
  offset: number;
  limit: number;
  has_more: boolean;
  next_offset: number | null;
  stats: NodePoolStats;
  facets: Record<string, string[]>;
  warnings: string[];
};

export type NodePoolCollectionsResponse = {
  schema: "tags-machine-core.web.node-pool-collections/v1";
  role: string;
  items: Array<{ name: string; item_count: number }>;
};

export type SampledNode = {
  candidate: NodePoolCandidate;
  node: NodeDocument;
  draw_index: number;
  deck_cycle: number;
};

export type NodePoolSampleResponse = {
  schema: "tags-machine-core.web.node-pool-sample/v1";
  role: string;
  items: SampledNode[];
  stats: NodePoolStats;
};

export type NodePoolListAllResponse = {
  schema: "tags-machine-core.web.node-pool-list-all/v1";
  role: string;
  total: number;
  items: NodePoolCandidate[];
  stats: NodePoolStats;
};

export type NodePoolScanRequest = {
  role: string;
  spec: NodePoolSpec;
  q?: string;
  offset?: number;
  limit?: number;
  refresh?: boolean;
};

export type ComposePreviewResponse = {
  status: "ready" | "requires_agent";
  prompt_bundle?: {
    prompt: {
      positive: string;
      negative: string;
    };
    meta?: {
      composition?: {
        included_character_sections?: string[];
        suppressed_character_sections?: string[];
      };
      extra?: {
        policy?: {
          template?: string | null;
          effective_rule_order?: string[];
        };
        policy_trace?: Array<Record<string, unknown>>;
      };
    };
  };
  render_request?: Record<string, unknown>;
  agent_task?: Record<string, unknown>;
  /** NovelAI 最终提示词的 token 用量（和官网同样的分词器和上限）。 */
  token_usage?: TokenUsage;
};

/** 提示词 token 用量，规则和 NovelAI 官网图片页一致。 */
export type TokenUsage = {
  tokenizer: string;
  limit: number | null;
  /** false 表示分词器不可用，数字是估算。 */
  exact: boolean;
  /** 主提示词和各角色提示词是否共用上限（NovelAI V4+）。 */
  shared: boolean;
  base: number;
  characters: number[];
  total: number;
  over: boolean;
  /** 按代码块的数量：positive / positive c2 …（只有契约帧有）。 */
  blocks?: Record<string, number>;
  model?: string | null;
};

export type JobRecord = {
  id: string;
  name: string;
  status: "queued" | "running" | "cancelling" | "succeeded" | "failed" | "cancelled" | "interrupted";
  created_at?: number;
  updated_at?: number;
  result?: GenerationResult;
  error?: string | null;
  events?: JobEvent[];
};

export type JobEvent = {
  type: string;
  [key: string]: unknown;
};

export type GenerationImage = {
  path: string;
  filename?: string;
  meta?: Record<string, unknown>;
};

export type GenerationResult = {
  images?: GenerationImage[];
  request_body?: Record<string, unknown>;
  [key: string]: unknown;
};

export type ImageMetadataResponse = {
  schema: "tags-machine-core.web.image-metadata/v1";
  path: string;
  filename: string;
  size_bytes: number;
  modified_at: string;
  model: string | null;
  dimensions: { width: number; height: number } | null;
  png_text: Record<string, unknown>;
  parameters: Record<string, unknown>;
  nodes: ImageMetadataNode[];
  random_nodes: ImageMetadataRandomNode[];
  /** 本项目出的图才有；旧图和外部图为 null。 */
  timing?: ImageTiming | null;
  metadata_error?: string;
};

export type ImageMetadataNode = {
  role: string;
  id?: string;
  kind?: string;
  ref?: string;
  index?: number;
  content_hash?: string;
};

export type ImageMetadataRandomNode = {
  role: string;
  name: string | null;
  ref: string | null;
  slot_id: string | null;
  relative: string | null;
  draw_index: number | null;
  deck_cycle: number | null;
};

export type ImageParameterDiffItem = {
  path: string;
  kind: "value" | "type" | "key" | "length" | string;
  left: unknown;
  right: unknown;
};

export type ImageParameterDiffResponse = {
  schema: "tags-machine-core.web.image-parameter-diff/v1";
  previous: { path: string; filename: string };
  current: { path: string; filename: string };
  match: boolean;
  diff_count: number;
  diffs: ImageParameterDiffItem[];
  previous_normalized: Record<string, unknown>;
  current_normalized: Record<string, unknown>;
};

export type HistoryRunKind = "compare" | "random" | "sequential" | "sequential-all" | "primary" | "contract" | "studio" | "loose" | "other";

export type HistoryRun = {
  id: string;
  name: string;
  kind: HistoryRunKind;
  path: string;
  created_at: number;
  image_count: number;
  group_count: number;
  covers: string[];
  /** 后端还记得的出图任务（提交时的名字和状态）；更早的批次为 null。 */
  job: { id: string; label: string | null; status: JobRecord["status"] } | null;
};

export type HistoryImageInfo = {
  backend: string | null;
  seed: number | string | null;
  width: number | null;
  height: number | null;
  nodes: Array<{ role: string; name: string }>;
  timing: ImageTiming | null;
};

export type HistoryImage = {
  path: string;
  filename: string;
  group: string;
  created_at: number;
  size_bytes: number;
  info: HistoryImageInfo;
};

export type HistoryRunImagesResponse = {
  schema: "tags-machine-core.web.history-run-images/v1";
  run_id: string;
  path: string;
  total: number;
  offset: number;
  limit: number;
  images: HistoryImage[];
};

export type NovelAIUsageInfo = {
  configured: boolean;
  token_masked: string;
  /** 多 token 管理里的 id 和自定义名称（老后端没有这两个字段）。 */
  token_id?: string;
  token_name?: string;
  active: boolean;
  tier: number;
  tier_name: string;
  anlas: number;
  fixed_anlas: number;
  purchased_anlas: number;
  usage_percent: number;
  time_until_next_percent: number;
  unlimited_v5_eligible: boolean;
  error?: string | null;
};

/** Web 里保存的一个 NovelAI token；明文 token 永远不会返回给前端。 */
export type NovelAITokenEntry = {
  id: string;
  name: string;
  token_masked: string;
  /** config：configs/local.yaml 或环境变量里的 token，只能改名不能删除；saved：网页添加的。 */
  source: "config" | "saved";
  /** token：直接保存的 token；account：保存账号密码，用时登录换 token（token_masked 为空，看 account）。 */
  kind?: "token" | "account";
  account?: string | null;
  /** 账号：pending 后台排队登录 / ok 已登录 / failed 登录失败（login_error 是原因或限流等待说明）。 */
  login_status?: "pending" | "ok" | "failed" | null;
  login_error?: string | null;
  active: boolean;
  created_at?: number | null;
};

export type NovelAITokenList = {
  schema: "tags-machine-core.web.novelai-tokens/v1";
  active_id: string | null;
  tokens: NovelAITokenEntry[];
};

export type NovelAITokenImportResult = NovelAITokenList & {
  added: NovelAITokenEntry[];
  /** 账号导入：之前登录失败、这次重新排队的。 */
  requeued?: NovelAITokenEntry[];
  /** 在 Token 页签粘贴了账号密码列表时，后端自动按账号导入，返回 "accounts"。 */
  imported_as?: "accounts";
  /** line 从 1 开始；reason: duplicate 已存在或同批重复，invalid 格式不对。 */
  skipped: { line: number; reason: "duplicate" | "invalid" | "login_failed"; message: string }[];
};
