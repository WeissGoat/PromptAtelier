import { X } from "lucide-react";
import { useEffect, useState } from "react";

import { apiPost, errorMessage } from "../api/client";
import type { NodeReadResponse } from "../api/types";
import { nodeSlotStatus } from "../nodes/temporaryNodes";
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

function requiresRestoreConfirmation(slot: NodeSlotState): boolean {
  const status = nodeSlotStatus(slot);
  return status === "modified" || status === "temporary";
}

export function NodeEditorDrawer({ open, slot, onClose, onApply, onRestore, onSaved }: NodeEditorDrawerProps) {
  const [text, setText] = useState("");
  const [baselineText, setBaselineText] = useState("");
  const [targetRef, setTargetRef] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      const nextText = formatNode(slot?.draftNode ?? null);
      setText(nextText);
      setBaselineText(nextText);
      setTargetRef(slot?.sourceRef ?? "");
      setError("");
    }
  }, [open, slot]);

  if (!open || !slot) return null;
  const activeSlot = slot;

  async function validateNode(): Promise<NodeDocument> {
    const parsed = parseNode(text, activeSlot.role);
    const response = await apiPost<NodePreviewResponse>("/nodes/preview", { node: parsed });
    return response.node;
  }

  function updateBaseline(node: NodeDocument) {
    const nextBaseline = formatNode(node);
    setText(nextBaseline);
    setBaselineText(nextBaseline);
  }

  function requestClose() {
    if (text !== baselineText && !window.confirm("当前 JSON 修改尚未应用或保存，是否关闭？")) {
      return;
    }
    onClose();
  }

  async function handleApply() {
    setBusy(true);
    setError("");
    try {
      const node = await validateNode();
      updateBaseline(node);
      onApply(activeSlot.role, node);
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleSave() {
    const saveRef = (activeSlot.sourceRef ?? targetRef).trim();
    if (!saveRef) {
      setError("请输入节点库内的目标 ref。");
      return;
    }

    let node: NodeDocument;
    try {
      node = parseNode(text, activeSlot.role);
    } catch (err) {
      setError(errorMessage(err));
      return;
    }
    if (!window.confirm(`将保存节点到 ${saveRef}，是否继续？`)) return;

    setBusy(true);
    setError("");
    try {
      const response = await fetch(`${apiRoot}/nodes/save`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ref: saveRef, node }),
      });
      if (!response.ok) throw new Error(await response.text());
      const saved = await response.json() as NodeReadResponse;
      updateBaseline(saved.node);
      setTargetRef(saved.ref);
      onSaved(activeSlot.role, saved.ref, saved.node);
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  function handleRestore() {
    if (!requiresRestoreConfirmation(activeSlot) || window.confirm("当前临时修改将被还原，是否继续？")) {
      onRestore(activeSlot.role);
    }
  }

  const saveRef = (slot.sourceRef ?? targetRef).trim();

  return (
    <div className="drawer-backdrop" onMouseDown={requestClose} role="presentation">
      <aside aria-label="节点编辑器" className="node-editor-drawer" onMouseDown={(event) => event.stopPropagation()}>
        <div className="drawer-header">
          <div>
            <h2>编辑节点</h2>
            <small>{slot.sourceRef ?? "临时节点"}</small>
          </div>
          <button aria-label="关闭节点编辑器" className="icon-button" onClick={requestClose} title="关闭" type="button">
            <X size={18} />
          </button>
        </div>
        {!slot.sourceRef ? (
          <label className="field compact drawer-target">
            <span>Target ref</span>
            <input
              aria-label="Target ref"
              onChange={(event) => setTargetRef(event.target.value)}
              placeholder="characters/new-node"
              value={targetRef}
            />
          </label>
        ) : null}
        <label className="field drawer-editor">
          <span>节点 JSON</span>
          <textarea aria-label="节点 JSON" onChange={(event) => setText(event.target.value)} spellCheck={false} value={text} />
        </label>
        {error ? <div className="alert error-alert" role="alert">{error}</div> : null}
        <div className="drawer-actions">
          <button disabled={busy} onClick={handleRestore} type="button">还原原始节点</button>
          <span />
          <button disabled={busy} onClick={() => void handleApply()} type="button">应用到本次运行</button>
          <button disabled={busy || !saveRef} onClick={() => void handleSave()} title={slot.sourceRef ? "保存并覆盖节点库" : "保存为新节点"} type="button">保存到节点库</button>
        </div>
      </aside>
    </div>
  );
}
