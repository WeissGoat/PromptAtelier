import { ChevronDown, ChevronRight, Play } from "lucide-react";
import { useState } from "react";

import type { ImageRecord, RegenOverrides, RegenSettings } from "./api";

export const defaultRegenSettings: RegenSettings = {
  count: 1,
  seed_mode: "source",
  seed: null,
  size_mode: "source",
  width: null,
  height: null,
  overrides: {},
};

export const MODELS = [
  "nai-diffusion-4-5-full",
  "nai-diffusion-4-5-curated",
  "nai-diffusion-4-full",
  "nai-diffusion-4-curated",
  "nai-diffusion-5-full",
  "nai-diffusion-5-curated",
  "nai-diffusion-3",
];
export const SAMPLERS = ["k_euler", "k_euler_ancestral", "k_dpmpp_2s_ancestral", "k_dpmpp_2m", "k_dpmpp_2m_sde", "k_dpmpp_sde"];
export const SCHEDULES = ["native", "karras", "exponential", "polyexponential"];
export const SIZE_PRESETS: Array<[number, number]> = [
  [832, 1216],
  [1216, 832],
  [1024, 1024],
];

type RegenPanelProps = {
  image: ImageRecord;
  settings: RegenSettings;
  submitting: boolean;
  error: string | null;
  onChange: (settings: RegenSettings) => void;
  onSubmit: () => void;
};

