import { X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { apiGet, errorMessage } from "../api/client";
import type { NodeListResponse, NodeSummary } from "../api/types";
import type { NodeRole } from "../nodes/types";

type NodePickerProps = {
  label: string;
  role: NodeRole;
  value: string;
  placeholder: string;
  onSelect: (node: NodeSummary) => void;
  onClear: () => void;
};

export function NodePicker({ label, role, value, placeholder, onSelect, onClear }: NodePickerProps) {
  const pickerId = useId().replace(/:/g, "");
  const resultsId = `${role}-node-results-${pickerId}`;
  const rootRef = useRef<HTMLDivElement>(null);
  const requestId = useRef(0);
  const [nodes, setNodes] = useState<NodeSummary[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [text, setText] = useState(value);

  useEffect(() => setText(value), [value]);

  useEffect(() => {
    if (!open) return;
    const query = text === value ? "" : text.trim();
    const timer = window.setTimeout(() => void loadNodes(query), 300);
    return () => window.clearTimeout(timer);
    // loadNodes only depends on role and requestId, which are stable for this component.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, role, text, value]);

  useEffect(() => {
    if (!open) return;
    function handlePointerDown(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) closeResults();
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") closeResults();
    }
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  function closeResults() {
    requestId.current += 1;
    setOpen(false);
    setLoading(false);
    setError("");
  }

  async function loadNodes(query: string) {
    const currentRequest = ++requestId.current;
    setLoading(true);
    setError("");
    try {
      const search = new URLSearchParams({ role, limit: "6" });
      if (query) search.set("q", query);
      const result = await apiGet<NodeListResponse>(`/nodes?${search.toString()}`);
      if (currentRequest !== requestId.current) return;
      setNodes(result.nodes.slice(0, 6));
    } catch (requestError) {
      if (currentRequest !== requestId.current) return;
      setNodes([]);
      setError(errorMessage(requestError));
    } finally {
      if (currentRequest === requestId.current) setLoading(false);
    }
  }

  function selectNode(node: NodeSummary) {
    requestId.current += 1;
    setText(node.name);
    setOpen(false);
    setLoading(false);
    setError("");
    onSelect(node);
  }

  return (
    <div className="field node-picker" ref={rootRef}>
      <span>{label}</span>
      <div className="node-picker-row">
        <input
          aria-controls={resultsId}
          aria-expanded={open}
          aria-label={label}
          autoComplete="off"
          onChange={(event) => {
            setText(event.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          placeholder={placeholder}
          role="combobox"
          value={text}
        />
        <button
          aria-label={`Clear ${label} node`}
          className="icon-button"
          disabled={!value}
          onClick={() => {
            closeResults();
            setText("");
            onClear();
          }}
          title="清除选择"
          type="button"
        >
          <X size={16} />
        </button>
      </div>
      {open ? (
        <div aria-label={`${label}节点搜索结果`} className="node-picker-results" id={resultsId} role="listbox">
          {loading ? <div className="node-picker-message">正在搜索...</div> : null}
          {!loading && error ? <div className="node-picker-message field-error">{error}</div> : null}
          {!loading && !error && nodes.length === 0 ? <div className="node-picker-message">没有匹配节点</div> : null}
          {!loading && !error ? nodes.map((node) => (
            <button
              aria-label={node.name}
              key={node.ref}
              onMouseDown={(event) => {
                event.preventDefault();
                selectNode(node);
              }}
              role="option"
              type="button"
            >
              <span>{node.name}</span>
            </button>
          )) : null}
        </div>
      ) : null}
    </div>
  );
}
