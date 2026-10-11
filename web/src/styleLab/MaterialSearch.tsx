import { Check, Copy, LoaderCircle, Search, SlidersHorizontal, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { errorMessage, nodePreviewUrl } from "../api/client";
import type { FacetOption, MaterialNode, MaterialRole } from "./api";
import { searchMaterials } from "./api";
import { FACET_FIELD_LABELS, facetSummary, facetValueLabel, MORE_FACETS, PRIMARY_FACETS } from "./facetLabels";

const PAGE = 30;
/** 动作库第一次建索引要十几秒，超过这个时间再提示，免得每次都闪一下。 */
const SLOW_HINT_MS = 1500;

type MaterialSearchProps = {
  role: MaterialRole;
  placeholder?: string;
  disabled?: boolean;
  isPicked?: (ref: string) => boolean;
  onPick: (node: MaterialNode) => void;
  /** 传了就由外面保存分类筛选（素材架用它跨配方保留），否则组件自己记。 */
  facets?: Record<string, string>;
  onFacetsChange?: (facets: Record<string, string>) => void;
};

/** 下拉式的素材搜索：输入或选了分类才展开结果；内容相同的副本目录已在后端合并。 */
export function MaterialSearch({
  role,
  placeholder,
  disabled,
  isPicked,
  onPick,
  facets: savedFacets,
  onFacetsChange,
}: MaterialSearchProps) {
  const [query, setQuery] = useState("");
  const [localFacets, setLocalFacets] = useState<Record<string, string>>({});
  const facets = savedFacets ?? localFacets;
  const setFacets = (next: Record<string, string>) => (savedFacets ? onFacetsChange?.(next) : setLocalFacets(next));
  const [moreFacets, setMoreFacets] = useState(() => MORE_FACETS.some((field) => facets[field]));
  const [open, setOpen] = useState(false);
  const [nodes, setNodes] = useState<MaterialNode[]>([]);
  const [options, setOptions] = useState<Record<string, FacetOption[]>>({});
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [slow, setSlow] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState(0);
  const boxRef = useRef<HTMLDivElement>(null);
  const showFacets = role === "action";

  // 换了角色/动作页签：清掉上一页的搜索词；外面保存的分类筛选按页签各自保留。
  useEffect(() => {
    setQuery("");
    setLocalFacets({});
    setNodes([]);
    setOptions({});
  }, [role]);

  useEffect(() => {
    let cancelled = false;
    const slowTimer = setTimeout(() => !cancelled && setSlow(true), SLOW_HINT_MS);
    const timer = setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await searchMaterials(role, query, facets, { limit: PAGE });
        if (cancelled) return;
        setNodes(data.nodes);
        setOptions(data.facet_options);
        setTotal(data.total);
        setHasMore(data.has_more);
        setActive(0);
      } catch (exc) {
        if (!cancelled) setError(errorMessage(exc));
      } finally {
        if (!cancelled) {
          setLoading(false);
          setSlow(false);
        }
      }
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      clearTimeout(slowTimer);
    };
  }, [role, query, facets]);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const loadMore = async () => {
    setLoading(true);
    try {
      const data = await searchMaterials(role, query, facets, { offset: nodes.length, limit: PAGE });
      setNodes((current) => [...current, ...data.nodes]);
      setHasMore(data.has_more);
    } catch (exc) {
      setError(errorMessage(exc));
    } finally {
      setLoading(false);
    }
  };

  const pick = (node: MaterialNode) => {
    if (isPicked?.(node.ref)) return;
    onPick(node);
    // 收起下拉，让刚放到下面的素材块露出来。
    setOpen(false);
  };

  const setFacet = (field: string, value: string) => {
    const next = { ...facets };
    if (value) next[field] = value;
    else delete next[field];
    setFacets(next);
    setOpen(true);
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") {
      setOpen(false);
      return;
    }
    if (!open && (event.key === "ArrowDown" || event.key === "Enter")) {
      setOpen(true);
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setActive((index) => Math.max(0, Math.min(nodes.length - 1, index + (event.key === "ArrowDown" ? 1 : -1))));
    } else if (event.key === "Enter" && nodes[active]) {
      event.preventDefault();
      pick(nodes[active]);
    }
  };

  const facetCount = Object.keys(facets).length;
  const fields = moreFacets ? [...PRIMARY_FACETS, ...MORE_FACETS] : PRIMARY_FACETS;

  return (
    <div className="sl-msearch" ref={boxRef}>
      {showFacets ? (
        <div className="sl-facets">
          {fields.map((field) => (
            <label className={`sl-facet ${facets[field] ? "on" : ""}`} key={field}>
              <span>{FACET_FIELD_LABELS[field]}</span>
              <select aria-label={`按${FACET_FIELD_LABELS[field]}筛选`} onChange={(event) => setFacet(field, event.target.value)} value={facets[field] ?? ""}>
                <option value="">全部</option>
                {/* 已选的值即使在当前结果里没有了也要留着，否则下拉框显示不出来。 */}
                {facets[field] && !(options[field] ?? []).some((item) => item.value === facets[field]) ? (
                  <option value={facets[field]}>{facetValueLabel(field, facets[field])} · 0</option>
                ) : null}
                {(options[field] ?? []).map((item) => (
                  <option key={item.value} value={item.value}>
                    {facetValueLabel(field, item.value)} · {item.count}
                  </option>
                ))}
              </select>
            </label>
          ))}
          <button className="sl-ghost tiny" onClick={() => setMoreFacets(!moreFacets)} type="button">
            <SlidersHorizontal size={12} aria-hidden="true" />
            {moreFacets ? "收起" : "更多分类"}
          </button>
          {facetCount ? (
            <button className="sl-ghost tiny" onClick={() => setFacets({})} type="button">
              <X size={12} aria-hidden="true" />
              清除 {facetCount}
            </button>
          ) : null}
        </div>
      ) : null}
      <label className="sl-search">
        <Search size={14} aria-hidden="true" />
        <input
          aria-autocomplete="list"
          aria-expanded={open}
          aria-label={role === "character" ? "搜索角色" : "搜索动作"}
          disabled={disabled}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder={placeholder ?? (role === "character" ? "角色名 / 作品，点开下拉选择" : "动作关键字，点开下拉选择")}
          role="combobox"
          value={query}
        />
        {loading ? <LoaderCircle className="sl-spin" size={14} /> : null}
      </label>
      {open && !disabled ? (
        <div className="sl-msearch-menu" role="listbox">
          <div className="sl-msearch-status">
            {slow && loading ? "第一次建立素材索引，要十几秒…" : error ? <span className="sl-error">{error}</span> : `共 ${total} 个${role === "character" ? "角色" : "动作"}`}
          </div>
          {nodes.map((node, index) => {
            const picked = isPicked?.(node.ref) ?? false;
            return (
              <button
                aria-selected={index === active}
                className={`sl-msearch-item ${index === active ? "active" : ""}`}
                disabled={picked}
                key={node.ref}
                onClick={() => pick(node)}
                onMouseEnter={() => setActive(index)}
                role="option"
                title={[node.relative, ...node.copy_paths.map((path) => `副本：${path}`)].filter(Boolean).join("\n")}
                type="button"
              >
                {node.has_preview ? <img alt="" loading="lazy" src={nodePreviewUrl(node.ref, 96)} /> : <span className="sl-msearch-noimg" />}
                <span className="sl-msearch-text">
                  <span className="sl-msearch-name">{node.name}</span>
                  <span className="sl-msearch-sub">
                    {node.relative?.includes("/") ? node.relative.slice(0, node.relative.lastIndexOf("/")) : ""}
                    {node.facets && Object.keys(node.facets).length ? ` ${facetSummary(node.facets)}` : ""}
                  </span>
                </span>
                {node.copies ? (
                  <span className="sl-pill" title={node.copy_paths.join("\n")}>
                    <Copy size={10} aria-hidden="true" /> 合并 {node.copies + 1} 份
                  </span>
                ) : null}
                {picked ? (
                  <span className="sl-pill ok">
                    <Check size={10} aria-hidden="true" /> 已选
                  </span>
                ) : null}
              </button>
            );
          })}
          {!loading && !nodes.length && !error ? <p className="sl-muted sl-msearch-empty">没有找到。</p> : null}
          {hasMore ? (
            <button className="sl-link-btn sl-msearch-more" disabled={loading} onClick={() => void loadMore()} type="button">
              再显示 {Math.min(PAGE, total - nodes.length)} 个
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
