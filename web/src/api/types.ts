import type { NodeDocument } from "../nodes/types";

export type NodeSummary = {
  role: string;
  name: string;
  ref: string;
  relative?: string;
};

export type NodeReadResponse = {
  schema: "tags-machine-core.web.node/v1";
  ref: string;
  node: NodeDocument;
  form: Record<string, unknown>;
  raw?: { filename: string; text: string } | null;
};

export type NodeListResponse = {
  schema: string;
  role: string;
  nodes: NodeSummary[];
  offset: number;
  limit: number;
  has_more: boolean;
};

export type ComposePreviewResponse = {
  status: "ready" | "requires_agent";
  prompt_bundle?: {
    prompt: {
      positive: string;
      negative: string;
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
