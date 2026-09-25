import { Columns, History, Loader2, Plus, RotateCcw } from "lucide-react";
import { useCallback, useState } from "react";

import { getVariantIdentityMap } from "../compare/runnableVariants";
import type { BaseTemplate, CompareRound } from "../compare/types";
import { useCompareBatchRunner, type RoundRunTask } from "../compare/useCompareBatchRunner";
import { CompareWorkspaceProvider } from "../compare/CompareWorkspaceProvider";
import { useCompareWorkspace } from "../compare/useCompareWorkspace";
import { CompareIndexSidebar } from "../components/CompareIndexSidebar";
import { CompareRoundSection } from "../components/CompareRoundSection";
import { CompareTemplateBar } from "../components/CompareTemplateBar";
import { DeepCompareModal } from "../components/DeepCompareModal";
import { ImageDetailDialog, type ImageDetailItem } from "../components/ImageDetailDialog";

function CompareStudioContent() {
  const {
    state,
    updateVariant,
    addNewRound,
    batchDeriveRounds,
    openDeepCompare,
    closeDeepCompare,
    findVariant,
    clearWorkspace,
    restoreBackendWorkspace,
  } = useCompareWorkspace();
  const {
    runVariant,
    runRound,
    runRoundsSequence,
    queueProgress,
    isBusy,
    stop,
  } = useCompareBatchRunner();

  const [selectedVariantIds, setSelectedVariantIds] = useState<string[]>([]);
  const [selectedDetailImage, setSelectedDetailImage] = useState<{
    paths?: string[];
    items?: ImageDetailItem[];
    index: number;
  } | null>(null);
  const [activeRoundId, setActiveRoundId] = useState<string>(state.rounds[0]?.id || "");
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState<boolean>(false);

  function toggleSelectVariant(id: string) {
    setSelectedVariantIds((prev) => {
      if (prev.includes(id)) {
        return prev.filter((item) => item !== id);
      }
      if (prev.length >= 2) {
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

  const handleBatchDerive = useCallback(
    (
      sourceRound: CompareRound,
      items: Array<{ template: BaseTemplate; filename: string }>,
      autoRun: boolean,
    ) => {
      const createdRounds = batchDeriveRounds(sourceRound.id, items);
      if (createdRounds.length === 0) return;

      if (autoRun) {
        const tasks: RoundRunTask[] = createdRounds.map((r) => {
          const identityMap = getVariantIdentityMap(r.variants, r.template);
          const runnable = r.variants.filter((v) => identityMap.get(v.id)?.isRunnable ?? true);
          return {
            roundId: r.id,
            roundName: r.name,
            template: r.template,
            variants: runnable,
          };
        });

        void runRoundsSequence(tasks, (roundId, variantId, patch) => {
          updateVariant(roundId, variantId, patch);
        });
      }
    },
    [batchDeriveRounds, runRoundsSequence, updateVariant],
  );

  const [isRestoring, setIsRestoring] = useState(false);
  const [restoreMessage, setRestoreMessage] = useState<string | null>(null);

  const handleRestore = useCallback(async () => {
    setIsRestoring(true);
    setRestoreMessage(null);
    try {
      const ok = await restoreBackendWorkspace();
      if (ok) {
        setRestoreMessage("已恢复最近自动保存的批次与生成图片");
        setTimeout(() => setRestoreMessage(null), 4000);
      } else {
        setRestoreMessage("未找到可恢复的服务端快照");
        setTimeout(() => setRestoreMessage(null), 3000);
      }
    } finally {
      setIsRestoring(false);
    }
  }, [restoreBackendWorkspace]);

  return (
    <main className="page-panel compare-page">
      <div className="compare-page-header">
        <div className="page-title">
          <h2>Compare Studio (提示词对比工坊)</h2>
          <span className="status-pill">
            {state.rounds.length > 0 ? `${state.rounds.length} 轮批次` : "就绪"}
          </span>
          {restoreMessage ? (
            <span style={{ fontSize: 12, color: "#10b981", marginLeft: 8, fontWeight: 500 }}>
              {restoreMessage}
            </span>
          ) : null}
        </div>
        <div className="compare-header-actions" style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button
            className="secondary-button compact"
            onClick={handleRestore}
            disabled={isRestoring}
            title="从服务端自动备份恢复最近对比批次"
            type="button"
          >
            {isRestoring ? <Loader2 className="spinning" size={14} /> : <History size={14} />} 找回/恢复最近对比
          </button>
          {state.rounds.length > 0 ? (
            <button
              className="secondary-button compact"
              onClick={clearWorkspace}
              title="清空重置全部对比批次"
              type="button"
            >
              <RotateCcw size={14} /> 清空工作区
            </button>
          ) : null}
        </div>
      </div>

      {state.rounds.length === 0 ? (
        <>
          <CompareTemplateBar />
          <div className="compare-page-footer-actions" style={{ display: "flex", flexDirection: "column", gap: 8, alignItems: "center" }}>
            <button
              className="add-round-downward-btn"
              onClick={() => {
                const newId = addNewRound();
                setActiveRoundId(newId);
              }}
              type="button"
            >
              <Plus size={18} /> 往下新增新的一批对比 (New Batch Below)
            </button>
            <button
              className="secondary-button"
              onClick={handleRestore}
              disabled={isRestoring}
              title="从服务端自动保存恢复所有批次"
              type="button"
            >
              {isRestoring ? <Loader2 className="spinning" size={16} /> : <History size={16} />} 恢复最近自动保存的对比工作区
            </button>
          </div>
        </>
      ) : (
        <div className="compare-layout-body">
          <CompareIndexSidebar
            activeRoundId={activeRoundId}
            isCollapsed={isSidebarCollapsed}
            onSelectRound={setActiveRoundId}
            onToggleCollapse={() => setIsSidebarCollapsed((prev) => !prev)}
          />

          <div className="compare-main-content">
            {queueProgress ? (
              <div className="compare-queue-progress-banner" role="status">
                <div className="queue-progress-info">
                  <Loader2 className="spinning" size={16} />
                  <span>
                    正在跨批次连续出图: 批次 <strong>{queueProgress.currentRoundIndex}/{queueProgress.totalRounds}</strong>
                    {queueProgress.roundName ? ` (${queueProgress.roundName})` : ""} · 变体 <strong>{queueProgress.currentVariantIndex}/{queueProgress.totalVariants}</strong>
                    {queueProgress.variantName ? ` [${queueProgress.variantName}]` : ""}
                  </span>
                </div>
                <button className="secondary-button compact danger" onClick={stop} type="button">
                  停止排队出图
                </button>
              </div>
            ) : null}

            <div className="compare-rounds-container">
              {state.rounds.map((round) => (
                <CompareRoundSection
                  canDeleteRound={state.rounds.length > 1}
                  isBusy={isBusy}
                  key={round.id}
                  onBatchDerive={handleBatchDerive}
                  onOpenImageDetail={setSelectedDetailImage}
                  onRunRound={(r, runnableVariants) =>
                    runRound(runnableVariants ?? r.variants, r.template, (vId, patch) => {
                      updateVariant(r.id, vId, patch);
                    })
                  }
                  onRunVariant={(v) =>
                    runVariant(v, round.template, (patch) => {
                      updateVariant(round.id, v.id, patch);
                    })
                  }
                  onToggleSelectVariant={toggleSelectVariant}
                  round={round}
                  selectedVariantIds={selectedVariantIds}
                  template={round.template}
                />
              ))}
            </div>

            <div className="compare-page-footer-actions">
              <button
                className="add-round-downward-btn"
                onClick={() => {
                  const newId = addNewRound();
                  setActiveRoundId(newId);
                  setTimeout(() => {
                    document.getElementById(`round-section-${newId}`)?.scrollIntoView({
                      behavior: "smooth",
                      block: "start",
                    });
                  }, 60);
                }}
                type="button"
              >
                <Plus size={18} /> 往下新增新的一批对比 (New Batch Below)
              </button>
            </div>
          </div>
        </div>
      )}

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

      {/* Image Detail Dialog (aligned with CustomStudio) */}
      {selectedDetailImage ? (
        <ImageDetailDialog
          initialIndex={selectedDetailImage.index}
          items={selectedDetailImage.items}
          onClose={() => setSelectedDetailImage(null)}
          paths={selectedDetailImage.paths}
        />
      ) : null}
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
