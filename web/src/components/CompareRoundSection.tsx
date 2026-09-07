import { ChevronDown, ChevronUp, GitFork, Play, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import type { BaseTemplate, CompareRound, PromptVariant } from "../compare/types";
import { useCompareWorkspace } from "../compare/useCompareWorkspace";
import { VariantCard } from "./VariantCard";

type CompareRoundSectionProps = {
  round: CompareRound;
  template: BaseTemplate;
  isBusy: boolean;
  canDeleteRound: boolean;
  selectedVariantIds: string[];
  onToggleSelectVariant: (variantId: string) => void;
  onRunVariant: (variant: PromptVariant) => Promise<void>;
  onRunRound: (round: CompareRound) => Promise<void>;
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
}: CompareRoundSectionProps) {
  const { addVariant, addNewRound, removeVariant } = useCompareWorkspace();
  const [showBasePrompt, setShowBasePrompt] = useState(false);

  return (
    <section className="compare-round-section">
      <div className="round-header">
        <div className="round-title-group">
          <span className="round-name-tag">{round.name}</span>
          <button
            className="toggle-prompt-summary-btn"
            onClick={() => setShowBasePrompt(!showBasePrompt)}
            type="button"
          >
            本批基准 {showBasePrompt ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </button>
        </div>

        <div className="round-actions">
          <button
            className="primary-button compact"
            disabled={isBusy || round.variants.length === 0}
            onClick={() => void onRunRound(round)}
            type="button"
          >
            <Play size={13} /> 运行本批全部变体 ({round.variants.length})
          </button>

          <button
            className="secondary-button compact"
            onClick={() => addNewRound(round.basePrompt)}
            title="以本批基准词为模版在下方开启新一批对比"
            type="button"
          >
            <GitFork size={13} /> 往下派生新批次
          </button>

          {canDeleteRound ? (
            <button
              className="icon-btn danger"
              onClick={() => {
                for (const v of round.variants) {
                  removeVariant(round.id, v.id);
                }
              }}
              title="删除整批"
              type="button"
            >
              <Trash2 size={14} />
            </button>
          ) : null}
        </div>
      </div>

      {showBasePrompt ? (
        <div className="round-base-prompt-box">
          <span className="box-label">批次基准提示词:</span>
          <code>{round.basePrompt || "(空)"}</code>
        </div>
      ) : null}

      <div className="round-cards-row">
        {round.variants.map((variant) => (
          <VariantCard
            canDelete={round.variants.length > 1}
            isBusy={isBusy}
            isSelectedForCompare={selectedVariantIds.includes(variant.id)}
            key={variant.id}
            onRun={() => onRunVariant(variant)}
            onToggleCompare={() => onToggleSelectVariant(variant.id)}
            roundId={round.id}
            template={template}
            variant={variant}
          />
        ))}

        <div
          className="add-variant-card-slot"
          onClick={() => addVariant(round.id)}
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
