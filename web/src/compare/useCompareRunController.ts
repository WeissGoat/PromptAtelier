import { useCallback, useMemo, useRef, useState } from "react";

import { apiGet, apiPost, errorMessage } from "../api/client";
import type { ComposePreviewResponse, JobRecord } from "../api/types";
import type { NodeRole } from "../nodes/types";
import { buildComposeRenderRequest } from "../workspace/requestBuilder";
import type { PromptBehaviorParams, RenderWorkspaceParams, RoleNodeGroup } from "../workspace/types";
import { buildCompareMatrix, selectedSlots, type CompareCombination } from "./matrix";
import { buildCompareRunPlan, type CompareRunItem } from "./runPlan";

export type CompareCombinationStatus = "queued" | "running" | "succeeded" | "failed";

export type CompareCombinationResult = {
  runId: string;
  groupIndex: number;
  groupSeed: number;
  combination: CompareCombination;
  labels: Record<NodeRole, string>;
  status: CompareCombinationStatus;
  job: JobRecord | null;
  error: string;
};

export type CompareRunSummary = {
  total: number;
  queued: number;
  running: number;
  succeeded: number;
  failed: number;
};

export type CompareGroupSummary = CompareRunSummary & {
  groupIndex: number;
  seed: number;
};

type ControllerDependencies = {
  pollIntervalMs?: number;
  get?: (path: string) => Promise<unknown>;
  post?: (path: string, body: unknown) => Promise<unknown>;
  randomSeed?: () => number;
  outputDirFactory?: () => string;
};

const terminalStatuses = new Set<JobRecord["status"]>(["succeeded", "failed", "cancelled"]);

export function createCompareOutputDir(): string {
  const timestamp = new Date().toISOString().replace(/\D/g, "").slice(0, 14);
  const suffix = globalThis.crypto?.randomUUID
    ? globalThis.crypto.randomUUID().slice(0, 8)
    : Math.random().toString(16).slice(2, 10).padEnd(8, "0");
  return `outputs/compare_${timestamp}_${suffix}`;
}

export function createCompareGroupOutputDir(parent: string, groupIndex: number, seed: number): string {
  const root = parent.replace(/[\\/]+$/, "");
  return `${root}/group_${String(groupIndex).padStart(3, "0")}_seed_${seed}`;
}

function slotLabel(slot: CompareCombination[NodeRole]): string {
  return slot?.draftNode?.name || slot?.draftNode?.id || slot?.sourceNode?.name || slot?.sourceRef || "未选择";
}

function initialResult(item: CompareRunItem): CompareCombinationResult {
  return {
    runId: item.runId,
    groupIndex: item.groupIndex,
    groupSeed: item.groupSeed,
    combination: item.combination,
    labels: {
      artist: slotLabel(item.combination.artist),
      character: slotLabel(item.combination.character),
      action: slotLabel(item.combination.action),
    },
    status: "queued",
    job: null,
    error: "",
  };
}

function summarize(results: CompareCombinationResult[]): CompareRunSummary {
  return {
    total: results.length,
    queued: results.filter((item) => item.status === "queued").length,
    running: results.filter((item) => item.status === "running").length,
    succeeded: results.filter((item) => item.status === "succeeded").length,
    failed: results.filter((item) => item.status === "failed").length,
  };
}

function summarizeGroups(results: CompareCombinationResult[]): CompareGroupSummary[] {
  const groupIndexes = [...new Set(results.map((item) => item.groupIndex))];
  return groupIndexes.map((groupIndex) => {
    const items = results.filter((item) => item.groupIndex === groupIndex);
    return {
      groupIndex,
      seed: items[0]?.groupSeed ?? 0,
      ...summarize(items),
    };
  });
}

