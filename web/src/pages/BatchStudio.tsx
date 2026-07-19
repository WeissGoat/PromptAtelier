import { ListChecks, Play } from "lucide-react";
import { useMemo, useState } from "react";

import { apiPost, errorMessage } from "../api/client";
import type { BatchPreviewResponse, JobRecord } from "../api/types";

export function BatchStudio() {
  const [batchSpec, setBatchSpec] = useState("examples/batches/blackboard_action_new_manga_monochrome.yaml");
  const [characters, setCharacters] = useState("special_next_select");
  const [actionGroups, setActionGroups] = useState("action_new");
  const [artist, setArtist] = useState("109841329_03_manga_monochrome_yabuki_rance_no_vibe_latest_stable");
  const [maxTasks, setMaxTasks] = useState(1);
  const [nt, setNt] = useState(1);
  const [useInlineSpec, setUseInlineSpec] = useState(true);
  const [preview, setPreview] = useState<BatchPreviewResponse | null>(null);
  const [job, setJob] = useState<JobRecord | null>(null);
  const [status, setStatus] = useState("Ready");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const requestBody = useMemo(() => {
    if (!useInlineSpec) {
      return {
        batch_spec: batchSpec,
        fresh: true,
        limit: maxTasks,
      };
    }
    return {
      spec: {
        require: [
          "examples/project/base.yaml",
          "examples/project/collections.yaml",
          "examples/project/nai_const_action_groups.yaml",
        ],
        name: "web-batch-draft",
        batch: {
          characters,
          action_groups: actionGroups.split(",").map((item) => item.trim()).filter(Boolean),
          artist,
          composer: "script",
          auto_num: true,
          max_tasks: maxTasks,
          nt,
        },
        archive: {
          save_parameter_image: true,
        },
      },
      fresh: true,
      limit: maxTasks,
    };
  }, [actionGroups, artist, batchSpec, characters, maxTasks, nt, useInlineSpec]);

  async function planPreview() {
    setBusy(true);
    setError("");
    setStatus("Planning");
    try {
      const result = await apiPost<BatchPreviewResponse>("/batches/preview", requestBody);
      setPreview(result);
      setStatus(`Tasks: ${result.task_count}`);
    } catch (err) {
      setStatus("Planning failed");
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function runBatch() {
    setBusy(true);
    setError("");
    setStatus("Starting batch");
    try {
      const result = await apiPost<JobRecord>("/batches/run", requestBody);
      setJob(result);
      setStatus(`Job ${result.id}: ${result.status}`);
    } catch (err) {
      setStatus("Batch failed");
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="page-panel batch-page">
      <section className="panel batch-config-panel">
        <div className="panel-title">
          <h2>Batch Studio</h2>
          <span className="status-pill">{status}</span>
        </div>
        <label className="toggle-row">
          <input checked={useInlineSpec} onChange={(event) => setUseInlineSpec(event.target.checked)} type="checkbox" />
          Inline draft
        </label>
        <label className="field">
          <span>Batch YAML</span>
          <input aria-label="Batch YAML" disabled={useInlineSpec} onChange={(event) => setBatchSpec(event.target.value)} value={batchSpec} />
        </label>
        <div className="params-grid">
          <label className="field">
            <span>Characters</span>
            <input aria-label="Characters" disabled={!useInlineSpec} onChange={(event) => setCharacters(event.target.value)} value={characters} />
          </label>
          <label className="field">
            <span>Action Groups</span>
            <input aria-label="Action Groups" disabled={!useInlineSpec} onChange={(event) => setActionGroups(event.target.value)} value={actionGroups} />
          </label>
          <label className="field">
            <span>Artist</span>
            <input aria-label="Artist" disabled={!useInlineSpec} onChange={(event) => setArtist(event.target.value)} value={artist} />
          </label>
          <label className="field">
            <span>Max Tasks</span>
            <input aria-label="Max Tasks" min={1} onChange={(event) => setMaxTasks(Number(event.target.value))} type="number" value={maxTasks} />
          </label>
          <label className="field">
            <span>NT</span>
            <input aria-label="Batch NT" min={1} onChange={(event) => setNt(Number(event.target.value))} type="number" value={nt} />
          </label>
        </div>
        <div className="button-row">
          <button disabled={busy} onClick={planPreview} type="button">
            <ListChecks size={16} />
            Plan Preview
          </button>
          <button disabled={busy} onClick={runBatch} type="button">
            <Play size={16} />
            Run Batch
          </button>
        </div>
        {error ? <div className="alert error-alert">{error}</div> : null}
      </section>
      <section className="panel">
        <div className="panel-title">
          <h2>Plan</h2>
        </div>
        <pre className="json-preview">{JSON.stringify(preview ?? requestBody, null, 2)}</pre>
        {job ? <pre className="json-preview compact-json">{JSON.stringify(job, null, 2)}</pre> : null}
      </section>
    </main>
  );
}
