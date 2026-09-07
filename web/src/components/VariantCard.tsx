import {
  CheckSquare,
  Copy,
  GitFork,
  Lock,
  Play,
  RotateCcw,
  Square,
  Trash2,
  Unlock,
} from "lucide-react";
import { useState } from "react";

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
}: VariantCardProps) {
  const {
    duplicateVariant,
    updateVariant,
    removeVariant,
    resetVariantToTemplate,
    forkVariantToNewRound,
  } = useCompareWorkspace();

  const [isCustomSeed, setIsCustomSeed] = useState(variant.seedOverride !== null);

  const effectiveSeed =
    variant.seedOverride !== null && variant.seedOverride !== undefined
      ? variant.seedOverride
      : template.seed;

  return (
    <article className={`variant-card ${variant.status}`}>
      <div className="variant-card-header">
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
          <span className="diff-pill unchanged">与本轮基准一致</span>
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

      <div className="variant-result-container">
        {variant.resultImage ? (
          <div className="variant-image-preview">
            <img alt={variant.name} src={variant.resultImage.url} />
            <div className="image-overlay-actions">
              <button
                className={`compare-select-btn ${isSelectedForCompare ? "selected" : ""}`}
                onClick={onToggleCompare}
                type="button"
              >
                {isSelectedForCompare ? <CheckSquare size={14} /> : <Square size={14} />}
                {isSelectedForCompare ? "已选对比" : "勾选对比"}
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
