type PromptPreviewProps = {
  prompt: string;
  negative: string;
  renderRequest: unknown;
};

export function PromptPreview({ prompt, negative, renderRequest }: PromptPreviewProps) {
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
      <pre className="json-preview">{JSON.stringify(renderRequest ?? {}, null, 2)}</pre>
    </div>
  );
}
