import { Eye, Grid2X2, Play, RotateCcw } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { apiGet, apiPost, apiUrl, errorMessage } from "../api/client";
import type { ComposePreviewResponse, GenerationImage, GenerationResult, JobRecord } from "../api/types";
import { compareDimensions } from "../compare/matrix";
import { compareRunCount } from "../compare/runPlan";
import { createCompareGroupOutputDir, createCompareOutputDir } from "../compare/useCompareRunController";
import { hasUsablePositivePrompt, nodeSlotStatus } from "../nodes/temporaryNodes";
import type { NodeRole } from "../nodes/types";
import { hasRandomSlots, resolveRandomItems, type RandomSelectionRecord } from "../randomNodes/resolve";
import { findPromptBehaviorVariant } from "../workspace/promptBehavior";
import { useCustomWorkspace } from "../workspace/CustomWorkspaceProvider";
import { buildComposeRenderRequest } from "../workspace/requestBuilder";
import type { NodeVariantSlot } from "../workspace/types";
import { PromptPreview } from "./PromptPreview";
import { ImageDetailDialog } from "./ImageDetailDialog";

const terminalJobStatuses = new Set<JobRecord["status"]>(["succeeded", "failed", "cancelled"]);
const slotLabels: Record<NodeRole, string> = { artist: "Artist", character: "Character", action: "Action" };

function randomSeed(): number {
  if (globalThis.crypto?.getRandomValues) return globalThis.crypto.getRandomValues(new Uint32Array(1))[0];
  return Math.floor(Math.random() * 0x1_0000_0000);
}

function novelaiArtistPayload(slot: NodeVariantSlot): Record<string, unknown> | null {
  const renderers = slot.draftNode?.renderers;
  if (!renderers || typeof renderers !== "object" || Array.isArray(renderers)) return null;
  const payload = (renderers as Record<string, unknown>).novelai;
  return payload && typeof payload === "object" && !Array.isArray(payload)
    ? payload as Record<string, unknown>
    : null;
}

function hasTextList(value: unknown): boolean {
  return Array.isArray(value) && value.some((item) => typeof item === "string" && item.trim());
}

function isLegacyTagsArtist(slot: NodeVariantSlot): boolean {
  const legacy = slot.draftNode?.legacy;
  if (!legacy || typeof legacy !== "object" || Array.isArray(legacy)) return false;
  const sourceFile = (legacy as Record<string, unknown>).source_file;
  return typeof sourceFile === "string" && sourceFile.toLowerCase().endsWith("tags.txt");
}

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
  const selected = (slot: NodeVariantSlot) => slot.sourceKind === "random"
    ? Boolean(slot.randomSpec?.source.value.trim())
    : Boolean(slot.draftNode);
  if (!selected(slots.character) && !selected(slots.action)) return "请至少选择或新建一个 Character 或 Action 节点。";
  for (const role of Object.keys(slots) as NodeRole[]) {
    const slot = slots[role];
    if (slot.sourceKind === "random") {
      if (!slot.randomSpec?.source.value.trim()) return `${slotLabels[role]} 随机节点尚未配置来源。`;
      continue;
    }
    const status = nodeSlotStatus(slot);
    if (role === "artist" && slot.draftNode && status !== "original") {
      const artistPayload = novelaiArtistPayload(slot);
      if (slot.sourceRef && isLegacyTagsArtist(slot) && !artistPayload) {
        return "Artist 节点来自旧版浏览器缓存，请重新选择该 Artist 后再生成。";
      }
      if (artistPayload) {
        const hasRendererPrompt = hasTextList(artistPayload.prompt_prefix) || hasTextList(artistPayload.prompt_suffix);
        if (!hasRendererPrompt && !hasUsablePositivePrompt(slot.draftNode)) {
          return "Artist 临时节点的画风提示词不能为空。";
        }
        continue;
      }
    }
    if (slot.draftNode && status !== "original" && !hasUsablePositivePrompt(slot.draftNode)) {
      return `${slotLabels[role]} 临时节点的正向 prompt 不能为空。`;
    }
  }
  return null;
}

type ImageSelection = { paths: string[]; index: number };

