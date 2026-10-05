import { Eye, Grid2X2, ListOrdered, Play, RotateCcw } from "lucide-react";
import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { apiGet, apiPost, apiUrl, errorMessage } from "../api/client";
import type { ComposePreviewResponse, GenerationImage, GenerationResult, JobRecord, NodePoolCandidate, NodeReadResponse } from "../api/types";
import { compareDimensions } from "../compare/matrix";
import { compareRunCount } from "../compare/runPlan";
import { compareComposeRequest, compareItemLabels, createCompareGroupOutputDir, createCompareOutputDir, planCompareRun } from "../compare/useCompareRunController";
import { hasUsablePositivePrompt, nodeSlotStatus } from "../nodes/temporaryNodes";
import type { NodeRole } from "../nodes/types";
import { listAllPoolNodes } from "../randomNodes/api";
import { hasRandomSlots, hasSequentialSlot, isSequentialSlot, resolveRandomItems, type RandomSelectionRecord } from "../randomNodes/resolve";
import { findPromptBehaviorVariant } from "../workspace/promptBehavior";
import { useCustomWorkspace } from "../workspace/CustomWorkspaceProvider";
import { buildComposeRenderRequest, buildGeneratePayload } from "../workspace/requestBuilder";
import { describeJobProgress } from "../comfyui/jobProgress";
import { notifyComfyTargetsChanged } from "../comfyui/targetStatus";
import type { NodeVariantSlot, RenderWorkspaceParams } from "../workspace/types";
import {
  backgroundGenerateOptions,
  loadBackgroundPreference,
  randomSelectionLabel,
  saveBackgroundPreference,
  submitBackgroundBatch,
  type BackgroundBatchRequest,
  type BackgroundRequestItem,
} from "../generation/backgroundRun";
import { BackgroundRunsPanel } from "./BackgroundRunsPanel";
import { PromptPreview } from "./PromptPreview";
import { ImageDetailDialog } from "./ImageDetailDialog";

const terminalJobStatuses = new Set<JobRecord["status"]>(["succeeded", "failed", "cancelled"]);
const slotLabels: Record<NodeRole, string> = { artist: "Artist", character: "Character", action: "Action", clothing: "Clothing" };

function randomSeed(): number {
  if (globalThis.crypto?.getRandomValues) return globalThis.crypto.getRandomValues(new Uint32Array(1))[0];
  return Math.floor(Math.random() * 0x1_0000_0000);
}

/** 轮数 / 张数一类的正整数；空值、NaN、小数都收敛成可用值。 */
function positiveInt(value: number | undefined, fallback = 1): number {
  return typeof value === "number" && Number.isFinite(value) ? Math.max(1, Math.trunc(value)) : fallback;
}

