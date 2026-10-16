import { Layers } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { errorMessage } from "../api/client";
import type { NodePoolCandidate } from "../api/types";
import { scanNodePool } from "../randomNodes/api";
import type { NodeVariantSlot } from "../workspace/types";
import { NodePreviewImage } from "./NodePreviewImage";

const STRIP_SIZE = 6;

export function nodeGroupModeLabel(slot: NodeVariantSlot): string {
  return slot.randomSpec?.drawMode === "sequential" ? "顺序" : "随机";
}

/**
 * 节点组在槽位里的摘要：抽取方式、成员数、几张成员预览图。
 * 顺序模式从当前位置开始显示，第一张就是下一次要跑的节点。
 */
export function NodeGroupSummary({ slot, onOpen }: { slot: NodeVariantSlot; onOpen?: () => void }) {
  const spec = slot.randomSpec;
  const sequential = spec?.drawMode === "sequential";
  const cursor = sequential ? slot.poolCursor ?? 0 : 0;
  const specSignature = useMemo(() => JSON.stringify(spec), [spec]);
  const [members, setMembers] = useState<NodePoolCandidate[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [unselected, setUnselected] = useState(0);
  const [error, setError] = useState("");
  const noneSelected = Boolean(spec?.selection && spec.selection.refs.length === 0);

  useEffect(() => {
    if (!spec?.source.value.trim() || noneSelected) {
      setMembers([]);
      setTotal(null);
      return;
    }
    let active = true;
    const timer = window.setTimeout(() => {
      void scanNodePool({ role: slot.role, spec, offset: cursor, limit: STRIP_SIZE })
        .then((response) => {
          if (!active) return;
          setMembers(response.items);
          setTotal(response.total);
          setUnselected(response.stats.unselected ?? 0);
          setError("");
        })
        .catch((requestError) => {
          if (active) setError(errorMessage(requestError));
        });
    }, 300);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
    // spec 用签名比较，避免每次渲染都重新扫描。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [specSignature, cursor, slot.role, noneSelected]);

  const source = spec?.source;
  const finished = sequential && total !== null && cursor >= total;
  // 有勾选时显示"已选 x / 整组 y"，否则"共 y 个"。
  const count = spec?.selection ? `已选 ${total ?? 0} / ${(total ?? 0) + unselected}` : `共 ${total} 个`;
  let detail = "";
  if (!source?.value) detail = "未配置来源";
  else if (noneSelected) detail = "一个成员都没勾选";
  else if (total === null) detail = error ? "" : "正在读取成员…";
  else if (sequential) detail = finished ? `${count} · 已跑完，请重置位置` : `${count} · 下一个 #${cursor + 1}${members[0] ? ` ${members[0].name}` : ""}`;
  else detail = `${count} · 每次随机抽一个`;

  return (
    <button aria-label={`编辑节点组：${source?.value ?? "未配置"}`} className="node-group-summary" onClick={onOpen} type="button">
      <span className="node-group-title">
        <Layers size={15} />
        <strong>节点组 · {nodeGroupModeLabel(slot)}</strong>
        {source?.value ? <small title={source.value}>{source.type} · {source.value}</small> : null}
      </span>
      <span className="node-group-detail">{detail}</span>
      {error ? <span className="field-error">{error}</span> : null}
      {members.length ? (
        <span className="node-group-strip">
          {members.map((member, index) => (
            <NodePreviewImage
              className={sequential && index === 0 ? "node-group-thumb next" : "node-group-thumb"}
              hasPreview={member.has_preview}
              key={member.ref}
              name={member.name}
              nodeRef={member.ref}
              size={160}
              zoomable={false}
            />
          ))}
          {total !== null && total > cursor + members.length ? <small>+{total - cursor - members.length}</small> : null}
        </span>
      ) : null}
    </button>
  );
}
