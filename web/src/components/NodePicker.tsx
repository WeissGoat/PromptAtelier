import { RefreshCw, X } from "lucide-react";
import { useEffect, useState } from "react";

import { apiGet, errorMessage } from "../api/client";
import type { NodeListResponse, NodeSummary } from "../api/types";

type NodePickerProps = {
  label: string;
  role: "artist" | "character" | "action";
  value: string;
  placeholder: string;
  minSearchLength?: number;
  onSelect: (node: NodeSummary) => void;
  onClear: () => void;
};

export function NodePicker({
  label,
  role,
  value,
  placeholder,
  minSearchLength = 0,
  onSelect,
  onClear,
}: NodePickerProps) {
  const [nodes, setNodes] = useState<NodeSummary[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [text, setText] = useState(value);

  useEffect(() => {
    setText(value);
  }, [value]);

  useEffect(() => {
    const query = text.trim();
    if (query.length < minSearchLength) {
      return;
    }
    if (query === value) {
      return;
    }
    const timer = window.setTimeout(() => {
      void loadNodes(query);
    }, 300);
    return () => window.clearTimeout(timer);
    // loadNodes is intentionally omitted so typing only controls the debounce.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, minSearchLength]);

  async function loadNodes(query = "") {
    const normalizedQuery = query.trim();
    if (normalizedQuery.length < minSearchLength) {
      setLoaded(false);
      setError(`输入至少 ${minSearchLength} 个字再搜索`);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const search = new URLSearchParams({ role });
      search.set("limit", "80");
      if (normalizedQuery) {
        search.set("q", normalizedQuery);
      }
      const result = await apiGet<NodeListResponse>(`/nodes?${search.toString()}`);
      setNodes(result.nodes);
      setLoaded(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  function selectNode(node: NodeSummary) {
    onSelect(node);
    // Selection is not committed until the owning slot has read and accepted it.
    setText(value);
  }

  return (
    <div className="field node-picker">
      <span>{label}</span>
      <div className="node-picker-row">
        <input
          aria-label={label}
          onChange={(event) => {
            setText(event.target.value);
          }}
          placeholder={placeholder}
          title={value}
          value={text}
        />
        <button
          aria-label={`Load ${label} nodes`}
          className="icon-button"
          disabled={loading}
          onClick={() => void loadNodes(text)}
          title={`Load ${label} nodes`}
          type="button"
        >
          <RefreshCw size={16} />
        </button>
        <button
          aria-label={`Clear ${label} node`}
          className="icon-button"
          disabled={!value}
          onClick={() => {
            setText(value);
            onClear();
          }}
          title="清除选择"
          type="button"
        >
          <X size={16} />
        </button>
      </div>
      {loaded && nodes.length > 0 ? (
        <div aria-label={`${label}节点搜索结果`} className="node-picker-results" role="listbox">
          {nodes.map((node) => {
            const detail = node.relative ?? node.ref;
            return (
              <button aria-label={`${node.name} ${detail}`} key={node.ref} onClick={() => selectNode(node)} role="option" type="button">
                <span>{node.name}</span>
                <small>{detail}</small>
              </button>
            );
          })}
        </div>
      ) : null}
      <small className={error ? "field-error" : "field-hint"}>
        {error ||
          (loaded
            ? `${nodes.length} nodes loaded`
            : minSearchLength > 0
              ? `输入至少 ${minSearchLength} 个字搜索`
              : "Type directly or load from design")}
      </small>
    </div>
  );
}
