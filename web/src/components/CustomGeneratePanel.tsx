import { Eye, Grid2X2, Play, RotateCcw } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { apiGet, apiPost, apiUrl, errorMessage } from "../api/client";
import type { ComposePreviewResponse, GenerationImage, GenerationResult, JobRecord } from "../api/types";
import { compareDimensions } from "../compare/matrix";
import { hasUsablePositivePrompt, nodeSlotStatus } from "../nodes/temporaryNodes";
import type { NodeRole } from "../nodes/types";
import { useCustomWorkspace } from "../workspace/CustomWorkspaceProvider";
import { buildComposeRenderRequest } from "../workspace/requestBuilder";
import type { NodeVariantSlot } from "../workspace/types";
import { PromptPreview } from "./PromptPreview";

const terminalJobStatuses = new Set<JobRecord["status"]>(["succeeded", "failed", "cancelled"]);
const slotLabels: Record<NodeRole, string> = { artist: "Artist", character: "Character", action: "Action" };

function seedForImage(image: GenerationImage, result: GenerationResult | undefined): string | null {
  const imageSeed = image.meta?.seed;
  if (typeof imageSeed === "string" || typeof imageSeed === "number") return String(imageSeed);
  const requestBody = result?.request_body;
  if (!requestBody) return null;
  const requests = Array.isArray(requestBody.requests) ? requestBody.requests : [requestBody];
  for (const request of requests) {
    if (!request || typeof request !== "object") continue;
    const record = request as Record<string, unknown>;
    const parameters = record.parameters;
    const seed = record.seed ?? (parameters && typeof parameters === "object" ? (parameters as Record<string, unknown>).seed : undefined);
    if (typeof seed === "string" || typeof seed === "number") return String(seed);
  }
  return null;
}

function validateSelected(slots: Record<NodeRole, NodeVariantSlot>): string | null {
  if (!slots.character.draftNode && !slots.action.draftNode) return "请至少选择或新建一个 Character 或 Action 节点。";
  for (const role of Object.keys(slots) as NodeRole[]) {
    const slot = slots[role];
    if (slot.draftNode && nodeSlotStatus(slot) !== "original" && !hasUsablePositivePrompt(slot.draftNode)) {
      return `${slotLabels[role]} 临时节点的正向 prompt 不能为空。`;
    }
  }
  return null;
}

function ImageGrid({ job, prefix = "Generated" }: { job: JobRecord; prefix?: string }) {
  if (job.status !== "succeeded" || !job.result?.images?.length) return null;
  return (
    <div className="generated-image-grid">
      {job.result.images.map((image, index) => {
        const seed = seedForImage(image, job.result);
        return (
          <figure className="generated-image" key={`${image.path}-${index}`}>
            <img alt={`${prefix} image ${index + 1}`} src={apiUrl(`/results/image?path=${encodeURIComponent(image.path)}`)} />
            <figcaption>{seed ? <span>Seed: {seed}</span> : null}<code>{image.path}</code></figcaption>
          </figure>
        );
      })}
    </div>
  );
}

