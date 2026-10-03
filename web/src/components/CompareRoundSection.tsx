import { GitFork, Layers, Play, Plus, RotateCcw, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";

import { getVariantIdentityMap, isVariantCompleted } from "../compare/runnableVariants";
import type { BaseTemplate, CompareRound, PromptVariant } from "../compare/types";
import { useCompareWorkspace } from "../compare/useCompareWorkspace";
import { BatchDeriveDialog } from "./BatchDeriveDialog";
import { CompareTemplateBar } from "./CompareTemplateBar";
import type { ImageDetailItem } from "./ImageDetailDialog";
import { VariantCard } from "./VariantCard";

type CompareRoundSectionProps = {
  round: CompareRound;
  template?: BaseTemplate;
  isBusy: boolean;
  canDeleteRound: boolean;
  selectedVariantIds: string[];
  onToggleSelectVariant: (variantId: string) => void;
  onRunVariant: (variant: PromptVariant) => Promise<void>;
  onRunRound: (round: CompareRound, runnableVariants?: PromptVariant[]) => Promise<void>;
  onBatchDerive?: (
    sourceRound: CompareRound,
    items: Array<{ template: BaseTemplate; filename: string }>,
    autoRun: boolean,
  ) => void;
  onOpenImageDetail: (selection: {
    paths?: string[];
    items?: ImageDetailItem[];
    index: number;
  }) => void;
};

export function CompareRoundSection({
  round,
  template,
  isBusy,
  canDeleteRound,
  selectedVariantIds,
  onToggleSelectVariant,
  onRunVariant,
  onRunRound,
  onBatchDerive,
  onOpenImageDetail,
}: CompareRoundSectionProps) {
  const { addVariant, addNewRound, removeRound, reorderVariants } = useCompareWorkspace();
  const [isBatchDeriveOpen, setIsBatchDeriveOpen] = useState(false);
  const effectiveTemplate = round.template || template;

  const identityMap = useMemo(
    () =>
      effectiveTemplate
        ? getVariantIdentityMap(round.variants, effectiveTemplate)
        : new Map(),
    [round.variants, effectiveTemplate],
  );

  const runnableVariants = useMemo(
    () => round.variants.filter((v) => identityMap.get(v.id)?.isRunnable ?? true),
    [round.variants, identityMap],
  );
  const runnableCount = runnableVariants.length;
  const skippedCount = round.variants.length - runnableCount;

  const pendingVariants = useMemo(
    () => runnableVariants.filter((v) => !isVariantCompleted(v)),
    [runnableVariants],
  );
  const pendingCount = pendingVariants.length;
  const completedCount = runnableCount - pendingCount;

  const [draggedIndex, setDraggedIndex] = useState<number | null>(null);
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);
  const [dragOverSide, setDragOverSide] = useState<"left" | "right" | null>(null);

  const handleDragStart = (index: number) => {
    setDraggedIndex(index);
  };

  const handleDragEnd = () => {
    setDraggedIndex(null);
    setDragOverIndex(null);
    setDragOverSide(null);
  };

  const handleDragOver = (e: React.DragEvent, targetIndex: number) => {
    if (draggedIndex === null) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";

    const rect = e.currentTarget.getBoundingClientRect();
    const midX = rect.left + rect.width / 2;
    const side = e.clientX < midX ? "left" : "right";

    // Don't show drop indicator if dropping would be a no-op
    let isNoOp = false;
    if (draggedIndex === targetIndex) {
      isNoOp = true;
    } else if (side === "left" && draggedIndex === targetIndex - 1) {
      isNoOp = true;
    } else if (side === "right" && draggedIndex === targetIndex + 1) {
      isNoOp = true;
    }

    if (isNoOp) {
      if (dragOverIndex !== null || dragOverSide !== null) {
        setDragOverIndex(null);
        setDragOverSide(null);
      }
      return;
    }

    if (dragOverIndex !== targetIndex || dragOverSide !== side) {
      setDragOverIndex(targetIndex);
      setDragOverSide(side);
    }
  };

  const handleDrop = (e: React.DragEvent, targetIndex: number) => {
    e.preventDefault();
    if (draggedIndex === null) return;

    const rect = e.currentTarget.getBoundingClientRect();
    const midX = rect.left + rect.width / 2;
    const side = e.clientX < midX ? "left" : "right";

    const sourceIndex = draggedIndex;
    let destIndex: number;
    if (side === "left") {
      destIndex = sourceIndex < targetIndex ? targetIndex - 1 : targetIndex;
    } else {
      destIndex = sourceIndex < targetIndex ? targetIndex : targetIndex + 1;
    }

    if (destIndex !== sourceIndex && destIndex >= 0 && destIndex < round.variants.length) {
      reorderVariants(round.id, sourceIndex, destIndex);
    }

    handleDragEnd();
  };

  const detailItems: ImageDetailItem[] = useMemo(() => {
    const items: ImageDetailItem[] = [];
    if (round.template?.sourceImage?.sourcePath) {
      items.push({
        path: round.template.sourceImage.sourcePath,
        label: "本批底模",
        name: "底模原图",
        badge: "底模",
      });
    }
    for (const v of round.variants) {
      if (v.resultImage?.path) {
        const identity = identityMap.get(v.id);
        let badge: string | undefined;
        if (identity?.isControlGroup) {
          badge = "对照组";
        } else {
          const added = v.diff.added.length;
          const removed = v.diff.removed.length;
          if (added > 0 && removed > 0) {
            badge = `+${added}/-${removed}`;
          } else if (added > 0) {
            badge = `+${added}`;
          } else if (removed > 0) {
            badge = `-${removed}`;
          }
        }
        items.push({
          path: v.resultImage.path,
          label: v.name,
          name: v.name,
          badge,
          isControlGroup: identity?.isControlGroup,
        });
      }
    }
    return items;
  }, [round.template?.sourceImage?.sourcePath, round.variants, identityMap]);

  return (
    <section className="compare-round-section" id={`round-section-${round.id}`}>
      <div className="round-header">
        <div className="round-title-group">
          <span className="round-name-tag">{round.name}</span>
        </div>

        <div className="round-actions">
          {completedCount === 0 ? (
            <button
              className="primary-button compact"
              disabled={isBusy || runnableCount === 0}
              onClick={() => void onRunRound(round, runnableVariants)}
              title={
                skippedCount > 0
                  ? `本批共 ${round.variants.length} 个变体，将运行 ${runnableCount} 个有效变体（含 1 个基准对照组，已跳过 ${skippedCount} 个重复变体）`
                  : `运行本批全部 ${round.variants.length} 个变体`
              }
              type="button"
            >
              <Play size={13} /> 运行本批全部变体 ({runnableCount})
            </button>
          ) : completedCount < runnableCount ? (
            <>
              <button
                className="primary-button compact"
                disabled={isBusy || pendingCount === 0}
                onClick={() => void onRunRound(round, pendingVariants)}
                title={`本批共 ${runnableCount} 个有效变体，已完成 ${completedCount} 个，本次将仅运行 ${pendingCount} 个未完成/失败变体（自动跳过已成功生成的卡片）`}
                type="button"
              >
                <Play size={13} /> 运行未完成变体 ({pendingCount})
              </button>
              <button
                className="secondary-button compact"
                disabled={isBusy || runnableCount === 0}
                onClick={() => void onRunRound(round, runnableVariants)}
                title={`重新运行本批全部 ${runnableCount} 个变体并覆盖已有生成图片`}
                type="button"
              >
                <RotateCcw size={13} /> 重跑全部 ({runnableCount})
              </button>
            </>
          ) : (
            <button
              className="secondary-button compact"
              disabled={isBusy || runnableCount === 0}
              onClick={() => void onRunRound(round, runnableVariants)}
              title={`本批所有 ${runnableCount} 个变体已生成完毕。点击将重新运行整批全部变体并覆盖已有图片`}
              type="button"
            >
              <RotateCcw size={13} /> 重新运行全部变体 ({runnableCount})
            </button>
          )}

          <button
            className="secondary-button compact"
            onClick={() => addNewRound(round.id)}
            title="以本批变体与diff为模版，在下方派生新一批对比"
            type="button"
          >
            <GitFork size={13} /> 往下派生新批次
          </button>

          <button
            className="secondary-button compact batch-derive-trigger-btn"
            onClick={() => setIsBatchDeriveOpen(true)}
            title="选择或拖入多张图片，自动为每张图片派生新批次并继承本批diff"
            type="button"
          >
            <Layers size={13} /> 多图批量派生...
          </button>

          {canDeleteRound ? (
            <button
              className="icon-btn danger"
              onClick={() => removeRound(round.id)}
              title="删除整批"
              type="button"
            >
              <Trash2 size={14} />
            </button>
          ) : null}
        </div>
      </div>

      <BatchDeriveDialog
        isOpen={isBatchDeriveOpen}
        onClose={() => setIsBatchDeriveOpen(false)}
        onConfirm={(items, autoRun) => {
          onBatchDerive?.(round, items, autoRun);
        }}
        sourceRound={round}
      />

      <CompareTemplateBar
        onOpenDetail={(templatePath) => {
          const targetIdx = detailItems.findIndex((item) => item.path === templatePath);
          onOpenImageDetail({
            items: detailItems,
            paths: detailItems.map((item) => item.path),
            index: Math.max(0, targetIdx),
          });
        }}
        round={round}
      />

      <div className="round-cards-row" onDragLeave={(e) => {
        // Clear dragOver indicators if leaving the cards row
        if (!e.currentTarget.contains(e.relatedTarget as Node)) {
          setDragOverIndex(null);
          setDragOverSide(null);
        }
      }}>
        {round.variants.map((variant, index) => (
          <VariantCard
            canDelete={round.variants.length > 1}
            dragOverSide={dragOverIndex === index ? dragOverSide : null}
            index={index}
            isBusy={isBusy}
            isDragging={draggedIndex === index}
            isControlGroup={identityMap.get(variant.id)?.isControlGroup}
            isDuplicate={identityMap.get(variant.id)?.isDuplicate}
            isSelectedForCompare={selectedVariantIds.includes(variant.id)}
            key={variant.id}
            onDragEnd={handleDragEnd}
            onDragOver={handleDragOver}
            onDragStart={handleDragStart}
            onDrop={handleDrop}
            onOpenDetail={() => {
              const targetPath = variant.resultImage?.path;
              const idx = targetPath ? detailItems.findIndex((item) => item.path === targetPath) : 0;
              onOpenImageDetail({
                items: detailItems,
                paths: detailItems.map((item) => item.path),
                index: Math.max(0, idx),
              });
            }}
            onRun={() => onRunVariant(variant)}
            onToggleCompare={() => onToggleSelectVariant(variant.id)}
            roundId={round.id}
            template={effectiveTemplate}
            variant={variant}
          />
        ))}

        <div
          className={`add-variant-card-slot ${draggedIndex !== null ? "can-drop" : ""}`}
          onClick={() => addVariant(round.id)}
          onDragOver={(e) => {
            if (draggedIndex !== null) {
              e.preventDefault();
              e.dataTransfer.dropEffect = "move";
            }
          }}
          onDrop={(e) => {
            e.preventDefault();
            if (draggedIndex !== null && draggedIndex !== round.variants.length - 1) {
              reorderVariants(round.id, draggedIndex, round.variants.length - 1);
            }
            handleDragEnd();
          }}
          role="button"
          tabIndex={0}
        >
          <div className="add-variant-inner">
            <Plus size={28} />
            <span>新增横向变体</span>
          </div>
        </div>
      </div>
    </section>
  );
}
