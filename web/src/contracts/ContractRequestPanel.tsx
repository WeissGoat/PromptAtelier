import { Plus, RefreshCw, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { errorMessage } from "../api/client";
import type { NodeSummary } from "../api/types";
import { NodePicker } from "../components/NodePicker";
import { contractsApi } from "./api";
import type { ActionGroupSummary, ContractSummary, FormatSummary } from "./types";

export type NodeChoice = { ref: string; name: string };

export type ContractDraft = {
  characters: NodeChoice[];
  actionGroup: NodeChoice | null;
  clothing: NodeChoice | null;
  background: NodeChoice | null;
  requirements: string;
  targetFormat: string;
  keepOrder: boolean;
  allowNewFrames: boolean;
  maxNewFrames: number;
};

export const EMPTY_DRAFT: ContractDraft = {
  characters: [],
  actionGroup: null,
  clothing: null,
  background: null,
  requirements: "",
  targetFormat: "nai-v4.5",
  keepOrder: true,
  allowNewFrames: true,
  maxNewFrames: 2,
};

type Props = {
  draft: ContractDraft;
  formats: FormatSummary[];
  contracts: ContractSummary[];
  activeId: string | null;
  creating: boolean;
  onChange(draft: ContractDraft): void;
  onCreate(): void;
  onOpen(id: string): void;
  onImportNew(): void;
  onRefresh(pull: boolean): void;
};

/** 节点 ref 的末段，用来把 Web 的绝对路径和契约里的相对路径对上。 */
function tail(ref: string): string {
  return ref.replace(/\\/g, "/").replace(/\/+$/, "").split("/").slice(-2).join("/");
}

function matchLevel(contract: ContractSummary, draft: ContractDraft): "full" | "partial" | null {
  const wanted: string[] = [];
  if (draft.actionGroup) wanted.push(tail(draft.actionGroup.ref).split("/").pop()!);
  draft.characters.forEach((item) => wanted.push(tail(item.ref)));
  if (!wanted.length) return "partial";
  const refs = [
    contract.nodes.action_group ?? "",
    ...Object.values(contract.nodes.characters ?? {}),
  ].map((ref) => tail(ref));
  const hits = wanted.filter((item) => refs.some((ref) => ref === item || ref.endsWith(`/${item}`) || ref === item.split("/").pop()));
  if (hits.length === wanted.length) return "full";
  return hits.length ? "partial" : null;
}

function ActionGroupPicker({ value, onChange }: { value: NodeChoice | null; onChange(value: NodeChoice | null): void }) {
  const [groups, setGroups] = useState<ActionGroupSummary[]>([]);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!open || groups.length) return;
    contractsApi.actionGroups().then(setGroups).catch((err) => setError(errorMessage(err)));
  }, [open, groups.length]);
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return groups.filter((group) => !needle || group.name.toLowerCase().includes(needle)).slice(0, 80);
  }, [groups, query]);
  return (
    <div className="field ct-group-picker">
      <span>动作组（st_ / stn_）</span>
      {value ? (
        <div className="ct-chosen">
          <span className="mono">{value.name}</span>
          <button aria-label="清除动作组" className="icon-button btn-ghost btn-sm" onClick={() => onChange(null)} type="button"><X size={13} /></button>
        </div>
      ) : (
        <input
          aria-label="搜索动作组"
          onChange={(event) => setQuery(event.target.value)}
          onFocus={() => setOpen(true)}
          placeholder="搜索 st_* / stn_*"
          value={query}
        />
      )}
      {open && !value ? (
        <div className="ct-dropdown" role="listbox">
          {error ? <p className="field-error">{error}</p> : null}
          {visible.map((group) => (
            <button
              key={group.ref}
              onClick={() => {
                onChange({ ref: group.ref, name: group.name });
                setOpen(false);
              }}
              role="option"
              type="button"
            >
              <span className="mono">{group.name}</span>
              <small>{group.member_count} 个</small>
            </button>
          ))}
          {!error && !visible.length ? <p className="muted">{groups.length ? "没有匹配的动作组" : "加载中…"}</p> : null}
          <button className="btn-ghost" onClick={() => setOpen(false)} type="button">收起</button>
        </div>
      ) : null}
    </div>
  );
}

const STATUS_LABEL: Record<string, string> = { pending: "等待 Agent", done: "已完成", invalid: "无法解析" };

