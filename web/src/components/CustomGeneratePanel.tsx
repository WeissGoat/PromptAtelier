import { Eye, Grid2X2, ListOrdered, Play } from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { apiGet, apiPost, errorMessage } from "../api/client";
import type { ComposePreviewResponse, NodePoolCandidate, NodeReadResponse } from "../api/types";
import { compareDimensions } from "../compare/matrix";
import { compareRunCount } from "../compare/runPlan";
import { compareComposeRequest, compareItemLabels, createCompareGroupOutputDir, createCompareOutputDir, planCompareRun } from "../compare/useCompareRunController";
import { hasUsablePositivePrompt, nodeSlotStatus } from "../nodes/temporaryNodes";
import type { NodeRole } from "../nodes/types";
import { listAllPoolNodes } from "../randomNodes/api";
import { hasRandomSlots, hasSequentialSlot, isSequentialSlot, resolveRandomItems } from "../randomNodes/resolve";
import { findPromptBehaviorVariant } from "../workspace/promptBehavior";
import { useCustomWorkspace } from "../workspace/CustomWorkspaceProvider";
import { buildComposeRenderRequest } from "../workspace/requestBuilder";
import { notifyComfyTargetsChanged } from "../comfyui/targetStatus";
import type { NodeVariantSlot, RenderWorkspaceParams } from "../workspace/types";
import {
  backgroundGenerateOptions,
  randomSelectionLabel,
  submitBackgroundBatch,
  type BackgroundBatchRequest,
  type BackgroundRequestItem,
} from "../generation/backgroundRun";
import { GenerationTasksPanel } from "./GenerationTasksPanel";
import { PromptPreview } from "./PromptPreview";
import { ImageDetailDialog, type ImageDetailItem } from "./ImageDetailDialog";

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

type ImageSelection = { items: ImageDetailItem[]; index: number };

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
  const previewRequestSignature = useMemo(() => primaryHasRandom
    ? JSON.stringify({ primary, params, behavior: activeBehavior.value })
    : JSON.stringify(previewRequest), [activeBehavior.value, params, previewRequest, primary, primaryHasRandom]);
  const signatureRef = useRef(previewRequestSignature);
  signatureRef.current = previewRequestSignature;
  const [previewSignature, setPreviewSignature] = useState("");
  const [status, setStatus] = useState("Ready");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [selectedImage, setSelectedImage] = useState<ImageSelection | null>(null);
  const dimensions = compareDimensions(groups, promptBehaviorGroup);
  const matrixTotal = dimensions.artist * dimensions.character * dimensions.action * dimensions.behavior;
  const rounds = positiveInt(params.n);
  const samplesPerRound = positiveInt(params.nt);
  const compareTotal = compareRunCount(matrixTotal, rounds, samplesPerRound);
  const preview = workspace.state.preview;
  const previewCurrent = previewSignature === previewRequestSignature;
  const displayPreview = previewCurrent ? preview : null;

  async function composePreview(
    request: ReturnType<typeof buildComposeRenderRequest>,
    expectedSignature: string,
  ): Promise<ComposePreviewResponse> {
    const result = await apiPost<ComposePreviewResponse>("/compose-preview", request);
    if (signatureRef.current !== expectedSignature) throw new Error("输入已变化，请重新预览。");
    workspace.setPreview(result);
    setPreviewSignature(expectedSignature);
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
      const result = await composePreview(request, previewRequestSignature);
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

  async function generate() {
    const validation = validateSelected(primary);
    if (validation) {
      setError(validation);
      setStatus("Generate blocked");
      return;
    }
    setBusy(true);
    setError("");
    setStatus("正在提交");
    try {
      if (primaryHasSequential) await submitSequential(false);
      else if (primaryHasRandom) await submitRandomPrimary();
      else await submitOrdinaryPrimary();
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
    try {
      await submitSequential(true);
    } catch (requestError) {
      setStatus("Sequential All failed");
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  }

  async function submitBackground(request: BackgroundBatchRequest) {
    const job = await submitBackgroundBatch(request);
    // 刷新运行位置状态：ComfyUI 可能马上要冷启动。
    notifyComfyTargetsChanged({ backend: "comfyui" });
    setStatus(`已提交：${request.label}（${job.id}）`);
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
    setBusy(true);
    setStatus("正在提交");
    try {
      await submitCompare();
    } catch (requestError) {
      setStatus("Compare failed");
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
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
          <Play size={16} /> {primaryHasSequential ? (rounds > 1 ? `Generate Next (${rounds})` : "Generate Next") : (rounds > 1 ? `Generate Primary (${rounds} 轮)` : "Generate Primary")}
        </button>
        {primaryHasSequential ? <button disabled={busy} onClick={() => void generateAllSequential()} type="button"><ListOrdered size={16} /> Run All</button> : null}
        <button disabled={busy} onClick={() => void generateCompare()} title="把 Compare 矩阵整批交给后端" type="button"><Grid2X2 size={16} /> Compare Generate · {compareTotal}</button>
      </div>
      <small className="compare-formula">Artist {dimensions.artist} × Character {dimensions.character} × Action {dimensions.action} × Behavior {dimensions.behavior} × Groups {rounds}{samplesPerRound > 1 ? ` × NT ${samplesPerRound}` : ""} = {compareTotal}</small>

      <GenerationTasksPanel onOpenImage={setSelectedImage} />
      {selectedImage ? <ImageDetailDialog initialIndex={selectedImage.index} items={selectedImage.items} onClose={() => setSelectedImage(null)} /> : null}
    </section>
  );
}
