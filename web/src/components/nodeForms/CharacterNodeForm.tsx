import { StructuredValueEditor } from "../StructuredValueEditor";
import { StringListField, recordValue, stringList } from "./NodeFormFields";
import { TagSectionsField } from "./TagSectionsField";

export function CharacterNodeForm({ values, onChange }: { values: Record<string, unknown>; onChange(values: Record<string, unknown>): void }) {
  const update = (key: string, value: unknown) => onChange({ ...values, [key]: value });
  return (
    <>
      <section className="node-form-section">
        <h3>基础信息</h3>
        <div className="node-form-grid">
          <label className="field"><span>ID</span><input aria-label="Character ID" onChange={(event) => update("id", event.target.value)} value={String(values.id ?? "")} /></label>
          <label className="field"><span>Name</span><input aria-label="Character name" onChange={(event) => update("name", event.target.value)} value={String(values.name ?? "")} /></label>
          <label className="field full-row"><span>Description</span><textarea aria-label="Character description" onChange={(event) => update("description", event.target.value)} value={String(values.description ?? "")} /></label>
        </div>
      </section>
      <StringListField label="Positive Prompt" onChange={(items) => update("positive", items)} values={stringList(values.positive)} />
      <StringListField label="Negative Prompt" onChange={(items) => update("negative", items)} values={stringList(values.negative)} />
      <StringListField label="Identity Minimal" multiline={false} onChange={(items) => update("identity_minimal", items)} values={stringList(values.identity_minimal)} />
      <section className="node-form-section"><h3>Relations</h3><StructuredValueEditor onChange={(next) => update("relations", next)} path={["relations"]} value={recordValue(values.relations)} /></section>
      <TagSectionsField label="角色标签" onChange={(next) => update("tags", next)} value={recordValue(values.tags)} />
    </>
  );
}
