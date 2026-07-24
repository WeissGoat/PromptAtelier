import { Plus, X } from "lucide-react";
import { useEffect, useState } from "react";

import { findPromptBehaviorVariant, promptBehaviorVariants } from "../workspace/promptBehavior";
import { useCustomWorkspace } from "../workspace/CustomWorkspaceProvider";
import { PromptBehaviorPanel } from "./PromptBehaviorPanel";

export function PromptBehaviorGroupPanel({ characterSections }: { characterSections: string[] }) {
  const workspace = useCustomWorkspace();
  const group = workspace.state.promptBehaviorGroup;
  const active = findPromptBehaviorVariant(group, workspace.state.activePromptBehaviorSlotId) ?? group.primary;
  const variants = promptBehaviorVariants(group);
  const [labelDraft, setLabelDraft] = useState(active.label);

  useEffect(() => setLabelDraft(active.label), [active.label, active.slotId]);

  function commitLabel() {
    const label = labelDraft.trim();
    if (!label) {
      setLabelDraft(active.label);
      return;
    }
    workspace.renamePromptBehavior(active.slotId, label);
  }

  function removeCompare(slotId: string, label: string) {
    if (!window.confirm(`删除 Prompt Behavior Compare "${label}"？`)) return;
    workspace.removePromptBehaviorCompare(slotId);
  }

  return (
    <section aria-label="Prompt behavior" className="prompt-behavior-group-panel">
      <div className="section-title-row">
        <div>
          <h3>Prompt Behavior</h3>
          <small>Prompt composition and renderer behavior</small>
        </div>
        <button
          aria-label="Add Prompt Behavior Compare"
          className="icon-button"
          onClick={() => workspace.addPromptBehaviorCompare()}
          title="Add Prompt Behavior Compare"
          type="button"
        >
          <Plus size={16} />
        </button>
      </div>

      <div className="prompt-behavior-variant-list">
        {variants.map((variant) => (
          <div className="prompt-behavior-variant-row" key={variant.slotId}>
            <button
              aria-label={`Select Prompt Behavior ${variant.label}`}
              className={`prompt-behavior-variant-select${variant.slotId === active.slotId ? " active" : ""}`}
              onClick={() => workspace.selectPromptBehavior(variant.slotId)}
              type="button"
            >
              <span>{variant.label}</span>
              <small>{variant.mode === "primary" ? "Primary" : "Compare"}</small>
            </button>
            {variant.mode === "compare" ? (
              <button
                aria-label={`Remove Prompt Behavior ${variant.label}`}
                className="icon-button prompt-behavior-remove"
                onClick={() => removeCompare(variant.slotId, variant.label)}
                title={`Remove ${variant.label}`}
                type="button"
              >
                <X size={14} />
              </button>
            ) : null}
          </div>
        ))}
      </div>

      <label className="field compact prompt-behavior-label-field">
        <span>方案名称</span>
        <input
          aria-label="Prompt Behavior label"
          onBlur={commitLabel}
          onChange={(event) => setLabelDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              commitLabel();
            }
          }}
          value={labelDraft}
        />
      </label>

      <PromptBehaviorPanel
        characterSections={characterSections}
        onChange={workspace.setPromptBehavior}
        value={active.value}
      />
    </section>
  );
}
