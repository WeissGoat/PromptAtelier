import { Braces, FileJson2, RotateCcw, Save, X } from "lucide-react";
import { useEffect, useState } from "react";

import { apiPost, apiPut, errorMessage } from "../api/client";
import type { NodeReadResponse, NodeSavePreviewResponse } from "../api/types";
import type { NodeDocument } from "../nodes/types";
import { useCustomWorkspace } from "../workspace/CustomWorkspaceProvider";
import { ActionNodeForm } from "./nodeForms/ActionNodeForm";
import { ArtistNodeForm } from "./nodeForms/ArtistNodeForm";
import { CharacterNodeForm } from "./nodeForms/CharacterNodeForm";
import { NodeSaveDiffDialog } from "./NodeSaveDiffDialog";
import { RandomNodeEditor } from "./RandomNodeEditor";

type NodePreviewResponse = { node: NodeDocument };

function formatNode(node: NodeDocument | null): string {
  return node ? JSON.stringify(node, null, 2) : "";
}

function sameValue(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function parseEditorNode(text: string): NodeDocument {
  const parsed: unknown = JSON.parse(text);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("节点必须是 JSON 对象。");
  const node = parsed as Partial<NodeDocument>;
  if (typeof node.id !== "string" || typeof node.kind !== "string") throw new Error("节点必须包含字符串类型的 id 和 kind。");
  if (!node.prompt || !Array.isArray(node.prompt.positive) || !Array.isArray(node.prompt.negative)) {
    throw new Error("节点必须包含 prompt.positive 和 prompt.negative 数组。");
  }
  return parsed as NodeDocument;
}

function SourceForm({ role, values, onChange }: { role: string; values: Record<string, unknown>; onChange(values: Record<string, unknown>): void }) {
  if (role === "artist") return <ArtistNodeForm onChange={onChange} values={values} />;
  if (role === "action") return <ActionNodeForm onChange={onChange} values={values} />;
  if (role === "character") return <CharacterNodeForm onChange={onChange} values={values} />;
  return <div className="empty-workspace">当前节点类型没有可用的 Form，请使用 JSON 查看运行时节点。</div>;
}

export function NodeWorkspaceEditor() {
  const workspace = useCustomWorkspace();
  const editor = workspace.state.editor;
  const slot = editor.slotId ? workspace.findSlot(editor.slotId) : null;
  const [jsonText, setJsonText] = useState(formatNode(editor.draftNode));
  const [jsonError, setJsonError] = useState("");
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [savePreview, setSavePreview] = useState<NodeSavePreviewResponse | null>(null);

  useEffect(() => {
    setJsonText(formatNode(editor.draftNode));
    setJsonError("");
    setError("");
    setStatus("");
    setSavePreview(null);
  }, [editor.slotId]);

  useEffect(() => {
    if (!slot?.sourceRef || !slot.sourceEditor || !editor.editValues || editor.tab !== "form") return;
    if (sameValue(editor.editValues, editor.baselineValues)) return;
    let active = true;
    const timer = window.setTimeout(() => {
      setStatus("正在更新临时节点...");
      void apiPost<NodePreviewResponse>("/nodes/editor-preview", {
        ref: slot.sourceRef,
        role: slot.role,
        values: editor.editValues,
      }).then((response) => {
        if (!active) return;
        workspace.setEditorDraft(response.node);
        workspace.updateDraft(slot.slotId, response.node);
        setJsonText(formatNode(response.node));
        setError("");
        setStatus("临时节点已更新");
      }).catch((requestError) => {
        if (!active) return;
        setError(errorMessage(requestError));
        setStatus("");
      });
    }, 200);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [editor.editValues, editor.tab, slot?.role, slot?.slotId, slot?.sourceEditor, slot?.sourceRef]);

  if (slot?.sourceKind === "random" && editor.kind === "random") {
    return <section className="panel node-workspace-panel"><RandomNodeEditor slot={slot} /></section>;
  }

  if (!slot || !editor.draftNode) {
    return (
      <section className="panel node-workspace-panel">
        <div className="panel-title"><h2>Node Editor</h2></div>
        <div className="empty-workspace">选择或新建节点后，点击编辑按钮在这里临时调整。</div>
      </section>
    );
  }

  const draft = editor.draftNode;
  const slotId = slot.slotId;
  const values = editor.editValues;
  const valuesChanged = !sameValue(values, editor.baselineValues);

  function requestClose() {
    if (jsonError && !window.confirm("当前 JSON 无效，关闭后会丢失尚未生效的文本。是否继续？")) return;
    workspace.closeEditor();
  }

  async function handleSavePreview() {
    if (!slot?.sourceRef || !values || !slot.sourceEditor?.capabilities.save) return;
    setBusy(true);
    setError("");
    try {
      const preview = await apiPost<NodeSavePreviewResponse>("/nodes/save-preview", {
        ref: slot.sourceRef,
        role: slot.role,
        values,
      });
      setSavePreview(preview);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  }

  async function commitSave() {
    if (!savePreview) return;
    setBusy(true);
    setError("");
    try {
      const saved = await apiPut<NodeReadResponse>("/nodes/save-commit", {
        preview_id: savePreview.preview_id,
      });
      workspace.applySavedNode(slotId, saved);
      setJsonText(formatNode(saved.node));
      setSavePreview(null);
      setStatus("已保存到原数据源");
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel node-workspace-panel">
      <div className="panel-title node-editor-title">
        <div><h2>{draft.name || draft.id}</h2><small>{slot.mode === "compare" ? "Compare" : "Primary"} · {slot.role}</small></div>
        <button aria-label="关闭节点编辑器" className="icon-button" onClick={requestClose} title="关闭" type="button"><X size={17} /></button>
      </div>
      <div className="editor-tabs" role="tablist">
        <button aria-selected={editor.tab === "form"} className={editor.tab === "form" ? "active" : ""} onClick={() => workspace.setEditorTab("form")} role="tab" type="button"><Braces size={15} /> Form</button>
        <button aria-selected={editor.tab === "json"} className={editor.tab === "json" ? "active" : ""} onClick={() => workspace.setEditorTab("json")} role="tab" type="button"><FileJson2 size={15} /> JSON</button>
      </div>

      <div className="node-editor-body">
        {editor.tab === "form" ? (
          values && slot.sourceEditor
            ? <SourceForm onChange={workspace.setEditorValues} role={slot.role} values={values} />
            : <div className="empty-workspace">空白节点暂时使用 JSON 编辑；保存时会按节点角色创建标准源文件。</div>
        ) : (
          <label className="field json-workspace-editor">
            <span>Runtime Node JSON</span>
            <textarea aria-label="Node JSON" onChange={(event) => {
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
            }} spellCheck={false} value={jsonText} />
          </label>
        )}
      </div>

      {status ? <div className="editor-status" aria-live="polite">{status}</div> : null}
      {jsonError ? <div className="alert error-alert" role="alert">JSON 格式无效：{jsonError}</div> : null}
      {error ? <div className="alert error-alert" role="alert">{error}</div> : null}
      <div className="node-editor-actions">
        <button disabled={busy || !slot.sourceNode} onClick={() => {
          if ((valuesChanged || jsonError) && !window.confirm("当前编辑将被还原，是否继续？")) return;
          workspace.restoreSlot(slot.slotId);
          workspace.closeEditor();
        }} type="button"><RotateCcw size={15} /> 还原</button>
        <span />
        <button disabled={busy || Boolean(jsonError) || !slot.sourceRef || !values || !slot.sourceEditor?.capabilities.save} onClick={() => void handleSavePreview()} type="button"><Save size={15} /> 保存节点</button>
      </div>
      {savePreview ? <NodeSaveDiffDialog busy={busy} error={error} onCancel={() => setSavePreview(null)} onConfirm={() => void commitSave()} preview={savePreview} /> : null}
    </section>
  );
}
