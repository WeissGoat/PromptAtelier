import { FileText, X } from "lucide-react";
import { useEffect, useState } from "react";

import type { NodeSavePreviewResponse } from "../api/types";

function lineKind(line: string): string {
  if (line.startsWith("+++ ") || line.startsWith("--- ")) return "file";
  if (line.startsWith("@@")) return "hunk";
  if (line.startsWith("+")) return "added";
  if (line.startsWith("-")) return "removed";
  return "context";
}

export function NodeSaveDiffDialog({
  preview,
  busy,
  error,
  onCancel,
  onConfirm,
}: {
  preview: NodeSavePreviewResponse;
  busy: boolean;
  error: string;
  onCancel(): void;
  onConfirm(): void;
}) {
  const [activePath, setActivePath] = useState(preview.files[0]?.path ?? "");
  useEffect(() => setActivePath(preview.files[0]?.path ?? ""), [preview.preview_id, preview.files]);
  const file = preview.files.find((item) => item.path === activePath) ?? preview.files[0];
  const changedCount = preview.files.filter((item) => item.changed).length;
  return (
    <div className="node-save-backdrop" role="presentation">
      <section aria-label="保存节点源文件 Diff" aria-modal="true" className="node-save-dialog" role="dialog">
        <header>
          <div><h2>确认写入原数据源</h2><small>{changedCount} 个文件发生变化</small></div>
          <button aria-label="关闭保存 Diff" className="icon-button" disabled={busy} onClick={onCancel} type="button"><X size={18} /></button>
        </header>
        <div className="node-save-tabs" role="tablist">
          {preview.files.map((item) => (
            <button aria-selected={item.path === file?.path} className={item.path === file?.path ? "active" : ""} key={item.path} onClick={() => setActivePath(item.path)} role="tab" type="button"><FileText size={14} /> {item.relative}{item.changed ? " *" : ""}</button>
          ))}
        </div>
        <div className="node-save-body">
          {file?.changed ? (
            <pre className="source-diff-view">{file.diff.split("\n").map((line, index) => <span className={lineKind(line)} key={`${index}-${line}`}>{line || " "}</span>)}</pre>
          ) : <div className="empty-workspace">这个文件没有变化。</div>}
          {file ? <details><summary>保存后的完整源文件</summary><pre className="json-preview">{file.after_text}</pre></details> : null}
          {error ? <div className="alert error-alert" role="alert">{error}</div> : null}
        </div>
        <footer>
          <button disabled={busy} onClick={onCancel} type="button">取消</button>
          <button disabled={busy || changedCount === 0} onClick={onConfirm} type="button">确认写入 {changedCount} 个文件</button>
        </footer>
      </section>
    </div>
  );
}