export function ContractRequestPanel(props: Props) {
  const { draft, onChange } = props;
  const [filterByNodes, setFilterByNodes] = useState(true);
  const update = (patch: Partial<ContractDraft>) => onChange({ ...draft, ...patch });
  const history = props.contracts
    .map((contract) => ({ contract, level: filterByNodes ? matchLevel(contract, draft) : "partial" as const }))
    .filter((item) => item.level !== null);
  const canCreate = Boolean(draft.actionGroup) && draft.characters.length > 0 && !props.creating;

  return (
    <section aria-label="请求与历史" className="panel ct-left">
      <div className="panel-title"><h2>请求</h2></div>
      <div className="field">
        <span>角色（可多选，按顺序为 c1、c2…）</span>
        {draft.characters.map((item, index) => (
          <div className="ct-chosen" key={item.ref}>
            <span className={`chip ct-char origin-c${index + 1}`}>c{index + 1}</span>
            <span className="ct-wrap">{item.name}</span>
            <button
              aria-label={`移除角色 ${item.name}`}
              className="icon-button btn-ghost btn-sm"
              onClick={() => update({ characters: draft.characters.filter((other) => other.ref !== item.ref) })}
              type="button"
            >
              <X size={13} />
            </button>
          </div>
        ))}
        <NodePicker
          key={draft.characters.length}
          label="添加角色"
          onClear={() => undefined}
          onSelect={(node: NodeSummary) => {
            if (!draft.characters.some((item) => item.ref === node.ref)) update({ characters: [...draft.characters, { ref: node.ref, name: node.name }] });
          }}
          placeholder="搜索角色"
          role="character"
          value=""
        />
      </div>
      <ActionGroupPicker onChange={(actionGroup) => update({ actionGroup })} value={draft.actionGroup} />
      <NodePicker
        displayValue={draft.clothing?.name}
        label="服装（可选）"
        onClear={() => update({ clothing: null })}
        onSelect={(node) => update({ clothing: { ref: node.ref, name: node.name } })}
        placeholder="搜索服装"
        role="clothing"
        value={draft.clothing?.ref ?? ""}
      />
      <NodePicker
        displayValue={draft.background?.name}
        label="背景（可选）"
        onClear={() => update({ background: null })}
        onSelect={(node) => update({ background: { ref: node.ref, name: node.name } })}
        placeholder="搜索背景"
        role="background"
        value={draft.background?.ref ?? ""}
      />
      <label className="field">
        <span>定制要求</span>
        <textarea
          onChange={(event) => update({ requirements: event.target.value })}
          placeholder="例如：背景统一改为夜晚教室，保持服装连续；第 3 帧之后加一个窗边回头的过渡镜头。"
          rows={5}
          value={draft.requirements}
        />
      </label>
      <div className="ct-row ct-options">
        <label className="field">
          <span>目标格式</span>
          <select onChange={(event) => update({ targetFormat: event.target.value })} value={draft.targetFormat}>
            {props.formats.map((format) => <option key={format.id} value={format.id}>{format.label || format.id}</option>)}
          </select>
        </label>
        <label className="ct-check"><input checked={draft.keepOrder} onChange={(event) => update({ keepOrder: event.target.checked })} type="checkbox" /> 保持顺序</label>
        <label className="ct-check"><input checked={draft.allowNewFrames} onChange={(event) => update({ allowNewFrames: event.target.checked })} type="checkbox" /> 允许新增帧</label>
        <label className="field ct-narrow">
          <span>最多新增</span>
          <input
            disabled={!draft.allowNewFrames}
            min={0}
            onChange={(event) => update({ maxNewFrames: Math.max(0, Number(event.target.value) || 0) })}
            type="number"
            value={draft.maxNewFrames}
          />
        </label>
      </div>
      <div className="ct-row">
        <button className="primary" disabled={!canCreate} onClick={props.onCreate} title={canCreate ? "" : "至少选一个角色和一个动作组"} type="button">
          <Plus size={14} /> 新建并生成要求
        </button>
      </div>

      <div className="panel-title ct-history-title">
        <h2>历史契约</h2>
        <div className="ct-row">
          <label className="ct-check"><input checked={filterByNodes} onChange={(event) => setFilterByNodes(event.target.checked)} type="checkbox" /> 按所选节点</label>
          <button
            aria-label="刷新契约列表"
            className="icon-button btn-sm"
            onClick={(event) => props.onRefresh(event.shiftKey)}
            title="重新扫描契约目录；按住 Shift 先对动作库 git pull --ff-only"
            type="button"
          >
            <RefreshCw size={13} />
          </button>
        </div>
      </div>
      <ul className="ct-history">
        {history.map(({ contract, level }) => (
          <li key={contract.id}>
            <button
              aria-current={contract.id === props.activeId ? "true" : undefined}
              className={contract.id === props.activeId ? "active" : ""}
              onClick={() => props.onOpen(contract.id)}
              type="button"
            >
              <span className="ct-history-title-line">
                <strong>{contract.title || contract.nodes.action_group || contract.id}</strong>
                <span className={`ct-pill ct-status-${contract.status}`}>{STATUS_LABEL[contract.status] ?? contract.status}</span>
              </span>
              <small className="mono">{contract.id}</small>
              <small>
                {contract.target_format} · {contract.frame_count} 帧
                {filterByNodes && level === "full" ? " · 完全匹配" : filterByNodes && level === "partial" && (draft.characters.length || draft.actionGroup) ? " · 部分匹配" : ""}
              </small>
            </button>
          </li>
        ))}
        {!history.length ? <li className="muted">没有契约</li> : null}
      </ul>
      <button className="btn-sm" disabled={!props.activeId} onClick={props.onImportNew} type="button">导入帧内容到当前契约</button>
    </section>
  );
}
