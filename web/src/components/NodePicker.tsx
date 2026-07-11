import { RefreshCw } from "lucide-react";
import { useEffect, useId, useMemo, useState } from "react";

import { apiGet, errorMessage } from "../api/client";
import type { NodeListResponse, NodeSummary } from "../api/types";

type NodePickerProps = {
  label: string;
  role: "artist" | "character" | "action";
  value: string;
  placeholder: string;
  minSearchLength?: number;
  onSelect?: (node: NodeSummary) => void;
  onClear?: () => void;
  /** @deprecated Kept temporarily for the existing studio until it adopts NodeSlot. */
  onChange?: (value: string) => void;
};

export function NodePicker({
  label,
  role,
  value,
  placeholder,
  minSearchLength = 0,
  onSelect,
  onClear,
  onChange,
}: NodePickerProps) {
  const listId = useId();
  const [nodes, setNodes] = useState<NodeSummary[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [text, setText] = useState(value);

  const selected = useMemo(
    () => nodes.find((node) => node.ref === value || node.name === value),
    [nodes, value],
  );

  useEffect(() => {
    setText(selected?.name ?? value);
  }, [selected?.name, value]);

  useEffect(() => {
    const query = text.trim();
    if (query.length < minSearchLength) {
      return;
    }
    if (nodes.some((node) => node.name === query && node.ref === value)) {
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

  function selectedName(ref: string): string {
    const match = nodes.find((node) => node.ref === ref || node.name === ref);
    return match?.name ?? ref;
  }

  function selectNode(nextValue: string): boolean {
    const match = nodes.find((node) => node.name === nextValue || node.ref === nextValue);
    if (!match) {
      return false;
    }
    onSelect?.(match);
    onChange?.(match.ref);
    setText(match.name);
    return true;
  }

  return (
    <div className="field node-picker">
      <span>{label}</span>
      <div className="node-picker-row">
        <input
          aria-label={label}
          list={listId}
          onBlur={() => {
            if (!selectNode(text)) {
              setText("");
              onClear?.();
            }
          }}
          onChange={(event) => {
            const nextValue = event.target.value;
            const match = nodes.find((node) => node.name === nextValue);
            if (match) {
              selectNode(match.name);
              return;
            }
            setText(nextValue);
          }}
          placeholder={placeholder}
          title={value}
          value={selectedName(text)}
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
      </div>
      <datalist id={listId}>
        {nodes.map((node) => (
          <option key={node.ref} value={node.name}>
            {node.relative ?? node.ref}
          </option>
        ))}
      </datalist>
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
