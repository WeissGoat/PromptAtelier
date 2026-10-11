import { FlaskConical, ImagePlus } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { apiGet, errorMessage } from "../api/client";
import type {
  Analysis,
  ImageRecord,
  LLMStatus,
  Recipe,
  RecipeSummary,
  RegenSettings,
  StyleLabRun,
  TranslateProvider,
  WorkspaceInfo,
  WorkspacePayload,
} from "./api";
import {
  ACTIVE_RUN_STATUSES,
  analyzeWorkspace,
  cancelJob,
  createImageGroup,
  createRecipe,
  getAnalysis,
  getLLMStatus,
  getWorkspace,
  listRecipes,
  listRuns,
  listWorkspaces,
  openFolder,
  removeImages,
  rescanWorkspace,
  restoreImages,
  startRegenerate,
  uploadImages,
} from "./api";
import { CommonalityPanel } from "./CommonalityPanel";
import { GroupPanel, groupImageIds, groupOfImage } from "./GroupPanel";
import { emptyFilters, filterImages, FilterPanel, ImageGrid, type ImageFilters } from "./ImageBrowser";
import { ImageInspector } from "./ImageInspector";
import { ImageViewerProvider } from "./ImageViewer";
import { RecipeWorkspace } from "./RecipeWorkspace";
import { DuplicateNotice, duplicateOf, type DuplicateRequest } from "./DuplicateNotice";
import { defaultRegenSettings, RegenPanel } from "./RegenPanel";
import { RunPanel } from "./RunPanel";
import { translationStore } from "./translations";
import { WorkspaceBar } from "./WorkspaceBar";
import "./styleLab.css";
import "./styleLabRecipe.css";
import "./styleLabExport.css";
import "./styleLabProbe.css";
import "./styleLabMaterials.css";
import "./styleLabViewer.css";

const STORAGE = {
  workspace: "promptatelier.style-lab.workspace/v1",
  selection: "promptatelier.style-lab.selection/v1",
  translate: "promptatelier.style-lab.translate/v1",
  regen: "promptatelier.style-lab.regen/v1",
  recipe: "promptatelier.style-lab.open-recipe/v1",
  provider: "promptatelier.style-lab.translate-provider/v1",
};
const IMAGE_FILE_RE = /\.(png|webp|jpe?g)$/i;
const ANALYSIS_REFRESH_TICKS = 3;
const RUN_POLL_MS = 1500;
const JOB_POLL_MS = 2000;

function load<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    return raw === null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

function save(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // 只在当前页面记住。
  }
}

type JobSnapshot = { status: string; events?: Array<{ type: string; done?: number; total?: number }> };