function ImageGrid({
  job,
  prefix = "Generated",
  sequencePaths,
  onOpenImage,
}: {
  job: JobRecord;
  prefix?: string;
  sequencePaths?: string[];
  onOpenImage(selection: ImageSelection): void;
}) {
  if (job.status !== "succeeded" || !job.result?.images?.length) return null;
  const localPaths = job.result.images.map((image) => image.path);
  const paths = sequencePaths?.length ? sequencePaths : localPaths;
  return (
    <div className="generated-image-grid">
      {job.result.images.map((image, index) => {
        const seed = seedForImage(image, job.result);
        return (
          <figure className="generated-image" key={`${image.path}-${index}`}>
            <button aria-label={`打开 ${prefix} image ${index + 1} 大图`} className="image-preview-button" onClick={() => onOpenImage({ paths, index: Math.max(0, paths.indexOf(image.path)) })} type="button">
              <img alt={`${prefix} image ${index + 1}`} src={apiUrl(`/results/image?path=${encodeURIComponent(image.path)}`)} />
            </button>
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
  const promptBehaviorGroup = workspace.state.promptBehaviorGroup;
  const primaryBehavior = promptBehaviorGroup.primary;
  const activeBehavior = findPromptBehaviorVariant(
    promptBehaviorGroup,
    workspace.state.activePromptBehaviorSlotId,
  ) ?? primaryBehavior;
  const primary = useMemo(() => ({
    artist: groups.artist.primary,
    character: groups.character.primary,
    action: groups.action.primary,
  }), [groups]);
  const primaryHasRandom = hasRandomSlots(primary);
  const previewRequest = useMemo(() => primaryHasRandom ? null : buildComposeRenderRequest(primary, params, {
    compare: false,
    promptBehavior: activeBehavior.value,
  }), [activeBehavior.value, params, primary, primaryHasRandom]);
  const primaryRequest = useMemo(() => primaryHasRandom ? null : buildComposeRenderRequest(primary, params, {
    compare: false,
    promptBehavior: primaryBehavior.value,
  }), [params, primary, primaryBehavior.value, primaryHasRandom]);
  const previewRequestSignature = useMemo(() => primaryHasRandom
    ? JSON.stringify({ primary, params, behavior: activeBehavior.value })
    : JSON.stringify(previewRequest), [activeBehavior.value, params, previewRequest, primary, primaryHasRandom]);
  const primaryRequestSignature = useMemo(() => primaryHasRandom
    ? JSON.stringify({ primary, params, behavior: primaryBehavior.value })
    : JSON.stringify(primaryRequest), [params, primary, primaryBehavior.value, primaryHasRandom, primaryRequest]);
  const signatureRef = useRef({ preview: previewRequestSignature, primary: primaryRequestSignature });
  signatureRef.current = { preview: previewRequestSignature, primary: primaryRequestSignature };
  const [previewSignature, setPreviewSignature] = useState("");
  const [job, setJob] = useState<JobRecord | null>(null);
  const [randomJobs, setRandomJobs] = useState<Array<{ job: JobRecord; selections: RandomSelectionRecord[] }>>([]);
  const [status, setStatus] = useState("Ready");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [selectedImage, setSelectedImage] = useState<ImageSelection | null>(null);
  const pollToken = useRef(0);
  const dimensions = compareDimensions(groups, promptBehaviorGroup);
  const matrixTotal = dimensions.artist * dimensions.character * dimensions.action * dimensions.behavior;
  const compareTotal = compareRunCount(matrixTotal, params.nt);
  const compare = workspace.compareRun;
  const ordinaryImagePaths = job?.status === "succeeded"
    ? job.result?.images?.map((image) => image.path) ?? []
    : [];
  const randomImagePaths = randomJobs.flatMap((item) => item.job.status === "succeeded"
    ? item.job.result?.images?.map((image) => image.path) ?? []
    : []);
  const compareImagePaths = compare.results.flatMap((result) => result.job?.status === "succeeded"
    ? result.job.result?.images?.map((image) => image.path) ?? []
    : []);
  const preview = workspace.state.preview;
  const previewCurrent = previewSignature === previewRequestSignature;
  const displayPreview = previewCurrent ? preview : null;

  useEffect(() => () => { pollToken.current += 1; }, []);

  async function compose(
    request: ReturnType<typeof buildComposeRenderRequest>,
    expectedSignature: string,
    signatureKind: "preview" | "primary",
    persistPreview: boolean,
  ): Promise<ComposePreviewResponse> {
    const result = await apiPost<ComposePreviewResponse>("/compose-preview", request);
    if (signatureRef.current[signatureKind] !== expectedSignature) throw new Error("输入已变化，请重新预览。");
    if (persistPreview) {
      workspace.setPreview(result);
      setPreviewSignature(expectedSignature);
    }
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
    setStatus(`Previewing ${activeBehavior.label}`);
    try {
      const request = primaryHasRandom
        ? buildComposeRenderRequest(
          (await resolveRandomItems([{ value: null, slots: primary }]))[0].slots,
          params,
          { compare: true, promptBehavior: activeBehavior.value },
        )
        : previewRequest!;
      const result = await compose(request, previewRequestSignature, "preview", true);
      setStatus(result.render_request ? `Preview ready: ${activeBehavior.label}` : "Agent required");
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
    setStatus("Generating Primary");
    try {
      if (primaryHasRandom) {
        await generateRandomPrimary();
        return;
      }
      const primaryPreviewCurrent = previewSignature === primaryRequestSignature;
      const ready = primaryPreviewCurrent && preview?.render_request
        ? preview
        : await compose(
          primaryRequest!,
          primaryRequestSignature,
          "primary",
          activeBehavior.slotId === primaryBehavior.slotId,
        );
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

  async function generateRandomPrimary() {
    const count = Math.max(1, Math.trunc(params.nt));
    const resolved = await resolveRandomItems(Array.from({ length: count }, (_, index) => ({ value: index, slots: primary })));
    const parsedSeed = Number(params.seed);
    const explicitSeed = Number.isInteger(parsedSeed) && parsedSeed >= 0;
    const outputDir = createCompareOutputDir().replace("compare_", "random_");
    const token = ++pollToken.current;
    setJob(null);
    setRandomJobs([]);
    for (let index = 0; index < resolved.length; index += 1) {
      if (pollToken.current !== token) return;
      const seed = explicitSeed ? parsedSeed + index : randomSeed();
      setStatus(`Generating random ${index + 1} / ${resolved.length}`);
      const runParams = { ...params, nt: 1, seed: String(seed) };
      const request = buildComposeRenderRequest(resolved[index].slots, runParams, {
        compare: true,
        promptBehavior: primaryBehavior.value,
      });
      const ready = await apiPost<ComposePreviewResponse>("/compose-preview", request);
      if (!ready.render_request) throw new Error("该随机节点组合需要外部 Agent 先完成提示词拼接。");
      let current = await apiPost<JobRecord>("/generate", {
        render_request: ready.render_request,
        output_dir: createCompareGroupOutputDir(outputDir, index + 1, seed),
        random_selections: resolved[index].randomSelections,
      });
      setRandomJobs((jobs) => [...jobs, { job: current, selections: resolved[index].randomSelections }]);
      while (!terminalJobStatuses.has(current.status) && pollToken.current === token) {
        await new Promise((resolve) => window.setTimeout(resolve, 500));
        current = await apiGet<JobRecord>(`/jobs/${encodeURIComponent(current.id)}`);
        setRandomJobs((jobs) => jobs.map((item) => item.job.id === current.id ? { ...item, job: current } : item));
      }
      if (current.status !== "succeeded") throw new Error(current.error || `Generation ${current.status}`);
    }
    setStatus(`Random Primary complete · ${resolved.length}`);
  }

  async function generateCompare() {
    setError("");
    try {
      await compare.start(groups, params, promptBehaviorGroup);
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
        promptBundle={displayPreview?.prompt_bundle}
        renderRequest={displayPreview?.render_request}
      />
      <div className="button-row ordinary-generate-actions">
        <button disabled={busy} onClick={() => void runPreview()} type="button"><Eye size={16} /> Preview</button>
        <button disabled={busy} onClick={() => void generate()} type="button"><Play size={16} /> Generate Primary</button>
      </div>
      {job ? <section className="job-result"><strong>Job {job.id}</strong><span>Status: {job.status}</span><ImageGrid job={job} onOpenImage={setSelectedImage} sequencePaths={ordinaryImagePaths} /></section> : null}
      {randomJobs.length ? <section className="job-result"><strong>Random Primary</strong><span>{randomJobs.filter((item) => item.job.status === "succeeded").length} / {randomJobs.length}</span>{randomJobs.map((item) => <ImageGrid job={item.job} key={item.job.id} onOpenImage={setSelectedImage} prefix="Random" sequencePaths={randomImagePaths} />)}</section> : null}

      <section className="compare-generate-section">
        <div className="section-title-row">
          <div>
            <h3>Compare Matrix</h3>
            <small>Artist {dimensions.artist} × Character {dimensions.character} × Action {dimensions.action} × Behavior {dimensions.behavior} × Groups {params.nt} = {compareTotal}</small>
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
        <div className="compare-groups">
          {compare.groupSummaries.map((group) => (
            <section className="compare-group" key={group.groupIndex}>
              <div className="compare-group-title">
                <strong>Group {group.groupIndex} · Seed {group.seed}</strong>
                <span>成功 {group.succeeded} / {group.total}{group.failed ? ` · 失败 ${group.failed}` : ""}</span>
              </div>
              <div className="compare-result-grid">
                {compare.results.filter((result) => result.groupIndex === group.groupIndex).map((result) => (
                  <article className={`compare-result-card ${result.status}`} key={result.runId}>
                    <div className="compare-result-header"><strong>{result.status}</strong>{result.job ? <span>{result.job.id}</span> : null}</div>
                    <dl>
                      <dt>Artist</dt><dd>{result.labels.artist}</dd>
                      <dt>Character</dt><dd>{result.labels.character}</dd>
                      <dt>Action</dt><dd>{result.labels.action}</dd>
                      <dt>Behavior</dt><dd>{result.behavior.label}</dd>
                    </dl>
                    {result.error ? <div className="field-error">{result.error}</div> : null}
                    {result.job ? <ImageGrid job={result.job} onOpenImage={setSelectedImage} prefix="Compare" sequencePaths={compareImagePaths} /> : null}
                  </article>
                ))}
              </div>
            </section>
          ))}
        </div>
      </section>
      {selectedImage ? <ImageDetailDialog initialIndex={selectedImage.index} onClose={() => setSelectedImage(null)} paths={selectedImage.paths} /> : null}
    </section>
  );
}
