import { apiGet, apiPost, apiPut } from "../api/client";
import type {
  ActionGroupDetail,
  ActionGroupSummary,
  ContractDetail,
  ContractResults,
  ContractSummary,
  FormatSummary,
} from "./types";

export type CreateContractPayload = {
  action_group: string;
  characters: string[];
  clothing?: string | null;
  background?: string | null;
  requirements: string;
  target_format: string;
  options: { keep_order: boolean; allow_new_frames: boolean; max_new_frames: number };
};

export const contractsApi = {
  formats: () => apiGet<{ formats: FormatSummary[] }>("/formats").then((data) => data.formats),
  actionGroups: (query = "") =>
    apiGet<{ groups: ActionGroupSummary[] }>(`/contracts/action-groups${query ? `?q=${encodeURIComponent(query)}` : ""}`).then((data) => data.groups),
  actionGroup: (ref: string) => apiGet<ActionGroupDetail>(`/contracts/action-groups/detail?ref=${encodeURIComponent(ref)}`),
  list: () => apiGet<{ contracts: ContractSummary[]; now: number }>("/contracts"),
  index: (since: number) =>
    apiGet<{ changed: ContractSummary[]; ids: string[]; now: number }>(`/contracts/index?since=${since}`),
  refresh: (pull: boolean) =>
    apiPost<{ pull: Record<string, unknown> | null; contracts: ContractSummary[]; now: number }>(
      `/contracts/refresh${pull ? "?pull=1" : ""}`,
      {},
    ),
  create: (payload: CreateContractPayload) => apiPost<ContractDetail>("/contracts", payload),
  get: (id: string) => apiGet<ContractDetail>(`/contracts/${encodeURIComponent(id)}`),
  prompt: (id: string, kind: "tools" | "standalone") =>
    apiGet<{ text: string }>(`/contracts/${encodeURIComponent(id)}/prompt?kind=${kind}`).then((data) => data.text),
  importFrames: (id: string, text: string, hash?: string) =>
    apiPost<ContractDetail>(`/contracts/${encodeURIComponent(id)}/import`, { text, hash }),
  saveFrame: (id: string, frameId: string, prompts: Record<string, string>, hash: string) =>
    apiPut<ContractDetail>(`/contracts/${encodeURIComponent(id)}/frames/${encodeURIComponent(frameId)}`, { prompts, hash }),
  results: (id: string) => apiGet<ContractResults>(`/contracts/${encodeURIComponent(id)}/results`),
  updatePicks: (id: string, frameId: string, change: { add?: string[]; remove?: string[] }) =>
    apiPut<{ picks: Record<string, string[]> }>(`/contracts/${encodeURIComponent(id)}/picks`, { frame_id: frameId, ...change }),
};