export function RegenPanel({ image, settings, submitting, error, onChange, onSubmit }: RegenPanelProps) {
  const [showOverrides, setShowOverrides] = useState(Object.keys(settings.overrides).length > 0);
  const set = (patch: Partial<RegenSettings>) => onChange({ ...settings, ...patch });
  const setOverride = (key: keyof RegenOverrides, value: string | number | undefined) => {
    const next = { ...settings.overrides } as Record<string, unknown>;
    if (value === undefined || value === "" || Number.isNaN(value)) {
      delete next[key];
    } else {
      next[key] = value;
    }
    set({ overrides: next as RegenOverrides });
  };
  const invalidSeed = settings.seed_mode === "fixed" && settings.seed === null;
  const invalidSize = settings.size_mode === "custom" && (!settings.width || !settings.height);
  const overrideCount = Object.keys(settings.overrides).length;

  return (
    <section className="sl-section sl-regen">
      <header className="sl-section-head">
        <span className="sl-section-label">原参重生</span>
        <span className="sl-muted">用原图全部参数直接出图，检查本地生图链路</span>
      </header>

      <div className="sl-form-row">
        <label htmlFor="sl-count">张数</label>
        <input
          id="sl-count"
          max={8}
          min={1}
          onChange={(event) => set({ count: Math.min(8, Math.max(1, Number(event.target.value) || 1)) })}
          type="number"
          value={settings.count}
        />
      </div>

      <div className="sl-form-row">
        <span className="sl-form-label">种子</span>
        <Segmented
          onChange={(value) => set({ seed_mode: value as RegenSettings["seed_mode"] })}
          options={[
            ["source", `原图${image.seed !== null ? ` ${image.seed}` : ""}`],
            ["random", "随机"],
            ["fixed", "指定"],
          ]}
          value={settings.seed_mode}
        />
        {settings.seed_mode === "fixed" ? (
          <input
            aria-label="指定种子"
            className={invalidSeed ? "invalid" : ""}
            min={0}
            onChange={(event) => set({ seed: event.target.value === "" ? null : Number(event.target.value) })}
            placeholder="种子"
            type="number"
            value={settings.seed ?? ""}
          />
        ) : null}
      </div>
      {settings.count > 1 && settings.seed_mode !== "random" ? (
        <p className="sl-hint">多张时种子依次 +1。</p>
      ) : null}

      <div className="sl-form-row">
        <span className="sl-form-label">尺寸</span>
        <Segmented
          onChange={(value) => set({ size_mode: value as RegenSettings["size_mode"] })}
          options={[
            ["source", image.width && image.height ? `原图 ${image.width}×${image.height}` : "原图"],
            ["custom", "自定义"],
          ]}
          value={settings.size_mode}
        />
      </div>
      {settings.size_mode === "custom" ? (
        <div className="sl-form-row sl-indent">
          <input
            aria-label="宽"
            className={invalidSize && !settings.width ? "invalid" : ""}
            onChange={(event) => set({ width: event.target.value === "" ? null : Number(event.target.value) })}
            placeholder="宽"
            step={64}
            type="number"
            value={settings.width ?? ""}
          />
          <span>×</span>
          <input
            aria-label="高"
            className={invalidSize && !settings.height ? "invalid" : ""}
            onChange={(event) => set({ height: event.target.value === "" ? null : Number(event.target.value) })}
            placeholder="高"
            step={64}
            type="number"
            value={settings.height ?? ""}
          />
          {SIZE_PRESETS.map(([w, h]) => (
            <button className="sl-mini-btn" key={`${w}x${h}`} onClick={() => set({ width: w, height: h })} type="button">
              {w}×{h}
            </button>
          ))}
        </div>
      ) : null}

      <button className="sl-disclosure" onClick={() => setShowOverrides(!showOverrides)} type="button">
        {showOverrides ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        覆盖参数{overrideCount ? `（${overrideCount}）` : ""}
      </button>
      {showOverrides ? (
        <div className="sl-overrides">
          <OverrideSelect
            label="模型"
            onChange={(value) => setOverride("model", value)}
            options={MODELS}
            source={image.model}
            value={settings.overrides.model}
          />
          <OverrideSelect
            label="采样器"
            onChange={(value) => setOverride("sampler", value)}
            options={SAMPLERS}
            source={image.sampler}
            value={settings.overrides.sampler}
          />
          <OverrideSelect
            label="调度"
            onChange={(value) => setOverride("noise_schedule", value)}
            options={SCHEDULES}
            source={image.noise_schedule}
            value={settings.overrides.noise_schedule}
          />
          <OverrideNumber
            label="步数"
            onChange={(value) => setOverride("steps", value)}
            source={image.steps}
            step={1}
            value={settings.overrides.steps}
          />
          <OverrideNumber
            label="CFG"
            onChange={(value) => setOverride("scale", value)}
            source={image.scale}
            step={0.1}
            value={settings.overrides.scale}
          />
          <OverrideNumber
            label="CFG rescale"
            onChange={(value) => setOverride("cfg_rescale", value)}
            source={image.cfg_rescale}
            step={0.02}
            value={settings.overrides.cfg_rescale}
          />
        </div>
      ) : null}

      {error ? <p className="sl-error">{error}</p> : null}
      <button
        className="sl-primary"
        disabled={submitting || !image.has_metadata}
        onClick={() => {
          if (!invalidSeed && !invalidSize) {
            onSubmit();
          }
        }}
        type="button"
      >
        <Play size={15} aria-hidden="true" />
        {submitting ? "提交中…" : `原参重生 · ${settings.count} 张`}
      </button>
      {invalidSeed ? <p className="sl-error">填写种子，或改用原图 / 随机种子。</p> : null}
      {invalidSize ? <p className="sl-error">填写宽和高，或改用原图尺寸。</p> : null}
    </section>
  );
}

export function Segmented({
  options,
  value,
  onChange,
}: {
  options: Array<[string, string]>;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="sl-segmented" role="radiogroup">
      {options.map(([key, label]) => (
        <button aria-checked={value === key} className={value === key ? "on" : ""} key={key} onClick={() => onChange(key)} role="radio" type="button">
          {label}
        </button>
      ))}
    </div>
  );
}

function OverrideSelect({
  label,
  options,
  source,
  value,
  onChange,
}: {
  label: string;
  options: string[];
  source: string | null;
  value: string | undefined;
  onChange: (value: string | undefined) => void;
}) {
  return (
    <label className="sl-override">
      <span>{label}</span>
      <select onChange={(event) => onChange(event.target.value || undefined)} value={value ?? ""}>
        <option value="">原图：{source ?? "—"}</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

function OverrideNumber({
  label,
  source,
  value,
  step,
  onChange,
}: {
  label: string;
  source: number | null;
  value: number | undefined;
  step: number;
  onChange: (value: number | undefined) => void;
}) {
  return (
    <label className="sl-override">
      <span>{label}</span>
      <input
        onChange={(event) => onChange(event.target.value === "" ? undefined : Number(event.target.value))}
        placeholder={`原图：${source ?? "—"}`}
        step={step}
        type="number"
        value={value ?? ""}
      />
    </label>
  );
}
