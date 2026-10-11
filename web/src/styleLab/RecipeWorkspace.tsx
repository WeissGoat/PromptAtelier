import { ArrowLeft, FlaskConical, Play, Save, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { errorMessage } from "../api/client";
import type {
  ArtistExport,
  ArtistTestRun,
  ImageRecord,
  Recipe,
  RecipePreview,
  RecipeSummary,
  RegenSettings,
  StyleGroup,
  StyleLabRun,
  TagCategory,
} from "./api";
import {
  ACTIVE_RUN_STATUSES,
  cancelJob,
  deleteRecipe,
  generateRecipe,
  getExportDefaults,
  getRecipe,
  isArtistTestRun,
  listRecipeRuns,
  previewRecipe,
  saveNewRecipe,
  saveRecipe,
  sourceImageUrl,
} from "./api";
import { ArtistTestPanel } from "./ArtistTestPanel";
import { DuplicateNotice, duplicateOf, type DuplicateRequest } from "./DuplicateNotice";
import { ExportDialog } from "./ExportDialog";
import { fileName, formatTime, modelLabel } from "./format";
import { sourceViewerItem, useImageViewer } from "./ImageViewer";
import { LibraryPanel } from "./LibraryPanel";
import { normalizeRecipe, postFrequency } from "./recipeModel";
import { RecipeEditor } from "./RecipeEditor";
import { defaultRegenSettings, Segmented, SIZE_PRESETS } from "./RegenPanel";
import { RunPanel } from "./RunPanel";

const RUN_SETTINGS_KEY = "promptatelier.style-lab.recipe-run/v1";
const DRAFT_KEY_PREFIX = "promptatelier.style-lab.recipe-draft/v1";

type DraftBackup = { baseVersion: number; draft: Recipe };

function draftKey(workspaceId: string, recipeId: string): string {
  return `${DRAFT_KEY_PREFIX}/${workspaceId}/${recipeId}`;
}

/** 未保存的草稿备份在浏览器里：刷新、误关页面后还能找回。只对同一个已保存版本有效。 */
function readDraftBackup(workspaceId: string, recipeId: string): DraftBackup | null {
  try {
    const raw = window.localStorage.getItem(draftKey(workspaceId, recipeId));
    if (!raw) return null;
    const backup = JSON.parse(raw) as DraftBackup;
    return { ...backup, draft: normalizeRecipe(backup.draft) };
  } catch {
    return null;
  }
}

function writeDraftBackup(workspaceId: string, recipeId: string, backup: DraftBackup | null): void {
  try {
    if (backup) window.localStorage.setItem(draftKey(workspaceId, recipeId), JSON.stringify(backup));
    else window.localStorage.removeItem(draftKey(workspaceId, recipeId));
  } catch {
    // 存不下就只保留在内存里。
  }
}
const PREVIEW_DELAY_MS = 400;
const RUN_POLL_MS = 1500;

function loadRunSettings(): RegenSettings {
  try {
    const raw = window.localStorage.getItem(RUN_SETTINGS_KEY);
    return raw ? { ...defaultRegenSettings, ...(JSON.parse(raw) as Partial<RegenSettings>), overrides: {} } : defaultRegenSettings;
  } catch {
    return defaultRegenSettings;
  }
}

type RecipeWorkspaceProps = {
  workspaceId: string;
  recipeId: string;
  recipes: RecipeSummary[];
  images: ImageRecord[];
  groups: StyleGroup[];
  categories: Record<string, TagCategory>;
  analysisReady: boolean;
  translateOn: boolean;
  /** 刚从图片生成、还没保存的配方（version 0）：第一次改动时自动保存。 */
  unsaved: Recipe | null;
  onBack: () => void;
  onOpenRecipe: (id: string) => void;
  onSaved: () => void;
  onCreated: (recipe: Recipe) => void;
  onDeleted: () => void;
};

export function RecipeWorkspace({
  workspaceId,
  recipeId,
  recipes,
  images,
  groups,
  categories,
  analysisReady,
  translateOn,
  unsaved,
  onBack,
  onOpenRecipe,
  onSaved,
  onCreated,
  onDeleted,
}: RecipeWorkspaceProps) {
  const viewer = useImageViewer();
  const [saved, setSaved] = useState<Recipe | null>(null);
  const [draft, setDraft] = useState<Recipe | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [preview, setPreview] = useState<RecipePreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [runs, setRuns] = useState<StyleLabRun[]>([]);
  const [testRuns, setTestRuns] = useState<ArtistTestRun[]>([]);
  const [exports, setExports] = useState<ArtistExport[]>([]);
  const [exportOpen, setExportOpen] = useState(false);
  const [runSettings, setRunSettings] = useState<RegenSettings>(loadRunSettings);
  const [submitting, setSubmitting] = useState(false);
  const [duplicate, setDuplicate] = useState<DuplicateRequest | null>(null);
  const [restored, setRestored] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setSaved(null);
    setDraft(null);
    setPreview(null);
    setError(null);
    if (unsaved && unsaved.id === recipeId) {
      setSaved(unsaved);
      setDraft(unsaved);
      setRestored(false);
      return;
    }
    getRecipe(workspaceId, recipeId)
      .then((data) => {
        if (cancelled) return;
        const backup = readDraftBackup(workspaceId, recipeId);
        const usable = backup && backup.baseVersion === data.recipe.version && JSON.stringify(backup.draft) !== JSON.stringify(data.recipe);
        setSaved(data.recipe);
        setDraft(usable ? backup.draft : data.recipe);
        setRestored(Boolean(usable));
        if (backup && !usable) writeDraftBackup(workspaceId, recipeId, null);
      })
      .catch((exc) => !cancelled && setError(errorMessage(exc)));
    return () => {
      cancelled = true;
    };
    // 只在换配方时读取；unsaved 保存后会变成 null，不用重新读。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId, recipeId]);

  const source = useMemo(() => images.find((image) => image.id === draft?.source_image_id) ?? null, [images, draft?.source_image_id]);
  const group = useMemo(() => {
    for (const item of groups) {
      if (draft?.group_id && (item.id === draft.group_id || item.children.some((child) => child.id === draft.group_id))) return item;
    }
    return groups.find((item) => source && item.image_ids.includes(source.id)) ?? null;
  }, [groups, draft?.group_id, source]);
  // 配方可能挂在某个变体（子分组）上：回归对照只从这个变体里挑图。
  const groupImageIds = useMemo(() => {
    if (!group) return null;
    const child = group.children.find((item) => item.id === draft?.group_id);
    return (child ?? group).image_ids;
  }, [group, draft?.group_id]);
  const frequency = useMemo(() => {
    const ids = new Set(group?.image_ids ?? images.map((image) => image.id));
    return postFrequency(images.filter((image) => ids.has(image.id)));
  }, [group, images]);

  const dirty = Boolean(draft && saved && JSON.stringify(draft) !== JSON.stringify(saved));
  const isNew = saved?.version === 0;

  useEffect(() => {
    if (!draft || !saved || saved.version === 0) return;
    writeDraftBackup(workspaceId, recipeId, dirty ? { baseVersion: saved.version, draft } : null);
  }, [workspaceId, recipeId, draft, saved, dirty]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  // 编辑阶段的草稿变化后稍等一下再算"实际发送"。
  useEffect(() => {
    if (!draft || draft.stage !== "edit") return;
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const data = await previewRecipe(workspaceId, draft);
        if (!cancelled) {
          setPreview(data.preview);
          setPreviewError(null);
        }
      } catch (exc) {
        if (!cancelled) setPreviewError(errorMessage(exc));
      }
    }, PREVIEW_DELAY_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [workspaceId, draft]);

  const refreshRuns = useCallback(async () => {
    try {
      const data = await listRecipeRuns(workspaceId, recipeId);
      setRuns(data.runs.filter((run): run is StyleLabRun => run.kind === "recipe"));
      setTestRuns(data.runs.filter(isArtistTestRun));
    } catch {
      // 下一轮再试。
    }
  }, [workspaceId, recipeId]);

  const refreshExports = useCallback(async () => {
    try {
      setExports((await getExportDefaults(workspaceId, recipeId)).exports);
    } catch {
      setExports([]);
    }
  }, [workspaceId, recipeId]);

  // 还没保存的新配方在后端没有出图记录和导出，不用去读。
  const persistedId = saved && saved.version > 0 ? saved.id : null;
  useEffect(() => {
    if (!persistedId) return;
    void refreshRuns();
    void refreshExports();
  }, [persistedId, refreshRuns, refreshExports]);

  const hasActive = [...runs, ...testRuns].some((run) => ACTIVE_RUN_STATUSES.has(run.status));
  useEffect(() => {
    if (!hasActive) return;
    const timer = setInterval(() => void refreshRuns(), RUN_POLL_MS);
    return () => clearInterval(timer);
  }, [hasActive, refreshRuns]);

  const save = useCallback(async (): Promise<Recipe | null> => {
    if (!draft || !saved) return null;
    if (!dirty) return saved;
    setSaving(true);
    setError(null);
    const creating = saved.version === 0;
    try {
      const data = creating ? await saveNewRecipe(workspaceId, draft) : await saveRecipe(workspaceId, draft, saved.version);
      setSaved(data.recipe);
      // 保存途中又改了的保留下来，下次再存。
      setDraft((current) => (current === draft ? data.recipe : current));
      setRestored(false);
      writeDraftBackup(workspaceId, recipeId, null);
      if (creating) onCreated(data.recipe);
      else onSaved();
      return data.recipe;
    } catch (exc) {
      setError(
        (exc as { status?: number }).status === 409
          ? "这个配方在别的页面里被改过并保存了。复制好你的改动后刷新页面再改。"
          : errorMessage(exc),
      );
      return null;
    } finally {
      setSaving(false);
    }
  }, [draft, saved, dirty, workspaceId, recipeId, onSaved, onCreated]);

  // 新配方第一次有改动就保存，之后和普通配方一样手动保存。没动过就不会留下。
  useEffect(() => {
    if (isNew && dirty && !saving && !error) void save();
  }, [isNew, dirty, saving, error, save]);

  const remove = async () => {
    if (!saved || isNew) return;
    if (!window.confirm(`删除配方「${saved.name}」？已经导出的 artist 和出图结果不受影响。`)) return;
    try {
      await deleteRecipe(workspaceId, saved.id);
      writeDraftBackup(workspaceId, recipeId, null);
      onDeleted();
    } catch (exc) {
      setError(errorMessage(exc));
    }
  };

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void save();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [save]);

  const generate = async (force = false) => {
    const current = await save();
    if (!current) return;
    setSubmitting(true);
    setError(null);
    setDuplicate(null);
    try {
      const { run } = await generateRecipe(workspaceId, current.id, runSettings, force);
      setRuns((items) => [run, ...items]);
    } catch (exc) {
      const found = duplicateOf(exc);
      if (found) setDuplicate(found);
      else setError(errorMessage(exc));
    } finally {
      setSubmitting(false);
    }
  };

  const openExport = async () => {
    if (await save()) setExportOpen(true);
  };

  const updateRunSettings = (next: RegenSettings) => {
    setRunSettings(next);
    try {
      window.localStorage.setItem(RUN_SETTINGS_KEY, JSON.stringify(next));
    } catch {
      // 只在当前页面记住。
    }
  };

  if (!draft || !saved) {
    return (
      <div className="sl-recipe-loading">
        {error ? <p className="sl-error">{error}</p> : <p className="sl-muted">读取配方…</p>}
        <button className="sl-ghost" onClick={onBack} type="button">
          <ArrowLeft size={14} aria-hidden="true" />
          返回图片
        </button>
      </div>
    );
  }

  return (
    <div className="sl-recipe-body">
      <aside className="sl-recipe-side">
        <button className="sl-ghost" onClick={onBack} type="button">
          <ArrowLeft size={14} aria-hidden="true" />
          返回图片
        </button>
        <input
          aria-label="配方名"
          className="sl-recipe-name"
          onChange={(event) => setDraft({ ...draft, name: event.target.value })}
          value={draft.name}
        />
        <div className="sl-recipe-meta">
          {isNew ? (
            <span>新配方，还没保存；改动后自动保存，不改直接返回就不会留下</span>
          ) : (
            <>
              <span>v{saved.version}</span>
              <span>{dirty ? "有未保存的修改" : `已保存 ${formatTime(saved.updated_at)}`}</span>
            </>
          )}
        </div>
        <div className="sl-recipe-actions">
          <button className="sl-ghost" disabled={!dirty || saving} onClick={() => void save()} title="Ctrl+S" type="button">
            <Save size={14} aria-hidden="true" />
            {saving ? "保存中…" : "保存"}
          </button>
          {!isNew ? (
            <button className="sl-ghost danger" onClick={() => void remove()} title="删除这个配方" type="button">
              <Trash2 size={14} aria-hidden="true" />
              删除
            </button>
          ) : null}
        </div>
        {source ? (
          <figure className="sl-recipe-source">
            <button className="sl-zoomable" onClick={() => viewer.open([sourceViewerItem(source)])} title="查看大图和文件位置" type="button">
              <img alt="原图" src={sourceImageUrl(workspaceId, source.id, 480)} />
            </button>
            <figcaption>
              原图 {fileName(source.path)} · {modelLabel(source.model)}
            </figcaption>
          </figure>
        ) : null}
        {group ? (
          <section className="sl-recipe-group">
            <h3>所属分组</h3>
            <p>
              {group.name} · {group.post_count} 个投稿
            </p>
            <div className="sl-tags">
              {group.signature.slice(0, 10).map((item) => (
                <span className="sl-tag" key={item.tag} title={`${item.posts} 个投稿`}>
                  <span className="sl-tag-en">{item.tag}</span>
                </span>
              ))}
            </div>
          </section>
        ) : null}
        <section className="sl-recipe-group">
          <h3>配方</h3>
          {recipes.map((item) => (
            <button
              className={`sl-recipe-link ${item.id === recipeId ? "on" : ""}`}
              key={item.id}
              onClick={() => item.id !== recipeId && onOpenRecipe(item.id)}
              type="button"
            >
              <FlaskConical size={13} aria-hidden="true" />
              <span>{item.name}</span>
              <span className="sl-count">v{item.version}</span>
            </button>
          ))}
        </section>
      </aside>

      <main className="sl-recipe-main">
        {error ? (
          <div className="sl-banner error" role="alert">
            {error}
          </div>
        ) : null}
        {restored ? (
          <div className="sl-banner">
            已恢复上次没保存的修改。
            <button
              className="sl-link-btn"
              onClick={() => {
                setDraft(saved);
                setRestored(false);
              }}
              type="button"
            >
              丢弃，回到 v{saved.version}
            </button>
          </div>
        ) : null}
        <RecipeEditor
          analysisReady={analysisReady}
          categories={categories}
          draft={draft}
          frequency={frequency}
          onChange={setDraft}
          preview={preview}
          previewError={previewError}
          source={source}
          translateOn={translateOn}
        />
        {draft.stage === "edit" ? (
          <section className="sl-zone zone-generate">
            <header className="sl-zone-head">
              <span className="sl-zone-title">测试出图</span>
              <span className="sl-muted">走正式出图链路，和导出后的 artist 完全一致</span>
            </header>
            <div className="sl-form-row">
              <label htmlFor="sl-recipe-count">张数</label>
              <input
                id="sl-recipe-count"
                max={8}
                min={1}
                onChange={(event) => updateRunSettings({ ...runSettings, count: Math.min(8, Math.max(1, Number(event.target.value) || 1)) })}
                type="number"
                value={runSettings.count}
              />
              <span className="sl-form-label">种子</span>
              <Segmented
                onChange={(value) => updateRunSettings({ ...runSettings, seed_mode: value as RegenSettings["seed_mode"] })}
                options={[
                  ["source", "原图"],
                  ["random", "随机"],
                  ["fixed", "指定"],
                ]}
                value={runSettings.seed_mode}
              />
              {runSettings.seed_mode === "fixed" ? (
                <input
                  aria-label="指定种子"
                  onChange={(event) => updateRunSettings({ ...runSettings, seed: event.target.value === "" ? null : Number(event.target.value) })}
                  type="number"
                  value={runSettings.seed ?? ""}
                />
              ) : null}
            </div>
            <div className="sl-form-row">
              <span className="sl-form-label">尺寸</span>
              <Segmented
                onChange={(value) => updateRunSettings({ ...runSettings, size_mode: value as RegenSettings["size_mode"] })}
                options={[
                  ["source", source?.width ? `原图 ${source.width}×${source.height}` : "原图"],
                  ["custom", "自定义"],
                ]}
                value={runSettings.size_mode}
              />
              {runSettings.size_mode === "custom"
                ? SIZE_PRESETS.map(([w, h]) => (
                    <button
                      className={`sl-mini-btn ${runSettings.width === w && runSettings.height === h ? "on" : ""}`}
                      key={`${w}x${h}`}
                      onClick={() => updateRunSettings({ ...runSettings, width: w, height: h })}
                      type="button"
                    >
                      {w}×{h}
                    </button>
                  ))
                : null}
            </div>
            {duplicate ? (
              <DuplicateNotice duplicate={duplicate} onDismiss={() => setDuplicate(null)} onForce={() => void generate(true)} />
            ) : null}
            <button
              className="sl-primary"
              disabled={
                submitting ||
                (runSettings.seed_mode === "fixed" && runSettings.seed === null) ||
                (runSettings.size_mode === "custom" && (!runSettings.width || !runSettings.height))
              }
              onClick={() => void generate()}
              type="button"
            >
              <Play size={15} aria-hidden="true" />
              {submitting ? "提交中…" : `${dirty ? "保存并" : ""}生成 · ${runSettings.count} 张`}
            </button>
          </section>
        ) : null}
        {source && draft.stage === "edit" ? (
          <RunPanel
            image={source}
            onCancel={(run) => run.job_id && void cancelJob(run.job_id)}
            runs={runs}
            workspaceId={workspaceId}
          />
        ) : null}
        {draft.stage === "edit" ? (
          <ArtistTestPanel
            dirty={dirty}
            exports={exports}
            groupImageIds={groupImageIds}
            images={images}
            onCancel={(run) => run.job_id && void cancelJob(run.job_id)}
            onExport={() => void openExport()}
            onStarted={(run) => setTestRuns((items) => [run, ...items])}
            recipeId={recipeId}
            recipeVersion={saved.version}
            runs={testRuns}
            sourceImageId={draft.source_image_id}
            workspaceId={workspaceId}
          />
        ) : null}
      </main>
      {exportOpen ? (
        <ExportDialog
          onClose={() => setExportOpen(false)}
          onExported={(entry) => {
            setExportOpen(false);
            setExports((items) => [...items, entry]);
          }}
          recipeId={recipeId}
          workspaceId={workspaceId}
        />
      ) : null}

      <LibraryPanel draft={draft} onChange={setDraft} translateOn={translateOn} />
    </div>
  );
}
