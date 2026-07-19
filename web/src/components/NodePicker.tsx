import { X } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";

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

const PAGE_SIZE = 20;

export function NodePicker({ label, role, value, placeholder, onSelect, onClear }: NodePickerProps) {
  const pickerId = useId().replace(/:/g, "");
  const resultsId = `${role}-node-results-${pickerId}`;
  const rootRef = useRef<HTMLDivElement>(null);
  const resultsRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const requestId = useRef(0);
  const activeQueryRef = useRef("");
  const [nodes, setNodes] = useState<NodeSummary[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [nextOffset, setNextOffset] = useState(0);
  const [error, setError] = useState("");
  const [loadMoreError, setLoadMoreError] = useState("");
  const [text, setText] = useState(value);

  useEffect(() => setText(value), [value]);

  useEffect(() => {
    if (!open) return;
    const query = text === value ? "" : text.trim();
    requestId.current += 1;
    activeQueryRef.current = query;
    setNodes([]);
    setHasMore(false);
    setNextOffset(0);
    setLoading(false);
    setLoadingMore(false);
    setError("");
    setLoadMoreError("");
    const timer = window.setTimeout(() => void loadFirstPage(query), 300);
    return () => window.clearTimeout(timer);
    // loadFirstPage only depends on role and requestId, which are stable for this component.
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
    setLoadingMore(false);
    setError("");
    setLoadMoreError("");
  }

  function searchParams(query: string, offset: number) {
    const search = new URLSearchParams({
      role,
      limit: String(PAGE_SIZE),
      offset: String(offset),
    });
    if (query) search.set("q", query);
    return search;
  }

  async function loadFirstPage(query: string) {
    const currentRequest = ++requestId.current;
    activeQueryRef.current = query;
    setLoading(true);
    setError("");
    setLoadMoreError("");
    try {
      const result = await apiGet<NodeListResponse>(`/nodes?${searchParams(query, 0).toString()}`);
      if (currentRequest !== requestId.current) return;
      setNodes(result.nodes);
      setHasMore(result.has_more);
      setNextOffset(result.offset + result.nodes.length);
    } catch (requestError) {
      if (currentRequest !== requestId.current) return;
      setNodes([]);
      setHasMore(false);
      setError(errorMessage(requestError));
    } finally {
      if (currentRequest === requestId.current) setLoading(false);
    }
  }

  const loadNextPage = useCallback(async (force = false) => {
    if (!open || loading || loadingMore || !hasMore || (loadMoreError && !force)) return;
    const currentRequest = ++requestId.current;
    const query = activeQueryRef.current;
    const offset = nextOffset;
    setLoadingMore(true);
    setLoadMoreError("");
    try {
      const search = new URLSearchParams({
        role,
        limit: String(PAGE_SIZE),
        offset: String(offset),
      });
      if (query) search.set("q", query);
      const result = await apiGet<NodeListResponse>(`/nodes?${search.toString()}`);
      if (currentRequest !== requestId.current) return;
      setNodes((current) => {
        const knownRefs = new Set(current.map((node) => node.ref));
        return [...current, ...result.nodes.filter((node) => !knownRefs.has(node.ref))];
      });
      setHasMore(result.has_more);
      setNextOffset(result.offset + result.nodes.length);
    } catch (requestError) {
      if (currentRequest !== requestId.current) return;
      setLoadMoreError(errorMessage(requestError));
    } finally {
      if (currentRequest === requestId.current) setLoadingMore(false);
    }
  }, [hasMore, loadMoreError, loading, loadingMore, nextOffset, open, role]);

  useEffect(() => {
    const root = resultsRef.current;
    const sentinel = sentinelRef.current;
    if (!open || !root || !sentinel || loading || loadingMore || !hasMore || loadMoreError) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) void loadNextPage();
      },
      { root, rootMargin: "48px 0px" },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasMore, loadMoreError, loadNextPage, loading, loadingMore, open]);

  function selectNode(node: NodeSummary) {
    requestId.current += 1;
    setText(node.name);
    setOpen(false);
    setLoading(false);
    setLoadingMore(false);
    setError("");
    setLoadMoreError("");
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
            requestId.current += 1;
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
        <div aria-label={`${label}节点搜索结果`} className="node-picker-results" id={resultsId} ref={resultsRef} role="listbox">
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
          {!loading && !error && hasMore ? <div aria-hidden="true" className="node-picker-sentinel" ref={sentinelRef} /> : null}
          {loadingMore ? <div className="node-picker-message node-picker-more-message">正在加载更多...</div> : null}
          {!loading && !error && loadMoreError ? (
            <div className="node-picker-more-error">
              <span>{loadMoreError}</span>
              <button
                onMouseDown={(event) => {
                  event.preventDefault();
                  void loadNextPage(true);
                }}
                type="button"
              >
                重试
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
