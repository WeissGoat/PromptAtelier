import { createContext, useContext } from "react";

import type {
  BaseTemplate,
  CompareRound,
  CompareWorkspaceState,
  PromptVariant,
} from "./types";

export type CompareWorkspaceContextValue = {
  state: CompareWorkspaceState;
  setBaseTemplate: (template: BaseTemplate) => void;
  setRoundTemplate: (roundId: string, template: BaseTemplate) => void;
  addVariant: (roundId: string, name?: string, prompt?: string) => void;
  duplicateVariant: (roundId: string, variantId: string) => void;
  updateVariant: (roundId: string, variantId: string, patch: Partial<PromptVariant>) => void;
  removeVariant: (roundId: string, variantId: string) => void;
  reorderVariants: (roundId: string, sourceIndex: number, targetIndex: number) => void;
  resetVariantToTemplate: (roundId: string, variantId: string) => void;
  syncRoundVariantsToTemplate: (roundId: string) => void;
  addNewRound: (sourceRoundId?: string, name?: string) => string;
  removeRound: (roundId: string) => void;
  reorderRounds: (sourceIndex: number, targetIndex: number) => void;
  forkVariantToNewRound: (roundId: string, variantId: string) => string;
  openDeepCompare: (leftVariantId: string, rightVariantId: string, mode?: "split" | "flicker") => void;
  closeDeepCompare: () => void;
  findVariant: (variantId: string) => { round: CompareRound; variant: PromptVariant } | null;
  clearWorkspace: () => void;
};

export const CompareWorkspaceContext = createContext<CompareWorkspaceContextValue | null>(null);

export function useCompareWorkspace(): CompareWorkspaceContextValue {
  const context = useContext(CompareWorkspaceContext);
  if (!context) {
    throw new Error("useCompareWorkspace must be used within CompareWorkspaceProvider");
  }
  return context;
}
