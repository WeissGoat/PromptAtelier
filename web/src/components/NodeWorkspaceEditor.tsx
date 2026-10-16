import { Braces, ChevronRight, FileCode2, FileJson2, MousePointerClick, RotateCcw, Save, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { apiPost, apiPut, errorMessage } from "../api/client";
import type { NodeReadResponse, NodeSavePreviewResponse } from "../api/types";
import type { NodeDocument } from "../nodes/types";
import { useCustomWorkspace } from "../workspace/CustomWorkspaceProvider";
import type { EditorTab } from "../workspace/types";
import { ActionNodeForm } from "./nodeForms/ActionNodeForm";
import { ArtistNodeForm } from "./nodeForms/ArtistNodeForm";
import { CharacterNodeForm } from "./nodeForms/CharacterNodeForm";
import { ClothingNodeForm } from "./nodeForms/ClothingNodeForm";
import { GenericNodeForm } from "./nodeForms/GenericNodeForm";
import { NodeSaveDiffDialog } from "./NodeSaveDiffDialog";
import { RandomNodeEditor } from "./RandomNodeEditor";
import { SourceFilesPanel } from "./SourceFilesPanel";

type NodePreviewResponse = { node: NodeDocument };

const roleLabels: Record<string, string> = {
  artist: "画风 Artist",
  character: "角色 Character",
  action: "动作 Action",
  clothing: "服装 Clothing",
};

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
  if (role === "clothing") return <ClothingNodeForm onChange={onChange} values={values} />;
  return null;
}

function IdleEditor() {
  return (
    <section className="panel node-workspace-panel inspector-idle">
      <div className="panel-title"><h2>Node Editor</h2></div>
      <div className="inspector-idle-body">
        <MousePointerClick size={22} />
        <p>点节点或节点组成员上的 <strong>编辑</strong>，在这里修改。</p>
        <ul>
          <li><strong>表单</strong>：按源文件字段编辑，或由 JSON 生成的通用表单</li>
          <li><strong>JSON</strong>：直接改运行时节点</li>
          <li><strong>源文件</strong>：改 tags.txt / meta.yaml 原文</li>
        </ul>
        <small>表单和 JSON 的修改只作用于这次出图；点“保存节点”或在源文件页保存才会写回素材库。</small>
      </div>
    </section>
  );
}

