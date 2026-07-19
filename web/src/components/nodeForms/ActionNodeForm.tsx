import { Plus, Trash2 } from "lucide-react";

import { StringListField, stringList } from "./NodeFormFields";

export function ActionNodeForm({ values, onChange }: { values: Record<string, unknown>; onChange(values: Record<string, unknown>): void }) {
  const selectedKeys = Array.isArray(values.selected_keys) ? values.selected_keys.map(stringList) : [];
  const update = (key: string, value: unknown) => onChange({ ...values, [key]: value });
  return (
    <>
      <section className="node-form-section">
        <h3>基础信息</h3>
        <div className="node-form-grid">
          <label className="field"><span>ID</span><input aria-label="Action ID" onChange={(event) => update("id", event.target.value)} value={String(values.id ?? "")} /></label>
          <label className="field"><span>Name</span><input aria-label="Action name" onChange={(event) => update("name", event.target.value)} value={String(values.name ?? "")} /></label>
          <label className="field full-row"><span>Description</span><textarea aria-label="Action description" onChange={(event) => update("description", event.target.value)} value={String(values.description ?? "")} /></label>
        </div>
      </section>
      <StringListField label="Action Prompt" onChange={(items) => update("prompt_lines", items)} values={stringList(values.prompt_lines)} />
      <StringListField label="Negative Prompt" onChange={(items) => update("negative", items)} values={stringList(values.negative)} />
      <section className="node-form-section">
        <div className="section-title-row"><h3>角色 Selected Keys</h3><button onClick={() => update("selected_keys", [...selectedKeys, []])} type="button"><Plus size={14} /> 添加角色</button></div>
        <div className="selected-keys-list">
          {selectedKeys.map((keys, index) => (
            <div className="selected-keys-row" key={`selected-${index}`}>
              <label className="field"><span>角色 {index + 1}</span><input aria-label={`Character ${index + 1} selected keys`} onChange={(event) => update("selected_keys", selectedKeys.map((item, itemIndex) => itemIndex === index ? event.target.value.split(",").map((key) => key.trim()).filter(Boolean) : item))} placeholder="character, copyright, hair" value={keys.join(", ")} /></label>
              <button aria-label={`删除角色 ${index + 1}`} className="icon-button" onClick={() => update("selected_keys", selectedKeys.filter((_, itemIndex) => itemIndex !== index))} title="删除角色" type="button"><Trash2 size={15} /></button>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}
