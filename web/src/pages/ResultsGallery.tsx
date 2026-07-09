import { RefreshCw } from "lucide-react";
import { useState } from "react";

import { apiGet } from "../api/client";
import type { ResultRun } from "../api/types";

export function ResultsGallery() {
  const [runs, setRuns] = useState<ResultRun[]>([]);
  const [selectedRun, setSelectedRun] = useState<ResultRun | null>(null);
  const [status, setStatus] = useState("Ready");

  async function refresh() {
    setStatus("Loading");
    const result = await apiGet<{ runs: ResultRun[] }>("/results/runs");
    setRuns(result.runs);
    setSelectedRun(result.runs[0] ?? null);
    setStatus(`Runs: ${result.runs.length}`);
  }

  return (
    <main className="page-panel results-page">
      <section className="panel">
        <div className="panel-title">
          <h2>Results Gallery</h2>
          <span className="status-pill">{status}</span>
        </div>
        <button className="inline-button" onClick={refresh} type="button">
          <RefreshCw size={16} />
          Refresh
        </button>
        <div className="run-list">
          {runs.map((run) => (
            <button key={run.path} onClick={() => setSelectedRun(run)} type="button">
              <span>{run.name}</span>
              <small>{run.task_count} tasks</small>
            </button>
          ))}
        </div>
      </section>
      <section className="panel">
        <div className="panel-title">
          <h2>Run Detail</h2>
        </div>
        <pre className="json-preview">{JSON.stringify(selectedRun ?? {}, null, 2)}</pre>
      </section>
    </main>
  );
}
