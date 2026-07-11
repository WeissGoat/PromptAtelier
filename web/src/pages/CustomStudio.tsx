import { Eye, Play } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { apiPost, errorMessage } from "../api/client";
import type { ComposePreviewResponse, JobRecord } from "../api/types";
import { NodeEditorDrawer } from "../components/NodeEditorDrawer";
import { NodeSlot } from "../components/NodeSlot";
import { PromptPreview } from "../components/PromptPreview";
import { RenderParamsPanel } from "../components/RenderParamsPanel";
import { hasUsablePositivePrompt, nodeSlotStatus } from "../nodes/temporaryNodes";
import type { NodeRole, NodeSlotState } from "../nodes/types";
import { useTemporaryNodes } from "../nodes/useTemporaryNodes";

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

export function CustomStudio() {
  const {
    slots,
    selectNode,
    createBlank,
    updateDraft,
    restore,
    clear,
    composeNodes,
    revision: nodeRevision,
  } = useTemporaryNodes();
  const [negative, setNegative] = useState("lowres");
  const [width, setWidth] = useState(1024);
  const [height, setHeight] = useState(1024);
  const [nt, setNt] = useState(1);
  const [seed, setSeed] = useState("-1");
  const [renderRevision, setRenderRevision] = useState(0);
  const [preview, setPreview] = useState<ComposePreviewResponse | null>(null);
  const [previewRevision, setPreviewRevision] = useState<number | null>(null);
  const [job, setJob] = useState<JobRecord | null>(null);
  const [editingRole, setEditingRole] = useState<NodeRole | null>(null);
  const [status, setStatus] = useState("Ready");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const previewRequestId = useRef(0);
  const activePreview = useRef<PreviewAttempt | null>(null);

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
      setJob(result);
      setStatus(`Job ${result.id}: ${result.status}`);
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
        <NodeSlot
          clear={clear}
          createBlank={createBlank}
          label="Artist"
          onEdit={(slot) => setEditingRole(slot.role)}
          placeholder="artist ref"
          restore={restore}
          role="artist"
          selectNode={selectNode}
          slot={slots.artist}
        />
        <NodeSlot
          clear={clear}
          createBlank={createBlank}
          label="Character"
          minSearchLength={2}
          onEdit={(slot) => setEditingRole(slot.role)}
          placeholder="type 2+ chars to search"
          restore={restore}
          role="character"
          selectNode={selectNode}
          slot={slots.character}
        />
        <NodeSlot
          clear={clear}
          createBlank={createBlank}
          label="Action"
          minSearchLength={2}
          onEdit={(slot) => setEditingRole(slot.role)}
          placeholder="type 2+ chars to search"
          restore={restore}
          role="action"
          selectNode={selectNode}
          slot={slots.action}
        />
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

      <section className="panel preview-panel">
        <div className="panel-title">
          <h2>Prompt Preview</h2>
          <span className="status-pill">{status}</span>
        </div>
        {error ? <div className="alert error-alert" role="alert">{error}</div> : null}
        <PromptPreview negative={previewNegative} prompt={previewPrompt} renderRequest={renderRequest} />
        {job ? <pre className="json-preview compact-json">{JSON.stringify(job, null, 2)}</pre> : null}
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

      <NodeEditorDrawer
        onApply={updateDraft}
        onClose={() => setEditingRole(null)}
        onRestore={restore}
        onSaved={selectNode}
        open={editingRole !== null}
        slot={editingRole ? slots[editingRole] : null}
      />
    </main>
  );
}
