import { X } from "lucide-react";
import { useEffect, useState } from "react";

import { apiPost, errorMessage } from "../api/client";
import type { NodeReadResponse } from "../api/types";
import type { NodeDocument, NodeRole, NodeSlotState } from "../nodes/types";

type NodePreviewResponse = {
  node: NodeDocument;
};

type NodeEditorDrawerProps = {
  open: boolean;
  slot: NodeSlotState | null;
  onClose: () => void;
  onApply: (role: NodeRole, node: NodeDocument) => void;
  onRestore: (role: NodeRole) => void;
  onSaved: (role: NodeRole, ref: string, node: NodeDocument) => void;
};

const apiRoot = import.meta.env.VITE_API_ROOT ?? "http://127.0.0.1:8765/api";

function formatNode(node: NodeDocument | null): string {
  return node ? JSON.stringify(node, null, 2) : "";
}

function parseNode(text: string, role: NodeRole): NodeDocument {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new Error("JSON 格式无效，请检查逗号、引号和括号。");
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("节点必须是 JSON 对象。");
  }
  const node = parsed as NodeDocument;
  if (node.kind !== role) {
    throw new Error(`节点类型必须为 ${role}。`);
  }
  if (typeof node.id !== "string" || !node.id.trim()) {
    throw new Error("节点 id 不能为空。");
  }
  return node;
}

export function NodeEditorDrawer({ open, slot, onClose, onApply, onRestore, onSaved }: NodeEditorDrawerProps) {
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setText(formatNode(slot?.draftNode ?? null));
      setError("");
    }
  }, [open, slot]);

  if (!open || !slot) return null;
  const activeSlot = slot;

  async function validateNode(): Promise<NodeDocument> {
    const parsed = parseNode(text, activeSlot.role);
    const response = await apiPost<NodePreviewResponse>("/nodes/preview", parsed);
    return response.node;
  }

  async function handleApply() {
    setBusy(true);
    setError("");
    try {
      const node = await validateNode();
      onApply(activeSlot.role, node);
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleSave() {
    if (!activeSlot.sourceRef) {
      setError("请先选择节点后再保存到节点库。");
      return;
    }
    if (!window.confirm("将覆盖节点库中的原始节点，是否继续？")) return;

    setBusy(true);
    setError("");
    try {
      const node = parseNode(text, activeSlot.role);
      const response = await fetch(`${apiRoot}/nodes/save`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ref: activeSlot.sourceRef, node }),
      });
      if (!response.ok) throw new Error(await response.text());
      const saved = await response.json() as NodeReadResponse;
      onSaved(activeSlot.role, saved.ref, saved.node);
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="drawer-backdrop" onMouseDown={onClose} role="presentation">
      <aside aria-label="节点编辑器" className="node-editor-drawer" onMouseDown={(event) => event.stopPropagation()}>
        <div className="drawer-header">
          <div>
            <h2>编辑节点</h2>
            <small>{slot.sourceRef ?? "临时节点"}</small>
          </div>
          <button aria-label="关闭节点编辑器" className="icon-button" onClick={onClose} title="关闭" type="button">
            <X size={18} />
          </button>
        </div>
        <label className="field drawer-editor">
          <span>节点 JSON</span>
          <textarea aria-label="节点 JSON" onChange={(event) => setText(event.target.value)} spellCheck={false} value={text} />
        </label>
        {error ? <div className="alert error-alert" role="alert">{error}</div> : null}
        <div className="drawer-actions">
          <button disabled={busy} onClick={() => onRestore(slot.role)} type="button">还原原始节点</button>
          <span />
          <button disabled={busy} onClick={() => void handleApply()} type="button">应用到本次运行</button>
          <button disabled={busy || !slot.sourceRef} onClick={() => void handleSave()} title={slot.sourceRef ? "保存并覆盖节点库" : "请先选择节点"} type="button">保存到节点库</button>
        </div>
      </aside>
    </div>
  );
}
