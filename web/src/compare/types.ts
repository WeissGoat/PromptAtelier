export type BaseTemplate = {
  prompt: string;
  negative: string;
  seed: number;
  width: number;
  height: number;
  steps: number;
  scale: number;
  sampler?: string;
  model?: string;
  raw_parameters?: Record<string, any>;
  is_infilling?: boolean;
  notice?: string;
  sourceImage?: {
    previewUrl?: string;
    filename?: string;
    sourcePath?: string;
  };
};

export type TagDiffToken = {
  text: string;
  type: "added" | "removed" | "unchanged";
};

export type TagDiffResult = {
  added: string[];
  removed: string[];
  unchanged: string[];
  tokens: TagDiffToken[];
};

export type PromptVariant = {
  id: string;
  name: string;
  prompt: string;
  diff: TagDiffResult;
  seedOverride: number | null;
  status: "idle" | "queued" | "running" | "succeeded" | "failed";
  jobId: string | null;
  resultImage?: {
    path: string;
    url: string;
    seed: number;
    durationMs?: number;
  };
  error?: string;
};

export type CompareRound = {
  id: string;
  name: string;
  basePrompt: string;
  variants: PromptVariant[];
  status: "idle" | "running" | "completed";
};

export type CompareWorkspaceState = {
  template: BaseTemplate;
  rounds: CompareRound[];
  deepCompare: {
    isOpen: boolean;
    leftVariantId: string | null;
    rightVariantId: string | null;
    mode: "split" | "flicker";
  };
  isBatchRunning: boolean;
};
