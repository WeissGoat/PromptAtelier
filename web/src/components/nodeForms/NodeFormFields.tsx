import { Plus, Trash2 } from "lucide-react";

export function StringListField({
  label,
  values,
  onChange,
  multiline = true,
}: {
  label: string;
  values: string[];
  onChange(values: string[]): void;
  multiline?: boolean;
}) {
  return (
    <section className="node-form-section">
      <div className="section-title-row">
        <h3>{label}</h3>
        <button onClick={() => onChange([...values, ""])} type="button"><Plus size={14} /> 添加</button>
      </div>
      <div className="prompt-fragment-list">
        {values.map((value, index) => (
          <div className="prompt-fragment-row" key={`${label}-${index}`}>
            {multiline ? (
              <textarea aria-label={`${label} ${index + 1}`} onChange={(event) => onChange(values.map((item, itemIndex) => itemIndex === index ? event.target.value : item))} value={value} />
            ) : (
              <input aria-label={`${label} ${index + 1}`} onChange={(event) => onChange(values.map((item, itemIndex) => itemIndex === index ? event.target.value : item))} value={value} />
            )}
            <button aria-label={`删除 ${label} ${index + 1}`} className="icon-button" onClick={() => onChange(values.filter((_, itemIndex) => itemIndex !== index))} title="删除" type="button"><Trash2 size={15} /></button>
          </div>
        ))}
      </div>
    </section>
  );
}
export function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return typeof value === "string" && value ? [value] : [];
  return value.map(String);
}

export function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