export function NodeWorkspaceEditor() {
  const workspace = useCustomWorkspace();
  const editor = workspace.state.editor;
  const slot = editor.slotId ? workspace.findSlot(editor.slotId) : null;
  const target = workspace.editorTarget;
  const [jsonText, setJsonText] = useState(formatNode(editor.draftNode));
  const [jsonError, setJsonError] = useState("");
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [savePreview, setSavePreview] = useState<NodeSavePreviewResponse | null>(null);
  const targetKey = `${editor.slotId ?? ""}\u0000${editor.memberRef ?? ""}`;
  const panelRef = useRef<HTMLElement>(null);

  useEffect(() => {
    // 窄屏时编辑栏和配方栏不在同一屏：打开新的编辑对象时把编辑栏滚进视野。
    const panel = panelRef.current;
    if (!panel || !editor.slotId || typeof panel.scrollIntoView !== "function") return;
    const rect = panel.getBoundingClientRect();
    if (rect.top < 0 || rect.top > window.innerHeight - 80) panel.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [targetKey, editor.kind, editor.slotId]);

  useEffect(() => {
    setJsonText(formatNode(editor.draftNode));
    setJsonError("");
    setError("");
    setStatus("");
    setSavePreview(null);
    // 换编辑对象时才重置；同一对象的草稿变化由各个输入自己同步。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetKey]);

  useEffect(() => {
    // 通用表单改的是运行时节点，JSON 文本跟着刷新（JSON 页签正在输入时不覆盖）。
    if (editor.tab !== "json") setJsonText(formatNode(editor.draftNode));
  }, [editor.draftNode, editor.tab]);

  useEffect(() => {
    if (!target?.sourceRef || !target.sourceEditor || !editor.editValues || editor.tab !== "form") return;
    if (sameValue(editor.editValues, editor.baselineValues)) return;
    let active = true;
    const timer = window.setTimeout(() => {
      setStatus("正在更新临时节点...");
      void apiPost<NodePreviewResponse>("/nodes/editor-preview", {
        ref: target.sourceRef,
        role: target.role,
        values: editor.editValues,
      }).then((response) => {
        if (!active) return;
        workspace.updateEditorTargetDraft(response.node);
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editor.editValues, editor.tab, target?.role, target?.sourceEditor, target?.sourceRef, targetKey]);

  if (slot?.sourceKind === "random" && editor.kind === "random" && !editor.memberRef) {
    return <section className="panel node-workspace-panel inspector-group" ref={panelRef}><RandomNodeEditor slot={slot} /></section>;
  }

  if (!slot || !target || !editor.draftNode) return <IdleEditor />;

  const draft = editor.draftNode;
  const values = editor.editValues;
  const valuesChanged = !sameValue(values, editor.baselineValues);
  const draftChanged = target.sourceNode ? !sameValue(target.draftNode, target.sourceNode) : true;
  const canSaveForm = Boolean(target.sourceRef && values && target.sourceEditor?.capabilities.save);
  const isMember = Boolean(target.memberRef);

  function requestClose() {
    if (jsonError && !window.confirm("当前 JSON 无效，关闭后会丢失尚未生效的文本。是否继续？")) return;
    workspace.closeEditor();
  }

  function setTab(tab: EditorTab) {
    workspace.setEditorTab(tab);
  }

  async function handleSavePreview() {
    if (!target?.sourceRef || !values || !canSaveForm) return;
    setBusy(true);
    setError("");
    try {
      const preview = await apiPost<NodeSavePreviewResponse>("/nodes/save-preview", {
        ref: target.sourceRef,
        role: target.role,
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
      const saved = await apiPut<NodeReadResponse>("/nodes/save-commit", { preview_id: savePreview.preview_id });
      workspace.applySavedToEditorTarget(saved);
      setJsonText(formatNode(saved.node));
      setSavePreview(null);
      setStatus("已保存到原数据源");
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  }

  function onSourceSaved(saved: NodeReadResponse) {
    workspace.applySavedToEditorTarget(saved);
    setJsonText(formatNode(saved.node));
  }

  const statusChip = !target.sourceRef
    ? <span className="chip warning">临时节点</span>
    : draftChanged
      ? <span className="chip accent">已修改</span>
      : <span className="chip">原始</span>;

  return (
    <section className="panel node-workspace-panel" ref={panelRef}>
      <div className="panel-title node-editor-title">
        <div className="node-editor-heading">
          <nav aria-label="编辑位置" className="editor-breadcrumb">
            <span>{roleLabels[target.role] ?? target.role}</span>
            <ChevronRight size={12} />
            <span>{slot.mode === "compare" ? "Compare" : "Primary"}</span>
            {isMember ? (
              <>
                <ChevronRight size={12} />
                <button className="link-button" onClick={() => workspace.openRandomEditor(slot.slotId)} title="回到节点组" type="button">节点组</button>
              </>
            ) : null}
          </nav>
          <h2>{draft.name || draft.id}</h2>
          <div className="node-editor-chips">
            {statusChip}
            {isMember ? <span className="chip violet">节点组成员</span> : null}
          </div>
        </div>
        <button aria-label="关闭节点编辑器" className="icon-button btn-ghost" onClick={requestClose} title="关闭" type="button"><X size={17} /></button>
      </div>
      <div className="editor-tabs" role="tablist">
        <button aria-selected={editor.tab === "form"} className={editor.tab === "form" ? "active" : ""} onClick={() => setTab("form")} role="tab" type="button"><Braces size={15} /> Form</button>
        <button aria-selected={editor.tab === "json"} className={editor.tab === "json" ? "active" : ""} onClick={() => setTab("json")} role="tab" type="button"><FileJson2 size={15} /> JSON</button>
        <button aria-selected={editor.tab === "source"} className={editor.tab === "source" ? "active" : ""} disabled={!target.sourceRef} onClick={() => setTab("source")} role="tab" title={target.sourceRef ? "直接编辑 tags.txt / meta.yaml 等源文件" : "临时节点还没有源文件"} type="button"><FileCode2 size={15} /> 源文件</button>
      </div>

      {editor.tab === "source" && target.sourceRef ? (
        <div className="node-editor-body">
          <SourceFilesPanel hasUnsavedDraft={draftChanged} nodeRef={target.sourceRef} onSaved={onSourceSaved} role={target.role} />
        </div>
      ) : (
        <>
          <div className="node-editor-body">
            {editor.tab === "form" ? (
              values && target.sourceEditor
                ? <SourceForm onChange={workspace.setEditorValues} role={target.role} values={values} />
                : (
                  <>
                    <div className="editor-hint">{target.sourceRef ? "这个节点没有专门的源文件表单，下面是由 JSON 生成的通用表单。" : "空白临时节点：下面是由 JSON 生成的通用表单。"}</div>
                    <GenericNodeForm node={draft} onChange={(node) => workspace.updateEditorTargetDraft(node)} />
                  </>
                )
            ) : (
              <label className="field json-workspace-editor">
                <span>Runtime Node JSON</span>
                <textarea aria-label="Node JSON" onChange={(event) => {
                  const text = event.target.value;
                  setJsonText(text);
                  try {
                    workspace.updateEditorTargetDraft(parseEditorNode(text));
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
            <button disabled={busy || !target.sourceNode} onClick={() => {
              if ((valuesChanged || draftChanged || jsonError) && !window.confirm("当前编辑将被还原，是否继续？")) return;
              workspace.restoreEditorTarget();
              workspace.closeEditor();
            }} type="button"><RotateCcw size={15} /> 还原</button>
            <span />
            <button className="btn-primary" disabled={busy || Boolean(jsonError) || !canSaveForm} onClick={() => void handleSavePreview()} title={canSaveForm ? "把表单写回源文件（先看 Diff）" : "这个节点只能在“源文件”页签直接保存"} type="button"><Save size={15} /> 保存节点</button>
          </div>
        </>
      )}
      {savePreview ? <NodeSaveDiffDialog busy={busy} error={error} onCancel={() => setSavePreview(null)} onConfirm={() => void commitSave()} preview={savePreview} /> : null}
    </section>
  );
}
