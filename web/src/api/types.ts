export type NodeSummary = {
  role: string;
  name: string;
  ref: string;
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
  result?: unknown;
  error?: string | null;
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
