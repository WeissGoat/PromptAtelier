import { Eye, Play, Save } from "lucide-react";
import { useMemo, useState } from "react";

import { apiPost } from "../api/client";
import type { ComposePreviewResponse, JobRecord } from "../api/types";
import { NodeEditor } from "../components/NodeEditor";
import { NodePicker } from "../components/NodePicker";
import { PromptPreview } from "../components/PromptPreview";
import { RenderParamsPanel } from "../components/RenderParamsPanel";

export function CustomStudio() {
  const [artist, setArtist] = useState("109841329_03_manga_monochrome_yabuki_rance_no_vibe_latest_stable");
  const [character, setCharacter] = useState("");
  const [action, setAction] = useState("");
  const [prompt, setPrompt] = useState("1girl, standing");
  const [negative, setNegative] = useState("lowres");
  const [nodeDraft, setNodeDraft] = useState("kind: character\nname: draft\nprompt:\n  positive:\n    - 1girl");
  const [width, setWidth] = useState(1024);
  const [height, setHeight] = useState(1024);
  const [nt, setNt] = useState(1);
  const [seed, setSeed] = useState("-1");
  const [preview, setPreview] = useState<ComposePreviewResponse | null>(null);
  const [job, setJob] = useState<JobRecord | null>(null);
  const [status, setStatus] = useState("Ready");

  const renderRequest = preview?.render_request;
  const previewPrompt = preview?.prompt_bundle?.prompt.positive ?? prompt;
  const previewNegative = preview?.prompt_bundle?.prompt.negative ?? negative;

  const requestBody = useMemo(() => {
    const nodes = [
      character ? { role: "character", ref: character } : null,
      action ? { role: "action", ref: action } : null,
      artist ? { role: "artist", ref: artist } : null,
    ].filter(Boolean);
    return {
      compose: {
        prompt,
        negative,
        nodes,
      },
      render: {
        backend: "novelai",
        artist,
        width,
        height,
        seed: Number.isFinite(Number(seed)) ? Number(seed) : undefined,
        params: {
          n_samples: nt,
        },
      },
    };
  }, [action, artist, character, height, negative, nt, prompt, seed, width]);

  async function runPreview() {
    setStatus("Previewing");
    const result = await apiPost<ComposePreviewResponse>("/compose-preview", requestBody);
    setPreview(result);
    setStatus(result.status === "ready" ? "Preview ready" : "Agent required");
  }

  async function generate() {
    const readyPreview = preview?.render_request ? preview : await apiPost<ComposePreviewResponse>("/compose-preview", requestBody);
    if (!readyPreview.render_request) {
      setPreview(readyPreview);
      setStatus("Agent required");
      return;
    }
    setPreview(readyPreview);
    const result = await apiPost<JobRecord>("/generate", {
      render_request: readyPreview.render_request,
    });
    setJob(result);
    setStatus(`Job ${result.id}: ${result.status}`);
  }

  return (
    <main className="studio-grid">
      <section className="panel controls-panel">
        <div className="panel-title">
          <h2>Nodes</h2>
        </div>
        <NodePicker label="Artist" onChange={setArtist} placeholder="artist ref" value={artist} />
        <NodePicker label="Character" onChange={setCharacter} placeholder="character path or ref" value={character} />
        <NodePicker label="Action" onChange={setAction} placeholder="action path or ref" value={action} />
        <label className="field">
          <span>Full Prompt</span>
          <textarea aria-label="Full prompt" onChange={(event) => setPrompt(event.target.value)} value={prompt} />
        </label>
        <label className="field compact">
          <span>Negative</span>
          <textarea aria-label="Negative prompt" onChange={(event) => setNegative(event.target.value)} value={negative} />
        </label>
        <RenderParamsPanel
          height={height}
          nt={nt}
          onHeightChange={setHeight}
          onNtChange={setNt}
          onSeedChange={setSeed}
          onWidthChange={setWidth}
          seed={seed}
          width={width}
        />
      </section>

      <NodeEditor onChange={setNodeDraft} value={nodeDraft} />

      <section className="panel preview-panel">
        <div className="panel-title">
          <h2>Prompt Preview</h2>
          <span className="status-pill">{status}</span>
        </div>
        <PromptPreview negative={previewNegative} prompt={previewPrompt} renderRequest={renderRequest} />
        {job ? <pre className="json-preview compact-json">{JSON.stringify(job, null, 2)}</pre> : null}
        <div className="button-row">
          <button onClick={runPreview} type="button">
            <Eye size={16} />
            Preview
          </button>
          <button onClick={generate} type="button">
            <Play size={16} />
            Generate
          </button>
          <button disabled type="button" title="Node save arrives with structured editing">
            <Save size={16} />
            Save
          </button>
        </div>
      </section>
    </main>
  );
}
