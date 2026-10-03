import { useEffect, useState } from "react";

import { apiGet, errorMessage } from "../api/client";
import type { ComfyUITargetsResponse } from "../api/types";
import { describeTargetStatus, onComfyTargetsChanged, targetStatusTone } from "../comfyui/targetStatus";

const REFRESH_MS = 15_000;

type ComfyTargetPanelProps = {
  value: string | undefined;
  onChange: (value: string) => void;
};

/** 工作区级别的 ComfyUI 运行位置。状态由后端查询，云端只读容器数，不会因为查看状态而启动。 */
export function ComfyTargetPanel({ value, onChange }: ComfyTargetPanelProps) {
  const [data, setData] = useState<ComfyUITargetsResponse | null>(null);
  const [fetchedAt, setFetchedAt] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await apiGet<ComfyUITargetsResponse>("/comfyui/targets");
        if (cancelled) return;
        setData(response);
        setFetchedAt(Date.now());
        setError("");
      } catch (loadError) {
        if (!cancelled) setError(errorMessage(loadError));
      }
    }
    void load();
    const refresh = window.setInterval(() => void load(), REFRESH_MS);
    const tick = window.setInterval(() => setNow(Date.now()), 1000);
    const unsubscribe = onComfyTargetsChanged(() => void load());
    return () => {
      cancelled = true;
      unsubscribe();
      window.clearInterval(refresh);
      window.clearInterval(tick);
    };
  }, []);

  const targets = data?.targets ?? [];
  const selectedName = value || data?.default_target || targets[0]?.name || "";
  const selected = targets.find((target) => target.name === selectedName) ?? null;
  const elapsedSeconds = fetchedAt ? Math.max(0, Math.floor((now - fetchedAt) / 1000)) : 0;

  return (
    <div className="comfy-target-panel">
      <label className="field compact">
        <span>ComfyUI 运行位置</span>
        <select
          aria-label="ComfyUI 运行位置"
          disabled={!targets.length}
          onChange={(event) => onChange(event.target.value)}
          value={selectedName}
        >
          {targets.map((target) => (
            <option key={target.name} value={target.name}>{target.label}</option>
          ))}
        </select>
      </label>
      {selected ? (
        <span
          className={`status-pill target-status ${targetStatusTone(selected)}`}
          role="status"
          title={selected.status.detail ?? selected.base_url}
        >
          {describeTargetStatus(selected, elapsedSeconds)}
        </span>
      ) : null}
      {error ? <small className="field-error">{error}</small> : null}
    </div>
  );
}
