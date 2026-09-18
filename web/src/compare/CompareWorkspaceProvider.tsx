import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import {
  clearCompareWorkspaceSnapshot,
  createDefaultCompareWorkspace,
  defaultCompareTemplate,
  loadCompareWorkspaceSnapshot,
  saveCompareWorkspaceSnapshot,
} from "./storage";
import { applyTagDiff, computeTagDiff } from "./tagDiff";
import type {
  BaseTemplate,
  CompareRound,
  CompareWorkspaceState,
  PromptVariant,
} from "./types";
import { CompareWorkspaceContext, type CompareWorkspaceContextValue } from "./useCompareWorkspace";

export const defaultBaseTemplate: BaseTemplate = defaultCompareTemplate;

function makeId(prefix: string): string {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
}

export function createVariant(basePrompt: string, name: string, prompt?: string): PromptVariant {
  const text = prompt !== undefined ? prompt : basePrompt;
  const diff = computeTagDiff(basePrompt, text);
  return {
    id: makeId("var"),
    name,
    prompt: text,
    diff,
    inheritedDiff: { added: [...diff.added], removed: [...diff.removed] },
    seedOverride: null,
    status: "idle",
    jobId: null,
  };
}

export function CompareWorkspaceProvider({ children }: { children: ReactNode }) {
  const initial = useMemo(() => {
    if (typeof window === "undefined" || !window.localStorage) {
      return createDefaultCompareWorkspace();
    }
    return loadCompareWorkspaceSnapshot(window.localStorage).state;
  }, []);

  const [state, setState] = useState<CompareWorkspaceState>(initial);

  useEffect(() => {
    if (typeof window === "undefined" || !window.localStorage) return;
    const timer = window.setTimeout(() => {
      saveCompareWorkspaceSnapshot(window.localStorage, state);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [state]);

  const setBaseTemplate = useCallback((template: BaseTemplate) => {
    setState((prev) => {
      if (prev.rounds.length === 0) {
        const initialVariant = createVariant(template.prompt, "变体 1-A");
        const round1: CompareRound = {
          id: makeId("round"),
          name: "第 1 批对比",
          template,
          basePrompt: template.prompt,
          variants: [initialVariant],
          status: "idle",
        };
        return {
          ...prev,
          template,
          rounds: [round1],
        };
      }
      const firstRoundId = prev.rounds[0].id;
      const updatedRounds = prev.rounds.map((round) => {
        if (round.id !== firstRoundId) return round;
        const updatedVariants: PromptVariant[] = round.variants.map((v) => {
          const diffToApply =
            v.inheritedDiff && (v.inheritedDiff.added.length > 0 || v.inheritedDiff.removed.length > 0)
              ? v.inheritedDiff
              : v.diff && (v.diff.added.length > 0 || v.diff.removed.length > 0)
              ? { added: [...v.diff.added], removed: [...v.diff.removed] }
              : { added: [], removed: [] };
          const newPrompt = applyTagDiff(template.prompt, diffToApply);
          const newDiff = computeTagDiff(template.prompt, newPrompt);
          return {
            ...v,
            prompt: newPrompt,
            diff: newDiff,
            inheritedDiff: { added: [...diffToApply.added], removed: [...diffToApply.removed] },
            resultImage: undefined,
            status: "idle" as const,
            jobId: null,
            error: undefined,
          };
        });
        return {
          ...round,
          template,
          basePrompt: template.prompt,
          variants: updatedVariants,
          status: "idle" as const,
        };
      });
      return {
        ...prev,
        template,
        rounds: updatedRounds,
      };
    });
  }, []);

  const setRoundTemplate = useCallback((roundId: string, template: BaseTemplate) => {
    setState((prev) => ({
      ...prev,
      template,
      rounds: prev.rounds.map((round) => {
        if (round.id !== roundId) return round;
        const updatedVariants: PromptVariant[] = round.variants.map((v) => {
          const diffToApply =
            v.inheritedDiff && (v.inheritedDiff.added.length > 0 || v.inheritedDiff.removed.length > 0)
              ? v.inheritedDiff
              : v.diff && (v.diff.added.length > 0 || v.diff.removed.length > 0)
              ? { added: [...v.diff.added], removed: [...v.diff.removed] }
              : { added: [], removed: [] };
          const newPrompt = applyTagDiff(template.prompt, diffToApply);
          const newDiff = computeTagDiff(template.prompt, newPrompt);
          return {
            ...v,
            prompt: newPrompt,
            diff: newDiff,
            inheritedDiff: { added: [...diffToApply.added], removed: [...diffToApply.removed] },
            resultImage: undefined,
            status: "idle" as const,
            jobId: null,
            error: undefined,
          };
        });
        return {
          ...round,
          template,
          basePrompt: template.prompt,
          variants: updatedVariants,
          status: "idle" as const,
        };
      }),
    }));
  }, []);

  const syncRoundVariantsToTemplate = useCallback((roundId: string) => {
    setState((prev) => ({
      ...prev,
      rounds: prev.rounds.map((round) => {
        if (round.id !== roundId) return round;
        const targetPrompt = round.template.prompt;
        const updatedVariants: PromptVariant[] = round.variants.map((v) => ({
          ...v,
          prompt: targetPrompt,
          diff: computeTagDiff(targetPrompt, targetPrompt),
          inheritedDiff: { added: [], removed: [] },
          seedOverride: null,
          resultImage: undefined,
          status: "idle" as const,
          jobId: null,
          error: undefined,
        }));
        return {
          ...round,
          basePrompt: targetPrompt,
          variants: updatedVariants,
          status: "idle" as const,
        };
      }),
    }));
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
        clone.inheritedDiff = target.inheritedDiff
          ? { added: [...target.inheritedDiff.added], removed: [...target.inheritedDiff.removed] }
          : { added: [...target.diff.added], removed: [...target.diff.removed] };
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
                const newDiff = computeTagDiff(round.basePrompt, patch.prompt);
                updated.diff = newDiff;
                updated.inheritedDiff = { added: [...newDiff.added], removed: [...newDiff.removed] };
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

  const reorderVariants = useCallback((roundId: string, sourceIndex: number, targetIndex: number) => {
    setState((prev) => ({
      ...prev,
      rounds: prev.rounds.map((round) => {
        if (round.id !== roundId) return round;
        if (
          sourceIndex < 0 ||
          sourceIndex >= round.variants.length ||
          targetIndex < 0 ||
          targetIndex >= round.variants.length ||
          sourceIndex === targetIndex
        ) {
          return round;
        }
        const updated = [...round.variants];
        const [moved] = updated.splice(sourceIndex, 1);
        updated.splice(targetIndex, 0, moved);
        return {
          ...round,
          variants: updated,
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
              inheritedDiff: { added: [], removed: [] },
              seedOverride: null,
            };
          }),
        };
      }),
    }));
  }, []);

  const addNewRound = useCallback((sourceRoundId?: string, name?: string): string => {
    const newRoundId = makeId("round");
    setState((prev) => {
      const nextIndex = prev.rounds.length + 1;
      const roundName = name || `第 ${nextIndex} 批对比`;

      const sourceRound = sourceRoundId
        ? prev.rounds.find((r) => r.id === sourceRoundId)
        : prev.rounds.length > 0
        ? prev.rounds[prev.rounds.length - 1]
        : null;

      if (sourceRound) {
        const clonedTemplate: BaseTemplate = { ...sourceRound.template };
        const variants: PromptVariant[] = sourceRound.variants.map((v, idx) => {
          const letter = String.fromCharCode(65 + (idx % 26));
          const diffToInherit =
            (v.diff.added.length > 0 || v.diff.removed.length > 0)
              ? { added: [...v.diff.added], removed: [...v.diff.removed] }
              : (v.inheritedDiff ?? { added: [], removed: [] });
          const prompt = applyTagDiff(clonedTemplate.prompt, diffToInherit);
          const diff = computeTagDiff(clonedTemplate.prompt, prompt);
          const variantName = v.name ? v.name.replace(/变体\s*\d+-/, `变体 ${nextIndex}-`) : `变体 ${nextIndex}-${letter}`;
          return {
            id: makeId("var"),
            name: variantName,
            prompt,
            diff,
            inheritedDiff: diffToInherit,
            seedOverride: v.seedOverride,
            status: "idle" as const,
            jobId: null,
          };
        });

        const newRound: CompareRound = {
          id: newRoundId,
          name: roundName,
          template: clonedTemplate,
          basePrompt: clonedTemplate.prompt,
          variants: variants.length > 0 ? variants : [createVariant(clonedTemplate.prompt, `变体 ${nextIndex}-A`)],
          status: "idle",
        };

        const sourceIndex = sourceRoundId
          ? prev.rounds.findIndex((r) => r.id === sourceRoundId)
          : prev.rounds.length - 1;
        const nextRounds = [...prev.rounds];
        if (sourceIndex >= 0) {
          nextRounds.splice(sourceIndex + 1, 0, newRound);
        } else {
          nextRounds.push(newRound);
        }

        return {
          ...prev,
          rounds: nextRounds,
        };
      }

      const prompt = prev.template.prompt || "";
      const initialVariant = createVariant(prompt, `变体 ${nextIndex}-A`);
      const newRound: CompareRound = {
        id: newRoundId,
        name: roundName,
        template: { ...prev.template },
        basePrompt: prompt,
        variants: [initialVariant],
        status: "idle",
      };
      return {
        ...prev,
        rounds: [...prev.rounds, newRound],
      };
    });
    return newRoundId;
  }, []);

  const removeRound = useCallback((roundId: string) => {
    setState((prev) => {
      if (prev.rounds.length <= 1) return prev;
      const targetRound = prev.rounds.find((r) => r.id === roundId);
      const targetVariantIds = new Set(targetRound?.variants.map((v) => v.id) || []);

      const shouldResetDeepCompare =
        (prev.deepCompare.leftVariantId && targetVariantIds.has(prev.deepCompare.leftVariantId)) ||
        (prev.deepCompare.rightVariantId && targetVariantIds.has(prev.deepCompare.rightVariantId));

      return {
        ...prev,
        rounds: prev.rounds.filter((r) => r.id !== roundId),
        deepCompare: shouldResetDeepCompare
          ? { isOpen: false, leftVariantId: null, rightVariantId: null, mode: "split" }
          : prev.deepCompare,
      };
    });
  }, []);

  const reorderRounds = useCallback((sourceIndex: number, targetIndex: number) => {
    setState((prev) => {
      if (
        sourceIndex < 0 ||
        sourceIndex >= prev.rounds.length ||
        targetIndex < 0 ||
        targetIndex >= prev.rounds.length ||
        sourceIndex === targetIndex
      ) {
        return prev;
      }
      const updated = [...prev.rounds];
      const [moved] = updated.splice(sourceIndex, 1);
      updated.splice(targetIndex, 0, moved);
      return {
        ...prev,
        rounds: updated,
      };
    });
  }, []);

  const forkVariantToNewRound = useCallback((roundId: string, variantId: string): string => {
    const newRoundId = makeId("round");
    setState((prev) => {
      const sourceRound = prev.rounds.find((r) => r.id === roundId);
      const sourceVariant = sourceRound?.variants.find((v) => v.id === variantId);
      const prompt = sourceVariant ? sourceVariant.prompt : prev.template.prompt || "";
      const nextIndex = prev.rounds.length + 1;
      const roundName = `第 ${nextIndex} 批 (继承自 ${sourceVariant?.name || "上一轮"})`;
      const template: BaseTemplate = sourceRound
        ? { ...sourceRound.template, prompt }
        : { ...prev.template, prompt };
      const initialVariant = createVariant(prompt, `变体 ${nextIndex}-A`);
      const newRound: CompareRound = {
        id: newRoundId,
        name: roundName,
        template,
        basePrompt: prompt,
        variants: [initialVariant],
        status: "idle",
      };
      const sourceIndex = prev.rounds.findIndex((r) => r.id === roundId);
      const nextRounds = [...prev.rounds];
      if (sourceIndex >= 0) {
        nextRounds.splice(sourceIndex + 1, 0, newRound);
      } else {
        nextRounds.push(newRound);
      }
      return {
        ...prev,
        rounds: nextRounds,
      };
    });
    return newRoundId;
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
    if (typeof window !== "undefined" && window.localStorage) {
      clearCompareWorkspaceSnapshot(window.localStorage);
    }
    setState(createDefaultCompareWorkspace());
  }, []);

  const value: CompareWorkspaceContextValue = {
    state,
    setBaseTemplate,
    setRoundTemplate,
    addVariant,
    duplicateVariant,
    updateVariant,
    removeVariant,
    reorderVariants,
    resetVariantToTemplate,
    syncRoundVariantsToTemplate,
    addNewRound,
    removeRound,
    reorderRounds,
    forkVariantToNewRound,
    openDeepCompare,
    closeDeepCompare,
    findVariant,
    clearWorkspace,
  };

  return <CompareWorkspaceContext.Provider value={value}>{children}</CompareWorkspaceContext.Provider>;
}
