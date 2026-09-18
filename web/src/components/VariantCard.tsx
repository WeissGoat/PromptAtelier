import {
  CheckSquare,
  Copy,
  FolderOpen,
  GitFork,
  GripVertical,
  Lock,
  Play,
  RotateCcw,
  Square,
  Trash2,
  Unlock,
} from "lucide-react";
import { useState } from "react";

import { apiPost, errorMessage } from "../api/client";
import type { BaseTemplate, PromptVariant } from "../compare/types";
import { useCompareWorkspace } from "../compare/useCompareWorkspace";

type VariantCardProps = {
  roundId: string;
  variant: PromptVariant;
  template: BaseTemplate;
  onRun: () => Promise<void>;
  isBusy: boolean;
  canDelete: boolean;
  isSelectedForCompare: boolean;
  onToggleCompare: () => void;
  onOpenDetail?: () => void;
  index?: number;
  isDragging?: boolean;
  dragOverSide?: "left" | "right" | null;
  onDragStart?: (index: number) => void;
  onDragEnd?: () => void;
  onDragOver?: (e: React.DragEvent, index: number) => void;
  isControlGroup?: boolean;
  isDuplicate?: boolean;
  onDrop?: (e: React.DragEvent, index: number) => void;
};

export function VariantCard({
  roundId,
  variant,
  template,
  onRun,
  isBusy,
  canDelete,
  isSelectedForCompare,
  onToggleCompare,
  onOpenDetail,
  index,
  isDragging,
  dragOverSide,
  onDragStart,
  onDragEnd,
  onDragOver,
  onDrop,
  isControlGroup,
  isDuplicate,
}: VariantCardProps) {
  const {
    duplicateVariant,
    updateVariant,
    removeVariant,
    resetVariantToTemplate,
    forkVariantToNewRound,
  } = useCompareWorkspace();

  const [isCustomSeed, setIsCustomSeed] = useState(variant.seedOverride !== null);

  const [openingFolder, setOpeningFolder] = useState(false);
  const [folderNotice, setFolderNotice] = useState<string | null>(null);

  async function handleOpenFolder(imagePath: string) {
    setOpeningFolder(true);
    setFolderNotice(null);
    try {
      await apiPost("/results/open-image-folder", { path: imagePath });
      setFolderNotice("已定位");
      setTimeout(() => setFolderNotice(null), 2000);
    } catch (err) {
      setFolderNotice(errorMessage(err));
      setTimeout(() => setFolderNotice(null), 3000);
    } finally {
      setOpeningFolder(false);
    }
  }

  const effectiveSeed =
    variant.seedOverride !== null && variant.seedOverride !== undefined
      ? variant.seedOverride
      : template.seed;

  const [isHandleHovered, setIsHandleHovered] = useState(false);
  const [isDraggingSelf, setIsDraggingSelf] = useState(false);

  return (
    <article
      aria-grabbed={isDragging || isDraggingSelf}
      className={`variant-card ${variant.status} ${
        isDragging || isDraggingSelf ? "dragging" : ""
      } ${
        dragOverSide === "left"
          ? "drag-over-left"
          : dragOverSide === "right"
          ? "drag-over-right"
          : ""
      }`}
      draggable={isHandleHovered}
      onDragEnd={() => {
        setIsDraggingSelf(false);
        setIsHandleHovered(false);
        onDragEnd?.();
      }}
      onDragOver={(e) => {
        if (index !== undefined) {
          onDragOver?.(e, index);
        }
      }}
      onDragStart={(e) => {
        setIsDraggingSelf(true);
        if (index !== undefined) {
          e.dataTransfer.setData("text/plain", String(index));
          e.dataTransfer.effectAllowed = "move";
          onDragStart?.(index);
        }
      }}
      onDrop={(e) => {
        if (index !== undefined) {
          onDrop?.(e, index);
        }
      }}
    >
      <div className="variant-card-header">
        <div
          aria-label="拖拽调整变体顺序"
          className="variant-drag-handle"
          onMouseEnter={() => setIsHandleHovered(true)}
          onMouseLeave={() => {
            if (!isDraggingSelf) {
              setIsHandleHovered(false);
            }
          }}
          title="按住左右拖拽调整顺序"
        >
          <GripVertical size={16} />
        </div>
        <input
          aria-label="变体名称"
          className="variant-name-input"
          onChange={(e) => updateVariant(roundId, variant.id, { name: e.target.value })}
          value={variant.name}
        />
        <div className="variant-header-actions">
          <button
            className="icon-btn"
            onClick={() => duplicateVariant(roundId, variant.id)}
            title="复制此变体"
            type="button"
          >
            <Copy size={14} />
          </button>
          <button
            className="icon-btn"
            onClick={() => resetVariantToTemplate(roundId, variant.id)}
            title="还原为基准提示词"
            type="button"
          >
            <RotateCcw size={14} />
          </button>
          {canDelete ? (
            <button
              className="icon-btn danger"
              onClick={() => removeVariant(roundId, variant.id)}
              title="删除变体"
              type="button"
            >
              <Trash2 size={14} />
            </button>
          ) : null}
        </div>
      </div>

      <div className="variant-prompt-field">
        <label className="field-caption">
          <span>正向提示词</span>
          <span className="diff-count-hint">
            {variant.diff.added.length > 0 && (
              <span className="diff-added-count">+{variant.diff.added.length}</span>
            )}
            {variant.diff.removed.length > 0 && (
              <span className="diff-removed-count">-{variant.diff.removed.length}</span>
            )}
          </span>
        </label>
        <textarea
          aria-label="变体提示词"
          className="variant-prompt-textarea"
          onChange={(e) => updateVariant(roundId, variant.id, { prompt: e.target.value })}
          rows={4}
          value={variant.prompt}
        />
      </div>

      <div className="variant-diff-pills-row">
        {variant.diff.added.length === 0 && variant.diff.removed.length === 0 ? (
          isControlGroup ? (
            <span
              className="diff-pill unchanged control-group"
              title="对照组：与本批基准底模提示词一致，批量运行时将作为对比基准正常生成"
            >
              对照组 (与基准一致)
            </span>
          ) : isDuplicate ? (
            <span
              className="diff-pill duplicate"
              title="与本批对照组提示词完全一致，批量运行将自动跳过"
            >
              与对照组重复 (跳过)
            </span>
          ) : (
            <span
              className="diff-pill unchanged"
              title="与本批基准底模提示词一致"
            >
              与本轮基准一致
            </span>
          )
        ) : isDuplicate ? (
          <span
            className="diff-pill duplicate"
            title="与同批前面的变体提示词与Seed完全一致，批量运行将自动跳过"
          >
            与同批变体重复 (跳过)
          </span>
        ) : null}
        {variant.diff.added.map((tag, i) => (
          <span className="diff-pill added" key={`add-${i}`}>
            + {tag}
          </span>
        ))}
        {variant.diff.removed.map((tag, i) => (
          <span className="diff-pill removed" key={`rem-${i}`}>
            - {tag}
          </span>
        ))}
      </div>

      <div className="variant-seed-control">
        <button
          className={`seed-toggle-btn ${isCustomSeed ? "unlocked" : "locked"}`}
          onClick={() => {
            if (isCustomSeed) {
              setIsCustomSeed(false);
              updateVariant(roundId, variant.id, { seedOverride: null });
            } else {
              setIsCustomSeed(true);
              updateVariant(roundId, variant.id, { seedOverride: template.seed });
            }
          }}
          type="button"
        >
          {isCustomSeed ? <Unlock size={12} /> : <Lock size={12} />}
          {isCustomSeed ? "独立 Seed" : `锁底模 Seed: ${effectiveSeed}`}
        </button>

        {isCustomSeed ? (
          <input
            aria-label="覆盖种子"
            className="custom-seed-input"
            onChange={(e) => {
              const num = parseInt(e.target.value, 10);
              updateVariant(roundId, variant.id, {
                seedOverride: isNaN(num) ? 0 : num,
              });
            }}
            type="number"
            value={variant.seedOverride ?? template.seed}
          />
        ) : null}
      </div>

      <div className="variant-execute-row">
        <button
          className="primary-button compact run-variant-btn"
          disabled={isBusy || variant.status === "running" || variant.status === "queued"}
          onClick={() => void onRun()}
          type="button"
        >
          <Play size={13} /> {variant.status === "running" ? "生成中..." : "生成单张"}
        </button>
        <span className={`status-badge ${variant.status}`}>{variant.status}</span>
      </div>

      {variant.error ? <div className="variant-error-msg">{variant.error}</div> : null}

      <div className={`variant-result-container ${variant.resultImage ? "has-image" : "empty"}`}>
        {variant.resultImage ? (
          <div className="variant-image-preview">
            <img
              alt={variant.name}
              className="clickable-result-image"
              onClick={onOpenDetail}
              src={variant.resultImage.url}
              title="点开缩略图查看大图详情与参数 (对齐 Custom)"
            />
            <div className="image-overlay-actions">
              <button
                className={`compare-select-btn ${isSelectedForCompare ? "selected" : ""}`}
                onClick={onToggleCompare}
                type="button"
              >
                {isSelectedForCompare ? <CheckSquare size={14} /> : <Square size={14} />}
                {isSelectedForCompare ? "已选对比" : "勾选对比"}
              </button>
              <button
                className="folder-open-btn"
                disabled={openingFolder}
                onClick={(e) => {
                  e.stopPropagation();
                  void handleOpenFolder(variant.resultImage!.path);
                }}
                title="打开生成图片所在文件夹"
                type="button"
              >
                <FolderOpen size={14} />
                {folderNotice ? folderNotice : "打开文件夹"}
              </button>
            </div>
          </div>
        ) : (
          <div className="variant-image-placeholder">
            <span>尚未生成图像</span>
          </div>
        )}
      </div>

      <div className="variant-card-footer">
        <button
          className="fork-downward-btn"
          onClick={() => forkVariantToNewRound(roundId, variant.id)}
          title="以当前变体提示词为新基准，在下方开启新一轮对比"
          type="button"
        >
          <GitFork size={13} /> 以此为基准往下派生 ⬇
        </button>
      </div>
    </article>
  );
}