export function useCompareRunController(dependencies: ControllerDependencies = {}) {
  const get = dependencies.get ?? apiGet;
  const post = dependencies.post ?? apiPost;
  const pollIntervalMs = dependencies.pollIntervalMs ?? 500;
  const randomSeed = dependencies.randomSeed ?? (() => {
    if (globalThis.crypto?.getRandomValues) return globalThis.crypto.getRandomValues(new Uint32Array(1))[0];
    return Math.floor(Math.random() * 0x100000000);
  });
  const outputDirFactory = dependencies.outputDirFactory ?? createCompareOutputDir;
  const runToken = useRef(0);
  const [results, setResults] = useState<CompareCombinationResult[]>([]);
  const [running, setRunning] = useState(false);

  const updateResult = useCallback((token: number, runId: string, patch: Partial<CompareCombinationResult>) => {
    if (runToken.current !== token) return;
    setResults((current) => current.map((item) => item.runId === runId ? { ...item, ...patch } : item));
  }, []);

  const pollJob = useCallback(async (token: number, job: JobRecord): Promise<JobRecord> => {
    let current = job;
    while (!terminalStatuses.has(current.status)) {
      await new Promise((resolve) => window.setTimeout(resolve, pollIntervalMs));
      if (runToken.current !== token) throw new Error("Compare run cancelled");
      current = await get(`/jobs/${encodeURIComponent(job.id)}`) as JobRecord;
    }
    return current;
  }, [get, pollIntervalMs]);

  const start = useCallback(async (
    groups: Record<NodeRole, RoleNodeGroup>,
    params: RenderWorkspaceParams,
    promptBehavior?: PromptBehaviorParams,
  ) => {
    if (!selectedSlots(groups.character).length && !selectedSlots(groups.action).length) {
      throw new Error("Compare Generate 至少需要一个 Character 或 Action 节点。");
    }
    const token = ++runToken.current;
    const matrix = buildCompareMatrix(groups);
    const plan = buildCompareRunPlan(matrix, { nt: params.nt, seed: params.seed, randomSeed });
    const outputDir = outputDirFactory();
    setResults(plan.items.map(initialResult));
    setRunning(true);
    let nextIndex = 0;

    async function runItem(item: CompareRunItem) {
      updateResult(token, item.runId, { status: "running", error: "" });
      try {
        const runParams: RenderWorkspaceParams = { ...params, seed: String(item.groupSeed) };
        const request = buildComposeRenderRequest(item.combination, runParams, { compare: true, promptBehavior });
        const preview = await post("/compose-preview", request) as ComposePreviewResponse;
        if (!preview.render_request) throw new Error("该组合需要外部 Agent 先完成提示词拼接。");
        const queued = await post("/generate", {
          render_request: preview.render_request,
          output_dir: createCompareGroupOutputDir(outputDir, item.groupIndex, item.groupSeed),
        }) as JobRecord;
        updateResult(token, item.runId, { job: queued });
        const completed = await pollJob(token, queued);
        if (completed.status !== "succeeded") throw new Error(completed.error || `Job ${completed.status}`);
        updateResult(token, item.runId, { status: "succeeded", job: completed });
      } catch (runError) {
        if (runToken.current !== token) return;
        updateResult(token, item.runId, { status: "failed", error: errorMessage(runError) });
      }
    }

    async function worker() {
      while (runToken.current === token) {
        const index = nextIndex++;
        if (index >= plan.items.length) return;
        await runItem(plan.items[index]);
      }
    }

    // NovelAI 同一账号并发请求时，一组会稳定触发 429；Compare 按单 worker 串行提交。
    await worker();
    if (runToken.current === token) setRunning(false);
  }, [outputDirFactory, pollJob, post, randomSeed, updateResult]);

  const reset = useCallback(() => {
    runToken.current += 1;
    setRunning(false);
    setResults([]);
  }, []);

  const summary = useMemo(() => summarize(results), [results]);
  const groupSummaries = useMemo(() => summarizeGroups(results), [results]);
  return useMemo(
    () => ({ start, reset, summary, groupSummaries, results, running }),
    [groupSummaries, reset, results, running, start, summary],
  );
}

export type CompareRunController = ReturnType<typeof useCompareRunController>;
