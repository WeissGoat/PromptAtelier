import { Eye, Play } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { apiGet, apiPost, apiUrl, errorMessage } from "../api/client";
import type { ComposePreviewResponse, GenerationImage, GenerationResult, JobRecord } from "../api/types";
import { NodeRoleGroup } from "../components/NodeRoleGroup";
import { editorHasChanges, NodeWorkspaceEditor } from "../components/NodeWorkspaceEditor";
import { PromptPreview } from "../components/PromptPreview";
import { RenderParamsPanel } from "../components/RenderParamsPanel";
import { hasUsablePositivePrompt, nodeSlotStatus, serializeNodeSlot } from "../nodes/temporaryNodes";
import type { NodeRole, NodeSlotState } from "../nodes/types";
import { useCustomWorkspace } from "../workspace/CustomWorkspaceProvider";

const slotLabels: Record<NodeRole, string> = {
  artist: "Artist",
  character: "Character",
  action: "Action",
};

type PreviewIntent = "preview" | "generate";

type PreviewAttempt = {
  id: number;
  intent: PreviewIntent;
  revision: number;
  signature: string;
};

type PreviewOutcome =
  | { attempt: PreviewAttempt; result: ComposePreviewResponse }
  | { attempt: PreviewAttempt; error: unknown };

const JOB_POLL_INTERVAL_MS = 500;
const terminalJobStatuses = new Set<JobRecord["status"]>(["succeeded", "failed", "cancelled"]);

function isTerminalJob(job: JobRecord): boolean {
  return terminalJobStatuses.has(job.status);
}

function jobProgress(job: JobRecord): string {
  const event = job.events?.[job.events.length - 1];
  return event?.type ?? job.status;
}

function seedForImage(image: GenerationImage, result: GenerationResult | undefined): string | null {
  const imageSeed = image.meta?.seed;
  if (typeof imageSeed === "string" || typeof imageSeed === "number") return String(imageSeed);

  const requestBody = result?.request_body;
  if (!requestBody) return null;
  const candidates: Array<Record<string, unknown>> = [requestBody];
  if (Array.isArray(requestBody.requests)) {
    const splitIndex = image.meta?.split_request_index;
    const request = typeof splitIndex === "number" ? requestBody.requests[splitIndex] : requestBody.requests[0];
    if (request && typeof request === "object") candidates.push(request as Record<string, unknown>);
  }
  for (const request of candidates) {
    const parameters = request.parameters;
    const seed = request.seed ?? (parameters && typeof parameters === "object"
      ? (parameters as Record<string, unknown>).seed
      : undefined);
    if (typeof seed === "string" || typeof seed === "number") return String(seed);
  }
  return null;
}

