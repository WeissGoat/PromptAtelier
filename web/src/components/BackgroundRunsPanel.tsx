import { CircleStop, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { apiGet, apiPost, apiUrl, errorMessage } from "../api/client";
import { describeJobProgress } from "../comfyui/jobProgress";
import {
  BACKGROUND_BATCH_JOB,
  BACKGROUND_RUNS_CHANGED,
  itemProgressJob,
  type BackgroundBatchItem,
  type BackgroundBatchJob,
} from "../generation/backgroundRun";

const terminalStatuses = new Set(["succeeded", "failed", "cancelled"]);
const statusLabels: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  cancelling: "正在停止",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已停止",
};

type Props = {
  onOpenImage(selection: { paths: string[]; index: number }): void;
  pollIntervalMs?: number;
};

function formatTime(seconds: number | undefined): string {
  if (!seconds) return "";
  return new Date(seconds * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function RunningItem({ job, item, total }: { job: BackgroundBatchJob; item: BackgroundBatchItem; total: number }) {
  const progress = describeJobProgress(itemProgressJob(job, item), Date.now() / 1000);
  return (
    <small className="job-progress">
      第 {item.index + 1}/{total} 项{item.label ? `：${item.label}` : ""}{progress ? ` · ${progress}` : " · 出图中"}
    </small>
  );
}

function BackgroundRun({ job, defaultOpen, onCancel, onOpenImage }: {
  job: BackgroundBatchJob;
  defaultOpen: boolean;
  onCancel(id: string): void;
  onOpenImage: Props["onOpenImage"];
}) {
  const result = job.result;
  const items = result?.items ?? [];
  const counts = result?.counts;
  const running = items.find((item) => item.status === "running");
  const finished = items.filter((item) => item.status === "succeeded" && item.images.length);
  const failed = items.filter((item) => item.status === "failed");
  const paths = finished.flatMap((item) => item.images.map((image) => image.path));
  const active = !terminalStatuses.has(job.status);
  return (
    <details className="background-run" open={defaultOpen}>
      <summary>
        <strong>{result?.label ?? job.id}</strong>
        <span className={`status-pill background-status-${job.status}`}>{statusLabels[job.status] ?? job.status}</span>
        {counts ? (
          <span>
            成功 {counts.succeeded} / {result.total}
            {counts.failed ? ` · 失败 ${counts.failed}` : ""}
            {counts.cancelled ? ` · 跳过 ${counts.cancelled}` : ""}
          </span>
        ) : null}
        <small>{formatTime(job.created_at)}</small>
      </summary>
      {active ? (
        <div className="background-run-actions">
          {running && result ? <RunningItem item={running} job={job} total={result.total} /> : <small className="job-progress">等待开始</small>}
          <button disabled={job.status === "cancelling"} onClick={() => onCancel(job.id)} title="跑完当前这张后停止，剩下的跳过" type="button">
            <CircleStop size={15} /> 停止
          </button>
        </div>
      ) : null}
      {/* 逐项错误已经列在下面时不再重复整体错误（"全部 N 项都失败了：…"）。 */}
      {job.status === "failed" && job.error && !failed.length ? <div className="field-error">{job.error}</div> : null}
      {result?.output_dir ? <small className="field-hint">输出目录：<code>{result.output_dir}</code></small> : null}
      {finished.length ? (
        <div className="generated-image-grid">
          {finished.flatMap((item) => item.images.map((image, imageIndex) => (
            <figure className="generated-image" key={`${image.path}-${imageIndex}`}>
              <button
                aria-label={`打开后台第 ${item.index + 1} 项大图`}
                className="image-preview-button"
                onClick={() => onOpenImage({ paths, index: Math.max(0, paths.indexOf(image.path)) })}
                type="button"
              >
                <img alt={item.label ?? `后台第 ${item.index + 1} 项`} loading="lazy" src={apiUrl(`/results/image?path=${encodeURIComponent(image.path)}`)} />
              </button>
              <figcaption>
                <span>#{item.index + 1}{item.label ? ` ${item.label}` : ""}</span>
                {item.seed !== undefined ? <span>Seed: {item.seed}</span> : null}
              </figcaption>
            </figure>
          )))}
        </div>
      ) : null}
      {failed.length ? (
        <ul className="background-run-errors">
          {failed.map((item) => <li key={item.index}>#{item.index + 1}{item.label ? ` ${item.label}` : ""}：{item.error}</li>)}
        </ul>
      ) : null}
    </details>
  );
}

/** 后台批量任务列表：任务在 Web 后端里跑，重新打开网页也能接着看；后端重启后列表清空，已出的图仍在 Results。 */
export function BackgroundRunsPanel({ onOpenImage, pollIntervalMs = 1500 }: Props) {
  const [jobs, setJobs] = useState<BackgroundBatchJob[]>([]);
  const [error, setError] = useState("");
  const timer = useRef<number | null>(null);
  const mounted = useRef(true);

  const refresh = useCallback(async () => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
    try {
      const response = await apiGet<{ jobs: BackgroundBatchJob[] }>(`/jobs?name=${BACKGROUND_BATCH_JOB}&limit=10`);
      if (!mounted.current) return;
      setJobs(response.jobs);
      setError("");
      if (response.jobs.some((job) => !terminalStatuses.has(job.status))) {
        timer.current = window.setTimeout(() => void refresh(), pollIntervalMs);
      }
    } catch (requestError) {
      if (mounted.current) setError(errorMessage(requestError));
    }
  }, [pollIntervalMs]);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    const onChanged = () => void refresh();
    window.addEventListener(BACKGROUND_RUNS_CHANGED, onChanged);
    return () => {
      mounted.current = false;
      window.removeEventListener(BACKGROUND_RUNS_CHANGED, onChanged);
      if (timer.current !== null) window.clearTimeout(timer.current);
    };
  }, [refresh]);

  async function cancel(id: string) {
    try {
      await apiPost(`/jobs/${encodeURIComponent(id)}/cancel`, {});
    } catch (requestError) {
      setError(errorMessage(requestError));
    }
    void refresh();
  }

  // 没有任务时整块不显示（包括列表请求失败）；有任务时才把错误显示出来。
  if (!jobs.length) return null;
  return (
    <section className="background-runs" aria-label="后台任务">
      <div className="section-title-row">
        <div>
          <h3>后台任务</h3>
          <small>在 Web 后端里逐张跑，关掉网页不影响；后端重启后这里清空，已出的图仍在 Results。</small>
        </div>
        <button onClick={() => void refresh()} title="刷新" type="button"><RefreshCw size={15} /></button>
      </div>
      {error ? <div className="alert error-alert">{error}</div> : null}
      {jobs.map((job, index) => (
        <BackgroundRun
          defaultOpen={index === 0 || !terminalStatuses.has(job.status)}
          job={job}
          key={job.id}
          onCancel={(id) => void cancel(id)}
          onOpenImage={onOpenImage}
        />
      ))}
    </section>
  );
}
