import type { NodeDocument } from "../nodes/types";
import type { NodePoolSpec } from "../workspace/types";

export type NodeSummary = {
  role: string;
  name: string;
  ref: string;
  relative?: string;
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
};

export type NodePoolStats = {
  raw_total: number;
  total: number;
  missing_classify: number;
  invalid_classify: number;
  classify_mismatch: number;
  invalid_node: number;
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
};

export type JobRecord = {
  id: string;
  name: string;
  status: "queued" | "running" | "cancelling" | "succeeded" | "failed" | "cancelled";
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
  metadata_error?: string;
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

export type BatchPreviewResponse = {
  schema: string;
  batch: string;
  task_count: number;
  run_dir: string;
  output_dir: string;
  selector_summary?: Record<string, unknown>;
  sample_tasks: Array<Record<string, unknown>>;
};

export type ResultRun = {
  name: string;
  path: string;
  task_count: number;
};
