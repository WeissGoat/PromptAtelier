import { FilePlus2, Pencil, RotateCcw, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { apiGet, errorMessage } from "../api/client";
import type { NodeReadResponse, NodeSummary } from "../api/types";
import { nodeSlotStatus } from "../nodes/temporaryNodes";
import type { NodeDocument } from "../nodes/types";
import type { NodeVariantSlot } from "../workspace/types";
import { NodePicker } from "./NodePicker";

type NodeSlotProps = {
  label: string;
  slot: NodeVariantSlot;
  placeholder: string;
  onSelect: (ref: string, node: NodeDocument) => void;
  onCreateBlank: () => void;
  onRestore: () => void;
  onClear: () => void;
  onEdit: () => void;
  onRemove?: () => void;
};

function statusLabel(slot: NodeVariantSlot): string {
  const status = nodeSlotStatus(slot);
  if (status === "original") return "原始节点";
  if (status === "modified") return "临时修改";
  if (status === "temporary") return "空白临时节点";
  return "未选择";
}

function requiresConfirmation(slot: NodeVariantSlot): boolean {
  const status = nodeSlotStatus(slot);
  return status === "modified" || status === "temporary";
}

function displayName(slot: NodeVariantSlot): string {
  return slot.draftNode?.name || slot.sourceNode?.name || slot.draftNode?.id || "";
}

export function NodeSlot({
  label,
  slot,
  placeholder,
  onSelect,
  onCreateBlank,
  onRestore,
  onClear,
  onEdit,
  onRemove,
}: NodeSlotProps) {
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const readRequestId = useRef(0);

  useEffect(() => {
    readRequestId.current += 1;
    setLoading(false);
  }, [slot.sourceRef, slot.sourceNode, slot.draftNode]);

  function invalidatePendingRead() {
    readRequestId.current += 1;
    setLoading(false);
  }

  async function handleSelect(node: NodeSummary) {
    if (requiresConfirmation(slot) && !window.confirm("当前临时修改将被替换，是否继续？")) return;
    const requestId = ++readRequestId.current;
    setLoading(true);
    setError("");
    try {
      const response = await apiGet<NodeReadResponse>(`/nodes/read?${new URLSearchParams({ ref: node.ref })}`);
      if (requestId !== readRequestId.current) return;
      onSelect(response.ref, response.node);
    } catch (requestError) {
      if (requestId !== readRequestId.current) return;
      setError(errorMessage(requestError));
    } finally {
      if (requestId === readRequestId.current) setLoading(false);
    }
  }

  function runReplacingAction(action: () => void, message: string) {
    if (requiresConfirmation(slot) && !window.confirm(message)) return;
    invalidatePendingRead();
    action();
  }

  return (
    <section className={`node-slot ${slot.mode === "compare" ? "compare-node-slot" : ""}`}>
      <div className="node-slot-header">
        <div className="node-slot-labels">
          {slot.mode === "compare" ? <span className="compare-badge">Compare</span> : null}
          <span className="node-status">{statusLabel(slot)}</span>
        </div>
        <div className="node-slot-actions">
          <button aria-label={`编辑${label}节点`} className="icon-button" disabled={!slot.draftNode} onClick={onEdit} title="编辑节点" type="button"><Pencil size={16} /></button>
          <button aria-label={`新建空白${label}节点`} className="icon-button" onClick={() => runReplacingAction(onCreateBlank, "当前临时修改将被替换，是否继续？")} title="新建空白节点" type="button"><FilePlus2 size={16} /></button>
          <button aria-label={`还原${label}节点`} className="icon-button" disabled={!slot.sourceNode} onClick={() => runReplacingAction(onRestore, "当前临时修改将被还原，是否继续？")} title="还原原始节点" type="button"><RotateCcw size={16} /></button>
          {onRemove ? (
            <button aria-label={`删除${label} Compare节点`} className="icon-button" onClick={onRemove} title="删除 Compare 节点" type="button"><Trash2 size={16} /></button>
          ) : null}
        </div>
      </div>
      <NodePicker
        label={label}
        onClear={() => runReplacingAction(onClear, "当前临时修改将被清除，是否继续？")}
        onSelect={(node) => void handleSelect(node)}
        placeholder={placeholder}
        role={slot.role}
        value={displayName(slot)}
      />
      {loading ? <small className="field-hint">正在读取节点...</small> : null}
      {error ? <small className="field-error">{error}</small> : null}
    </section>
  );
}
