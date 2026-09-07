import { useCallback, useRef, useState } from "react";

import { apiGet, apiPost, apiUrl, errorMessage } from "../api/client";
import type { JobRecord } from "../api/types";
import type { BaseTemplate, PromptVariant } from "./types";

const terminalJobStatuses = new Set<JobRecord["status"]>(["succeeded", "failed", "cancelled"]);

export function normalizeNovelAIModel(raw?: string): string {
  if (!raw) return "nai-diffusion-4-5-full";
  const lower = raw.trim().toLowerCase();
  if (lower.includes("furry")) return "nai-diffusion-furry-3";
  if (lower.includes("4.5") || lower.includes("4-5") || lower.includes("v4.5")) {
    return lower.includes("curated") ? "nai-diffusion-4-5-curated" : "nai-diffusion-4-5-full";
  }
  if (
    lower.includes("v4") ||
    lower.includes("4-full") ||
    lower.includes("diffusion 4") ||
    lower.includes("diffusion-4")
  ) {
    return lower.includes("curated") ? "nai-diffusion-4-curated" : "nai-diffusion-4-full";
  }
  if (lower.includes("v3") || lower.includes("diffusion 3") || lower.includes("diffusion-3")) {
    return "nai-diffusion-3";
  }
  if (lower.includes("safe")) return "safe-diffusion";
  if (lower.includes("v2")) return "nai-diffusion-2";
  if (lower.startsWith("nai-diffusion")) return lower;
  return "nai-diffusion-4-5-full";
}

type RunnerOptions = {
  concurrency?: number;
  pollIntervalMs?: number;
  post?: (path: string, body: unknown) => Promise<unknown>;
  get?: (path: string) => Promise<unknown>;
};

export function useCompareBatchRunner(options: RunnerOptions = {}) {
  const [isBusy, setIsBusy] = useState(false);
  const abortRef = useRef(false);

  const post = options.post ?? apiPost;
  const get = options.get ?? apiGet;
  const pollIntervalMs = options.pollIntervalMs ?? 500;

  const runVariant = useCallback(
    async (
      variant: PromptVariant,
      template: BaseTemplate,
      onUpdate: (patch: Partial<PromptVariant>) => void,
    ) => {
      onUpdate({ status: "queued", error: undefined });

      const seed =
        variant.seedOverride !== null && variant.seedOverride !== undefined
          ? variant.seedOverride
          : template.seed > 0
          ? template.seed
          : Math.floor(Math.random() * 0x1_0000_0000);

      const requestBody = {
        render_request: {
          backend: "novelai",
          prompt: variant.prompt,
          negative_prompt: template.negative,
          model: normalizeNovelAIModel(template.model),
          seed,
          size: {
            width: template.width,
            height: template.height,
          },
          params: {
            seed,
            width: template.width,
            height: template.height,
            steps: template.steps,
            scale: template.scale,
            sampler: template.sampler || "k_euler",
          },
          meta: {
            source: "compare_studio",
            variant_id: variant.id,
            variant_name: variant.name,
          },
        },
      };

      try {
        const job = (await post("/generate", requestBody)) as JobRecord;
        onUpdate({ status: "running", jobId: job.id });

        let current = job;
        while (!terminalJobStatuses.has(current.status) && !abortRef.current) {
          await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
          current = (await get(`/jobs/${encodeURIComponent(current.id)}`)) as JobRecord;
          onUpdate({ status: current.status as PromptVariant["status"] });
        }

        if (current.status === "succeeded") {
          const image = current.result?.images?.[0];
          if (image) {
            const resultSeed = image.meta?.seed ?? seed;
            const url = apiUrl(`/results/image?path=${encodeURIComponent(image.path)}`);
            onUpdate({
              status: "succeeded",
              jobId: current.id,
              resultImage: {
                path: image.path,
                url,
                seed: Number(resultSeed),
              },
            });
          } else {
            onUpdate({ status: "succeeded", jobId: current.id });
          }
        } else {
          const rawErr = current.error;
          const errMsg =
            typeof rawErr === "object" && rawErr !== null
              ? (rawErr as { message?: string }).message || JSON.stringify(rawErr)
              : String(rawErr || `Generation ${current.status}`);
          onUpdate({
            status: "failed",
            jobId: current.id,
            error: errMsg,
          });
        }
      } catch (err) {
        onUpdate({
          status: "failed",
          error: errorMessage(err),
        });
      }
    },
    [get, pollIntervalMs, post],
  );

  const runRound = useCallback(
    async (
      variants: PromptVariant[],
      template: BaseTemplate,
      onUpdate: (variantId: string, patch: Partial<PromptVariant>) => void,
    ) => {
      setIsBusy(true);
      abortRef.current = false;

      try {
        for (const variant of variants) {
          if (abortRef.current) break;
          await runVariant(variant, template, (patch) => onUpdate(variant.id, patch));
        }
      } finally {
        setIsBusy(false);
      }
    },
    [runVariant],
  );

  const stop = useCallback(() => {
    abortRef.current = true;
    setIsBusy(false);
  }, []);

  return {
    runVariant,
    runRound,
    isBusy,
    stop,
  };
}