export function CustomStudio() {
  const workspace = useCustomWorkspace();
  const slots = useMemo(() => ({
    artist: workspace.state.groups.artist.primary,
    character: workspace.state.groups.character.primary,
    action: workspace.state.groups.action.primary,
  }), [workspace.state.groups]);
  const composeNodes = useMemo(() => ([slots.artist, slots.character, slots.action]
    .map((slot) => serializeNodeSlot(slot))
    .filter((slot): slot is NonNullable<typeof slot> => Boolean(slot))), [slots]);
  const nodeRevision = workspace.state.revision;
  const [negative, setNegative] = useState("");
  const [width, setWidth] = useState(1024);
  const [height, setHeight] = useState(1024);
  const [nt, setNt] = useState(1);
  const [seed, setSeed] = useState("-1");
  const [renderRevision, setRenderRevision] = useState(0);
  const [preview, setPreview] = useState<ComposePreviewResponse | null>(null);
  const [previewRevision, setPreviewRevision] = useState<number | null>(null);
  const [job, setJob] = useState<JobRecord | null>(null);
  const [status, setStatus] = useState("Ready");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const previewRequestId = useRef(0);
  const activePreview = useRef<PreviewAttempt | null>(null);
  const jobPollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const jobPollRequestId = useRef(0);
  const jobStartedAt = useRef<number | null>(null);
  const [jobElapsedSeconds, setJobElapsedSeconds] = useState(0);

  const revision = nodeRevision + renderRevision;
  const previewIsCurrent = previewRevision === revision;
  const renderRequest = preview?.render_request;
  const previewPrompt = preview?.prompt_bundle?.prompt.positive ?? "";
  const previewNegative = preview?.prompt_bundle?.prompt.negative ?? negative;
  const artistSlot = slots.artist;
  const artistIsInline = Boolean(artistSlot.draftNode) && nodeSlotStatus(artistSlot) !== "original";

  const requestBody = useMemo(() => {
    const parsedSeed = Number(seed);
    return {
      compose: {
        nodes: composeNodes,
        negative,
      },
      render: {
        backend: "novelai",
        artist: artistIsInline ? undefined : artistSlot.sourceRef ?? undefined,
        width,
        height,
        seed: Number.isFinite(parsedSeed) && parsedSeed >= 0 ? parsedSeed : undefined,
        params: {
          n_samples: nt,
        },
      },
    };
  }, [artistIsInline, artistSlot.sourceRef, composeNodes, height, negative, nt, seed, width]);
  const previewSignature = useMemo(() => JSON.stringify(requestBody), [requestBody]);
  const previewSignatureRef = useRef(previewSignature);
  previewSignatureRef.current = previewSignature;

  function isCurrentPreview(attempt: PreviewAttempt): boolean {
    return previewRequestId.current === attempt.id && previewSignatureRef.current === attempt.signature;
  }

  function stopJobPolling() {
    jobPollRequestId.current += 1;
    if (jobPollTimer.current !== null) {
      clearTimeout(jobPollTimer.current);
      jobPollTimer.current = null;
    }
  }

  function updateJobElapsed(nextJob: JobRecord) {
    const startedAt = nextJob.created_at ? nextJob.created_at * 1000 : jobStartedAt.current;
    if (startedAt !== null) {
      setJobElapsedSeconds(Math.max(0, Math.floor((Date.now() - startedAt) / 1000)));
    }
  }

  function watchJob(initialJob: JobRecord) {
    stopJobPolling();
    const pollRequestId = jobPollRequestId.current;
    jobStartedAt.current = initialJob.created_at ? initialJob.created_at * 1000 : Date.now();
    setJobElapsedSeconds(0);
    setJob(initialJob);
    setStatus(`Job ${initialJob.id}: ${initialJob.status}`);

    const poll = async () => {
      try {
        const nextJob = await apiGet<JobRecord>(`/jobs/${encodeURIComponent(initialJob.id)}`);
        if (jobPollRequestId.current !== pollRequestId) return;
        setJob(nextJob);
        updateJobElapsed(nextJob);
        setStatus(`Job ${nextJob.id}: ${nextJob.status}`);
        if (isTerminalJob(nextJob)) {
          if (nextJob.status === "failed") setError(nextJob.error || "Generation failed");
          stopJobPolling();
          return;
        }
        jobPollTimer.current = setTimeout(() => void poll(), JOB_POLL_INTERVAL_MS);
      } catch (pollError) {
        if (jobPollRequestId.current !== pollRequestId) return;
        setStatus(`Job ${initialJob.id}: polling failed`);
        setError(errorMessage(pollError));
        stopJobPolling();
      }
    };

    if (!isTerminalJob(initialJob)) {
      jobPollTimer.current = setTimeout(() => void poll(), JOB_POLL_INTERVAL_MS);
    }
  }

  useEffect(() => () => stopJobPolling(), []);

  useEffect(() => {
    const active = activePreview.current;
    if (!active || active.signature === previewSignature) return;

    previewRequestId.current += 1;
    activePreview.current = null;
    setBusy(false);
    if (active.intent === "generate") {
      setStatus("Generate blocked");
      setError("输入已变化，请重新生成。");
    } else {
      setStatus("Preview stale");
      setError("");
    }
  }, [previewSignature]);

  function updateRenderParameter<T>(setter: (value: T) => void, value: T) {
    setter(value);
    setRenderRevision((current) => current + 1);
  }

  function openNodeEditor(slotId: string) {
    const editor = workspace.state.editor;
    if (
      editor.slotId
      && editor.slotId !== slotId
      && editorHasChanges(editor.draftNode, editor.baselineNode)
      && !window.confirm("当前节点编辑尚未应用，切换后会丢失这些修改。是否继续？")
    ) return;
    workspace.openEditor(slotId);
  }

  function validationError(): string | null {
    const hasCharacterOrAction = [slots.character, slots.action].some((slot) => slot.draftNode);
    if (!hasCharacterOrAction) {
      return "请至少选择或新建一个 Character 或 Action 节点。";
    }

    const emptyDraft = Object.values(slots).find((slot: NodeSlotState) => (
      slot.draftNode
      && nodeSlotStatus(slot) !== "original"
      && !hasUsablePositivePrompt(slot.draftNode)
    ));
    return emptyDraft ? `${slotLabels[emptyDraft.role]} 节点的临时 prompt 不能为空。` : null;
  }

  async function composePreview(intent: PreviewIntent): Promise<PreviewOutcome | null> {
    const attempt: PreviewAttempt = {
      id: ++previewRequestId.current,
      intent,
      revision,
      signature: previewSignature,
    };
    activePreview.current = attempt;
    try {
      const result = await apiPost<ComposePreviewResponse>("/compose-preview", requestBody);
      if (!isCurrentPreview(attempt)) return null;
      setPreview(result);
      if (result.render_request) {
        setPreviewRevision(attempt.revision);
      }
      return { attempt, result };
    } catch (requestError) {
      if (!isCurrentPreview(attempt)) return null;
      return { attempt, error: requestError };
    } finally {
      if (isCurrentPreview(attempt)) {
        activePreview.current = null;
        if (intent === "preview") setBusy(false);
      }
    }
  }

  async function runPreview() {
    const message = validationError();
    if (message) {
      setError(message);
      setStatus("Preview blocked");
      return;
    }

    setBusy(true);
    setError("");
    setStatus("Previewing");
    const outcome = await composePreview("preview");
    if (!outcome || !isCurrentPreview(outcome.attempt)) return;
    if ("error" in outcome) {
      setStatus("Preview failed");
      setError(errorMessage(outcome.error));
      return;
    }
    setStatus(outcome.result.status === "ready" ? "Preview ready" : "Agent required");
  }

  async function generate() {
    const message = validationError();
    if (message) {
      setError(message);
      setStatus("Generate blocked");
      return;
    }

    setBusy(true);
    setError("");
    setStatus("Generating");
    const generationSignature = previewSignature;
    try {
      let readyPreview = previewIsCurrent && preview?.render_request ? preview : null;
      if (!readyPreview) {
        const outcome = await composePreview("generate");
        if (!outcome || !isCurrentPreview(outcome.attempt)) return;
        if ("error" in outcome) {
          setStatus("Generate failed");
          setError(errorMessage(outcome.error));
          return;
        }
        readyPreview = outcome.result;
      }
      if (!readyPreview.render_request) {
        setStatus("Agent required");
        return;
      }
      const result = await apiPost<JobRecord>("/generate", {
        render_request: readyPreview.render_request,
      });
      watchJob(result);
    } catch (err) {
      if (previewSignatureRef.current !== generationSignature) return;
      setStatus("Generate failed");
      setError(errorMessage(err));
    } finally {
      if (previewSignatureRef.current === generationSignature && !activePreview.current) {
        setBusy(false);
      }
    }
  }

  return (
    <main className="studio-grid">
      <section className="panel controls-panel">
        <div className="panel-title">
          <h2>Nodes</h2>
        </div>
        <NodeRoleGroup onEditSlot={openNodeEditor} role="artist" />
        <NodeRoleGroup onEditSlot={openNodeEditor} role="character" />
        <NodeRoleGroup onEditSlot={openNodeEditor} role="action" />
        <label className="field compact">
          <span>Negative</span>
          <textarea
            aria-label="Negative prompt"
            onChange={(event) => updateRenderParameter(setNegative, event.target.value)}
            value={negative}
          />
        </label>
        <RenderParamsPanel
          height={height}
          nt={nt}
          onHeightChange={(value) => updateRenderParameter(setHeight, value)}
          onNtChange={(value) => updateRenderParameter(setNt, value)}
          onSeedChange={(value) => updateRenderParameter(setSeed, value)}
          onWidthChange={(value) => updateRenderParameter(setWidth, value)}
          seed={seed}
          width={width}
        />
      </section>

      <NodeWorkspaceEditor />

      <section className="panel preview-panel">
        <div className="panel-title">
          <h2>Prompt Preview</h2>
          <span className="status-pill">{status}</span>
        </div>
        {error ? <div className="alert error-alert" role="alert">{error}</div> : null}
        <PromptPreview negative={previewNegative} prompt={previewPrompt} renderRequest={renderRequest} />
        {job ? (
          <section className="job-result" aria-live="polite">
            <div className="job-summary">
              <strong>Job {job.id}</strong>
              <span>Status: {job.status}</span>
              <span>Progress: {jobProgress(job)}</span>
              <span>Elapsed: {jobElapsedSeconds}s</span>
            </div>
            {job.status === "succeeded" && job.result?.images?.length ? (
              <div className="generated-image-grid">
                {job.result.images.map((image, index) => {
                  const seed = seedForImage(image, job.result);
                  return (
                    <figure className="generated-image" key={`${image.path}-${index}`}>
                      <img alt={`Generated image ${index + 1}`} src={apiUrl(`/results/image?path=${encodeURIComponent(image.path)}`)} />
                      <figcaption>
                        <code>{image.path}</code>
                        {seed ? <span>Seed: {seed}</span> : null}
                      </figcaption>
                    </figure>
                  );
                })}
              </div>
            ) : null}
            <details>
              <summary>Raw job details</summary>
              <pre className="json-preview compact-json">{JSON.stringify(job, null, 2)}</pre>
            </details>
          </section>
        ) : null}
        <div className="button-row">
          <button disabled={busy} onClick={() => void runPreview()} type="button">
            <Eye size={16} />
            Preview
          </button>
          <button disabled={busy} onClick={() => void generate()} type="button">
            <Play size={16} />
            Generate
          </button>
        </div>
      </section>

    </main>
  );
}
