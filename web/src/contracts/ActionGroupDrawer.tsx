import { Copy, Crosshair, X } from "lucide-react";
import { useEffect, useState } from "react";

import { NodePreviewImage } from "../components/NodePreviewImage";
import type { ActionMember, ContractDetail } from "./types";

const CLASSIFY_KEYS = ["phase", "cast", "pose", "environment", "clothing"] as const;

function flat(value: unknown): string {
  if (Array.isArray(value)) return value.join(",") || "—";
  if (value && typeof value === "object") return Object.entries(value).map(([k, v]) => `${k}:${flat(v)}`).join(";");
  return value == null || value === "" ? "—" : String(value);
}

function MemberCard({ member, frames, onLocate }: { member: ActionMember; frames: string[]; onLocate(frameId: string): void }) {
  const used = frames.length > 0;
  return (
    <article className={used ? "ct-member" : "ct-member is-missing"}>
      <NodePreviewImage className="ct-member-preview" name={member.title} nodeRef={member.path} size={160} />
      <div className="ct-member-body">
        <div className="ct-row">
          <strong>{member.index ? `#${member.index} ` : ""}{member.title}</strong>
          <span className={used ? "ct-pill ct-pill-ok" : "ct-pill ct-pill-warn"}>{used ? `用于 ${frames.join(", ")}` : "未使用"}</span>
        </div>
        <small className="mono ct-wrap">{member.ref}</small>
        <div className="ct-kvs">
          {CLASSIFY_KEYS.map((key) => (
            <span className="ct-kv" key={key}><b>{key}</b>{flat(member.classify[key])}</span>
          ))}
          <span className="ct-kv"><b>scope</b>{member.character_scope ?? "—"}</span>
        </div>
        <pre className="ct-raw">{member.positive}</pre>
        {member.negative ? <pre className="ct-raw ct-raw-negative">{member.negative}</pre> : null}
        <div className="ct-row">
          {frames.map((frameId) => (
            <button className="btn-sm" key={frameId} onClick={() => onLocate(frameId)} type="button"><Crosshair size={12} /> 定位到 {frameId}</button>
          ))}
          <button className="btn-sm" onClick={() => void navigator.clipboard?.writeText(member.ref)} type="button"><Copy size={12} /> 复制 ref</button>
          <button className="btn-sm" onClick={() => void navigator.clipboard?.writeText(member.positive)} type="button"><Copy size={12} /> 复制原始提示词</button>
        </div>
      </div>
    </article>
  );
}

/** 动作组参考抽屉：按组内顺序列出全部成员，标明被哪些帧使用（§9）。 */
export function ActionGroupDrawer({ detail, onClose, onLocate }: { detail: ContractDetail; onClose(): void; onLocate(frameId: string): void }) {
  const [filter, setFilter] = useState<"all" | "missing">("all");
  const group = detail.sources.action_group;
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  if (!group) return null;
  const used = detail.coverage?.used ?? {};
  const members = group.members.filter((member) => filter === "all" || !used[member.ref]);
  const missing = group.members.filter((member) => !used[member.ref]).length;
  const references = Object.entries(detail.sources.references);
  return (
    <aside aria-label="动作组参考" className="ct-drawer">
      <header className="ct-drawer-head">
        <div>
          <h2>动作组参考</h2>
          <small className="mono">{group.name} · {group.member_count} 个动作</small>
        </div>
        <button aria-label="关闭动作组参考" className="icon-button" onClick={onClose} type="button"><X size={16} /></button>
      </header>
      <div className="ct-row ct-drawer-filter">
        <div className="ct-seg" role="group" aria-label="筛选">
          <button aria-pressed={filter === "all"} className={filter === "all" ? "on" : ""} onClick={() => setFilter("all")} type="button">全部 {group.member_count}</button>
          <button aria-pressed={filter === "missing"} className={filter === "missing" ? "on" : ""} onClick={() => setFilter("missing")} type="button">未使用 {missing}</button>
        </div>
        <span className="ct-pill ct-pill-ok">已覆盖 {group.member_count - missing}</span>
        {missing ? <span className="ct-pill ct-pill-warn">缺少 {missing}</span> : null}
        {detail.coverage?.custom_frames.length ? <span className="ct-pill ct-pill-acc">新增 {detail.coverage.custom_frames.length} 帧</span> : null}
      </div>
      <div className="ct-drawer-body">
        {members.map((member) => (
          <MemberCard
            frames={used[member.ref] ?? []}
            key={member.ref}
            member={member}
            onLocate={(frameId) => {
              onLocate(frameId);
              onClose();
            }}
          />
        ))}
        {references.length ? <h3 className="ct-subhead">自定义帧引用的参考动作</h3> : null}
        {references.map(([ref, member]) => (
          <MemberCard
            frames={detail.frames.filter((frame) => frame.inspired_by.includes(ref)).map((frame) => frame.id)}
            key={ref}
            member={member}
            onLocate={(frameId) => {
              onLocate(frameId);
              onClose();
            }}
          />
        ))}
      </div>
      <footer className="ct-drawer-foot muted">信息来自节点的 meta.yaml / tags.txt / classify.yaml；预览图取动作目录里的图片，没有图片时显示占位。</footer>
    </aside>
  );
}
