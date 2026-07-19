import { StringListField, recordValue, stringList } from "./NodeFormFields";

export function ArtistNodeForm({ values, onChange }: { values: Record<string, unknown>; onChange(values: Record<string, unknown>): void }) {
  const params = recordValue(values.params);
  const update = (key: string, value: unknown) => onChange({ ...values, [key]: value });
  const updateParam = (key: string, value: unknown) => update("params", { ...params, [key]: value });
  return (
    <>
      <section className="node-form-section">
        <h3>基础信息</h3>
        <label className="field"><span>Name</span><input aria-label="Artist name" onChange={(event) => update("name", event.target.value)} value={String(values.name ?? "")} /></label>
      </section>
      <StringListField label="Prompt Prefix" onChange={(items) => update("prompt_prefix", items)} values={stringList(values.prompt_prefix)} />
      <StringListField label="Prompt Suffix" onChange={(items) => update("prompt_suffix", items)} values={stringList(values.prompt_suffix)} />
      <section className="node-form-section node-form-grid">
        <label className="field full-row"><span>Negative Prompt</span><textarea aria-label="Artist negative prompt" onChange={(event) => update("negative_prompt", event.target.value)} value={String(values.negative_prompt ?? "")} /></label>
        <label className="field full-row"><span>After Negative</span><textarea aria-label="Artist after negative" onChange={(event) => update("after_negative_prompt", event.target.value)} value={String(values.after_negative_prompt ?? "")} /></label>
      </section>
      <section className="node-form-section">
        <h3>NovelAI 常用参数</h3>
        <div className="node-form-grid">
          <label className="field full-row"><span>Model</span><input aria-label="Artist model" onChange={(event) => updateParam("model", event.target.value)} value={String(params.model ?? "")} /></label>
          <label className="field"><span>Sampler</span><input aria-label="Artist sampler" onChange={(event) => updateParam("sampler", event.target.value)} value={String(params.sampler ?? "")} /></label>
          <label className="field"><span>Noise Schedule</span><input aria-label="Artist noise schedule" onChange={(event) => updateParam("noise_schedule", event.target.value)} value={String(params.noise_schedule ?? "")} /></label>
          <label className="field"><span>Steps</span><input aria-label="Artist steps" onChange={(event) => updateParam("steps", Number(event.target.value))} type="number" value={String(params.steps ?? 28)} /></label>
          <label className="field"><span>Scale</span><input aria-label="Artist scale" onChange={(event) => updateParam("scale", Number(event.target.value))} type="number" value={String(params.scale ?? 5)} /></label>
        </div>
      </section>
      <StringListField label="Flags" multiline={false} onChange={(items) => update("flags", items)} values={stringList(values.flags)} />
    </>
  );
}
