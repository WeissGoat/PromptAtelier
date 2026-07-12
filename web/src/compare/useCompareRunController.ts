import { useCallback, useMemo, useRef, useState } from "react";

import { apiGet, apiPost, errorMessage } from "../api/client";
import type { ComposePreviewResponse, JobRecord } from "../api/types";
import type { NodeRole } from "../nodes/types";
import { buildComposeRenderRequest } from "../workspace/requestBuilder";
import type { RenderWorkspaceParams, RoleNodeGroup } from "../workspace/types";
import { buildCompareMatrix, selectedSlots, type CompareCombination } from "./matrix";

export type CompareCombinationStatus = "queued" | "running" | "succeeded" | "failed";

export type CompareCombinationResult = {
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

type ControllerDependencies = {
  pollIntervalMs?: number;
  get?: (path: string) => Promise<unknown>;
  post?: (path: string, body: unknown) => Promise<unknown>;
  randomSeed?: () => number;
};

const terminalStatuses = new Set<JobRecord["status"]>(["succeeded", "failed", "cancelled"]);

function slotLabel(slot: CompareCombination[NodeRole]): string {
  return slot?.draftNode?.name || slot?.draftNode?.id || slot?.sourceNode?.name || slot?.sourceRef || "未选择";
}

function initialResult(combination: CompareCombination): CompareCombinationResult {
  return {
    combination,
    labels: {
      artist: slotLabel(combination.artist),
      character: slotLabel(combination.character),
      action: slotLabel(combination.action),
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

export function useCompareRunController(dependencies: ControllerDependencies = {}) {
  const get = dependencies.get ?? apiGet;
  const post = dependencies.post ?? apiPost;
  const pollIntervalMs = dependencies.pollIntervalMs ?? 500;
  const randomSeed = dependencies.randomSeed ?? (() => {
    if (globalThis.crypto?.getRandomValues) return globalThis.crypto.getRandomValues(new Uint32Array(1))[0];
    return Math.floor(Math.random() * 0x100000000);
  });
  const runToken = useRef(0);
  const [results, setResults] = useState<CompareCombinationResult[]>([]);
  const [running, setRunning] = useState(false);

  const updateResult = useCallback((token: number, combinationId: string, patch: Partial<CompareCombinationResult>) => {
    if (runToken.current !== token) return;
    setResults((current) => current.map((item) => item.combination.combinationId === combinationId ? { ...item, ...patch } : item));
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

  const start = useCallback(async (groups: Record<NodeRole, RoleNodeGroup>, params: RenderWorkspaceParams) => {
    if (!selectedSlots(groups.character).length && !selectedSlots(groups.action).length) {
      throw new Error("Compare Generate 至少需要一个 Character 或 Action 节点。");
    }
    const token = ++runToken.current;
    const matrix = buildCompareMatrix(groups);
    const parsedSeed = Number(params.seed);
    const sharedSeed = Number.isInteger(parsedSeed) && parsedSeed >= 0 ? parsedSeed : randomSeed();
    const runParams: RenderWorkspaceParams = { ...params, seed: String(sharedSeed) };
    setResults(matrix.map(initialResult));
    setRunning(true);
    let nextIndex = 0;

    async function runCombination(combination: CompareCombination) {
      const combinationId = combination.combinationId;
      updateResult(token, combinationId, { status: "running", error: "" });
      try {
        const request = buildComposeRenderRequest(combination, runParams, { compare: true });
        const preview = await post("/compose-preview", request) as ComposePreviewResponse;
        if (!preview.render_request) throw new Error("该组合需要外部 Agent 先完成提示词拼接。");
        const queued = await post("/generate", { render_request: preview.render_request }) as JobRecord;
        updateResult(token, combinationId, { job: queued });
        const completed = await pollJob(token, queued);
        if (completed.status !== "succeeded") throw new Error(completed.error || `Job ${completed.status}`);
        updateResult(token, combinationId, { status: "succeeded", job: completed });
      } catch (runError) {
        if (runToken.current !== token) return;
        updateResult(token, combinationId, { status: "failed", error: errorMessage(runError) });
      }
    }

    async function worker() {
      while (runToken.current === token) {
        const index = nextIndex++;
        if (index >= matrix.length) return;
        await runCombination(matrix[index]);
      }
    }

    // NovelAI 同一账号并发请求时，一组会稳定触发 429；Compare 按单 worker 串行提交。
    await worker();
    if (runToken.current === token) setRunning(false);
  }, [pollJob, post, randomSeed, updateResult]);

  const reset = useCallback(() => {
    runToken.current += 1;
    setRunning(false);
    setResults([]);
  }, []);

  const summary = useMemo(() => summarize(results), [results]);
  return useMemo(() => ({ start, reset, summary, results, running }), [reset, results, running, start, summary]);
}

export type CompareRunController = ReturnType<typeof useCompareRunController>;
