import { Play, Ruler } from "lucide-react";
import { useEffect, useState } from "react";

import { apiGet, apiPost, errorMessage } from "../api/client";
import type { NodeSummary } from "../api/types";
import { ComfyTargetPanel } from "../components/ComfyTargetPanel";
import { NodePicker } from "../components/NodePicker";
import { createCompareOutputDir } from "../compare/useCompareRunController";
import { submitBackgroundBatch, type BackgroundRequestItem } from "../generation/backgroundRun";
import type { NodeDocument } from "../nodes/types";
import { artistBackend, artistSizePresets, type ComposeRenderRequest, type RenderBackend } from "../workspace/requestBuilder";
import type { NodeVariantSlot, SizeOrientation } from "../workspace/types";
import { TokenBadge } from "./FrameCard";
import type { ContractDetail, ContractFrame, TokenUsage } from "./types";

export type ContractSizeChoice = "contract" | "random" | SizeOrientation | "custom";

export type GenerateSettings = {
  artist: NodeSummary | null;
  size: ContractSizeChoice;
  width: number;
  height: number;
  nt: number;
  seed: string;
  negative: string;
  comfyuiTarget?: string;
  characterPrompts: "auto" | "off";
  addMaleCaption: boolean;
};

export const DEFAULT_GENERATE_SETTINGS: GenerateSettings = {
  artist: null,
  size: "contract",
  width: 832,
  height: 1216,
  nt: 1,
  seed: "",
  negative: "",
  characterPrompts: "auto",
  addMaleCaption: false,
};

const ORIENTATION_LABELS: Record<SizeOrientation, string> = { portrait: "竖", landscape: "横", square: "方" };

type ArtistInfo = { backend: RenderBackend; presets: Partial<Record<SizeOrientation, { width: number; height: number }>> };

/** 画风节点的后端和竖横方预设（复用 Custom 的规则）。 */
function useArtistInfo(artist: NodeSummary | null): ArtistInfo | null {
  const [info, setInfo] = useState<ArtistInfo | null>(null);
  useEffect(() => {
    if (!artist) {
      setInfo(null);
      return;
    }
    let cancelled = false;
    apiGet<{ node: NodeDocument }>(`/nodes/read?ref=${encodeURIComponent(artist.ref)}&role=artist`)
      .then((data) => {
        if (cancelled) return;
        const slot = { draftNode: data.node } as unknown as NodeVariantSlot;
        setInfo({ backend: artistBackend(slot), presets: artistSizePresets(slot) });
      })
      .catch(() => {
        if (cancelled) return;
        const comfy = artist.backends?.includes("comfyui") && !artist.backends?.includes("novelai");
        setInfo({ backend: comfy ? "comfyui" : "novelai", presets: {} });
      });
    return () => {
      cancelled = true;
    };
  }, [artist]);
  return info;
}

/** 一帧的出图请求：composer=agent，提示词是契约里 Agent 写好的完整提示词，画风由脚本叠加。 */
export function buildFrameRequest(
  detail: ContractDetail,
  frame: ContractFrame,
  settings: GenerateSettings,
  info: ArtistInfo,
  outputDir: string,
): BackgroundRequestItem {
  const artist = settings.artist!;
  const characterIds = frame.characters.length ? frame.characters : Object.keys(detail.sources.characters);
  const nodes = characterIds
    .map((id) => detail.sources.characters[id])
    .filter(Boolean)
    .map((node) => ({ role: "character", ref: node.path }));
  if (!nodes.length) {
    // agent composer 至少要一个非画风节点；角色读取失败时退回到来源动作节点。
    const member = detail.sources.action_group?.members.find((item) => item.index === frame.member_index);
    if (member) nodes.push({ role: "action", ref: member.path });
  }
  let size: string = settings.size;
  let note = "";
  if (settings.size === "contract") {
    size = frame.size ?? "random";
    if (frame.size && Object.keys(info.presets).length && !info.presets[frame.size]) {
      size = "random";
      note = `画风没有${ORIENTATION_LABELS[frame.size]}图预设，随机`;
    }
  }
  const negative = [frame.submit.negative ?? "", settings.negative].map((text) => text.trim()).filter(Boolean).join(", ");
  const renderParams: Record<string, unknown> = { n_samples: Math.max(1, Math.trunc(settings.nt || 1)), size };
  if (info.backend === "novelai" && settings.characterPrompts === "auto") {
    renderParams.character_prompts = { mode: "auto", add_male_caption: settings.addMaleCaption };
  }
  const parsedSeed = Number(settings.seed);
  const compose = {
    composer: "agent",
    nodes,
    negative: "",
    agent_result: { positive: frame.submit.positive ?? "", negative },
    contract: { id: detail.id, frame_id: frame.id, prompt_hash: frame.prompt_hash, artist: artist.name },
  };
  const request = {
    compose,
    render: {
      backend: info.backend,
      artist: artist.ref,
      width: settings.width,
      height: settings.height,
      seed: settings.seed.trim() !== "" && Number.isFinite(parsedSeed) && parsedSeed >= 0 ? parsedSeed : undefined,
      params: renderParams,
    },
  } as unknown as ComposeRenderRequest;
  return {
    label: `${frame.id} ${frame.title}${note ? `（${note}）` : ""}`,
    labels: { contract: detail.request.title || detail.id, frame: frame.id, artist: artist.name },
    compose_request: request,
    generate: {
      output_dir: `${outputDir}/${frame.id}`,
      ...(info.backend === "comfyui" && settings.comfyuiTarget ? { comfyui_target: settings.comfyuiTarget } : {}),
    },
  };
}

