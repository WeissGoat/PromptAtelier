import type { NodeDocument, PromptFragment } from "../../nodes/types";
import { StructuredValueEditor } from "../StructuredValueEditor";
import { StringListField } from "./NodeFormFields";

// 这些字段由下面的专门控件编辑，或者是只读的标识。
const MANAGED_KEYS = new Set(["schema", "kind", "id", "name", "description", "prompt"]);

function fragmentTexts(fragments: PromptFragment[] | undefined): string[] {
  return (fragments ?? []).map((fragment) => fragment.text);
}

function withTexts(fragments: PromptFragment[] | undefined, texts: string[]): PromptFragment[] {
  // 保留原片段上的 role / weight / scopes，只换文本；新增的行是普通片段。
  return texts.map((text, index) => ({ ...(fragments?.[index] ?? {}), text }));
}

/**
 * 由运行时 JSON 生成的通用表单：没有专门源文件表单的节点（ComfyUI 画风、空白临时节点等）用它编辑。
 * 改动只进临时节点，和 JSON 页签是同一份数据。
 */
export function GenericNodeForm({ node, onChange }: { node: NodeDocument; onChange(node: NodeDocument): void }) {
  const update = (patch: Partial<NodeDocument>) => onChange({ ...node, ...patch });
  const extra = Object.fromEntries(Object.entries(node).filter(([key]) => !MANAGED_KEYS.has(key)));

  return (
    <>
      <section className="node-form-section">
        <h3>基础信息</h3>
        <div className="node-form-grid">
          <label className="field"><span>ID</span><input aria-label="Node ID" onChange={(event) => update({ id: event.target.value })} value={node.id} /></label>
          <label className="field"><span>Name</span><input aria-label="Node name" onChange={(event) => update({ name: event.target.value })} value={node.name ?? ""} /></label>
          <label className="field full-row"><span>Description</span><textarea aria-label="Node description" onChange={(event) => update({ description: event.target.value })} value={node.description ?? ""} /></label>
        </div>
      </section>
      <StringListField
        label="Positive Prompt"
        onChange={(texts) => update({ prompt: { ...node.prompt, positive: withTexts(node.prompt.positive, texts) } })}
        values={fragmentTexts(node.prompt.positive)}
      />
      <StringListField
        label="Negative Prompt"
        onChange={(texts) => update({ prompt: { ...node.prompt, negative: withTexts(node.prompt.negative, texts) } })}
        values={fragmentTexts(node.prompt.negative)}
      />
      <section className="node-form-section">
        <h3>其他字段</h3>
        <StructuredValueEditor
          onChange={(next) => {
            const value = (next && typeof next === "object" && !Array.isArray(next) ? next : {}) as Record<string, unknown>;
            const managed = Object.fromEntries(Object.entries(node).filter(([key]) => MANAGED_KEYS.has(key)));
            onChange({ ...value, ...managed } as NodeDocument);
          }}
          value={extra}
        />
      </section>
    </>
  );
}
