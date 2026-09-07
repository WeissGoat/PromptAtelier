import { useCallback, useState, type ReactNode } from "react";

import { computeTagDiff } from "./tagDiff";
import type {
  BaseTemplate,
  CompareRound,
  CompareWorkspaceState,
  PromptVariant,
} from "./types";
import { CompareWorkspaceContext, type CompareWorkspaceContextValue } from "./useCompareWorkspace";

export const defaultBaseTemplate: BaseTemplate = {
  prompt: "",
  negative:
    "lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry",
  seed: -1,
  width: 1024,
  height: 1024,
  steps: 28,
  scale: 5.0,
  sampler: "k_euler",
  model: "nai-diffusion-3",
};

function makeId(prefix: string): string {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
}

export function createVariant(basePrompt: string, name: string, prompt?: string): PromptVariant {
  const text = prompt !== undefined ? prompt : basePrompt;
  return {
    id: makeId("var"),
    name,
    prompt: text,
    diff: computeTagDiff(basePrompt, text),
    seedOverride: null,
    status: "idle",
    jobId: null,
  };
}

export function CompareWorkspaceProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<CompareWorkspaceState>({
    template: defaultBaseTemplate,
    rounds: [],
    deepCompare: {
      isOpen: false,
      leftVariantId: null,
      rightVariantId: null,
      mode: "split",
    },
    isBatchRunning: false,
  });

  const setBaseTemplate = useCallback((template: BaseTemplate) => {
    setState((prev) => {
      const initialVariant = createVariant(template.prompt, "变体 1-A");
      const round1: CompareRound = {
        id: makeId("round"),
        name: "第 1 批对比",
        basePrompt: template.prompt,
        variants: [initialVariant],
        status: "idle",
      };
      return {
        ...prev,
        template,
        rounds: [round1],
      };
    });
  }, []);

  const addVariant = useCallback((roundId: string, name?: string, prompt?: string) => {
    setState((prev) => ({
      ...prev,
      rounds: prev.rounds.map((round) => {
        if (round.id !== roundId) return round;
        const letter = String.fromCharCode(65 + (round.variants.length % 26));
        const roundNum = round.name.match(/\d+/)?.[0] || "1";
        const variantName = name || `变体 ${roundNum}-${letter}`;
        const newVariant = createVariant(round.basePrompt, variantName, prompt);
        return {
          ...round,
          variants: [...round.variants, newVariant],
        };
      }),
    }));
  }, []);

  const duplicateVariant = useCallback((roundId: string, variantId: string) => {
    setState((prev) => ({
      ...prev,
      rounds: prev.rounds.map((round) => {
        if (round.id !== roundId) return round;
        const target = round.variants.find((v) => v.id === variantId);
        if (!target) return round;
        const copyName = `${target.name} (副本)`;
        const clone = createVariant(round.basePrompt, copyName, target.prompt);
        clone.seedOverride = target.seedOverride;
        return {
          ...round,
          variants: [...round.variants, clone],
        };
      }),
    }));
  }, []);

  const updateVariant = useCallback(
    (roundId: string, variantId: string, patch: Partial<PromptVariant>) => {
      setState((prev) => ({
        ...prev,
        rounds: prev.rounds.map((round) => {
          if (round.id !== roundId) return round;
          return {
            ...round,
            variants: round.variants.map((v) => {
              if (v.id !== variantId) return v;
              const updated = { ...v, ...patch };
              if (patch.prompt !== undefined) {
                updated.diff = computeTagDiff(round.basePrompt, patch.prompt);
              }
              return updated;
            }),
          };
        }),
      }));
    },
    [],
  );

  const removeVariant = useCallback((roundId: string, variantId: string) => {
    setState((prev) => ({
      ...prev,
      rounds: prev.rounds.map((round) => {
        if (round.id !== roundId) return round;
        return {
          ...round,
          variants: round.variants.filter((v) => v.id !== variantId),
        };
      }),
    }));
  }, []);

  const resetVariantToTemplate = useCallback((roundId: string, variantId: string) => {
    setState((prev) => ({
      ...prev,
      rounds: prev.rounds.map((round) => {
        if (round.id !== roundId) return round;
        return {
          ...round,
          variants: round.variants.map((v) => {
            if (v.id !== variantId) return v;
            return {
              ...v,
              prompt: round.basePrompt,
              diff: computeTagDiff(round.basePrompt, round.basePrompt),
              seedOverride: null,
            };
          }),
        };
      }),
    }));
  }, []);

  const addNewRound = useCallback((basePrompt?: string, name?: string) => {
    setState((prev) => {
      const nextIndex = prev.rounds.length + 1;
      const roundName = name || `第 ${nextIndex} 批对比`;
      const prompt = basePrompt !== undefined ? basePrompt : prev.template.prompt || "";
      const initialVariant = createVariant(prompt, `变体 ${nextIndex}-A`);
      const newRound: CompareRound = {
        id: makeId("round"),
        name: roundName,
        basePrompt: prompt,
        variants: [initialVariant],
        status: "idle",
      };
      return {
        ...prev,
        rounds: [...prev.rounds, newRound],
      };
    });
  }, []);

  const forkVariantToNewRound = useCallback((roundId: string, variantId: string) => {
    setState((prev) => {
      const sourceRound = prev.rounds.find((r) => r.id === roundId);
      const sourceVariant = sourceRound?.variants.find((v) => v.id === variantId);
      const prompt = sourceVariant ? sourceVariant.prompt : prev.template.prompt || "";
      const nextIndex = prev.rounds.length + 1;
      const roundName = `第 ${nextIndex} 批 (继承自 ${sourceVariant?.name || "上一轮"})`;
      const initialVariant = createVariant(prompt, `变体 ${nextIndex}-A`);
      const newRound: CompareRound = {
        id: makeId("round"),
        name: roundName,
        basePrompt: prompt,
        variants: [initialVariant],
        status: "idle",
      };
      return {
        ...prev,
        rounds: [...prev.rounds, newRound],
      };
    });
  }, []);

  const openDeepCompare = useCallback(
    (leftVariantId: string, rightVariantId: string, mode: "split" | "flicker" = "split") => {
      setState((prev) => ({
        ...prev,
        deepCompare: {
          isOpen: true,
          leftVariantId,
          rightVariantId,
          mode,
        },
      }));
    },
    [],
  );

  const closeDeepCompare = useCallback(() => {
    setState((prev) => ({
      ...prev,
      deepCompare: {
        ...prev.deepCompare,
        isOpen: false,
      },
    }));
  }, []);

  const findVariant = useCallback(
    (variantId: string) => {
      for (const round of state.rounds) {
        const variant = round.variants.find((v) => v.id === variantId);
        if (variant) return { round, variant };
      }
      return null;
    },
    [state.rounds],
  );

  const clearWorkspace = useCallback(() => {
    setState({
      template: defaultBaseTemplate,
      rounds: [],
      deepCompare: {
        isOpen: false,
        leftVariantId: null,
        rightVariantId: null,
        mode: "split",
      },
      isBatchRunning: false,
    });
  }, []);

  const value: CompareWorkspaceContextValue = {
    state,
    setBaseTemplate,
    addVariant,
    duplicateVariant,
    updateVariant,
    removeVariant,
    resetVariantToTemplate,
    addNewRound,
    forkVariantToNewRound,
    openDeepCompare,
    closeDeepCompare,
    findVariant,
    clearWorkspace,
  };

  return <CompareWorkspaceContext.Provider value={value}>{children}</CompareWorkspaceContext.Provider>;
}
