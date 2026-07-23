import { Plus, X } from "lucide-react";
import { useState } from "react";

import type { PolicyRuleState, PromptBehaviorParams } from "../workspace/types";

const POLICY_RULES = [
  "tag_normalize",
  "dedupe",
  "character_section_filter",
  "tag_conflict",
  "character_count",
  "clothing_policy",
  "visibility_policy",
  "character_extension",
  "character_weight",
] as const;

const ruleLabels: Record<string, string> = {
  tag_normalize: "Tag Normalize",
  dedupe: "Dedupe",
  character_section_filter: "Character Section Filter",
  tag_conflict: "Tag Conflict",
  character_count: "Character Count",
  clothing_policy: "Clothing Policy",
  visibility_policy: "Visibility Policy",
  character_extension: "Character Extension",
  character_weight: "Character Weight",
};

const ruleOptions: Record<string, string[]> = {
  character_section_filter: ["blocked_sections"],
  clothing_policy: ["mode"],
  visibility_policy: ["mode"],
  character_extension: ["trigger_mode", "enabled_slots"],
  character_weight: ["style", "level", "numeric_weight", "existing_weight", "missing_identity"],
};

type PromptBehaviorPanelProps = {
  value: PromptBehaviorParams;
  characterSections: string[];
  onChange: (value: PromptBehaviorParams) => void;
};

function uniqueSections(values: string[]): string[] {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))];
}

function stateFor(value: PromptBehaviorParams, ruleId: string): PolicyRuleState {
  return value.policyRules[ruleId]?.state ?? "inherit";
}

function optionsFor(value: PromptBehaviorParams, ruleId: string): Record<string, unknown> {
  return value.policyRules[ruleId]?.options ?? {};
}

