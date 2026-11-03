import type { TokenUsage } from "../api/types";

export type { TokenUsage };

export type IssueSeverity = "error" | "warn" | "info";

export type ContractIssue = {
  validator: string;
  severity: IssueSeverity;
  message: string;
  frame_id?: string;
  block?: string;
  tag?: string;
  fix_hint?: string;
};

export type NodeRefEntry = { ref: string; content_hash?: string | null };

export type ContractRequest = {
  schema: string;
  id: string;
  title: string;
  status: "pending" | "done";
  created_at: string;
  target_format: string;
  nodes: {
    characters: Record<string, NodeRefEntry>;
    action_group: NodeRefEntry | null;
    clothing: NodeRefEntry | null;
    background: NodeRefEntry | null;
  };
  requirements: string;
  options: { keep_order: boolean; allow_new_frames: boolean; max_new_frames: number };
  author: string;
};

export type ContractFrame = {
  id: string;
  title: string;
  source: string | null;
  is_custom: boolean;
  inspired_by: string[];
  characters: string[];
  size: "portrait" | "landscape" | "square" | null;
  meta: Record<string, string>;
  notes: string;
  /** 键为 positive / negative / positive c2 …，值为代码块原文。 */
  prompts: Record<string, string>;
  /** 提交生图用的文本：按格式 profile 处理过换行。 */
  submit: Record<string, string>;
  member_ref: string | null;
  member_index: number | null;
  prompt_hash: string;
  /** 正向提示词的 token 用量（和 NovelAI 官网同样的分词器）；格式没有上限时为 null。 */
  token_usage: TokenUsage | null;
};


export type ClassifySummary = Record<string, unknown>;

export type ActionMember = {
  index: number;
  name: string;
  title: string;
  ref: string;
  group_ref: string | null;
  path: string;
  positive: string;
  negative: string;
  source_file: string;
  classify: ClassifySummary;
  character_scope: string | null;
  clothing_state: string | null;
};

export type ActionGroupDetail = {
  ref: string;
  name: string;
  path: string;
  kind: "st" | "stn";
  member_count: number;
  content_hash: string;
  members: ActionMember[];
};

export type ActionGroupSummary = {
  ref: string;
  name: string;
  path: string;
  kind: "st" | "stn";
  member_count: number;
  first_member: string | null;
};

export type SourceNode = {
  ref: string;
  path: string;
  id: string;
  name: string;
  character_id?: string | null;
  variant?: string | null;
  sections: Record<string, string[]>;
  negative: string[];
  content_hash: string;
};

export type ContractSources = {
  characters: Record<string, SourceNode>;
  action_group: ActionGroupDetail | null;
  clothing: SourceNode | null;
  background: SourceNode | null;
  references: Record<string, ActionMember>;
};

export type FormatSummary = {
  id: string;
  label: string;
  family: string;
  separator: string;
  newline: "separator" | "keep";
  weight_syntaxes: string[];
  allow_cjk: boolean;
  tokenizer: string;
  max_tokens: number | null;
  tokens_shared_with_characters?: boolean;
  /** 这个格式对应的模型 id（如 nai-diffusion-4-5-full）。 */
  models?: string[];
  multi_character: { supported: boolean; max: number };
};

export type ContractSummary = {
  id: string;
  title: string;
  status: "pending" | "done" | "invalid";
  created_at?: string;
  target_format?: string;
  frame_count: number;
  mtime: number;
  requirements?: string;
  error?: string;
  nodes: {
    characters?: Record<string, string>;
    action_group?: string | null;
    clothing?: string | null;
    background?: string | null;
  };
};

export type ContractDetail = {
  id: string;
  file: { path: string; hash: string; mtime: number };
  parse_error?: string;
  text?: string;
  summary: ContractSummary;
  request: ContractRequest;
  preamble: string;
  frames: ContractFrame[];
  sources: ContractSources;
  stale: Array<{ node: string; ref: string }>;
  coverage: {
    total: number;
    used: Record<string, string[]>;
    missing: Array<{ index: number; ref: string; title: string }>;
    custom_frames: string[];
  } | null;
  issues: ContractIssue[];
  issue_counts: Record<IssueSeverity, number>;
  profile: FormatSummary;
};

export type ContractResultImage = {
  path: string;
  run: string;
  frame_id: string;
  prompt_hash?: string;
  artist?: string;
  seed?: number;
  created_at: number;
  current: boolean;
  picked: boolean;
};

export type ContractResults = {
  id: string;
  frames: Record<string, ContractResultImage[]>;
  picks: Record<string, string[]>;
};
