import type { ComposePreviewResponse } from "../api/types";

type PromptPreviewProps = {
  prompt: string;
  negative: string;
  renderRequest: unknown;
  promptBundle?: ComposePreviewResponse["prompt_bundle"];
};

export function PromptPreview({ prompt, negative, renderRequest, promptBundle }: PromptPreviewProps) {
  const request = renderRequest && typeof renderRequest === "object" ? renderRequest as Record<string, unknown> : {};
  const parameters = request.parameters && typeof request.parameters === "object"
    ? request.parameters as Record<string, unknown>
    : {};
  const summary = [
    ["Model", request.model],
    ["Size", request.width && request.height ? `${request.width} × ${request.height}` : undefined],
    ["Sampler", request.sampler ?? parameters.sampler],
    ["Steps", request.steps ?? parameters.steps],
    ["Scale", request.scale ?? parameters.scale],
    ["Seed", request.seed ?? parameters.seed],
  ].filter((item): item is [string, unknown] => item[1] !== undefined && item[1] !== null);
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
