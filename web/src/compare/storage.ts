import { apiUrl } from "../api/client";
import type { BaseTemplate, CompareRound, CompareWorkspaceState, PromptVariant } from "./types";

export const COMPARE_WORKSPACE_STORAGE_KEY = "promptatelier.compare-workspace/v1";
export const COMPARE_WORKSPACE_SCHEMA = "promptatelier.compare-workspace/v1";

export const defaultCompareTemplate: BaseTemplate = {
  prompt: "",
  negative:
    "lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry",
  seed: -1,
  width: 1024,
  height: 1024,
  steps: 28,
  scale: 5.0,
  sampler: "k_euler",
  model: "nai-diffusion-4-5-full",
};

export function createDefaultCompareWorkspace(): CompareWorkspaceState {
  return {
    template: defaultCompareTemplate,
    rounds: [],
    deepCompare: {
      isOpen: false,
      leftVariantId: null,
      rightVariantId: null,
      mode: "split",
    },
    isBatchRunning: false,
  };
}

export type CompareWorkspaceLoadResult =
  | { status: "empty"; state: CompareWorkspaceState }
  | { status: "loaded"; state: CompareWorkspaceState }
  | { status: "invalid"; state: CompareWorkspaceState; message: string };

function sanitizeTemplate(template: BaseTemplate): BaseTemplate {
  if (!template) return defaultCompareTemplate;
  const sanitized = { ...template };
  if (sanitized.sourceImage) {
    const src = { ...sanitized.sourceImage };
    if (src.previewUrl?.startsWith("data:") && src.sourcePath) {
      src.previewUrl = apiUrl(`/results/image?path=${encodeURIComponent(src.sourcePath)}`);
    }
    sanitized.sourceImage = src;
  }
  return sanitized;
}

function sanitizeVariant(variant: PromptVariant): PromptVariant {
  return {
    ...variant,
    status: variant.status === "running" || variant.status === "queued" ? "idle" : variant.status,
    jobId: variant.status === "running" || variant.status === "queued" ? null : variant.jobId,
  };
}

export function saveCompareWorkspaceSnapshot(storage: Storage, state: CompareWorkspaceState): void {
  try {
    const sanitizedTemplate = sanitizeTemplate(state.template);
    const sanitizedRounds: CompareRound[] = state.rounds.map((round) => ({
      ...round,
      template: sanitizeTemplate(round.template),
      variants: round.variants.map(sanitizeVariant),
      status: round.status === "running" ? "idle" : round.status,
    }));

    const payload = {
      schema: COMPARE_WORKSPACE_SCHEMA,
      template: sanitizedTemplate,
      rounds: sanitizedRounds,
    };

    storage.setItem(COMPARE_WORKSPACE_STORAGE_KEY, JSON.stringify(payload));
  } catch (error) {
    console.warn("Failed to persist compare workspace to storage:", error);
  }
}

export function loadCompareWorkspaceSnapshot(storage: Storage): CompareWorkspaceLoadResult {
  try {
    const raw = storage.getItem(COMPARE_WORKSPACE_STORAGE_KEY);
    if (!raw) {
      return { status: "empty", state: createDefaultCompareWorkspace() };
    }

    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") {
      return { status: "invalid", state: createDefaultCompareWorkspace(), message: "Snapshot is not an object" };
    }
    if (parsed.schema !== COMPARE_WORKSPACE_SCHEMA) {
      return { status: "invalid", state: createDefaultCompareWorkspace(), message: "Snapshot schema mismatch" };
    }
    if (!parsed.template || !Array.isArray(parsed.rounds)) {
      return { status: "invalid", state: createDefaultCompareWorkspace(), message: "Snapshot missing template or rounds" };
    }

    const state: CompareWorkspaceState = {
      template: parsed.template,
      rounds: parsed.rounds,
      deepCompare: {
        isOpen: false,
        leftVariantId: null,
        rightVariantId: null,
        mode: "split",
      },
      isBatchRunning: false,
    };

    return { status: "loaded", state };
  } catch (error) {
    return {
      status: "invalid",
      state: createDefaultCompareWorkspace(),
      message: error instanceof Error ? error.message : String(error),
    };
  }
}

export function clearCompareWorkspaceSnapshot(storage: Storage): void {
  try {
    storage.removeItem(COMPARE_WORKSPACE_STORAGE_KEY);
  } catch (error) {
    console.warn("Failed to clear compare workspace storage:", error);
  }
}