type FinalLength = { frameId: string; usage?: TokenUsage; error?: string };

/** 用 compose-preview 得到每帧最终提交的提示词（含画风前后缀、分角色提示词），按官网规则数 token。 */
export async function checkFinalLengths(items: { frameId: string; request: ComposeRenderRequest }[]): Promise<FinalLength[]> {
  return Promise.all(items.map(async ({ frameId, request }) => {
    try {
      const result = await apiPost<{ token_usage?: TokenUsage }>("/compose-preview", request);
      return result.token_usage ? { frameId, usage: result.token_usage } : { frameId, error: "这个后端不限长度" };
    } catch (err) {
      return { frameId, error: errorMessage(err) };
    }
  }));
}

/** 画风实际用的模型和契约的目标格式不一致时提示（例如契约按 V4.5 写，画风是 V3 的 tags.txt 画风）。 */
export function formatMismatch(detail: ContractDetail | null, lengths: FinalLength[]): string {
  const profile = detail?.profile;
  const model = lengths.find((item) => item.usage?.model)?.usage?.model;
  if (!profile || !model || !profile.models?.length || profile.models.includes(model)) return "";
  return `画风用的是 ${model}，契约按 ${profile.label || profile.id} 写；权重写法、长度上限可能不适用`;
}

type Props = {
  detail: ContractDetail | null;
  selected: Set<string>;
  settings: GenerateSettings;
  onChange(settings: GenerateSettings): void;
  onSelectAll(all: boolean): void;
  /** 由主界面「生成此帧」触发的单帧提交。 */
  pendingFrame: string | null;
  onPendingHandled(): void;
  onSubmitted(message: string): void;
};