export function CustomGeneratePanel() {
  const workspace = useCustomWorkspace();
  const groups = workspace.state.groups;
  const params = workspace.state.params;
  const primary = useMemo(() => ({
    artist: groups.artist.primary,
    character: groups.character.primary,
    action: groups.action.primary,
  }), [groups]);
  const request = useMemo(() => buildComposeRenderRequest(primary, params, { compare: false }), [params, primary]);
  const signature = useMemo(() => JSON.stringify(request), [request]);
  const signatureRef = useRef(signature);
  signatureRef.current = signature;
  const [previewSignature, setPreviewSignature] = useState("");
  const [job, setJob] = useState<JobRecord | null>(null);
  const [status, setStatus] = useState("Ready");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const pollToken = useRef(0);
  const dimensions = compareDimensions(groups);
  const compareTotal = dimensions.artist * dimensions.character * dimensions.action;
  const compare = workspace.compareRun;
  const preview = workspace.state.preview;
  const previewCurrent = previewSignature === signature;
  const displayPreview = previewCurrent ? preview : null;

  useEffect(() => () => { pollToken.current += 1; }, []);

  async function compose(): Promise<ComposePreviewResponse> {
    const result = await apiPost<ComposePreviewResponse>("/compose-preview", request);
    if (signatureRef.current !== signature) throw new Error("输入已变化，请重新预览。");
    workspace.setPreview(result);
    setPreviewSignature(signature);
    return result;
  }

  async function runPreview() {
    const validation = validateSelected(primary);
    if (validation) {
      setError(validation);
      setStatus("Preview blocked");
      return;
    }
    setBusy(true);
    setError("");
    setStatus("Previewing");
    try {
      const result = await compose();
      setStatus(result.render_request ? "Preview ready" : "Agent required");
    } catch (requestError) {
      setStatus("Preview failed");
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  }

  async function pollJob(initial: JobRecord) {
    const token = ++pollToken.current;
    let current = initial;
    setJob(current);
    while (!terminalJobStatuses.has(current.status) && pollToken.current === token) {
      await new Promise((resolve) => window.setTimeout(resolve, 500));
      current = await apiGet<JobRecord>(`/jobs/${encodeURIComponent(initial.id)}`);
      if (pollToken.current === token) setJob(current);
    }
    if (pollToken.current !== token) return;
    setStatus(`Job ${current.id}: ${current.status}`);
    if (current.status !== "succeeded") setError(current.error || `Generation ${current.status}`);
  }

  async function generate() {
    const validation = validateSelected(primary);
    if (validation) {
      setError(validation);
      setStatus("Generate blocked");
      return;
    }
    setBusy(true);
    setError("");
    setStatus("Generating");
    try {
      const ready = previewCurrent && preview?.render_request ? preview : await compose();
      if (!ready.render_request) throw new Error("该节点组合需要外部 Agent 先完成提示词拼接。");
      const queued = await apiPost<JobRecord>("/generate", { render_request: ready.render_request });
      await pollJob(queued);
    } catch (requestError) {
      setStatus("Generate failed");
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  }

  async function generateCompare() {
    setError("");
    try {
      await compare.start(groups, params);
    } catch (requestError) {
      setError(errorMessage(requestError));
    }
  }

  return (
    <section className="panel generation-panel">
      <div className="panel-title">
        <h2>Prompt & Generate</h2>
        <span className="status-pill">{status}</span>
      </div>
      {error ? <div className="alert error-alert" role="alert">{error}</div> : null}
      <PromptPreview
        negative={displayPreview?.prompt_bundle?.prompt.negative ?? params.negative}
        prompt={displayPreview?.prompt_bundle?.prompt.positive ?? ""}
        renderRequest={displayPreview?.render_request}
      />
      <div className="button-row ordinary-generate-actions">
        <button disabled={busy} onClick={() => void runPreview()} type="button"><Eye size={16} /> Preview</button>
        <button disabled={busy} onClick={() => void generate()} type="button"><Play size={16} /> Generate</button>
      </div>
      {job ? <section className="job-result"><strong>Job {job.id}</strong><span>Status: {job.status}</span><ImageGrid job={job} /></section> : null}

      <section className="compare-generate-section">
        <div className="section-title-row">
          <div>
            <h3>Compare Matrix</h3>
            <small>Artist {dimensions.artist} × Character {dimensions.character} × Action {dimensions.action} = {compareTotal}</small>
          </div>
          <div className="button-row">
            {compare.results.length ? <button disabled={compare.running} onClick={compare.reset} title="清空 Compare 结果" type="button"><RotateCcw size={15} /></button> : null}
            <button disabled={compare.running || busy} onClick={() => void generateCompare()} type="button"><Grid2X2 size={16} /> Compare Generate · {compareTotal}</button>
          </div>
        </div>
        {compare.results.length ? (
          <div className="compare-progress" aria-live="polite">
            <span>排队 {compare.summary.queued}</span><span>运行 {compare.summary.running}</span><span>成功 {compare.summary.succeeded}</span><span>失败 {compare.summary.failed}</span>
          </div>
        ) : null}
        <div className="compare-result-grid">
          {compare.results.map((result) => (
            <article className={`compare-result-card ${result.status}`} key={result.combination.combinationId}>
              <div className="compare-result-header"><strong>{result.status}</strong>{result.job ? <span>{result.job.id}</span> : null}</div>
              <dl>
                <dt>Artist</dt><dd>{result.labels.artist}</dd>
                <dt>Character</dt><dd>{result.labels.character}</dd>
                <dt>Action</dt><dd>{result.labels.action}</dd>
              </dl>
              {result.error ? <div className="field-error">{result.error}</div> : null}
              {result.job ? <ImageGrid job={result.job} prefix="Compare" /> : null}
            </article>
          ))}
        </div>
      </section>
    </section>
  );
}