export function PromptBehaviorPanel({ value, characterSections, onChange }: PromptBehaviorPanelProps) {
  const [customSection, setCustomSection] = useState("");
  const availableSections = uniqueSections(["character", "role", ...characterSections]);
  const selectedSections = value.identityMinimal.sections;

  function update(patch: Partial<PromptBehaviorParams>) {
    onChange({ ...value, ...patch });
  }

  function setIdentityMode(mode: "inherit" | "override") {
    if (mode === "override" && !selectedSections.length) {
      update({ identityMinimal: { mode, sections: ["character", "role"] } });
      return;
    }
    update({ identityMinimal: { ...value.identityMinimal, mode } });
  }

  function toggleSection(section: string) {
    const exists = selectedSections.includes(section);
    if (exists && selectedSections.length === 1) return;
    const sections = exists
      ? selectedSections.filter((item) => item !== section)
      : [...selectedSections, section];
    update({ identityMinimal: { mode: "override", sections } });
  }

  function addCustomSection() {
    const section = customSection.trim();
    if (!section || selectedSections.includes(section)) return;
    setCustomSection("");
    update({ identityMinimal: { mode: "override", sections: [...selectedSections, section] } });
  }

  function setRuleState(ruleId: string, state: PolicyRuleState) {
    const current = value.policyRules[ruleId];
    const policyRules = {
      ...value.policyRules,
      [ruleId]: current?.options ? { state, options: current.options } : { state },
    };
    update({ policyRules });
  }

  function setRuleOption(ruleId: string, key: string, optionValue: unknown) {
    const current = value.policyRules[ruleId];
    update({
      policyRules: {
        ...value.policyRules,
        [ruleId]: {
          state: current?.state ?? "inherit",
          options: { ...optionsFor(value, ruleId), [key]: optionValue },
        },
      },
    });
  }

  return (
    <section className="prompt-behavior-panel" aria-label="Prompt behavior">
      <div className="section-title-row">
        <div>
          <h3>Prompt Behavior</h3>
          <small>Prompt composition and renderer behavior</small>
        </div>
      </div>

      <section className="behavior-section">
        <div className="behavior-section-title">
          <strong>Identity Minimal Sections</strong>
          <select
            aria-label="Identity minimal mode"
            onChange={(event) => setIdentityMode(event.target.value as "inherit" | "override")}
            value={value.identityMinimal.mode}
          >
            <option value="inherit">Inherit node configuration</option>
            <option value="override">Override for this run</option>
          </select>
        </div>
        {value.identityMinimal.mode === "override" ? (
          <>
            <div className="tag-choice-list">
              {availableSections.map((section) => (
                <label className="check-chip" key={section}>
                  <input
                    aria-label={`Identity section ${section}`}
                    checked={selectedSections.includes(section)}
                    onChange={() => toggleSection(section)}
                    type="checkbox"
                  />
                  {section}
                </label>
              ))}
              {selectedSections.filter((section) => !availableSections.includes(section)).map((section) => (
                <span className="check-chip custom-chip" key={section}>
                  {section}
                  <button aria-label={`Remove identity section ${section}`} onClick={() => toggleSection(section)} type="button"><X size={13} /></button>
                </span>
              ))}
            </div>
            <div className="inline-input-row">
              <input
                aria-label="Custom identity section"
                onChange={(event) => setCustomSection(event.target.value)}
                onKeyDown={(event) => { if (event.key === "Enter") addCustomSection(); }}
                placeholder="Add section"
                value={customSection}
              />
              <button aria-label="Add identity section" onClick={addCustomSection} title="Add identity section" type="button"><Plus size={15} /></button>
            </div>
            {selectedSections.length === 1 ? <small className="field-hint">At least one section must remain selected.</small> : null}
          </>
        ) : <small className="field-hint">Uses character meta.yaml identity_minimal, then the system default.</small>}
      </section>

      <section className="behavior-section">
        <div className="behavior-section-title"><strong>Character Prompts</strong></div>
        <div className="segmented-control" role="radiogroup" aria-label="Character Prompts mode">
          <label><input aria-label="Character Prompts Auto" checked={value.characterPrompts.mode === "auto"} onChange={() => update({ characterPrompts: { ...value.characterPrompts, mode: "auto" } })} type="radio" /> Auto</label>
          <label><input aria-label="Character Prompts Off" checked={value.characterPrompts.mode === "off"} onChange={() => update({ characterPrompts: { ...value.characterPrompts, mode: "off" } })} type="radio" /> Off</label>
        </div>
        {value.characterPrompts.mode === "auto" ? (
          <label className="toggle-row compact-toggle"><input checked={value.characterPrompts.addMaleCaption} onChange={(event) => update({ characterPrompts: { ...value.characterPrompts, addMaleCaption: event.target.checked } })} type="checkbox" /> Add male caption</label>
        ) : null}
      </section>

      <section className="behavior-section">
        <div className="behavior-section-title"><strong>Policy Rules</strong><small>Baseline: project legacy_compat</small></div>
        <div className="policy-rule-list">
          {POLICY_RULES.map((ruleId) => {
            const state = stateFor(value, ruleId);
            const options = optionsFor(value, ruleId);
            const supportsOptions = Boolean(ruleOptions[ruleId]?.length);
            return (
              <details className="policy-rule" key={ruleId} open={state === "enabled" && supportsOptions}>
                <summary><span>{ruleLabels[ruleId]}</span><select aria-label={`${ruleLabels[ruleId]} state`} onClick={(event) => event.stopPropagation()} onChange={(event) => setRuleState(ruleId, event.target.value as PolicyRuleState)} value={state}><option value="inherit">Inherit</option><option value="enabled">Enabled</option><option value="disabled">Disabled</option></select></summary>
                {state === "enabled" && supportsOptions ? (
                  <div className="policy-options">
                    {ruleId === "character_section_filter" ? <label className="field"><span>Blocked sections</span><input aria-label="Blocked sections" onChange={(event) => setRuleOption(ruleId, "blocked_sections", event.target.value.split(",").map((item) => item.trim()).filter(Boolean))} value={Array.isArray(options.blocked_sections) ? options.blocked_sections.join(", ") : "copyright"} /></label> : null}
                    {ruleId === "clothing_policy" || ruleId === "visibility_policy" ? <label className="field"><span>{ruleId === "clothing_policy" ? "Clothing mode" : "Visibility mode"}</span><select aria-label={ruleId === "clothing_policy" ? "Clothing mode" : "Visibility mode"} onChange={(event) => setRuleOption(ruleId, "mode", event.target.value)} value={String(options.mode ?? "enforce")}><option value="enforce">Enforce</option><option value="advisory">Advisory</option></select></label> : null}
                    {ruleId === "character_extension" ? <><label className="field"><span>Trigger mode</span><select aria-label="Trigger mode" onChange={(event) => setRuleOption(ruleId, "trigger_mode", event.target.value)} value={String(options.trigger_mode ?? "fixed")}><option value="fixed">Fixed</option><option value="fixed_plus_legacy">Fixed + legacy</option><option value="legacy">Legacy</option></select></label><label className="field"><span>Enabled slots</span><input aria-label="Enabled slots" onChange={(event) => setRuleOption(ruleId, "enabled_slots", event.target.value.split(",").map((item) => item.trim()).filter(Boolean))} value={Array.isArray(options.enabled_slots) ? options.enabled_slots.join(", ") : ""} placeholder="legwear, shoes, weapon" /></label></> : null}
                    {ruleId === "character_weight" ? <><label className="field"><span>Weight style</span><select aria-label="Weight style" onChange={(event) => setRuleOption(ruleId, "style", event.target.value)} value={String(options.style ?? "numeric")}><option value="numeric">Numeric</option><option value="braces">Braces</option></select></label><label className="field"><span>Weight level</span><input aria-label="Weight level" min={1} max={6} onChange={(event) => setRuleOption(ruleId, "level", Number(event.target.value))} type="number" value={String(options.level ?? 2)} /></label><label className="field"><span>Numeric weight</span><input aria-label="Numeric weight" min={0.1} max={10} onChange={(event) => setRuleOption(ruleId, "numeric_weight", Number(event.target.value))} step={0.1} type="number" value={String(options.numeric_weight ?? 2)} /></label></> : null}
                  </div>
                ) : null}
              </details>
            );
          })}
        </div>
      </section>
    </section>
  );
}
