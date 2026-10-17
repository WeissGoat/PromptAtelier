import { CheckSquare, EyeOff, Pencil, Play, RefreshCw, Search, Square, Undo2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { apiGet, errorMessage } from "../api/client";
import type { NodePoolCandidate, NodeReadResponse } from "../api/types";
import { listAllPoolNodes } from "../randomNodes/api";
import { withoutSelection } from "../randomNodes/resolve";
import { useCustomWorkspace } from "../workspace/CustomWorkspaceProvider";
import type { NodeVariantSlot } from "../workspace/types";
import { NodePreviewImage } from "./NodePreviewImage";

type MemberFilter = "all" | "selected" | "unselected" | "edited";

const PAGE = 120;

const filterLabels: Record<MemberFilter, string> = {
  all: "全部",
  selected: "已勾选",
  unselected: "未勾选",
  edited: "已修改",
};

function sameJson(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

/** 成员是否有没保存的临时修改（只看运行时节点，表单值没生效前不算）。 */
export function memberEdited(slot: NodeVariantSlot, ref: string): boolean {
  const draft = slot.memberDrafts?.[ref];
  return Boolean(draft && !sameJson(draft.draftNode, draft.sourceNode));
}

/**
 * 节点组成员：整组展开成一个个节点，可以勾选只在部分成员里随机/按序，也可以逐个编辑。
 * 没有勾选记录（spec.selection 为空）表示整组参与；勾选记录为空数组表示一个都没选。
 */
export function GroupMembers({ slot, variant = "list" }: { slot: NodeVariantSlot; variant?: "list" | "grid" }) {
  const workspace = useCustomWorkspace();
  const spec = slot.randomSpec;
  const browseSpec = useMemo(() => (spec ? withoutSelection(spec) : null), [spec]);
  const browseSignature = useMemo(() => JSON.stringify(browseSpec), [browseSpec]);
  const [members, setMembers] = useState<NodePoolCandidate[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<MemberFilter>("all");
  const [visible, setVisible] = useState(PAGE);
  const [opening, setOpening] = useState("");
  const requestId = useRef(0);

  const selection = spec?.selection;
  const explicit = Boolean(selection);
  const selectedSet = useMemo(() => new Set(selection?.refs ?? []), [selection]);
  const isChecked = (ref: string) => !explicit || selectedSet.has(ref);
  const sequential = spec?.drawMode === "sequential";
  const cursor = slot.poolCursor ?? 0;

  async function load(refresh = false) {
    if (!browseSpec?.source.value.trim()) {
      setMembers([]);
      setLoaded(false);
      return;
    }
    const id = ++requestId.current;
    setBusy(true);
    setError("");
    try {
      const response = await listAllPoolNodes(slot.role, refresh ? { ...browseSpec } : browseSpec);
      if (id !== requestId.current) return;
      setMembers(response.items);
      setLoaded(true);
    } catch (requestError) {
      if (id !== requestId.current) return;
      setError(errorMessage(requestError));
      setMembers([]);
    } finally {
      if (id === requestId.current) setBusy(false);
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 250);
    return () => window.clearTimeout(timer);
    // browseSpec 用签名比较，勾选变化不需要重新读成员。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [browseSignature, slot.role]);

  useEffect(() => setVisible(PAGE), [query, filter, browseSignature]);

  // 顺序模式下的次序：只在勾选的成员里数，和后端按勾选后的列表推进游标一致。
  const orderByRef = useMemo(() => {
    const order = new Map<string, number>();
    let index = 0;
    for (const member of members) {
      if (!explicit || selectedSet.has(member.ref)) {
        order.set(member.ref, index);
        index += 1;
      }
    }
    return order;
  }, [explicit, members, selectedSet]);
  const selectedCount = explicit ? orderByRef.size : members.length;

  const needle = query.trim().toLowerCase();
  const filtered = members.filter((member) => {
    if (needle && !`${member.name} ${member.relative ?? ""}`.toLowerCase().includes(needle)) return false;
    if (filter === "selected") return isChecked(member.ref);
    if (filter === "unselected") return !isChecked(member.ref);
    if (filter === "edited") return memberEdited(slot, member.ref);
    return true;
  });
  const shown = filtered.slice(0, visible);
  const editedCount = members.filter((member) => memberEdited(slot, member.ref)).length;

  function commitSelection(refs: string[]) {
    // 全部勾上就回到"整组"状态，之后组里新增的节点也会自动参与。
    if (refs.length >= members.length && members.every((member) => refs.includes(member.ref))) {
      workspace.setGroupSelection(slot.slotId, null);
      return;
    }
    workspace.setGroupSelection(slot.slotId, members.filter((member) => refs.includes(member.ref)).map((member) => member.ref));
  }

  function toggle(ref: string) {
    const current = explicit ? [...selectedSet] : members.map((member) => member.ref);
    commitSelection(current.includes(ref) ? current.filter((item) => item !== ref) : [...current, ref]);
  }

  function setVisibleChecked(checked: boolean) {
    // 批量操作只作用于当前筛选/搜索出来的成员。
    const targets = new Set(filtered.map((member) => member.ref));
    const current = new Set(explicit ? selectedSet : members.map((member) => member.ref));
    for (const ref of targets) {
      if (checked) current.add(ref);
      else current.delete(ref);
    }
    commitSelection([...current]);
  }

  function invert() {
    commitSelection(members.filter((member) => !isChecked(member.ref)).map((member) => member.ref));
  }

  async function editMember(member: NodePoolCandidate) {
    if (slot.memberDrafts?.[member.ref]) {
      workspace.openMemberEditor(slot.slotId, member.ref, member.name);
      return;
    }
    setOpening(member.ref);
    setError("");
    try {
      const response = await apiGet<NodeReadResponse>(`/nodes/read?${new URLSearchParams({ ref: member.ref, role: slot.role })}`);
      workspace.openMemberEditor(slot.slotId, member.ref, member.name, response);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setOpening("");
    }
  }

  function exclude(member: NodePoolCandidate) {
    if (!spec || spec.source.exclude_names.includes(member.name)) return;
    const position = orderByRef.get(member.ref);
    workspace.updateRandomSpec(slot.slotId, {
      ...spec,
      source: { ...spec.source, exclude_names: [...spec.source.exclude_names, member.name] },
      ...(spec.selection ? { selection: { refs: spec.selection.refs.filter((ref) => ref !== member.ref) } } : {}),
    });
    // 排除已经跑过的成员后，后面的都前移一位；游标跟着退一位，下一个还是原来那个节点。
    if (sequential && position !== undefined && position < cursor) workspace.setPoolCursor(slot.slotId, cursor - 1);
  }

  if (!spec) return null;
  const editingRef = workspace.state.editor.slotId === slot.slotId ? workspace.state.editor.memberRef : null;
  const canExclude = spec.source.type === "folder";

  return (
    <section aria-label="节点组成员" className={`group-members group-members-${variant}`}>
      <div className="group-members-toolbar">
        <label className="search-input">
          <Search size={14} />
          <input aria-label="搜索节点组成员" onChange={(event) => setQuery(event.target.value)} placeholder="搜索成员" value={query} />
        </label>
        <button aria-label="重新读取成员" className="icon-button btn-ghost" disabled={busy} onClick={() => void load(true)} title="重新读取成员" type="button">
          <RefreshCw className={busy ? "spin" : ""} size={14} />
        </button>
      </div>
      <div className="group-members-bar">
        <div aria-label="成员筛选" className="filter-tabs" role="tablist">
          {(Object.keys(filterLabels) as MemberFilter[]).map((key) => (
            <button aria-selected={filter === key} className={filter === key ? "active" : ""} key={key} onClick={() => setFilter(key)} role="tab" type="button">
              {filterLabels[key]}
              {key === "edited" && editedCount ? <span className="count">{editedCount}</span> : null}
            </button>
          ))}
        </div>
        <span className={`selection-count${explicit && selectedCount === 0 ? " empty" : ""}`}>
          {loaded ? (explicit ? `已选 ${selectedCount} / ${members.length}` : `整组 ${members.length} 个`) : ""}
        </span>
      </div>
      <div className="group-members-actions">
        <button className="btn-sm btn-ghost" disabled={!members.length} onClick={() => setVisibleChecked(true)} type="button"><CheckSquare size={13} /> {needle || filter !== "all" ? "勾选筛出的" : "全选"}</button>
        <button className="btn-sm btn-ghost" disabled={!members.length} onClick={() => setVisibleChecked(false)} type="button"><Square size={13} /> {needle || filter !== "all" ? "取消筛出的" : "全不选"}</button>
        <button className="btn-sm btn-ghost" disabled={!members.length} onClick={invert} type="button">反选</button>
        {explicit ? <button className="btn-sm btn-ghost" onClick={() => workspace.setGroupSelection(slot.slotId, null)} title="清除勾选记录，整组都参与" type="button"><Undo2 size={13} /> 恢复整组</button> : null}
      </div>
      {explicit && selectedCount === 0 && loaded ? <div className="inline-warning">一个成员都没勾选，出图前至少勾选一个。</div> : null}
      {error ? <div className="alert error-alert" role="alert">{error}</div> : null}

      <div
        className="group-members-scroll"
        onScroll={(event) => {
          const element = event.currentTarget;
          if (visible < filtered.length && element.scrollTop + element.clientHeight >= element.scrollHeight - 120) {
            setVisible((current) => current + PAGE);
          }
        }}
      >
        {shown.map((member) => {
          const checked = isChecked(member.ref);
          const order = orderByRef.get(member.ref);
          const isNext = sequential && order === cursor;
          const done = sequential && order !== undefined && order < cursor;
          const edited = memberEdited(slot, member.ref);
          const classes = ["group-member", checked ? "checked" : "unchecked", isNext ? "next" : "", done ? "done" : "", editingRef === member.ref ? "editing" : ""].filter(Boolean).join(" ");
          return (
            <article className={classes} key={member.ref} title={member.relative ?? member.name}>
              <label className="group-member-check">
                <input aria-label={`勾选 ${member.name}`} checked={checked} onChange={() => toggle(member.ref)} type="checkbox" />
              </label>
              <NodePreviewImage className="group-member-thumb" name={member.name} nodeRef={member.ref} size={variant === "grid" ? 240 : 96} />
              <div className="group-member-body">
                <span className="group-member-name">
                  {member.name}
                  {edited ? <span aria-label="已修改" className="dirty-dot" title="有临时修改，抽到它时用修改后的节点" /> : null}
                </span>
                <span className="group-member-meta">
                  {sequential && order !== undefined ? <span className="order">#{order + 1}</span> : null}
                  {isNext ? <span className="chip accent">下一个</span> : null}
                  {member.relative && member.relative !== member.name ? <span className="path">{member.relative}</span> : null}
                </span>
              </div>
              <div className="group-member-actions">
                {sequential && checked && !isNext && order !== undefined ? (
                  <button aria-label={`从 ${member.name} 开始`} className="icon-button btn-ghost" onClick={() => workspace.setPoolCursor(slot.slotId, order)} title="从这里开始按顺序跑" type="button"><Play size={13} /></button>
                ) : null}
                <button aria-label={`编辑成员 ${member.name}`} className="icon-button btn-ghost" disabled={opening === member.ref} onClick={() => void editMember(member)} title="编辑这个成员" type="button"><Pencil size={13} /></button>
                {canExclude ? (
                  <button aria-label={`排除 ${member.name}`} className="icon-button btn-ghost" onClick={() => exclude(member)} title="从节点组里排除（写进名称排除）" type="button"><EyeOff size={13} /></button>
                ) : null}
              </div>
            </article>
          );
        })}
        {busy && !members.length ? <div className="group-members-empty">正在读取成员…</div> : null}
        {!busy && loaded && !filtered.length ? <div className="group-members-empty">{members.length ? "没有符合条件的成员。" : "节点组里没有节点。"}</div> : null}
        {visible < filtered.length ? <div className="group-members-more">还有 {filtered.length - visible} 个，继续滚动加载</div> : null}
      </div>
    </section>
  );
}
