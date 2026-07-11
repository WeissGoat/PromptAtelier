import { FilePlus2, Pencil, RotateCcw, Trash2 } from "lucide-react";
import { useState } from "react";

import { apiGet, errorMessage } from "../api/client";
import type { NodeReadResponse, NodeSummary } from "../api/types";
import { nodeSlotStatus } from "../nodes/temporaryNodes";
import type { NodeRole, NodeSlotState } from "../nodes/types";
import { NodePicker } from "./NodePicker";

type NodeSlotProps = {
  label: string;
  role: NodeRole;
  slot: NodeSlotState;
  placeholder: string;
  minSearchLength?: number;
  selectNode: (role: NodeRole, ref: string, node: NodeReadResponse["node"]) => void;
  createBlank: (role: NodeRole) => void;
  restore: (role: NodeRole) => void;
  clear: (role: NodeRole) => void;
  onEdit: (slot: NodeSlotState) => void;
};

function statusLabel(slot: NodeSlotState): string {
  const status = nodeSlotStatus(slot);
  if (status === "original") return "原始节点";
  if (status === "modified") return "临时修改";
  if (status === "temporary") {
    return slot.draftNode?.id === `temporary-${slot.role}` ? "空白临时节点" : "临时修改";
  }
  return "未选择";
}

function requiresConfirmation(slot: NodeSlotState): boolean {
  const status = nodeSlotStatus(slot);
  return status === "modified" || status === "temporary";
}

export function NodeSlot({
  label,
  role,
  slot,
  placeholder,
  minSearchLength,
  selectNode,
  createBlank,
  restore,
  clear,
  onEdit,
}: NodeSlotProps) {
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSelect(node: NodeSummary) {
    if (requiresConfirmation(slot) && !window.confirm("当前临时修改将被替换，是否继续？")) {
      return;
    }
    setLoading(true);
    setError("");
    try {
      const response = await apiGet<NodeReadResponse>(`/nodes/read?${new URLSearchParams({ ref: node.ref })}`);
      selectNode(role, response.ref, response.node);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  function handleCreateBlank() {
    if (!requiresConfirmation(slot) || window.confirm("当前临时修改将被替换，是否继续？")) {
      createBlank(role);
    }
  }

  function handleClear() {
    if (!requiresConfirmation(slot) || window.confirm("当前临时修改将被清除，是否继续？")) {
      clear(role);
    }
  }

  function handleRestore() {
    if (!requiresConfirmation(slot) || window.confirm("当前临时修改将被还原，是否继续？")) {
      restore(role);
    }
  }

  return (
    <section className="node-slot">
      <div className="node-slot-header">
        <span className="node-status">{statusLabel(slot)}</span>
        <div className="node-slot-actions">
          <button aria-label={`编辑${label}节点`} className="icon-button" disabled={!slot.draftNode} onClick={() => onEdit(slot)} title="编辑节点" type="button">
            <Pencil size={16} />
          </button>
          <button aria-label={`新建空白${label}节点`} className="icon-button" onClick={handleCreateBlank} title="新建空白临时节点" type="button">
            <FilePlus2 size={16} />
          </button>
          <button aria-label={`还原${label}节点`} className="icon-button" disabled={!slot.sourceNode} onClick={handleRestore} title="还原原始节点" type="button">
            <RotateCcw size={16} />
          </button>
          <button aria-label={`清除${label}节点`} className="icon-button" disabled={!slot.draftNode} onClick={handleClear} title="清除节点" type="button">
            <Trash2 size={16} />
          </button>
        </div>
      </div>
      <NodePicker
        label={label}
        minSearchLength={minSearchLength}
        onClear={handleClear}
        onSelect={(node) => void handleSelect(node)}
        placeholder={placeholder}
        role={role}
        value={slot.sourceRef ?? ""}
      />
      {loading ? <small className="field-hint">正在读取节点...</small> : null}
      {error ? <small className="field-error">{error}</small> : null}
    </section>
  );
}
