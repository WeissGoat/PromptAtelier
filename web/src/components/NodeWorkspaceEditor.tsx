import { Braces, FileJson2, RotateCcw, Save, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { apiPost, apiUrl, errorMessage } from "../api/client";
import type { NodeReadResponse } from "../api/types";
import { cloneNode } from "../nodes/temporaryNodes";
import type { NodeDocument, PromptFragment } from "../nodes/types";
import { useCustomWorkspace } from "../workspace/CustomWorkspaceProvider";
import { StructuredValueEditor } from "./StructuredValueEditor";

type NodePreviewResponse = { node: NodeDocument };

const coreKeys = new Set(["schema", "kind", "id", "name", "description", "prompt", "tags"]);

function formatNode(node: NodeDocument | null): string {
  return node ? JSON.stringify(node, null, 2) : "";
}

function sameValue(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function promptFragment(value = ""): PromptFragment {
  return { text: value };
}

function parseEditorNode(text: string): NodeDocument {
  const parsed: unknown = JSON.parse(text);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("节点必须是 JSON 对象。");
  const node = parsed as Partial<NodeDocument>;
  if (typeof node.id !== "string" || typeof node.kind !== "string") throw new Error("节点必须包含字符串类型的 id 和 kind。");
  if (!node.prompt || !Array.isArray(node.prompt.positive) || !Array.isArray(node.prompt.negative)) {
    throw new Error("节点必须包含 prompt.positive 和 prompt.negative 数组。");
  }
  for (const fragment of [...node.prompt.positive, ...node.prompt.negative]) {
    if (!fragment || typeof fragment !== "object" || typeof fragment.text !== "string") {
      throw new Error("Prompt 数组中的每一项都必须包含 text 字符串。");
    }
  }
  return parsed as NodeDocument;
}

function editorHasChanges(draft: NodeDocument | null, baseline: NodeDocument | null, jsonError = ""): boolean {
  return Boolean(jsonError) || !sameValue(draft, baseline);
}

export function NodeWorkspaceEditor() {
  const workspace = useCustomWorkspace();
  const editor = workspace.state.editor;
  const slot = editor.slotId ? workspace.findSlot(editor.slotId) : null;
  const [jsonText, setJsonText] = useState(formatNode(editor.draftNode));
  const [jsonError, setJsonError] = useState("");
  const [targetRef, setTargetRef] = useState(slot?.sourceRef ?? "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setJsonText(formatNode(editor.draftNode));
    setJsonError("");
    setTargetRef(slot?.sourceRef ?? "");
    setError("");
  }, [editor.slotId]);

  const draft = editor.draftNode;
  const extensionEntries = useMemo(() => draft
    ? Object.entries(draft).filter(([key]) => !coreKeys.has(key))
    : [], [draft]);

  function updateDraft(next: NodeDocument) {
    workspace.setEditorDraft(next);
    if (slot) workspace.updateDraft(slot.slotId, next);
    setJsonText(formatNode(next));
    setJsonError("");
  }

  function updateField(key: keyof NodeDocument, value: unknown) {
    if (!draft) return;
    updateDraft({ ...draft, [key]: value } as NodeDocument);
  }

  function updatePrompt(kind: "positive" | "negative", fragments: PromptFragment[]) {
    if (!draft) return;
    updateDraft({ ...draft, prompt: { ...draft.prompt, [kind]: fragments } });
  }

  function requestClose() {
    if (jsonError && !window.confirm("当前 JSON 无效，关闭后会丢失尚未生效的文本。是否继续？")) return;
    workspace.closeEditor();
  }

  async function validateDraft(): Promise<NodeDocument> {
    if (jsonError || !draft) throw new Error(jsonError || "没有可应用的节点草稿。");
    if (!draft.id.trim()) throw new Error("节点 id 不能为空。");
    const response = await apiPost<NodePreviewResponse>("/nodes/preview", { node: draft });
    return response.node;
  }

  async function handleSave() {
    if (!slot) return;
    const saveRef = (slot.sourceRef ?? targetRef).trim();
    if (!saveRef) {
      setError("请输入节点库内的目标 ref。");
      return;
    }
    if (!window.confirm(`将节点保存到 ${saveRef}，是否继续？`)) return;
    setBusy(true);
    setError("");
    try {
      const normalized = await validateDraft();
      const response = await fetch(apiUrl("/nodes/save"), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ref: saveRef, node: normalized }),
      });
      if (!response.ok) throw new Error(await response.text());
      const saved = await response.json() as NodeReadResponse;
      workspace.selectNode(slot.slotId, saved.ref, saved.node);
      workspace.closeEditor();
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  }

  if (!slot || !draft) {
    return (
      <section className="panel node-workspace-panel">
        <div className="panel-title"><h2>Node Editor</h2></div>
        <div className="empty-workspace">选择或新建节点后，点击编辑按钮在这里临时调整。</div>
      </section>
    );
  }

  return (
    <section className="panel node-workspace-panel">
      <div className="panel-title node-editor-title">
        <div>
          <h2>{draft.name || draft.id}</h2>
          <small>{slot.mode === "compare" ? "Compare" : "Primary"} · {slot.role}</small>
        </div>
        <button aria-label="关闭节点编辑器" className="icon-button" onClick={requestClose} title="关闭" type="button"><X size={17} /></button>
      </div>
      <div className="editor-tabs" role="tablist">
        <button aria-selected={editor.tab === "form"} className={editor.tab === "form" ? "active" : ""} onClick={() => workspace.setEditorTab("form")} role="tab" type="button"><Braces size={15} /> Form</button>
        <button aria-selected={editor.tab === "json"} className={editor.tab === "json" ? "active" : ""} onClick={() => workspace.setEditorTab("json")} role="tab" type="button"><FileJson2 size={15} /> JSON</button>
      </div>

      <div className="node-editor-body">
        {editor.tab === "form" ? (
          <>
            <section className="node-form-section">
              <h3>基础信息</h3>
              <div className="node-form-grid">
                <label className="field"><span>ID</span><input aria-label="Node ID" onChange={(event) => updateField("id", event.target.value)} value={draft.id} /></label>
                <label className="field"><span>Name</span><input aria-label="Node name" onChange={(event) => updateField("name", event.target.value || null)} value={draft.name ?? ""} /></label>
                <label className="field full-row"><span>Description</span><textarea aria-label="Node description" onChange={(event) => updateField("description", event.target.value || null)} value={draft.description ?? ""} /></label>
              </div>
            </section>

            {(["positive", "negative"] as const).map((kind) => (
              <section className="node-form-section" key={kind}>
                <div className="section-title-row">
                  <h3>{kind === "positive" ? "Prompt" : "Negative Prompt"}</h3>
                  <button onClick={() => updatePrompt(kind, [...draft.prompt[kind], promptFragment()])} type="button">添加片段</button>
                </div>
                <div className="prompt-fragment-list">
                  {draft.prompt[kind].map((fragment, index) => (
                    <div className="prompt-fragment-row" key={`${kind}-${index}`}>
                      <textarea
                        aria-label={`${kind} prompt ${index + 1}`}
                        onChange={(event) => updatePrompt(kind, draft.prompt[kind].map((item, itemIndex) => itemIndex === index ? { ...item, text: event.target.value } : item))}
                        value={fragment.text}
                      />
                      <button className="icon-button" onClick={() => updatePrompt(kind, draft.prompt[kind].filter((_, itemIndex) => itemIndex !== index))} title="删除片段" type="button"><X size={15} /></button>
                    </div>
                  ))}
                </div>
              </section>
            ))}

            <section className="node-form-section">
              <h3>Tags</h3>
              <StructuredValueEditor onChange={(next) => updateField("tags", next)} path={["tags"]} value={draft.tags ?? {}} />
            </section>

            <section className="node-form-section">
              <h3>扩展字段</h3>
              <StructuredValueEditor
                onChange={(next) => {
                  const extensions = next as Record<string, unknown>;
                  const core = Object.fromEntries(Object.entries(draft).filter(([key]) => coreKeys.has(key)));
                  updateDraft({ ...core, ...extensions } as NodeDocument);
                }}
                path={["extensions"]}
                value={Object.fromEntries(extensionEntries)}
              />
            </section>
          </>
        ) : (
          <label className="field json-workspace-editor">
            <span>Node JSON</span>
            <textarea
              aria-label="Node JSON"
              onChange={(event) => {
                const text = event.target.value;
                setJsonText(text);
                try {
                  const parsed = parseEditorNode(text);
                  workspace.setEditorDraft(parsed);
                  workspace.updateDraft(slot.slotId, parsed);
                  setJsonError("");
                } catch (parseError) {
                  setJsonError(errorMessage(parseError));
                }
              }}
              spellCheck={false}
              value={jsonText}
            />
          </label>
        )}
      </div>

      {jsonError ? <div className="alert error-alert" role="alert">JSON 格式无效：{jsonError}</div> : null}
      {error ? <div className="alert error-alert" role="alert">{error}</div> : null}
      {!slot.sourceRef ? (
        <label className="field compact"><span>保存目标 ref</span><input aria-label="Target ref" onChange={(event) => setTargetRef(event.target.value)} placeholder={`${slot.role}s/new-node`} value={targetRef} /></label>
      ) : null}
      <div className="node-editor-actions">
        <button disabled={busy || !slot.sourceNode} onClick={() => {
          if (editorHasChanges(draft, editor.baselineNode, jsonError) && !window.confirm("当前编辑将被还原，是否继续？")) return;
          workspace.restoreSlot(slot.slotId);
          workspace.closeEditor();
        }} type="button"><RotateCcw size={15} /> 还原</button>
        <span />
        <button disabled={busy || Boolean(jsonError) || !(slot.sourceRef ?? targetRef).trim()} onClick={() => void handleSave()} type="button"><Save size={15} /> 保存节点</button>
      </div>
    </section>
  );
}