/** N 轮 × NT 张的种子规划：显式种子每轮间隔 NT，让各轮的 NT 张不撞种子；随机种子每轮单独抽。 */
function planSeeds(params: RenderWorkspaceParams) {
  const n = positiveInt(params.n);
  const nt = positiveInt(params.nt);
  const parsed = Number(params.seed);
  const explicit = Number.isInteger(parsed) && parsed >= 0;
  return {
    n,
    nt,
    explicit,
    seedAt: (index: number) => explicit ? (parsed + index * nt) % 0x1_0000_0000 : randomSeed(),
  };
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

function validateSelected(slots: Partial<Record<NodeRole, NodeVariantSlot | null>>): string | null {
  const selected = (slot: NodeVariantSlot | null | undefined) => slot?.sourceKind === "random"
    ? Boolean(slot.randomSpec?.source.value.trim())
    : Boolean(slot?.draftNode);
  if (!selected(slots.character) && !selected(slots.action)) return "请至少选择或新建一个 Character 或 Action 节点。";
  for (const role of Object.keys(slots) as NodeRole[]) {
    const slot = slots[role];
    if (!slot) continue;
    if (role === "clothing") {
      if (slot.sourceKind === "random" && !slot.randomSpec?.source.value.trim()) {
        return "Clothing 随机节点尚未配置来源。";
      }
      continue;
    }
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
type OrdinaryJobEntry = {
  job: JobRecord;
  roundIndex: number;
  totalRounds: number;
  seed: number;
};

/** ComfyUI 任务的当前阶段（启动 / 生成 / 下载）；任务轮询时整块重新渲染，已等待的秒数跟着走。 */
function JobProgress({ job }: { job: JobRecord | null | undefined }) {
  const text = job ? describeJobProgress(job, Date.now() / 1000) : null;
  return text ? <small className="job-progress">{text}</small> : null;
}

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

type JobResultCard = {
  key: string;
  title: string;
  job: JobRecord;
  /** 卡片里的 <dt>/<dd> 行；Seed 行由 JobResultSection 统一补在 rows 后面。 */
  rows: Array<[label: string, value: ReactNode]>;
  seed?: string | null;
  imagePrefix: string;
};

/** Primary / Random / Sequential 共用的一批任务结果：标题、完成数、清空按钮和每个任务一张卡片。 */
function JobResultSection({
  title,
  unit,
  cards,
  sequencePaths,
  busy,
  clearTitle,
  onClear,
  onOpenImage,
}: {
  title: string;
  unit: string;
  cards: JobResultCard[];
  sequencePaths: string[];
  busy: boolean;
  clearTitle: string;
  onClear(): void;
  onOpenImage(selection: ImageSelection): void;
}) {
  if (!cards.length) return null;
  return (
    <section className="job-result job-result-section">
      <div className="section-title-row">
        <div>
          <h3>{title}</h3>
          <small>{cards.filter((card) => card.job.status === "succeeded").length} / {cards.length} {unit}完成</small>
        </div>
        <div className="button-row">
          <button disabled={busy} onClick={onClear} title={clearTitle} type="button"><RotateCcw size={15} /></button>
        </div>
      </div>
      <div className="compare-result-grid">
        {cards.map((card) => {
          const seed = card.seed ?? (card.job.result?.images?.[0] ? seedForImage(card.job.result.images[0], card.job.result) : null);
          return (
            <article className={`compare-result-card ${card.job.status}`} key={card.key}>
              <div className="compare-result-header">
                <strong>{card.title}</strong>
                <span>{card.job.status}</span>
              </div>
              {card.job.status === "running" ? <JobProgress job={card.job} /> : null}
              <dl>
                {card.rows.map(([label, value]) => (
                  <Fragment key={label}><dt>{label}</dt><dd>{value}</dd></Fragment>
                ))}
                {seed != null ? <><dt>Seed</dt><dd>{seed}</dd></> : null}
              </dl>
              {card.job.error ? <div className="field-error">{card.job.error}</div> : null}
              <ImageGrid job={card.job} onOpenImage={onOpenImage} prefix={card.imagePrefix} sequencePaths={sequencePaths} />
            </article>
          );
        })}
      </div>
    </section>
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
    clothing: groups.character.primary.clothingSlots?.[0] ?? null,
  }), [groups]);
  const primaryHasRandom = hasRandomSlots(primary);
  const primaryHasSequential = hasSequentialSlot(primary);
  const previewRequest = useMemo(() => primaryHasRandom ? null : buildComposeRenderRequest(primary, params, {
    promptBehavior: activeBehavior.value,
  }), [activeBehavior.value, params, primary, primaryHasRandom]);
  const primaryRequest = useMemo(() => primaryHasRandom ? null : buildComposeRenderRequest(primary, params, {
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
  const [ordinaryJobs, setOrdinaryJobs] = useState<OrdinaryJobEntry[]>([]);
  const job = ordinaryJobs[ordinaryJobs.length - 1]?.job ?? null;
  const [randomJobs, setRandomJobs] = useState<Array<{ job: JobRecord; selections: RandomSelectionRecord[] }>>([]);
  const [sequentialJobs, setSequentialJobs] = useState<Array<{ job: JobRecord; actionName: string; actionIndex: number }>>([]);
  const [status, setStatus] = useState("Ready");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [selectedImage, setSelectedImage] = useState<ImageSelection | null>(null);
  const [background, setBackground] = useState(loadBackgroundPreference);
  const pollToken = useRef(0);
  const dimensions = compareDimensions(groups, promptBehaviorGroup);
  const matrixTotal = dimensions.artist * dimensions.character * dimensions.action * dimensions.behavior;
  const rounds = positiveInt(params.n);
  const samplesPerRound = positiveInt(params.nt);
  const compareTotal = compareRunCount(matrixTotal, rounds, samplesPerRound);
  const compare = workspace.compareRun;
  const ordinaryImagePaths = ordinaryJobs.flatMap((item) => item.job.status === "succeeded"
    ? item.job.result?.images?.map((image) => image.path) ?? []
    : []);
  const randomImagePaths = randomJobs.flatMap((item) => item.job.status === "succeeded"
    ? item.job.result?.images?.map((image) => image.path) ?? []
    : []);
  const sequentialImagePaths = sequentialJobs.flatMap((item) => item.job.status === "succeeded"
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
          { promptBehavior: activeBehavior.value },
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

  async function submitOrdinaryPrimary() {
    const { n: count, seedAt } = planSeeds(params);
    const outputDir = createCompareOutputDir("primary");
    const items: BackgroundRequestItem[] = [];
    for (let index = 0; index < count; index += 1) {
      const seed = seedAt(index);
      const runParams = { ...params, seed: String(seed) };
      items.push({
        label: count > 1 ? `Round ${index + 1} · Seed ${seed}` : `Primary · Seed ${seed}`,
        seed,
        compose_request: buildComposeRenderRequest(primary, runParams, {
          promptBehavior: primaryBehavior.value,
        }),
        generate: backgroundGenerateOptions(params, {
          output_dir: createCompareGroupOutputDir(outputDir, index + 1, seed),
        }),
      });
    }
    await submitBackground({
      label: `Primary · ${count} 轮`,
      kind: "primary",
      output_dir: outputDir,
      items,
    });
  }

  async function generateOrdinaryPrimary() {
    const { n: count, explicit: explicitSeed, seedAt } = planSeeds(params);
    const outputDir = createCompareOutputDir("primary");
    const token = ++pollToken.current;
    setOrdinaryJobs([]);

    for (let roundIndex = 0; roundIndex < count; roundIndex += 1) {
      if (pollToken.current !== token) return;
      // 单轮且种子为 -1：交给后端自己抽。
      const seed = explicitSeed || count > 1 ? seedAt(roundIndex) : -1;
      setStatus(count > 1 ? `Generating Primary (${roundIndex + 1}/${count})` : "Generating Primary");
      const runParams = seed >= 0 ? { ...params, seed: String(seed) } : params;
      const primaryPreviewCurrent = previewSignature === primaryRequestSignature;
      const ready = (roundIndex === 0 && count === 1 && primaryPreviewCurrent && preview?.render_request)
        ? preview
        : await compose(
          buildComposeRenderRequest(primary, runParams, {
            promptBehavior: primaryBehavior.value,
          }),
          primaryRequestSignature,
          "primary",
          roundIndex === 0 && count === 1 && activeBehavior.slotId === primaryBehavior.slotId,
        );
      if (!ready.render_request) throw new Error("该节点组合需要外部 Agent 先完成提示词拼接。");
      const generatePayload = count > 1
        ? buildGeneratePayload(ready.render_request, runParams, {
          output_dir: createCompareGroupOutputDir(outputDir, roundIndex + 1, seed),
        })
        : buildGeneratePayload(ready.render_request, runParams);
      let current = await apiPost<JobRecord>("/generate", generatePayload);
      setOrdinaryJobs((jobs) => [...jobs, { job: current, roundIndex, totalRounds: count, seed }]);
      notifyComfyTargetsChanged(ready.render_request);
      while (!terminalJobStatuses.has(current.status) && pollToken.current === token) {
        await new Promise((resolve) => window.setTimeout(resolve, 500));
        current = await apiGet<JobRecord>(`/jobs/${encodeURIComponent(current.id)}`);
        setOrdinaryJobs((jobs) => jobs.map((item) => item.job.id === current.id ? { ...item, job: current } : item));
      }
      notifyComfyTargetsChanged(ready.render_request);
      // 被新任务 / 清空打断：不是失败，静默退出。
      if (pollToken.current !== token) return;
      if (current.status !== "succeeded") throw new Error(current.error || `Generation ${current.status}`);
    }
    if (pollToken.current === token) {
      setStatus(count > 1 ? `Primary complete · ${count} rounds` : "Job complete");
    }
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
      if (primaryHasSequential) {
        await (background ? submitSequential(false) : generateSequentialStep());
        return;
      }
      if (primaryHasRandom) {
        await (background ? submitRandomPrimary() : generateRandomPrimary());
        return;
      }
      if (background) {
        await submitOrdinaryPrimary();
        return;
      }
      await generateOrdinaryPrimary();
    } catch (requestError) {
      setStatus("Generate failed");
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  }

  async function resolveSequentialAction(
    actionSlot: NodeVariantSlot,
    cursor: number,
  ): Promise<{ resolved: NodeVariantSlot; candidate: NodePoolCandidate; total: number }> {
    const response = await listAllPoolNodes(actionSlot.role, actionSlot.randomSpec!);
    if (!response.items.length) throw new Error("顺序池中没有可用候选节点。");
    const index = cursor % response.items.length;
    const candidate = response.items[index];
    const nodeResponse = await apiGet<NodeReadResponse>(
      `/nodes/read?${new URLSearchParams({ ref: candidate.ref, role: actionSlot.role })}`,
    );
    return {
      resolved: {
        ...actionSlot,
        sourceKind: "fixed",
        randomSpec: null,
        sourceRef: candidate.ref,
        sourceNode: structuredClone(nodeResponse.node),
        draftNode: structuredClone(nodeResponse.node),
      },
      candidate,
      total: response.items.length,
    };
  }

  async function runSingleSequentialGenerate(
    actionSlot: NodeVariantSlot,
    cursor: number,
    token: number,
    outputDir: string,
    seed: number,
  ): Promise<boolean> {
    if (pollToken.current !== token) return false;
    const { resolved, candidate, total } = await resolveSequentialAction(actionSlot, cursor);
    const actionName = candidate.name || candidate.ref;
    setStatus(`Sequential ${cursor + 1}/${total}: ${actionName}`);
    const runParams = { ...params, seed: String(seed) };
    const fixedPrimary = { ...primary, action: resolved };
    const request = buildComposeRenderRequest(fixedPrimary, runParams, {
      promptBehavior: primaryBehavior.value,
    });
    const ready = await apiPost<ComposePreviewResponse>("/compose-preview", request);
    if (!ready.render_request) throw new Error(`Action ${actionName}: 需要外部 Agent 先完成提示词拼接。`);
    let current = await apiPost<JobRecord>("/generate", buildGeneratePayload(ready.render_request, runParams, {
      output_dir: createCompareGroupOutputDir(outputDir, cursor + 1, seed),
    }));
    setSequentialJobs((jobs) => [...jobs, { job: current, actionName, actionIndex: cursor }]);
    notifyComfyTargetsChanged(ready.render_request);
    while (!terminalJobStatuses.has(current.status) && pollToken.current === token) {
      await new Promise((resolve) => window.setTimeout(resolve, 500));
      current = await apiGet<JobRecord>(`/jobs/${encodeURIComponent(current.id)}`);
      setSequentialJobs((jobs) => jobs.map((item) => item.job.id === current.id ? { ...item, job: current } : item));
    }
    notifyComfyTargetsChanged(ready.render_request);
    if (pollToken.current !== token) return false;
    if (current.status !== "succeeded") throw new Error(current.error || `Generation ${current.status}`);
    return true;
  }

  async function generateSequentialStep() {
    const actionSlot = primary.action;
    if (!actionSlot || !isSequentialSlot(actionSlot)) return;
    const { n, seedAt } = planSeeds(params);
    const startCursor = actionSlot.poolCursor ?? 0;
    // 和后台一致：N 步最多走到池末尾，不绕回开头重复出图。
    const total = (await listAllPoolNodes(actionSlot.role, actionSlot.randomSpec!)).items.length;
    if (!total) throw new Error("顺序池中没有可用候选节点。");
    const count = Math.min(n, total - startCursor);
    if (count < 1) throw new Error("顺序池已经跑到末尾，请先重置游标。");
    const outputDir = createCompareOutputDir("sequential");
    const token = ++pollToken.current;
    setSequentialJobs([]);
    for (let step = 0; step < count; step += 1) {
      if (pollToken.current !== token) break;
      const ok = await runSingleSequentialGenerate(actionSlot, startCursor + step, token, outputDir, seedAt(step));
      if (!ok) break;
      workspace.advancePoolCursor(actionSlot.slotId);
    }
    if (pollToken.current === token) {
      setStatus(count > 1 ? `Sequential complete · ${count} steps` : `Sequential step complete · action ${startCursor + 1}`);
    }
  }

  async function generateAllSequential() {
    const actionSlot = primary.action;
    if (!actionSlot || !isSequentialSlot(actionSlot)) return;
    const validation = validateSelected(primary);
    if (validation) {
      setError(validation);
      setStatus("Generate blocked");
      return;
    }
    setBusy(true);
    setError("");
    if (background) {
      try {
        await submitSequential(true);
      } catch (requestError) {
        setStatus("Sequential All failed");
        setError(errorMessage(requestError));
      } finally {
        setBusy(false);
      }
      return;
    }
    const { seedAt } = planSeeds(params);
    const startCursor = actionSlot.poolCursor ?? 0;
    const outputDir = createCompareOutputDir("sequential-all");
    const token = ++pollToken.current;
    setSequentialJobs([]);
    try {
      const listResponse = await listAllPoolNodes(actionSlot.role, actionSlot.randomSpec!);
      const total = listResponse.items.length;
      if (!total) throw new Error("顺序池中没有可用候选节点。");
      for (let cursor = startCursor; cursor < total; cursor += 1) {
        if (pollToken.current !== token) break;
        const ok = await runSingleSequentialGenerate(actionSlot, cursor, token, outputDir, seedAt(cursor - startCursor));
        if (!ok) break;
        workspace.advancePoolCursor(actionSlot.slotId);
      }
      if (pollToken.current === token) setStatus(`Sequential All complete · ${total - startCursor} actions`);
    } catch (requestError) {
      setStatus("Sequential All failed");
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  }

  async function generateRandomPrimary() {
    const { n: count, seedAt } = planSeeds(params);
    const resolved = await resolveRandomItems(Array.from({ length: count }, (_, index) => ({ value: index, slots: primary })));
    const outputDir = createCompareOutputDir("random");
    const token = ++pollToken.current;
    setRandomJobs([]);
    for (let index = 0; index < resolved.length; index += 1) {
      if (pollToken.current !== token) return;
      const seed = seedAt(index);
      setStatus(`Generating random ${index + 1} / ${resolved.length}`);
      const runParams = { ...params, seed: String(seed) };
      const request = buildComposeRenderRequest(resolved[index].slots, runParams, {
        promptBehavior: primaryBehavior.value,
      });
      const ready = await apiPost<ComposePreviewResponse>("/compose-preview", request);
      if (!ready.render_request) throw new Error("该随机节点组合需要外部 Agent 先完成提示词拼接。");
      let current = await apiPost<JobRecord>("/generate", buildGeneratePayload(ready.render_request, runParams, {
        output_dir: createCompareGroupOutputDir(outputDir, index + 1, seed),
        random_selections: resolved[index].randomSelections,
      }));
      setRandomJobs((jobs) => [...jobs, { job: current, selections: resolved[index].randomSelections }]);
      notifyComfyTargetsChanged(ready.render_request);
      while (!terminalJobStatuses.has(current.status) && pollToken.current === token) {
        await new Promise((resolve) => window.setTimeout(resolve, 500));
        current = await apiGet<JobRecord>(`/jobs/${encodeURIComponent(current.id)}`);
        setRandomJobs((jobs) => jobs.map((item) => item.job.id === current.id ? { ...item, job: current } : item));
      }
      notifyComfyTargetsChanged(ready.render_request);
      if (current.status !== "succeeded") throw new Error(current.error || `Generation ${current.status}`);
    }
    setStatus(`Random Primary complete · ${resolved.length}`);
  }

  async function submitBackground(request: BackgroundBatchRequest) {
    const job = await submitBackgroundBatch(request);
    // 刷新运行位置状态：ComfyUI 可能马上要冷启动。
    notifyComfyTargetsChanged({ backend: "comfyui" });
    setOrdinaryJobs([]);
    setRandomJobs([]);
    setSequentialJobs([]);
    setStatus(`已交给后台：${request.label}（${job.id}）`);
  }

  /** 随机组合 × N：先在浏览器里抽好节点，再整批交给后端。 */
  async function submitRandomPrimary() {
    const { n: count, seedAt } = planSeeds(params);
    const resolved = await resolveRandomItems(Array.from({ length: count }, (_, index) => ({ value: index, slots: primary })));
    const outputDir = createCompareOutputDir("random");
    const items: BackgroundRequestItem[] = resolved.map((entry, index) => {
      const seed = seedAt(index);
      const runParams = { ...params, seed: String(seed) };
      return {
        label: randomSelectionLabel(entry.randomSelections) || `随机 ${index + 1}`,
        seed,
        compose_request: buildComposeRenderRequest(entry.slots, runParams, { promptBehavior: primaryBehavior.value }),
        generate: backgroundGenerateOptions(params, {
          output_dir: createCompareGroupOutputDir(outputDir, index + 1, seed),
          random_selections: entry.randomSelections,
        }),
      };
    });
    await submitBackground({ label: `Random · ${items.length} 轮`, kind: "random", output_dir: outputDir, items });
  }

  /** 顺序池：all=false 只交当前这一个动作，all=true 交从当前位置到池末尾的全部动作；交出去就推进游标。 */
  async function submitSequential(all: boolean) {
    const actionSlot = primary.action;
    if (!actionSlot || !isSequentialSlot(actionSlot)) return;
    const startCursor = actionSlot.poolCursor ?? 0;
    const { n, seedAt } = planSeeds(params);
    const pool = await listAllPoolNodes(actionSlot.role, actionSlot.randomSpec!);
    const total = pool.items.length;
    if (!total) throw new Error("顺序池中没有可用候选节点。");
    const count = all
      ? Math.max(0, total - startCursor)
      : Math.min(n, total - startCursor);
    const cursors = Array.from({ length: count }, (_, offset) => startCursor + offset);
    if (!cursors.length) throw new Error("顺序池已经跑到末尾，请先重置游标。");
    const outputDir = createCompareOutputDir(all ? "sequential-all" : "sequential");
    const items: BackgroundRequestItem[] = [];
    for (const [offset, cursor] of cursors.entries()) {
      setStatus(`准备后台任务 ${offset + 1}/${cursors.length}`);
      const { resolved, candidate } = await resolveSequentialAction(actionSlot, cursor);
      const actionName = candidate.name || candidate.ref;
      const seed = seedAt(offset);
      const runParams = { ...params, seed: String(seed) };
      items.push({
        label: `#${(cursor % total) + 1} ${actionName}`,
        seed,
        compose_request: buildComposeRenderRequest({ ...primary, action: resolved }, runParams, {
          promptBehavior: primaryBehavior.value,
        }),
        generate: backgroundGenerateOptions(params, { output_dir: createCompareGroupOutputDir(outputDir, cursor + 1, seed) }),
      });
    }
    const label = all ? `Sequential All · ${cursors.length} 个动作` : `Sequential · ${cursors.length} 个动作`;
    await submitBackground({ label, kind: "sequential", output_dir: outputDir, items });
    for (let step = 0; step < cursors.length; step += 1) workspace.advancePoolCursor(actionSlot.slotId);
  }

  async function submitCompare() {
    const plan = await planCompareRun(groups, params, promptBehaviorGroup, randomSeed);
    const outputDir = createCompareOutputDir();
    const items: BackgroundRequestItem[] = plan.map((item) => {
      const labels = compareItemLabels(item.combination);
      const shown = Object.fromEntries(Object.entries({
        artist: labels.artist,
        character: labels.character,
        clothing: labels.clothing,
        action: labels.action,
        behavior: item.combination.promptBehavior.label,
      }).filter(([, value]) => value && value !== "未选择"));
      return {
        label: Object.values(shown).join(" · "),
        group: item.groupIndex,
        seed: item.groupSeed,
        labels: shown,
        compose_request: compareComposeRequest(item, params).request,
        generate: backgroundGenerateOptions(params, {
          output_dir: createCompareGroupOutputDir(outputDir, item.groupIndex, item.groupSeed),
          random_selections: item.randomSelections,
        }),
      };
    });
    const totalImages = items.length * positiveInt(params.nt);
    await submitBackground({ label: `Compare · ${totalImages} 张`, kind: "compare", output_dir: outputDir, items });
  }

  async function generateCompare() {
    setError("");
    if (background) {
      setBusy(true);
      try {
        await submitCompare();
      } catch (requestError) {
        setStatus("Compare failed");
        setError(errorMessage(requestError));
      } finally {
        setBusy(false);
      }
      return;
    }
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
        <button disabled={busy} onClick={() => void generate()} type="button">
          <Play size={16} /> {primaryHasSequential ? (rounds > 1 ? `Generate Next (${rounds})` : "Generate Next") : (rounds > 1 ? `Generate Primary (${rounds} 轮)` : "Generate Primary")}{background ? "（后台）" : ""}
        </button>
        {primaryHasSequential ? <button disabled={busy} onClick={() => void generateAllSequential()} type="button"><ListOrdered size={16} /> Run All{background ? "（后台）" : ""}</button> : null}
        <label className="toggle-row background-toggle" title="随机、顺序、Primary 和 Compare 整批交给 Web 后端逐张跑，关掉网页也会继续。">
          <input
            checked={background}
            onChange={(event) => {
              setBackground(event.target.checked);
              saveBackgroundPreference(event.target.checked);
            }}
            type="checkbox"
          />
          后台运行
        </label>
      </div>

      <JobResultSection
        busy={busy}
        cards={ordinaryJobs.map((item) => ({
          key: `${item.job.id}-${item.roundIndex}`,
          title: item.totalRounds > 1 ? `Round ${item.roundIndex + 1} / ${item.totalRounds}` : `Job ${item.job.id}`,
          job: item.job,
          rows: item.totalRounds > 1 ? [["Job ID", <code>{item.job.id}</code>]] : [],
          seed: item.seed >= 0 ? String(item.seed) : null,
          imagePrefix: item.totalRounds > 1 ? `Round ${item.roundIndex + 1}` : "Generated",
        }))}
        clearTitle="清空生成结果"
        onClear={() => setOrdinaryJobs([])}
        onOpenImage={setSelectedImage}
        sequencePaths={ordinaryImagePaths}
        title="Primary Results"
        unit="轮"
      />
      <JobResultSection
        busy={busy}
        cards={randomJobs.map((item, index) => ({
          key: `${item.job.id}-${index}`,
          title: `Round ${index + 1} / ${randomJobs.length}`,
          job: item.job,
          rows: [
            ...(item.selections ?? []).map((sel): [string, ReactNode] => [
              slotLabels[sel.role] || sel.role,
              sel.candidate?.name || sel.candidate?.ref,
            ]),
            ["Job ID", <code>{item.job.id}</code>],
          ],
          imagePrefix: `Random ${index + 1}`,
        }))}
        clearTitle="清空随机生成结果"
        onClear={() => setRandomJobs([])}
        onOpenImage={setSelectedImage}
        sequencePaths={randomImagePaths}
        title="Random Primary"
        unit="轮"
      />
      <JobResultSection
        busy={busy}
        cards={sequentialJobs.map((item, index) => ({
          key: `${item.job.id}-${index}`,
          title: `#${item.actionIndex + 1} ${item.actionName}`,
          job: item.job,
          rows: [["Action", item.actionName], ["Job ID", <code>{item.job.id}</code>]],
          imagePrefix: `Sequential ${item.actionIndex + 1}`,
        }))}
        clearTitle="清空顺序生成结果"
        onClear={() => setSequentialJobs([])}
        onOpenImage={setSelectedImage}
        sequencePaths={sequentialImagePaths}
        title="Sequential Actions"
        unit="个动作"
      />

      <BackgroundRunsPanel onOpenImage={setSelectedImage} />

      <section className="compare-generate-section">
        <div className="section-title-row">
          <div>
            <h3>Compare Matrix</h3>
            <small>Artist {dimensions.artist} × Character {dimensions.character} × Action {dimensions.action} × Behavior {dimensions.behavior} × Groups {rounds}{samplesPerRound > 1 ? ` × NT ${samplesPerRound}` : ""} = {compareTotal}</small>
          </div>
          <div className="button-row">
            {compare.results.length ? <button disabled={compare.running} onClick={compare.reset} title="清空 Compare 结果" type="button"><RotateCcw size={15} /></button> : null}
            <button disabled={compare.running || busy} onClick={() => void generateCompare()} type="button"><Grid2X2 size={16} /> Compare Generate · {compareTotal}{background ? "（后台）" : ""}</button>
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
                <strong>Group {group.groupIndex} · Seed {group.seed}{samplesPerRound > 1 ? ` ~ ${group.seed + samplesPerRound - 1}` : ""}</strong>
                <span>成功 {group.succeeded} / {group.total}{group.failed ? ` · 失败 ${group.failed}` : ""}</span>
              </div>
              <div className="compare-result-grid">
                {compare.results.filter((result) => result.groupIndex === group.groupIndex).map((result) => (
                  <article className={`compare-result-card ${result.status}`} key={result.runId}>
                    <div className="compare-result-header"><strong>{result.status}</strong>{result.job ? <span>{result.job.id}</span> : null}</div>
                    {result.status === "running" ? <JobProgress job={result.job} /> : null}
                    <dl>
                      <dt>Artist</dt><dd>{result.labels.artist}</dd>
                      <dt>Character</dt><dd>{result.labels.character}</dd>
                      {result.labels.clothing && result.labels.clothing !== "未选择" ? (
                        <>
                          <dt>Clothing</dt>
                          <dd>{result.labels.clothing}</dd>
                        </>
                      ) : null}
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