export function ContractGeneratePanel({ detail, selected, settings, onChange, onSelectAll, pendingFrame, onPendingHandled, onSubmitted }: Props) {
  const info = useArtistInfo(settings.artist);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [lengths, setLengths] = useState<FinalLength[] | null>(null);
  const [checking, setChecking] = useState(false);
  const update = (patch: Partial<GenerateSettings>) => {
    setLengths(null);
    onChange({ ...settings, ...patch });
  };

  // 帧内容或所选帧变了，上一次的检查结果就不准了。
  useEffect(() => setLengths(null), [detail, selected]);

  async function checkLengths() {
    setError("");
    if (!detail) return;
    if (!settings.artist || !info) {
      setError("先选择画风：最终长度包含画风的前后缀");
      return;
    }
    const frames = detail.frames.filter((frame) => selected.has(frame.id) && (frame.submit.positive ?? "").trim());
    if (!frames.length) {
      setError("所选帧没有可用的正向提示词");
      return;
    }
    setChecking(true);
    try {
      const items = frames.map((frame) => ({
        frameId: frame.id,
        request: buildFrameRequest(detail, frame, settings, info, "preview").compose_request as ComposeRenderRequest,
      }));
      setLengths(await checkFinalLengths(items));
    } finally {
      setChecking(false);
    }
  }

  async function submit(frameIds: string[]) {
    setError("");
    if (!detail) return;
    if (!settings.artist) {
      setError("先选择画风");
      return;
    }
    if (!info) {
      setError("画风信息还在加载，请稍后再试");
      return;
    }
    const frames = detail.frames.filter((frame) => frameIds.includes(frame.id) && (frame.submit.positive ?? "").trim());
    if (!frames.length) {
      setError("所选帧没有可用的正向提示词");
      return;
    }
    setBusy(true);
    try {
      const outputDir = createCompareOutputDir("contract");
      const items = frames.map((frame) => buildFrameRequest(detail, frame, settings, info, outputDir));
      await submitBackgroundBatch({
        label: `契约 · ${detail.request.title || detail.id} · ${frames.length} 帧`,
        kind: "primary",
        output_dir: outputDir,
        items,
      });
      onSubmitted(`已提交 ${frames.length} 帧，到「出图任务」或帧下方查看结果`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!pendingFrame) return;
    onPendingHandled();
    void submit([pendingFrame]);
    // 只在收到新的单帧请求时触发。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingFrame]);

  const presets = info?.presets ?? {};
  const orientations = (Object.keys(ORIENTATION_LABELS) as SizeOrientation[]).filter((key) => presets[key]);
  const frameCount = detail?.frames.length ?? 0;

  return (
    <section aria-label="生图" className="panel ct-right">
      <div className="panel-title"><h2>生图</h2></div>
      <NodePicker
        displayValue={settings.artist?.name}
        label="画风（不进契约）"
        onClear={() => update({ artist: null })}
        onSelect={(node) => update({ artist: node })}
        placeholder="搜索画风"
        role="artist"
        value={settings.artist?.ref ?? ""}
      />
      {info ? <small className="muted">后端：{info.backend === "comfyui" ? "ComfyUI" : "NovelAI"}</small> : null}
      <div className="params-grid">
        <label className="field params-size">
          <span>尺寸</span>
          <select aria-label="尺寸" onChange={(event) => update({ size: event.target.value as ContractSizeChoice })} value={settings.size}>
            <option value="contract">契约默认（帧的 size，没写时随机）</option>
            <option value="random">随机（覆盖所有帧）</option>
            {(orientations.length ? orientations : (Object.keys(ORIENTATION_LABELS) as SizeOrientation[])).map((key) => (
              <option key={key} value={key}>
                {ORIENTATION_LABELS[key]}{presets[key] ? ` · ${presets[key]!.width}×${presets[key]!.height}` : ""}（覆盖所有帧）
              </option>
            ))}
            <option value="custom">自定义宽高</option>
          </select>
        </label>
        <label className="field">
          <span>Width</span>
          <input aria-label="Width" disabled={settings.size !== "custom"} min={64} onChange={(event) => update({ width: Number(event.target.value) })} type="number" value={settings.width} />
        </label>
        <label className="field">
          <span>Height</span>
          <input aria-label="Height" disabled={settings.size !== "custom"} min={64} onChange={(event) => update({ height: Number(event.target.value) })} type="number" value={settings.height} />
        </label>
        <label className="field">
          <span title="每帧生成张数 (n_samples)">NT</span>
          <input aria-label="NT" min={1} onChange={(event) => update({ nt: Number(event.target.value) })} type="number" value={settings.nt} />
        </label>
        <label className="field">
          <span>Seed</span>
          <input aria-label="Seed" onChange={(event) => update({ seed: event.target.value })} placeholder="-1" value={settings.seed} />
        </label>
      </div>
      <label className="field">
        <span>额外 Negative（追加到每帧的 negative 之后）</span>
        <textarea onChange={(event) => update({ negative: event.target.value })} rows={2} value={settings.negative} />
      </label>
      {info?.backend === "comfyui" ? <ComfyTargetPanel onChange={(value) => update({ comfyuiTarget: value })} value={settings.comfyuiTarget} /> : null}
      <fieldset className="ct-fieldset">
        <legend>提示词行为</legend>
        <label className="ct-check">
          <input
            checked={settings.characterPrompts === "auto"}
            onChange={(event) => update({ characterPrompts: event.target.checked ? "auto" : "off" })}
            type="checkbox"
          />
          Character Prompts 自动（NovelAI V4+）
        </label>
        <label className="ct-check">
          <input
            checked={settings.addMaleCaption}
            disabled={settings.characterPrompts !== "auto"}
            onChange={(event) => update({ addMaleCaption: event.target.checked })}
            type="checkbox"
          />
          Add male caption
        </label>
        <small className="muted">与 agent composer 一致，契约提示词默认不走 Policy Rules；契约里带哪些角色词由 Agent 决定。</small>
      </fieldset>
      <div className="ct-row">
        <button className="btn-sm" disabled={!frameCount} onClick={() => onSelectAll(true)} type="button">全选</button>
        <button className="btn-sm" disabled={!selected.size} onClick={() => onSelectAll(false)} type="button">清空</button>
        <span className="muted">已选 {selected.size} / {frameCount} 帧</span>
      </div>
      <div className="ct-row">
        <button className="primary" disabled={busy || !detail || !selected.size} onClick={() => void submit([...selected])} type="button">
          <Play size={14} /> 生成所选帧
        </button>
        <button
          className="btn-sm"
          disabled={checking || !detail || !selected.size}
          onClick={() => void checkLengths()}
          title="按所选画风拼出最终提示词（含画风前后缀、分角色提示词），用和 NovelAI 官网相同的分词器数 token"
          type="button"
        >
          <Ruler size={13} /> {checking ? "检查中…" : "检查最终长度"}
        </button>
      </div>
      {lengths ? (
        <ul className="ct-lengths" aria-label="最终长度">
          {formatMismatch(detail, lengths) ? <li className="field-error">{formatMismatch(detail, lengths)}</li> : null}
          {lengths.map((item) => (
            <li key={item.frameId}>
              <span className="mono">{item.frameId}</span>
              {item.usage ? <TokenBadge usage={item.usage} /> : <small className="muted">{item.error}</small>}
              {item.usage?.model ? <small className="muted mono">{item.usage.model}</small> : null}
              {item.usage?.over ? <small className="field-error">超出部分会被截断</small> : null}
            </li>
          ))}
        </ul>
      ) : null}
      {error ? <p className="field-error">{error}</p> : null}
    </section>
  );
}
