import { Columns, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import type { CompareRound, PromptVariant } from "../compare/types";
import { useCompareBatchRunner } from "../compare/useCompareBatchRunner";
import { CompareWorkspaceProvider } from "../compare/CompareWorkspaceProvider";
import { useCompareWorkspace } from "../compare/useCompareWorkspace";
import { CompareRoundSection } from "../components/CompareRoundSection";
import { CompareTemplateBar } from "../components/CompareTemplateBar";
import { DeepCompareModal } from "../components/DeepCompareModal";

function CompareStudioContent() {
  const { state, updateVariant, addNewRound, openDeepCompare, closeDeepCompare, findVariant } =
    useCompareWorkspace();
  const { runVariant, runRound, isBusy } = useCompareBatchRunner();

  const [selectedVariantIds, setSelectedVariantIds] = useState<string[]>([]);

  function toggleSelectVariant(id: string) {
    setSelectedVariantIds((prev) => {
      if (prev.includes(id)) {
        return prev.filter((item) => item !== id);
      }
      if (prev.length >= 2) {
        // Keep the second one and add the new one
        return [prev[1], id];
      }
      return [...prev, id];
    });
  }

  const leftVariant =
    state.deepCompare.leftVariantId ? findVariant(state.deepCompare.leftVariantId)?.variant ?? null : null;
  const rightVariant =
    state.deepCompare.rightVariantId ? findVariant(state.deepCompare.rightVariantId)?.variant ?? null : null;

  const canOpenDeepCompare =
    selectedVariantIds.length === 2 &&
    findVariant(selectedVariantIds[0])?.variant.resultImage &&
    findVariant(selectedVariantIds[1])?.variant.resultImage;

  return (
    <main className="page-panel compare-page">
      <div className="compare-page-header">
        <div className="page-title">
          <h2>Compare Studio (提示词对比工坊)</h2>
          <span className="status-pill">
            {state.rounds.length > 0 ? `${state.rounds.length} 轮批次` : "就绪"}
          </span>
        </div>
      </div>

      <CompareTemplateBar />

      <div className="compare-rounds-container">
        {state.rounds.map((round) => (
          <CompareRoundSection
            canDeleteRound={state.rounds.length > 1}
            isBusy={isBusy}
            key={round.id}
            onRunRound={(r) =>
              runRound(r.variants, state.template, (vId, patch) => {
                updateVariant(r.id, vId, patch);
              })
            }
            onRunVariant={(v) =>
              runVariant(v, state.template, (patch) => {
                updateVariant(round.id, v.id, patch);
              })
            }
            onToggleSelectVariant={toggleSelectVariant}
            round={round}
            selectedVariantIds={selectedVariantIds}
            template={state.template}
          />
        ))}
      </div>

      <div className="compare-page-footer-actions">
        <button
          className="add-round-downward-btn"
          onClick={() => addNewRound()}
          type="button"
        >
          <Plus size={18} /> 往下新增新的一批对比 (New Batch Below)
        </button>
      </div>

      {/* Floating comparison bar when cards are selected */}
      {selectedVariantIds.length > 0 ? (
        <aside className="floating-compare-bar" role="toolbar">
          <div className="floating-bar-info">
            <span>已选择 {selectedVariantIds.length} / 2 张图片进行比对</span>
          </div>

          <div className="floating-bar-actions">
            <button
              className="primary-button compact"
              disabled={!canOpenDeepCompare}
              onClick={() => {
                if (selectedVariantIds.length === 2) {
                  openDeepCompare(selectedVariantIds[0], selectedVariantIds[1], "split");
                }
              }}
              type="button"
            >
              <Columns size={14} /> 进入深度视觉对比 (Deep Compare)
            </button>
            <button
              className="secondary-button compact"
              onClick={() => setSelectedVariantIds([])}
              type="button"
            >
              清空勾选
            </button>
          </div>
        </aside>
      ) : null}

      {/* Deep Compare Modal */}
      <DeepCompareModal
        isOpen={state.deepCompare.isOpen}
        leftVariant={leftVariant}
        onClose={closeDeepCompare}
        rightVariant={rightVariant}
      />
    </main>
  );
}

export function CompareStudio() {
  return (
    <CompareWorkspaceProvider>
      <CompareStudioContent />
    </CompareWorkspaceProvider>
  );
}
