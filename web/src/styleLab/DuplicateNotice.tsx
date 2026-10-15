import { CopyCheck } from "lucide-react";

import { ApiClientError } from "../api/client";
import { formatTime } from "./format";

/** 后端拦下的重复请求：和上一次（同一张图或同一个配方、同一种出图）发给 NovelAI 的内容完全相同。 */
export type DuplicateRequest = { runId: string | null; status: string | null; createdAt: number | null };

export function duplicateOf(exc: unknown): DuplicateRequest | null {
  if (!(exc instanceof ApiClientError) || exc.code !== "duplicate_request") return null;
  const details = (exc.details ?? {}) as { run_id?: string; status?: string; created_at?: number };
  return { runId: details.run_id ?? null, status: details.status ?? null, createdAt: details.created_at ?? null };
}

const STATUS_TEXT: Record<string, string> = {
  queued: "还在排队",
  running: "正在出图",
  succeeded: "已经出完",
};

export function DuplicateNotice({
  duplicate,
  onForce,
  onDismiss,
}: {
  duplicate: DuplicateRequest;
  onForce: () => void;
  onDismiss: () => void;
}) {
  const when = duplicate.createdAt ? formatTime(duplicate.createdAt) : "上一次";
  const state = duplicate.status ? STATUS_TEXT[duplicate.status] ?? "" : "";
  return (
    <div className="sl-duplicate" role="alert">
      <CopyCheck size={15} aria-hidden="true" />
      <span>
        和 {when} 的请求完全相同{state ? `（${state}）` : ""}，出图结果也会一样。换个种子或改改提示词再试，或者确认要重复出图。
      </span>
      <span className="sl-duplicate-actions">
        <button className="sl-ghost tiny" onClick={onDismiss} type="button">
          不出了
        </button>
        <button className="sl-primary small" onClick={onForce} type="button">
          仍要生成
        </button>
      </span>
    </div>
  );
}