export function StyleLabPage() {
  const [workspaces, setWorkspaces] = useState<WorkspaceInfo[]>([]);
  const [payload, setPayload] = useState<WorkspacePayload | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [filters, setFilters] = useState<ImageFilters>(emptyFilters);
  const [selection, setSelection] = useState<Record<string, string>>(() => load(STORAGE.selection, {}));
  const [translateOn, setTranslateOn] = useState<boolean>(() => load(STORAGE.translate, true));
  const [translateProvider, setTranslateProvider] = useState<TranslateProvider>(() => {
    const provider = load<TranslateProvider>(STORAGE.provider, "google");
    translationStore.setProvider(provider);
    return provider;
  });
  const [llm, setLlm] = useState<LLMStatus | null>(null);
  const [regenSettings, setRegenSettings] = useState<RegenSettings>(() => ({
    ...defaultRegenSettings,
    ...load<Partial<RegenSettings>>(STORAGE.regen, {}),
  }));
  const [runs, setRuns] = useState<StyleLabRun[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [regenError, setRegenError] = useState<string | null>(null);
  const [regenDuplicate, setRegenDuplicate] = useState<DuplicateRequest | null>(null);
  const [analyzing, setAnalyzing] = useState<{ jobId: string; done: number; total: number } | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [recipes, setRecipes] = useState<RecipeSummary[]>([]);
  const [selectedGroup, setSelectedGroup] = useState<string | null>(null);
  const [openRecipes, setOpenRecipes] = useState<Record<string, string | null>>(() => load(STORAGE.recipe, {}));
  const [creatingRecipe, setCreatingRecipe] = useState(false);
  // 刚从图片生成、还没保存的配方：改了才保存，没动过就不留下。
  const [pendingRecipe, setPendingRecipe] = useState<{ workspaceId: string; recipe: Recipe } | null>(null);
  const [dragging, setDragging] = useState(false);
  const [translating, setTranslating] = useState(false);
  const gridRef = useRef<HTMLDivElement>(null);

  const workspace = payload?.workspace ?? null;
  const images = payload?.images ?? [];
  const groupIds = useMemo(() => groupImageIds(analysis, selectedGroup), [analysis, selectedGroup]);
  const filtered = useMemo(
    () => filterImages(groupIds ? images.filter((image) => groupIds.has(image.id)) : images, filters),
    [images, filters, groupIds],
  );
  const unsavedRecipe = workspace && pendingRecipe?.workspaceId === workspace.id ? pendingRecipe.recipe : null;
  const openRecipeId = unsavedRecipe?.id ?? (workspace ? openRecipes[workspace.id] ?? null : null);
  const translateActive = translateOn && (translateProvider === "google" || Boolean(llm?.available));
  const selectedId = workspace ? selection[workspace.id] ?? null : null;
  const selectedImage = images.find((image) => image.id === selectedId) ?? null;

  const applyPayload = useCallback((next: WorkspacePayload) => {
    setPayload(next);
    setFilters(emptyFilters);
    setSelectedGroup(null);
    save(STORAGE.workspace, next.workspace.id);
    if (next.analysis_job_id) {
      setAnalyzing({ jobId: next.analysis_job_id, done: 0, total: 0 });
    }
    if (next.scan && next.scan.failed) {
      setNotice(`有 ${next.scan.failed} 张图片读取失败。`);
    }
    void listWorkspaces().then((data) => setWorkspaces(data.workspaces)).catch(() => undefined);
  }, []);

  const run = useCallback(async (task: () => Promise<WorkspacePayload>) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      applyPayload(await task());
    } catch (exc) {
      setError(errorMessage(exc));
    } finally {
      setBusy(false);
    }
  }, [applyPayload]);

  // 首次进入：读工作区列表、LLM 状态，并恢复上次打开的工作区。
  useEffect(() => {
    void listWorkspaces().then((data) => setWorkspaces(data.workspaces)).catch(() => undefined);
    void getLLMStatus().then(setLlm).catch(() => setLlm(null));
    const last = load<string | null>(STORAGE.workspace, null);
    if (last) {
      void getWorkspace(last)
        .then((data) => {
          setPayload(data);
          // 恢复工作区时补跑一次分析：缓存都命中时很快结束，有新 tag 时补上翻译和分类。
          return analyzeWorkspace(data.workspace.id);
        })
        .then((result) => result?.job_id && setAnalyzing({ jobId: result.job_id, done: 0, total: 0 }))
        .catch(() => undefined);
    }
  }, []);

  const refreshAnalysis = useCallback(async () => {
    if (!workspace) return;
    try {
      setAnalysis(await getAnalysis(workspace.id));
    } catch {
      // 分析只是增强，读不到不影响浏览。
    }
  }, [workspace]);

  const refreshRecipes = useCallback(async () => {
    if (!workspace) return;
    try {
      setRecipes((await listRecipes(workspace.id)).recipes);
    } catch {
      setRecipes([]);
    }
  }, [workspace]);

  useEffect(() => {
    setAnalysis(null);
    setRecipes([]);
    void refreshAnalysis();
    void refreshRecipes();
  }, [refreshAnalysis, refreshRecipes]);

  const openRecipe = useCallback(
    (id: string | null) => {
      if (!workspace) return;
      setPendingRecipe(null);
      setOpenRecipes((current) => {
        const next = { ...current, [workspace.id]: id };
        save(STORAGE.recipe, next);
        return next;
      });
    },
    [workspace],
  );

  const newRecipe = async () => {
    if (!workspace || !selectedImage) return;
    setCreatingRecipe(true);
    setRegenError(null);
    try {
      const { recipe } = await createRecipe(workspace.id, selectedImage.id, {
        groupId: groupOfImage(analysis, selectedImage.id),
        draft: true,
      });
      openRecipe(null);
      setPendingRecipe({ workspaceId: workspace.id, recipe });
    } catch (exc) {
      setRegenError(errorMessage(exc));
    } finally {
      setCreatingRecipe(false);
    }
  };

  useEffect(() => translationStore.subscribe(() => setTranslating(translationStore.pending > 0)), []);

  const selectImage = useCallback(
    (id: string) => {
      if (!workspace) {
        return;
      }
      setSelection((current) => {
        const next = { ...current, [workspace.id]: id };
        save(STORAGE.selection, next);
        return next;
      });
      setRegenError(null);
      setRegenDuplicate(null);
    },
    [workspace],
  );

  // 选中图片变化时读它的重生记录；有进行中的就轮询。
  const refreshRuns = useCallback(async () => {
    if (!workspace || !selectedId) {
      setRuns([]);
      return;
    }
    try {
      const data = await listRuns(workspace.id, selectedId);
      setRuns(data.runs);
    } catch {
      // 轮询失败下一轮再试。
    }
  }, [workspace, selectedId]);

  useEffect(() => {
    setRuns([]);
    void refreshRuns();
  }, [refreshRuns]);

  const hasActiveRun = runs.some((item) => ACTIVE_RUN_STATUSES.has(item.status));
  useEffect(() => {
    if (!hasActiveRun) {
      return;
    }
    const timer = setInterval(() => void refreshRuns(), RUN_POLL_MS);
    return () => clearInterval(timer);
  }, [hasActiveRun, refreshRuns]);

  // 分析任务（翻译 + tag 分类）进度：跑的过程中定期刷新分组，跑完后再刷新一次，
  // 并让之前没翻出来的 tag 重新请求（多半已经在缓存里）。
  useEffect(() => {
    if (!analyzing) {
      return;
    }
    let stopped = false;
    let ticks = 0;
    const timer = setInterval(async () => {
      try {
        const job = await apiGet<JobSnapshot>(`/jobs/${encodeURIComponent(analyzing.jobId)}`);
        if (stopped) {
          return;
        }
        ticks += 1;
        const progress = [...(job.events ?? [])].reverse().find((event) => event.type === "progress");
        if (["succeeded", "failed", "cancelled", "interrupted"].includes(job.status)) {
          setAnalyzing(null);
          translationStore.retryFailed();
          void refreshAnalysis();
        } else {
          if (progress?.total) {
            setAnalyzing({ jobId: analyzing.jobId, done: progress.done ?? 0, total: progress.total });
          }
          if (ticks % ANALYSIS_REFRESH_TICKS === 0) {
            void refreshAnalysis();
          }
        }
      } catch {
        setAnalyzing(null);
      }
    }, JOB_POLL_MS);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [analyzing?.jobId]); // eslint-disable-line react-hooks/exhaustive-deps

  // ←/→ 在当前筛选结果里切换图片。
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) {
        return;
      }
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") {
        return;
      }
      if (!filtered.length) {
        return;
      }
      event.preventDefault();
      const index = filtered.findIndex((image) => image.id === selectedId);
      const nextIndex =
        index < 0 ? 0 : Math.min(filtered.length - 1, Math.max(0, index + (event.key === "ArrowRight" ? 1 : -1)));
      const next = filtered[nextIndex];
      selectImage(next.id);
      gridRef.current
        ?.querySelector(`[data-image-id="${next.id}"]`)
        ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [filtered, selectedId, selectImage]);

  const updateRegenSettings = (next: RegenSettings) => {
    setRegenSettings(next);
    save(STORAGE.regen, next);
  };

  const submitRegenerate = async (force = false) => {
    if (!workspace || !selectedImage) {
      return;
    }
    setSubmitting(true);
    setRegenError(null);
    setRegenDuplicate(null);
    try {
      const { run: created } = await startRegenerate(workspace.id, selectedImage.id, regenSettings, force);
      setRuns((current) => [created, ...current.filter((item) => item.id !== created.id)]);
    } catch (exc) {
      const duplicate = duplicateOf(exc);
      if (duplicate) setRegenDuplicate(duplicate);
      else setRegenError(errorMessage(exc));
    } finally {
      setSubmitting(false);
    }
  };

  const cancelRun = async (target: StyleLabRun) => {
    if (target.job_id) {
      try {
        await cancelJob(target.job_id);
      } catch (exc) {
        setRegenError(errorMessage(exc));
      }
    }
  };

  /** 导入图片：加进当前图片组，或新建一个图片组。 */
  const importFiles = async (picked: File[], target: "current" | "new") => {
    const files = picked.filter((file) => IMAGE_FILE_RE.test(file.name));
    if (!files.length) {
      setError("选中的文件里没有 PNG / WebP / JPEG 图片。");
      return;
    }
    await run(async () => {
      const into = target === "current" && workspace?.kind === "files" ? workspace : (await createImageGroup([])).workspace;
      return uploadImages(into.id, files);
    });
  };

  // 拖文件进页面时显示投放区。按窗口计数 dragenter / dragleave，拖出窗口或松手后一定会收起。
  useEffect(() => {
    let depth = 0;
    const hasFiles = (event: DragEvent) => Boolean(event.dataTransfer?.types.includes("Files"));
    const enter = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      depth += 1;
      setDragging(true);
    };
    const leave = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      depth = Math.max(0, depth - 1);
      if (depth === 0) setDragging(false);
    };
    const over = (event: DragEvent) => {
      // 落在投放区以外时也别让浏览器直接打开图片。
      if (hasFiles(event)) event.preventDefault();
    };
    const reset = (event: DragEvent) => {
      if (hasFiles(event)) event.preventDefault();
      depth = 0;
      setDragging(false);
    };
    window.addEventListener("dragenter", enter);
    window.addEventListener("dragleave", leave);
    window.addEventListener("dragover", over);
    window.addEventListener("drop", reset);
    window.addEventListener("dragend", reset);
    return () => {
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("dragover", over);
      window.removeEventListener("drop", reset);
      window.removeEventListener("dragend", reset);
    };
  }, []);

  const removeImage = async (image: ImageRecord) => {
    if (!workspace) return;
    const message =
      workspace.kind === "files"
        ? "从图片组移除这张图？拖进来的副本会删掉，你电脑上的原图不受影响。"
        : "从工作区移除这张图？文件夹里的原图不会删，之后可以点顶部的「恢复移除的」放回来。";
    if (!window.confirm(message)) return;
    const index = filtered.findIndex((item) => item.id === image.id);
    const neighbor = filtered[index + 1] ?? filtered[index - 1] ?? null;
    setBusy(true);
    setError(null);
    try {
      const next = await removeImages(workspace.id, [image.id]);
      // 移除不重置筛选和分组，选中旁边那张。
      setPayload(next);
      if (neighbor) selectImage(neighbor.id);
      void listWorkspaces().then((data) => setWorkspaces(data.workspaces)).catch(() => undefined);
    } catch (exc) {
      setError(errorMessage(exc));
    } finally {
      setBusy(false);
    }
  };

  return (
    <ImageViewerProvider workspaceId={workspace?.id ?? ""}>
    <main className={`sl-page ${dragging ? "dragging" : ""}`}>
      <WorkspaceBar
        busy={busy}
        current={workspace}
        imageCount={images.length}
        llm={llm}
        onChangeProvider={(provider) => {
          setTranslateProvider(provider);
          translationStore.setProvider(provider);
          save(STORAGE.provider, provider);
        }}
        onCreateGroup={(files) => void importFiles(files, "new")}
        onOpenFolder={(path) => void run(() => openFolder(path))}
        onRestoreImages={() => workspace && void run(() => restoreImages(workspace.id))}
        onRescan={() => workspace && void run(() => rescanWorkspace(workspace.id))}
        onSelectWorkspace={(id) => void run(() => getWorkspace(id))}
        onToggleTranslate={() => {
          setTranslateOn(!translateOn);
          save(STORAGE.translate, !translateOn);
        }}
        pretranslate={analyzing && analyzing.total ? analyzing : null}
        translateOn={translateOn}
        translateProvider={translateProvider}
        translating={translating}
        workspaces={workspaces}
      />
      {error ? (
        <div className="sl-banner error" role="alert">
          {error}
        </div>
      ) : null}
      {notice ? <div className="sl-banner">{notice}</div> : null}

      {workspace && openRecipeId ? (
        <RecipeWorkspace
          analysisReady={Boolean(analysis && analysis.classified > 0)}
          categories={analysis?.categories ?? {}}
          groups={analysis?.groups ?? []}
          images={images}
          onBack={() => openRecipe(null)}
          onCreated={(recipe) => {
            openRecipe(recipe.id);
            void refreshRecipes();
          }}
          onDeleted={() => {
            openRecipe(null);
            void refreshRecipes();
          }}
          onOpenRecipe={(id) => openRecipe(id)}
          onSaved={() => void refreshRecipes()}
          recipeId={openRecipeId}
          recipes={recipes}
          unsaved={unsavedRecipe}
          translateOn={translateActive}
          workspaceId={workspace.id}
        />
      ) : !workspace ? (
        <div className="sl-welcome">
          <ImagePlus size={36} aria-hidden="true" />
          <h2>打开一个画风语料</h2>
          <p>在上方粘贴文件夹路径（例如 artist_parse 下的作者目录，有 origin 子目录时只扫描 origin），或把一组图片拖进来。</p>
        </div>
      ) : (
        <div className="sl-body">
          <FilterPanel
            filters={filters}
            header={
              <GroupPanel
                analysis={analysis}
                analyzing={analyzing && analyzing.total ? analyzing : null}
                llmAvailable={Boolean(llm?.available)}
                onOpenRecipe={(id) => openRecipe(id)}
                onSelectGroup={setSelectedGroup}
                recipes={recipes}
                selectedGroup={selectedGroup}
              />
            }
            images={groupIds ? images.filter((image) => groupIds.has(image.id)) : images}
            onChange={setFilters}
          />
          <div className="sl-center" ref={gridRef}>
            <ImageGrid images={filtered} onSelect={selectImage} selectedId={selectedId} workspaceId={workspace.id} />
            <CommonalityPanel
              images={filtered}
              onSelect={selectImage}
              selectedId={selectedId}
              translateOn={translateActive}
              workspaceId={workspace.id}
            />
          </div>
          <aside className="sl-inspector" aria-label="图片详情">
            {selectedImage ? (
              <ImageInspector
                image={selectedImage}
                onRemove={() => void removeImage(selectedImage)}
                translateOn={translateActive}
                workspaceId={workspace.id}
              >
                <button
                  className="sl-primary sl-new-recipe"
                  disabled={creatingRecipe || !selectedImage.has_metadata}
                  onClick={() => void newRecipe()}
                  title="以这张图的提示词为起点，划分画风并锁定"
                  type="button"
                >
                  <FlaskConical size={15} aria-hidden="true" />
                  {creatingRecipe ? "创建中…" : "从这张图新建配方"}
                </button>
                <RegenPanel
                  error={regenError}
                  notice={
                    regenDuplicate ? (
                      <DuplicateNotice
                        duplicate={regenDuplicate}
                        onDismiss={() => setRegenDuplicate(null)}
                        onForce={() => void submitRegenerate(true)}
                      />
                    ) : null
                  }
                  image={selectedImage}
                  onChange={updateRegenSettings}
                  onSubmit={() => void submitRegenerate()}
                  settings={regenSettings}
                  submitting={submitting}
                />
                <RunPanel image={selectedImage} onCancel={(item) => void cancelRun(item)} runs={runs} workspaceId={workspace.id} />
              </ImageInspector>
            ) : (
              <div className="sl-empty">选一张图片查看元数据，按 ← / → 切换。</div>
            )}
          </aside>
        </div>
      )}
      {dragging ? (
        <div className="sl-drop-overlay">
          {workspace?.kind === "files" ? (
            <DropTarget label={`加入当前图片组「${workspace.name}」`} onFiles={(files) => void importFiles(files, "current")} />
          ) : null}
          <DropTarget label="新建图片组" onFiles={(files) => void importFiles(files, "new")} />
        </div>
      ) : null}
    </main>
    </ImageViewerProvider>
  );
}

function DropTarget({ label, onFiles }: { label: string; onFiles: (files: File[]) => void }) {
  const [over, setOver] = useState(false);
  return (
    <div
      className={`sl-drop-target ${over ? "over" : ""}`}
      onDragLeave={() => setOver(false)}
      onDragOver={(event) => {
        event.preventDefault();
        setOver(true);
      }}
      onDrop={(event) => {
        event.preventDefault();
        setOver(false);
        onFiles([...event.dataTransfer.files]);
      }}
    >
      <ImagePlus size={28} aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}
