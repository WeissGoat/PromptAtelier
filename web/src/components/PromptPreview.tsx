type PromptPreviewProps = {
  prompt: string;
  negative: string;
  renderRequest: unknown;
};

export function PromptPreview({ prompt, negative, renderRequest }: PromptPreviewProps) {
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
      {renderRequest ? (
        <details className="raw-render-details">
          <summary>完整生图参数</summary>
          <pre className="json-preview">{JSON.stringify(renderRequest, null, 2)}</pre>
        </details>
      ) : null}
    </div>
  );
}
