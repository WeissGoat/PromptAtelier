import { ImagePlus } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { apiGet, errorMessage } from "../api/client";
import type {
  LLMStatus,
  RegenSettings,
  StyleLabRun,
  WorkspaceInfo,
  WorkspacePayload,
} from "./api";
import {
  ACTIVE_RUN_STATUSES,
  cancelJob,
  createImageGroup,
  getLLMStatus,
  getWorkspace,
  listRuns,
  listWorkspaces,
  openFolder,
  rescanWorkspace,
  startRegenerate,
  uploadImages,
} from "./api";
import { emptyFilters, filterImages, FilterPanel, ImageGrid, type ImageFilters } from "./ImageBrowser";
import { ImageInspector } from "./ImageInspector";
import { defaultRegenSettings, RegenPanel } from "./RegenPanel";
import { RunPanel } from "./RunPanel";
import { translationStore } from "./translations";
import { WorkspaceBar } from "./WorkspaceBar";
import "./styleLab.css";

const STORAGE = {
  workspace: "promptatelier.style-lab.workspace/v1",
  selection: "promptatelier.style-lab.selection/v1",
  translate: "promptatelier.style-lab.translate/v1",
  regen: "promptatelier.style-lab.regen/v1",
};
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
  const [llm, setLlm] = useState<LLMStatus | null>(null);
  const [regenSettings, setRegenSettings] = useState<RegenSettings>(() => ({
    ...defaultRegenSettings,
    ...load<Partial<RegenSettings>>(STORAGE.regen, {}),
  }));
  const [runs, setRuns] = useState<StyleLabRun[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [regenError, setRegenError] = useState<string | null>(null);
  const [pretranslate, setPretranslate] = useState<{ jobId: string; done: number; total: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const [translating, setTranslating] = useState(false);
  const gridRef = useRef<HTMLDivElement>(null);

  const workspace = payload?.workspace ?? null;
  const images = payload?.images ?? [];
  const filtered = useMemo(() => filterImages(images, filters), [images, filters]);
  const selectedId = workspace ? selection[workspace.id] ?? null : null;
  const selectedImage = images.find((image) => image.id === selectedId) ?? null;

  const applyPayload = useCallback((next: WorkspacePayload) => {
    setPayload(next);
    setFilters(emptyFilters);
    save(STORAGE.workspace, next.workspace.id);
    if (next.pretranslate_job_id) {
      setPretranslate({ jobId: next.pretranslate_job_id, done: 0, total: 0 });
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
      void getWorkspace(last).then(setPayload).catch(() => undefined);
    }
  }, []);

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

  // 预翻译任务进度。跑完后让之前没翻出来的 tag 重新请求一次（多半已经在缓存里）。
  useEffect(() => {
    if (!pretranslate) {
      return;
    }
    let stopped = false;
    const timer = setInterval(async () => {
      try {
        const job = await apiGet<JobSnapshot>(`/jobs/${encodeURIComponent(pretranslate.jobId)}`);
        if (stopped) {
          return;
        }
        const progress = [...(job.events ?? [])].reverse().find((event) => event.type === "progress");
        if (["succeeded", "failed", "cancelled", "interrupted"].includes(job.status)) {
          setPretranslate(null);
          translationStore.retryFailed();
        } else if (progress?.total) {
          setPretranslate({ jobId: pretranslate.jobId, done: progress.done ?? 0, total: progress.total });
        }
      } catch {
        setPretranslate(null);
      }
    }, JOB_POLL_MS);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [pretranslate?.jobId]); // eslint-disable-line react-hooks/exhaustive-deps

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

  const submitRegenerate = async () => {
    if (!workspace || !selectedImage) {
      return;
    }
    setSubmitting(true);
    setRegenError(null);
    try {
      const { run: created } = await startRegenerate(workspace.id, selectedImage.id, regenSettings);
      setRuns((current) => [created, ...current.filter((item) => item.id !== created.id)]);
    } catch (exc) {
      setRegenError(errorMessage(exc));
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

  const onDrop = async (event: React.DragEvent) => {
    event.preventDefault();
    setDragging(false);
    const files = [...event.dataTransfer.files].filter((file) => /\.(png|webp|jpe?g)$/i.test(file.name));
    if (!files.length) {
      setError("拖入的文件里没有 PNG / WebP / JPEG 图片。");
      return;
    }
    await run(async () => {
      const target = workspace?.kind === "files" ? workspace : (await createImageGroup([])).workspace;
      return uploadImages(target.id, files);
    });
  };

  return (
    <main
      className={`sl-page ${dragging ? "dragging" : ""}`}
      onDragLeave={(event) => {
        if (event.currentTarget === event.target) {
          setDragging(false);
        }
      }}
      onDragOver={(event) => {
        if (event.dataTransfer.types.includes("Files")) {
          event.preventDefault();
          setDragging(true);
        }
      }}
      onDrop={(event) => void onDrop(event)}
    >
      <WorkspaceBar
        busy={busy}
        current={workspace}
        imageCount={images.length}
        llm={llm}
        onOpenFolder={(path) => void run(() => openFolder(path))}
        onRescan={() => workspace && void run(() => rescanWorkspace(workspace.id))}
        onSelectWorkspace={(id) => void run(() => getWorkspace(id))}
        onToggleTranslate={() => {
          setTranslateOn(!translateOn);
          save(STORAGE.translate, !translateOn);
        }}
        pretranslate={pretranslate && pretranslate.total ? pretranslate : null}
        translateOn={translateOn}
        translating={translating}
        workspaces={workspaces}
      />
      {error ? (
        <div className="sl-banner error" role="alert">
          {error}
        </div>
      ) : null}
      {notice ? <div className="sl-banner">{notice}</div> : null}

      {!workspace ? (
        <div className="sl-welcome">
          <ImagePlus size={36} aria-hidden="true" />
          <h2>打开一个画风语料</h2>
          <p>在上方粘贴文件夹路径（例如 artist_parse 下的作者目录，有 origin 子目录时只扫描 origin），或把一组图片拖进来。</p>
        </div>
      ) : (
        <div className="sl-body">
          <FilterPanel filters={filters} images={images} onChange={setFilters} />
          <div className="sl-center" ref={gridRef}>
            <ImageGrid images={filtered} onSelect={selectImage} selectedId={selectedId} workspaceId={workspace.id} />
          </div>
          <aside className="sl-inspector" aria-label="图片详情">
            {selectedImage ? (
              <ImageInspector image={selectedImage} translateOn={translateOn && Boolean(llm?.available)} workspaceId={workspace.id}>
                <RegenPanel
                  error={regenError}
                  image={selectedImage}
                  onChange={updateRegenSettings}
                  onSubmit={() => void submitRegenerate()}
                  settings={regenSettings}
                  submitting={submitting}
                />
                <RunPanel imageId={selectedImage.id} onCancel={(item) => void cancelRun(item)} runs={runs} workspaceId={workspace.id} />
              </ImageInspector>
            ) : (
              <div className="sl-empty">选一张图片查看元数据，按 ← / → 切换。</div>
            )}
          </aside>
        </div>
      )}
      {dragging ? <div className="sl-drop-hint">松开即可导入为图片组</div> : null}
    </main>
  );
}
