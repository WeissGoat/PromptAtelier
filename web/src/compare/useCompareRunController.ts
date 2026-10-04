import { useCallback, useMemo, useRef, useState } from "react";

import { apiGet, apiPost, errorMessage } from "../api/client";
import type { ComposePreviewResponse, JobRecord } from "../api/types";
import { cloneNode } from "../nodes/temporaryNodes";
import type { GroupRole, NodeRole } from "../nodes/types";
import { resolveRandomItems, type RandomSelectionRecord } from "../randomNodes/resolve";
import { buildComposeRenderRequest, buildGeneratePayload } from "../workspace/requestBuilder";
import { notifyComfyTargetsChanged } from "../comfyui/targetStatus";
import { promptBehaviorFingerprint } from "../workspace/promptBehavior";
import type { PromptBehaviorGroup, RenderWorkspaceParams, RoleNodeGroup } from "../workspace/types";
import { buildCompareMatrix, selectedSlots, type CompareCombination } from "./matrix";
import { buildCompareRunPlan, type CompareRunItem } from "./runPlan";

export type CompareCombinationStatus = "queued" | "running" | "succeeded" | "failed";

export type CompareCombinationResult = {
  runId: string;
  groupIndex: number;
  groupSeed: number;
  combination: CompareCombination;
  labels: Record<NodeRole, string>;
  behavior: {
    slotId: string;
    label: string;
    fingerprint: string;
  };
  status: CompareCombinationStatus;
  job: JobRecord | null;
  error: string;
  randomSelections: RandomSelectionRecord[];
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

export function createCompareOutputDir(prefix: string = "compare"): string {
  const timestamp = new Date().toISOString().replace(/\D/g, "").slice(0, 14);
  const suffix = globalThis.crypto?.randomUUID
    ? globalThis.crypto.randomUUID().slice(0, 8)
    : Math.random().toString(16).slice(2, 10).padEnd(8, "0");
  return `outputs/compares/${prefix}_${timestamp}_${suffix}`;
}

export function createCompareGroupOutputDir(parent: string, groupIndex: number, seed: number): string {
  const root = parent.replace(/[\\/]+$/, "");
  return `${root}/group_${String(groupIndex).padStart(3, "0")}_seed_${seed}`;
}

function slotLabel(slot: CompareCombination[NodeRole]): string {
  if (slot?.sourceKind === "random") return `Random · ${slot.randomSpec?.source.type ?? "未配置"}`;
  return slot?.draftNode?.name || slot?.draftNode?.id || slot?.sourceNode?.name || slot?.sourceRef || "未选择";
}

export function compareItemLabels(combination: CompareCombination): Record<NodeRole, string> {
  return {
    artist: slotLabel(combination.artist),
    character: slotLabel(combination.character),
    action: slotLabel(combination.action),
    clothing: slotLabel(combination.clothing),
  };
}

export type ExecutableCompareItem = CompareRunItem & { randomSelections: RandomSelectionRecord[] };

/** Compare 要跑的每一项：展开矩阵、分组 seed、先抽好随机节点。前台和后台运行共用。 */
export async function planCompareRun(
  groups: Record<GroupRole, RoleNodeGroup>,
  params: RenderWorkspaceParams,
  promptBehaviorGroup: PromptBehaviorGroup,
  randomSeed: () => number,
): Promise<ExecutableCompareItem[]> {
  if (!selectedSlots(groups.character).length && !selectedSlots(groups.action).length) {
    throw new Error("Compare Generate 至少需要一个 Character 或 Action 节点。");
  }
  const matrix = buildCompareMatrix(groups, promptBehaviorGroup);
  const plan = buildCompareRunPlan(matrix, { nt: params.nt, seed: params.seed, randomSeed });
  const resolvedPlan = await resolveRandomItems(plan.items.map((item) => ({
    value: item,
    randomScope: `group-${item.groupIndex}`,
    slots: {
      artist: item.combination.artist,
      character: item.combination.character,
      action: item.combination.action,
      clothing: item.combination.clothing ?? null,
    },
  })));
  return resolvedPlan.map(({ value, slots, randomSelections }) => {
    const rawCharacter = slots.character;
    const clothing = slots.clothing;
    const effectiveCharacter = rawCharacter ? {
      ...rawCharacter,
      clothingRef: clothing?.sourceRef ?? null,
      clothingNode: clothing?.draftNode ? cloneNode(clothing.draftNode) : null,
    } : null;
    return {
      ...value,
      combination: {
        ...value.combination,
        artist: slots.artist,
        character: effectiveCharacter,
        action: slots.action,
        clothing,
      },
      randomSelections,
    };
  });
}

/** 一项 Compare 的 compose 请求：用这一组的 seed，单张出图。 */
export function compareComposeRequest(item: CompareRunItem, params: RenderWorkspaceParams) {
  const runParams: RenderWorkspaceParams = { ...params, seed: String(item.groupSeed) };
  return {
    runParams,
    request: buildComposeRenderRequest(item.combination, runParams, {
      compare: true,
      promptBehavior: item.combination.promptBehavior.value,
    }),
  };
}

function initialResult(item: CompareRunItem, randomSelections: RandomSelectionRecord[] = []): CompareCombinationResult {
  return {
    runId: item.runId,
    groupIndex: item.groupIndex,
    groupSeed: item.groupSeed,
    combination: item.combination,
    labels: compareItemLabels(item.combination),
    behavior: {
      slotId: item.combination.promptBehavior.slotId,
      label: item.combination.promptBehavior.label,
      fingerprint: promptBehaviorFingerprint(item.combination.promptBehavior.value),
    },
    status: "queued",
    job: null,
    error: "",
    randomSelections,
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

  const pollJob = useCallback(async (token: number, runId: string, job: JobRecord): Promise<JobRecord> => {
    let current = job;
    while (!terminalStatuses.has(current.status)) {
      await new Promise((resolve) => window.setTimeout(resolve, pollIntervalMs));
      if (runToken.current !== token) throw new Error("Compare run cancelled");
      current = await get(`/jobs/${encodeURIComponent(job.id)}`) as JobRecord;
      // 运行中的任务也同步到卡片上，ComfyUI 的启动 / 生成阶段才看得到。
      if (!terminalStatuses.has(current.status)) updateResult(token, runId, { job: current });
    }
    return current;
  }, [get, pollIntervalMs, updateResult]);

  const start = useCallback(async (
    groups: Record<GroupRole, RoleNodeGroup>,
    params: RenderWorkspaceParams,
    promptBehaviorGroup: PromptBehaviorGroup,
  ) => {
    if (!selectedSlots(groups.character).length && !selectedSlots(groups.action).length) {
      throw new Error("Compare Generate 至少需要一个 Character 或 Action 节点。");
    }
    const token = ++runToken.current;
    const executableItems = await planCompareRun(groups, params, promptBehaviorGroup, randomSeed);
    const outputDir = outputDirFactory();
    setResults(executableItems.map((item) => initialResult(item, item.randomSelections)));
    setRunning(true);
    let nextIndex = 0;

    async function runItem(item: ExecutableCompareItem) {
      updateResult(token, item.runId, { status: "running", error: "" });
      try {
        const { runParams, request } = compareComposeRequest(item, params);
        const preview = await post("/compose-preview", request) as ComposePreviewResponse;
        if (!preview.render_request) throw new Error("该组合需要外部 Agent 先完成提示词拼接。");
        const queued = await post("/generate", buildGeneratePayload(preview.render_request, runParams, {
          output_dir: createCompareGroupOutputDir(outputDir, item.groupIndex, item.groupSeed),
          random_selections: item.randomSelections,
        })) as JobRecord;
        updateResult(token, item.runId, { job: queued });
        notifyComfyTargetsChanged(preview.render_request);
        const completed = await pollJob(token, item.runId, queued);
        notifyComfyTargetsChanged(preview.render_request);
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
        if (index >= executableItems.length) return;
        await runItem(executableItems[index]);
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
