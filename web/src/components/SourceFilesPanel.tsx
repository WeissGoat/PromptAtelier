import { FileText, RefreshCw, RotateCcw, Save } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { apiGet, apiPost, apiPut, errorMessage } from "../api/client";
import type { NodeReadResponse, NodeSavePreviewResponse, NodeSourceFilesResponse } from "../api/types";
import { NodeSaveDiffDialog } from "./NodeSaveDiffDialog";

type Props = {
  nodeRef: string;
  role: string;
  /** 表单 / JSON 里还有没保存的临时修改：直接写源文件后会以源文件为准。 */
  hasUnsavedDraft: boolean;
  onSaved(response: NodeReadResponse): void;
};

/** 直接编辑节点目录里的原始文件（tags.txt、meta.yaml、classify.yaml…），保存前先看 Diff。 */
export function SourceFilesPanel({ nodeRef, role, hasUnsavedDraft, onSaved }: Props) {
  const [files, setFiles] = useState<NodeSourceFilesResponse["files"]>([]);
  const [texts, setTexts] = useState<Record<string, string>>({});
  const [active, setActive] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [preview, setPreview] = useState<NodeSavePreviewResponse | null>(null);
  const requestId = useRef(0);

  // 浏览器 textarea 只认 \n；比较和展示都按 \n，保存时后端会还原原文件的换行。
  const original = (name: string) => (files.find((file) => file.name === name)?.text ?? "").replace(/\r\n/g, "\n");
  const changed = files.filter((file) => texts[file.name] !== undefined && texts[file.name] !== original(file.name));

  async function load() {
    const id = ++requestId.current;
    setLoading(true);
    setError("");
    try {
      const response = await apiGet<NodeSourceFilesResponse>(`/nodes/source-files?${new URLSearchParams({ ref: nodeRef })}`);
      if (id !== requestId.current) return;
      setFiles(response.files);
      setTexts({});
      setActive((current) => (response.files.some((file) => file.name === current) ? current : response.files[0]?.name ?? ""));
    } catch (requestError) {
      if (id !== requestId.current) return;
      setError(errorMessage(requestError));
      setFiles([]);
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }

  useEffect(() => {
    setStatus("");
    void load();
    // 换了节点才重新读取。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodeRef]);

  async function previewSave() {
    if (!changed.length) return;
    setBusy(true);
    setError("");
    try {
      const response = await apiPost<NodeSavePreviewResponse>("/nodes/source-save-preview", {
        ref: nodeRef,
        role,
        files: changed.map((file) => ({ name: file.name, text: texts[file.name] })),
      });
      setPreview(response);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  }

  async function commit() {
    if (!preview) return;
    setBusy(true);
    setError("");
    try {
      const saved = await apiPut<NodeReadResponse>("/nodes/save-commit", { preview_id: preview.preview_id });
      setPreview(null);
      onSaved(saved);
      await load();
      setStatus("已写入源文件，节点已按新内容重新读取");
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  }

  const activeFile = files.find((file) => file.name === active);
  const activeText = activeFile ? texts[activeFile.name] ?? original(activeFile.name) : "";

  return (
    <div className="source-files">
      {hasUnsavedDraft ? (
        <div className="inline-warning">表单 / JSON 里还有没保存的临时修改。直接保存源文件后，节点会按源文件重新读取，那些临时修改会被替换。</div>
      ) : null}
      <div className="source-files-tabs" role="tablist">
        {files.map((file) => {
          const dirty = changed.some((item) => item.name === file.name);
          return (
            <button aria-selected={file.name === active} className={file.name === active ? "active" : ""} key={file.name} onClick={() => setActive(file.name)} role="tab" type="button">
              <FileText size={13} /> {file.name}{dirty ? <span aria-label="未保存" className="dirty-dot" /> : null}
            </button>
          );
        })}
        <span className="spacer" />
        <button aria-label="重新读取源文件" className="icon-button btn-ghost" disabled={loading || busy} onClick={() => {
          if (changed.length && !window.confirm("重新读取会丢掉还没保存的源文件改动，是否继续？")) return;
          void load();
        }} title="重新读取源文件" type="button"><RefreshCw className={loading ? "spin" : ""} size={14} /></button>
      </div>
      {activeFile ? (
        <textarea
          aria-label={`源文件 ${activeFile.name}`}
          className="source-file-editor"
          onChange={(event) => setTexts((current) => ({ ...current, [activeFile.name]: event.target.value }))}
          spellCheck={false}
          value={activeText}
        />
      ) : (
        <div className="empty-workspace">{loading ? "正在读取源文件…" : "这个节点目录里没有可编辑的文本源文件。"}</div>
      )}
      {status ? <div aria-live="polite" className="editor-status">{status}</div> : null}
      {error ? <div className="alert error-alert" role="alert">{error}</div> : null}
      <div className="node-editor-actions">
        <button disabled={busy || !changed.length} onClick={() => setTexts({})} type="button"><RotateCcw size={14} /> 撤销改动</button>
        <span />
        <button className="btn-primary" disabled={busy || !changed.length} onClick={() => void previewSave()} type="button">
          <Save size={14} /> 保存源文件{changed.length ? ` (${changed.length})` : ""}
        </button>
      </div>
      {preview ? <NodeSaveDiffDialog busy={busy} error={error} onCancel={() => setPreview(null)} onConfirm={() => void commit()} preview={preview} /> : null}
    </div>
  );
}
