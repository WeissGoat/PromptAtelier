import { apiDelete, apiGet, apiPost, apiUrl } from "../api/client";
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

export function sanitizeTemplate(template: BaseTemplate, pruneHeavy = false): BaseTemplate {
  if (!template) return defaultCompareTemplate;
  const sanitized = { ...template };
  if (sanitized.sourceImage) {
    const src = { ...sanitized.sourceImage };
    if (src.previewUrl?.startsWith("data:")) {
      if (src.sourcePath) {
        src.previewUrl = apiUrl(`/results/image?path=${encodeURIComponent(src.sourcePath)}`);
      } else {
        // Never keep multi-megabyte base64 strings in persistent state
        delete (src as Partial<typeof src>).previewUrl;
      }
    }
    sanitized.sourceImage = src;
  }

  if (pruneHeavy) {
    delete sanitized.raw_parameters;
  } else if (sanitized.raw_parameters && typeof sanitized.raw_parameters === "object") {
    // Remove heavy binary/base64 vibe transfer arrays from raw_parameters to prevent quota overflow
    const cleanedParams = { ...sanitized.raw_parameters };
    delete cleanedParams.reference_image_multiple;
    delete cleanedParams.reference_information_extracted_multiple;
    delete cleanedParams.extra_passthrough_testing;
    delete cleanedParams.signed_hash;
    delete cleanedParams.request_type;
    delete cleanedParams.uc;
    sanitized.raw_parameters = cleanedParams;
  }

  return sanitized;
}

export function sanitizeVariant(variant: PromptVariant): PromptVariant {
  return {
    ...variant,
    status: variant.status === "running" || variant.status === "queued" ? "idle" : variant.status,
    jobId: variant.status === "running" || variant.status === "queued" ? null : variant.jobId,
  };
}

export interface CompareWorkspacePayload {
  schema: string;
  template: BaseTemplate;
  rounds: CompareRound[];
}

export function serializeCompareWorkspacePayload(
  state: CompareWorkspaceState,
  pruneHeavy = false,
): CompareWorkspacePayload {
  const sanitizedTemplate = sanitizeTemplate(state.template, pruneHeavy);
  const sanitizedRounds: CompareRound[] = state.rounds.map((round) => ({
    ...round,
    template: sanitizeTemplate(round.template, pruneHeavy),
    variants: round.variants.map(sanitizeVariant),
    status: round.status === "running" ? "idle" : round.status,
  }));

  return {
    schema: COMPARE_WORKSPACE_SCHEMA,
    template: sanitizedTemplate,
    rounds: sanitizedRounds,
  };
}

export function saveCompareWorkspaceSnapshot(storage: Storage, state: CompareWorkspaceState): void {
  try {
    const payload = serializeCompareWorkspacePayload(state, false);
    storage.setItem(COMPARE_WORKSPACE_STORAGE_KEY, JSON.stringify(payload));
  } catch (error) {
    // If quota exceeded or other error, retry with aggressive pruning (drop raw_parameters)
    try {
      console.warn("Storage write failed, attempting aggressive prune...", error);
      const prunedPayload = serializeCompareWorkspacePayload(state, true);
      storage.setItem(COMPARE_WORKSPACE_STORAGE_KEY, JSON.stringify(prunedPayload));
    } catch (retryError) {
      console.error("Failed to persist compare workspace to storage even after pruning:", retryError);
    }
  }
}

export function parseCompareWorkspacePayload(raw: unknown): CompareWorkspaceLoadResult {
  if (!raw) {
    return { status: "empty", state: createDefaultCompareWorkspace() };
  }

  try {
    const parsed = typeof raw === "string" ? JSON.parse(raw) : raw;
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

export function loadCompareWorkspaceSnapshot(storage: Storage): CompareWorkspaceLoadResult {
  try {
    const raw = storage.getItem(COMPARE_WORKSPACE_STORAGE_KEY);
    return parseCompareWorkspacePayload(raw);
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

export async function fetchCompareWorkspaceFromBackend(): Promise<CompareWorkspaceLoadResult> {
  try {
    const data = await apiGet<CompareWorkspacePayload>("/compare/workspace");
    return parseCompareWorkspacePayload(data);
  } catch {
    return { status: "empty", state: createDefaultCompareWorkspace() };
  }
}

export async function saveCompareWorkspaceToBackend(state: CompareWorkspaceState): Promise<boolean> {
  try {
    const payload = serializeCompareWorkspacePayload(state, false);
    await apiPost("/compare/workspace", payload);
    return true;
  } catch (err) {
    console.warn("Failed to autosave compare workspace to backend:", err);
    return false;
  }
}

export async function clearCompareWorkspaceFromBackend(): Promise<boolean> {
  try {
    await apiDelete("/compare/workspace");
    return true;
  } catch (err) {
    console.warn("Failed to clear compare workspace on backend:", err);
    return false;
  }
}
