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
  addVariant: (roundId: string, name?: string, prompt?: string) => void;
  duplicateVariant: (roundId: string, variantId: string) => void;
  updateVariant: (roundId: string, variantId: string, patch: Partial<PromptVariant>) => void;
  removeVariant: (roundId: string, variantId: string) => void;
  resetVariantToTemplate: (roundId: string, variantId: string) => void;
  addNewRound: (basePrompt?: string, name?: string) => void;
  forkVariantToNewRound: (roundId: string, variantId: string) => void;
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
