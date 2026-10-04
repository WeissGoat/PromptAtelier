import type { ComposePreviewResponse } from "../api/types";

type PromptPreviewProps = {
  prompt: string;
  negative: string;
  renderRequest: unknown;
  promptBundle?: ComposePreviewResponse["prompt_bundle"];
};

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

export function PromptPreview({ prompt, negative, renderRequest, promptBundle }: PromptPreviewProps) {
  const request = record(renderRequest);
  const parameters = record(request.parameters);
  // compose-preview 返回的是 core RenderRequest：尺寸在 size 里，采样参数在 params 里。
  const params = record(request.params);
  const size = record(request.size);
  const width = request.width ?? size.width;
  const height = request.height ?? size.height;
  const comfyui = request.backend === "comfyui";
  const summary = [
    ["Backend", comfyui ? "ComfyUI" : undefined],
    ["Workflow", comfyui ? params.workflow : undefined],
    ["Model", request.model],
    ["Size", width && height ? `${width} × ${height}` : undefined],
    ["Sampler", request.sampler ?? parameters.sampler ?? params.sampler],
    ["Steps", request.steps ?? parameters.steps ?? params.steps],
    ["Scale", request.scale ?? parameters.scale ?? params.scale ?? params.cfg],
    ["Seed", request.seed ?? parameters.seed],
  ].filter((item): item is [string, unknown] => item[1] !== undefined && item[1] !== null);
  // ComfyUI 收到的是换算过权重的提示词；和 NovelAI 写法不同时单独列出来。
  const comfyuiPositive = comfyui && typeof params.positive_prompt === "string" && params.positive_prompt !== request.prompt
    ? params.positive_prompt
    : null;
  const comfyuiNegative = comfyui && typeof params.negative_prompt === "string" && params.negative_prompt !== request.negative_prompt
    ? params.negative_prompt
    : null;
  const requestMeta = request.meta && typeof request.meta === "object"
    ? request.meta as Record<string, unknown>
    : {};
  const characterPromptMeta = requestMeta.character_prompts && typeof requestMeta.character_prompts === "object"
    ? requestMeta.character_prompts as Record<string, unknown>
    : null;
  const composition = promptBundle?.meta?.composition;
  const policy = promptBundle?.meta?.extra?.policy;
  return (
    <div className="preview-stack">
      <label className="field">
        <span>Positive</span>
        <textarea aria-label="Positive preview" readOnly value={prompt} />
      </label>
      <label className="field compact">
        <span>Negative</span>
        <textarea aria-label="Negative preview" readOnly value={negative} />
      </label>
      {comfyuiPositive !== null ? (
        <label className="field compact">
          <span>ComfyUI Positive（权重已换算）</span>
          <textarea aria-label="ComfyUI positive preview" readOnly value={comfyuiPositive} />
        </label>
      ) : null}
      {comfyuiNegative !== null ? (
        <label className="field compact">
          <span>ComfyUI Negative（权重已换算）</span>
          <textarea aria-label="ComfyUI negative preview" readOnly value={comfyuiNegative} />
        </label>
      ) : null}
      {summary.length ? (
        <dl className="render-summary">
          {summary.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{String(value)}</dd></div>)}
        </dl>
      ) : <div className="empty-preview">点击 Preview 后显示最终提示词和生图参数。</div>}
      {promptBundle?.meta || characterPromptMeta ? (
        <dl className="behavior-summary">
          {policy?.template ? <div><dt>Policy baseline</dt><dd>{policy.template}</dd></div> : null}
          {composition?.included_character_sections?.length ? <div><dt>Identity included</dt><dd>{composition.included_character_sections.join(", ")}</dd></div> : null}
          {composition?.suppressed_character_sections?.length ? <div><dt>Identity suppressed</dt><dd>{composition.suppressed_character_sections.join(", ")}</dd></div> : null}
          {characterPromptMeta ? <div><dt>Character Prompts</dt><dd>{String(characterPromptMeta.status ?? `${characterPromptMeta.count ?? 0} captions`)}</dd></div> : null}
        </dl>
      ) : null}
      {renderRequest ? (
        <details className="raw-render-details">
          <summary>完整生图参数</summary>
          <pre className="json-preview">{JSON.stringify(renderRequest, null, 2)}</pre>
        </details>
      ) : null}
    </div>
  );
}
