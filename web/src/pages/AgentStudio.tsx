import { AlertTriangle, ClipboardCopy, Download, FileText, LayoutGrid, RefreshCw, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { errorMessage } from "../api/client";
import { GenerationTasksPanel } from "../components/GenerationTasksPanel";
import { ImageDetailDialog, type ImageDetailItem } from "../components/ImageDetailDialog";
import { ActionGroupDrawer } from "../contracts/ActionGroupDrawer";
import { contractsApi } from "../contracts/api";
import {
  ContractGeneratePanel,
  DEFAULT_GENERATE_SETTINGS,
  type GenerateSettings,
} from "../contracts/ContractGeneratePanel";
import { ContractRequestPanel, EMPTY_DRAFT, type ContractDraft } from "../contracts/ContractRequestPanel";
import { ContractStoryboard, DEFAULT_BOARD_FILTERS, type BoardFilters } from "../contracts/ContractStoryboard";
import { FrameCard, type FrameView } from "../contracts/FrameCard";
import { readSelectedFrames, readStored, STORAGE_KEYS, writeSelectedFrames, writeStored } from "../contracts/persist";
import type { ContractDetail, ContractFrame, ContractResultImage, ContractResults, ContractSummary, FormatSummary } from "../contracts/types";
import { BACKGROUND_RUNS_CHANGED } from "../generation/backgroundRun";
import { loadTileSize, type TileSize } from "../generation/tileSize";
import type { TranslateProvider } from "../styleLab/api";
import { translationStore } from "../styleLab/translations";
import "../styles/contracts.css";

const POLL_MS = 5000;
const RESULTS_POLL_MS = 10000;
const ACTIVE_KEY = "promptatelier.agent-studio.active/v1";

function readActive(): string | null {
  try {
    return window.localStorage?.getItem(ACTIVE_KEY) ?? null;
  } catch {
    return null;
  }
}

type PromptModal = { kind: "tools" | "standalone"; text: string } | null;

type ViewPrefs = { view: FrameView; showDiff: boolean; translate: boolean; board: boolean; boardFilters: BoardFilters };
const DEFAULT_VIEW: ViewPrefs = { view: "marked", showDiff: true, translate: false, board: false, boardFilters: DEFAULT_BOARD_FILTERS };

/** 上次勾选的帧里还在契约中的那些；没记录时全选。 */
function restoreSelection(contractId: string, frameIds: string[]): Set<string> {
  const saved = readSelectedFrames(contractId);
  return new Set(saved ? frameIds.filter((id) => saved.includes(id)) : frameIds);
}

export function AgentStudio() {
  const [formats, setFormats] = useState<FormatSummary[]>([]);
  const [contracts, setContracts] = useState<ContractSummary[]>([]);
  const [draft, setDraft] = useState<ContractDraft>(() => readStored(STORAGE_KEYS.draft, EMPTY_DRAFT));
  const [activeId, setActiveId] = useState<string | null>(readActive);
  const [detail, setDetail] = useState<ContractDetail | null>(null);
  const [results, setResults] = useState<ContractResults | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [finished, setFinished] = useState<ContractSummary | null>(null);
  const [fileChanged, setFileChanged] = useState(false);
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [promptModal, setPromptModal] = useState<PromptModal>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [importText, setImportText] = useState("");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [initialView] = useState(() => readStored(STORAGE_KEYS.view, DEFAULT_VIEW));
  const [view, setView] = useState<FrameView>(initialView.view);
  const [showDiff, setShowDiff] = useState(initialView.showDiff);
  const [translate, setTranslate] = useState(initialView.translate);
  const [board, setBoard] = useState(initialView.board);
  const [boardFilters, setBoardFilters] = useState<BoardFilters>({ ...DEFAULT_BOARD_FILTERS, ...initialView.boardFilters });
  const [boardFocus, setBoardFocus] = useState<string | null>(null);
  const [tileSize, setTileSize] = useState<TileSize>(loadTileSize);
  const [provider, setProvider] = useState<TranslateProvider>(translationStore.provider);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [settings, setSettings] = useState<GenerateSettings>(() => readStored(STORAGE_KEYS.settings, DEFAULT_GENERATE_SETTINGS));
  const [pendingFrame, setPendingFrame] = useState<string | null>(null);
  const [openImages, setOpenImages] = useState<{ items: ImageDetailItem[]; index: number } | null>(null);
  const sinceRef = useRef(0);
  const statusRef = useRef<Map<string, string>>(new Map());
  const restoredRef = useRef<string | null>(null);
  const detailRef = useRef<ContractDetail | null>(null);
  detailRef.current = detail;

  const rememberStatuses = useCallback((items: ContractSummary[]) => {
    items.forEach((item) => statusRef.current.set(item.id, item.status));
  }, []);

  const loadList = useCallback(async () => {
    const data = await contractsApi.list();
    setContracts(data.contracts);
    rememberStatuses(data.contracts);
    sinceRef.current = data.now;
  }, [rememberStatuses]);

  const loadDetail = useCallback(async (id: string) => {
    try {
      const data = await contractsApi.get(id);
      setDetail(data);
      setFileChanged(false);
      setError("");
      return data;
    } catch (err) {
      setError(errorMessage(err));
      setDetail(null);
      return null;
    }
  }, []);

  const loadResults = useCallback(async (id: string) => {
    try {
      setResults(await contractsApi.results(id));
    } catch {
      // 结果读取失败不影响查看契约。
    }
  }, []);

  useEffect(() => {
    contractsApi.formats().then(setFormats).catch((err) => setError(errorMessage(err)));
    loadList().catch((err) => setError(errorMessage(err)));
  }, [loadList]);

  useEffect(() => {
    try {
      if (activeId) window.localStorage?.setItem(ACTIVE_KEY, activeId);
    } catch {
      // 记不住也不影响使用。
    }
    setSelected(new Set());
    setResults(null);
    if (activeId) {
      restoredRef.current = null;
      void loadDetail(activeId).then((data) => {
        if (!data?.frames) return;
        setSelected(restoreSelection(activeId, data.frames.map((frame) => frame.id)));
        restoredRef.current = activeId;
      });
      void loadResults(activeId);
    } else {
      setDetail(null);
    }
  }, [activeId, loadDetail, loadResults]);

  useEffect(() => writeStored(STORAGE_KEYS.draft, draft), [draft]);
  useEffect(() => writeStored(STORAGE_KEYS.settings, settings), [settings]);
  useEffect(
    () => writeStored(STORAGE_KEYS.view, { view, showDiff, translate, board, boardFilters }),
    [view, showDiff, translate, board, boardFilters],
  );
  // 切换契约时勾选会先清空再恢复；恢复完之前不写，免得把记录覆盖成空。
  useEffect(() => {
    if (activeId && restoredRef.current === activeId) writeSelectedFrames(activeId, [...selected]);
  }, [activeId, selected]);

  // §5.5：每 5 秒问一次哪些契约变了；pending → done 时提示，正在看的契约被改时提示重新载入。
  useEffect(() => {
    const timer = window.setInterval(async () => {
      if (document.hidden) return;
      try {
        const data = await contractsApi.index(sinceRef.current);
        sinceRef.current = data.now;
        if (!data.changed.length && data.ids.length === statusRef.current.size) return;
        const current = detailRef.current;
        for (const item of data.changed) {
          const before = statusRef.current.get(item.id);
          if (current && item.id === current.id && item.mtime > current.file.mtime + 1e-6) {
            if (current.request.status === "pending") void loadDetail(item.id);
            else setFileChanged(true);
          } else if (before === "pending" && item.status === "done") {
            setFinished(item);
          }
        }
        await loadList();
      } catch {
        // 后端暂时不可用时下一轮再试。
      }
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [loadDetail, loadList]);

  useEffect(() => {
    if (!activeId) return;
    const refresh = () => void loadResults(activeId);
    const timer = window.setInterval(() => {
      if (!document.hidden) refresh();
    }, RESULTS_POLL_MS);
    window.addEventListener(BACKGROUND_RUNS_CHANGED, refresh);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener(BACKGROUND_RUNS_CHANGED, refresh);
    };
  }, [activeId, loadResults]);

  async function createContract() {
    if (!draft.actionGroup) return;
    setCreating(true);
    setError("");
    try {
      const created = await contractsApi.create({
        action_group: draft.actionGroup.ref,
        characters: draft.characters.map((item) => item.ref),
        clothing: draft.clothing?.ref ?? null,
        background: draft.background?.ref ?? null,
        requirements: draft.requirements,
        target_format: draft.targetFormat,
        options: { keep_order: draft.keepOrder, allow_new_frames: draft.allowNewFrames, max_new_frames: draft.maxNewFrames },
      });
      await loadList();
      setActiveId(created.id);
      setDetail(created);
      await showPrompt(created.id, "tools");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setCreating(false);
    }
  }

  async function showPrompt(id: string, kind: "tools" | "standalone") {
    try {
      setPromptModal({ kind, text: await contractsApi.prompt(id, kind) });
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function refreshList(pull: boolean) {
    try {
      const data = await contractsApi.refresh(pull);
      setContracts(data.contracts);
      rememberStatuses(data.contracts);
      const report = data.pull as { ok?: boolean; error?: string; skipped?: string } | null;
      if (pull) setNotice(report?.ok === false ? `动作库拉取失败：${report.error ?? ""}` : "已拉取动作库并重新扫描");
      if (activeId) await loadDetail(activeId);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function submitImport() {
    if (!detail) return;
    try {
      const data = await contractsApi.importFrames(detail.id, importText, detail.file.hash);
      setDetail(data);
      setSelected(new Set(data.frames.map((frame) => frame.id)));
      setImportOpen(false);
      setImportText("");
      setNotice(`已导入 ${data.frames.length} 帧并写回契约文件`);
      await loadList();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function saveFrame(frameId: string, prompts: Record<string, string>): Promise<boolean> {
    if (!detail) return false;
    setSaving(true);
    try {
      setDetail(await contractsApi.saveFrame(detail.id, frameId, prompts, detail.file.hash));
      setFileChanged(false);
      return true;
    } catch (err) {
      setError(errorMessage(err));
      return false;
    } finally {
      setSaving(false);
    }
  }

  async function togglePick(image: ContractResultImage) {
    if (!detail) return;
    try {
      await contractsApi.updatePicks(detail.id, image.frame_id, image.picked ? { remove: [image.path] } : { add: [image.path] });
      await loadResults(detail.id);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  function openFrameImages(frame: ContractFrame, images: ContractResultImage[], index: number) {
    setOpenImages({
      items: images.map((image) => ({
        path: image.path,
        label: `${frame.id} · ${image.artist ?? ""}${image.seed !== undefined && image.seed !== null ? ` · seed ${image.seed}` : ""}`,
        badge: image.current ? (image.picked ? "已采用" : undefined) : "提示词已改",
      })),
      index,
    });
  }

  const handleBoardFocus = useCallback(() => setBoardFocus(null), []);

  function locateFrame(frameId: string) {
    document.getElementById(`frame-${frameId}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  const issuesByFrame = useMemo(() => {
    const map = new Map<string, NonNullable<ContractDetail["issues"]>>();
    detail?.issues?.forEach((issue) => {
      const key = issue.frame_id ?? "";
      map.set(key, [...(map.get(key) ?? []), issue]);
    });
    return map;
  }, [detail]);

  const coverage = detail?.coverage;
  const contractIssues = issuesByFrame.get("") ?? [];

  const showBoard = board && detail !== null && !detail.parse_error;

  return (
    <main className={showBoard ? "studio-grid agent-studio is-board" : "studio-grid agent-studio"}>
      {showBoard && detail ? (
        <ContractStoryboard
          detail={detail}
          filters={boardFilters}
          focusFrame={boardFocus}
          onBack={() => setBoard(false)}
          onFiltersChange={setBoardFilters}
          onFocusHandled={handleBoardFocus}
          onGenerate={setPendingFrame}
          onOpenImage={openFrameImages}
          onTileSizeChange={setTileSize}
          onTogglePick={(image) => void togglePick(image)}
          results={results}
          tileSize={tileSize}
        />
      ) : (
      <>
      <ContractRequestPanel
        activeId={activeId}
        contracts={contracts}
        creating={creating}
        draft={draft}
        formats={formats}
        onChange={setDraft}
        onCreate={() => void createContract()}
        onImportNew={() => setImportOpen(true)}
        onOpen={setActiveId}
        onRefresh={(pull) => void refreshList(pull)}
      />

      <section aria-label="契约查看" className="panel ct-middle">
        {finished ? (
          <div className="ct-banner ct-banner-ok">
            Agent 已完成：{finished.title || finished.id}
            <button className="btn-sm" onClick={() => { setActiveId(finished.id); setFinished(null); }} type="button">打开</button>
            <button aria-label="关闭提示" className="icon-button btn-ghost btn-sm" onClick={() => setFinished(null)} type="button"><X size={13} /></button>
          </div>
        ) : null}
        {notice ? (
          <div className="ct-banner">
            {notice}
            <button aria-label="关闭提示" className="icon-button btn-ghost btn-sm" onClick={() => setNotice("")} type="button"><X size={13} /></button>
          </div>
        ) : null}
        {error ? (
          <div className="ct-banner ct-banner-error">
            {error}
            <button aria-label="关闭错误" className="icon-button btn-ghost btn-sm" onClick={() => setError("")} type="button"><X size={13} /></button>
          </div>
        ) : null}

        {!detail ? (
          <div className="ct-empty">
            <FileText size={28} />
            <p>在左侧选角色和动作组、写定制要求后「新建并生成要求」，把要求 prompt 复制给外部 agent；或打开一份历史契约。</p>
          </div>
        ) : detail.parse_error ? (
          <div className="ct-empty">
            <AlertTriangle size={24} />
            <p>契约文件无法解析：{detail.parse_error}</p>
            <pre className="ct-raw">{detail.text}</pre>
          </div>
        ) : (
          <>
            <header className="ct-head">
              <div className="ct-head-title">
                <h2>{detail.request.title || detail.request.nodes.action_group?.ref || detail.id}</h2>
                <div className="ct-row">
                  <span className={`ct-pill ct-status-${detail.request.status}`}>{detail.request.status === "done" ? "已完成" : "等待 Agent"}</span>
                  <span className="chip">{detail.profile.label || detail.profile.id}</span>
                  {coverage ? (
                    <button
                      className="ct-coverage"
                      onClick={() => setDrawerOpen(true)}
                      title="动作组成员数 · 新增帧 · 未使用成员；点击打开动作组参考"
                      type="button"
                    >
                      动作组 {coverage.total}
                      {coverage.custom_frames.length ? <b className="ct-plus">+{coverage.custom_frames.length}</b> : null}
                      {coverage.missing.length ? <b className="ct-minus">−{coverage.missing.length}</b> : null}
                    </button>
                  ) : null}
                  <span className={detail.issue_counts.error ? "ct-pill ct-pill-err" : "ct-pill ct-pill-ok"}>
                    {detail.issue_counts.error} 错误 · {detail.issue_counts.warn} 警告
                  </span>
                </div>
                <small className="mono ct-wrap" title={detail.file.path}>{detail.id}</small>
              </div>
              <div className="ct-row ct-head-actions">
                <button className="btn-sm" onClick={() => setBoard(true)} title="每帧一行，看整组的全部出图结果" type="button"><LayoutGrid size={13} /> 结果故事板</button>
                <button className="btn-sm" onClick={() => void showPrompt(detail.id, "tools")} type="button"><ClipboardCopy size={13} /> 工具版 prompt</button>
                <button className="btn-sm" onClick={() => void showPrompt(detail.id, "standalone")} type="button"><ClipboardCopy size={13} /> 自包含版 prompt</button>
                <button className="btn-sm" onClick={() => setImportOpen(true)} type="button"><Download size={13} /> 导入</button>
                <button
                  className="btn-sm"
                  onClick={(event) => void (event.shiftKey ? refreshList(true) : loadDetail(detail.id))}
                  title="重新载入；按住 Shift 先 git pull 动作库"
                  type="button"
                >
                  <RefreshCw size={13} /> 刷新
                </button>
              </div>
            </header>

            {fileChanged ? (
              <div className="ct-banner ct-banner-warn">
                文件已被外部修改
                <button className="btn-sm" onClick={() => void loadDetail(detail.id)} type="button">重新载入</button>
              </div>
            ) : null}
            {detail.stale.length ? (
              <div className="ct-banner ct-banner-warn">
                来源已更新：{detail.stale.map((item) => item.ref).join("、")}。标记和 diff 用的是节点的当前内容。
              </div>
            ) : null}
            {detail.request.requirements ? <blockquote className="ct-requirements">{detail.request.requirements}</blockquote> : null}
            {contractIssues.length ? (
              <ul className="ct-issues">
                {contractIssues.map((issue, index) => (
                  <li className={`ct-issue ct-issue-${issue.severity}`} key={index}><b>{issue.validator}</b> {issue.message}</li>
                ))}
              </ul>
            ) : null}

            <div className="ct-toolbar">
              <div className="ct-seg" role="group" aria-label="视图">
                {(["marked", "raw", "source"] as const).map((key) => (
                  <button aria-pressed={view === key} className={view === key ? "on" : ""} key={key} onClick={() => setView(key)} type="button">
                    {{ marked: "标记", raw: "原文", source: "来源原文" }[key]}
                  </button>
                ))}
              </div>
              <label className="ct-check"><input checked={showDiff} onChange={(event) => setShowDiff(event.target.checked)} type="checkbox" /> 显示 Diff</label>
              <label className="ct-check">
                翻译
                <select
                  aria-label="翻译来源"
                  onChange={(event) => {
                    const next = event.target.value as TranslateProvider;
                    translationStore.setProvider(next);
                    setProvider(next);
                  }}
                  value={provider}
                >
                  <option value="google">谷歌翻译</option>
                  <option value="llm">AI 翻译</option>
                </select>
              </label>
              <label className="ct-check"><input checked={translate} onChange={(event) => setTranslate(event.target.checked)} type="checkbox" /> 译文</label>
              <span className="ct-legend">
                <i className="origin-character origin-c1" />角色 <i className="origin-action" />动作 <i className="origin-clothing" />服装
                <i className="origin-background" />背景 <i className="origin-reference" />参考 <i className="origin-added" />新增
              </span>
            </div>

            {!detail.frames.length ? (
              <div className="ct-empty">
                <p>还没有帧。把要求 prompt 复制给外部 agent：有仓库的 agent 会直接写契约文件（这里每 5 秒检查一次）；纯对话的 agent 输出后点「导入」粘贴。</p>
              </div>
            ) : (
              <div className="ct-frames">
                {detail.frames.map((frame) => (
                  <FrameCard
                    frame={frame}
                    issues={issuesByFrame.get(frame.id) ?? []}
                    key={frame.id}
                    onGenerate={() => setPendingFrame(frame.id)}
                    onOpenImage={(images, index) => openFrameImages(frame, images, index)}
                    onSave={(prompts) => saveFrame(frame.id, prompts)}
                    onTogglePick={(image) => void togglePick(image)}
                    onViewAll={() => {
                      setBoardFocus(frame.id);
                      setBoard(true);
                    }}
                    onToggleSelect={() => setSelected((current) => {
                      const next = new Set(current);
                      if (next.has(frame.id)) next.delete(frame.id);
                      else next.add(frame.id);
                      return next;
                    })}
                    results={results?.frames[frame.id] ?? []}
                    saving={saving}
                    selected={selected.has(frame.id)}
                    showDiff={showDiff}
                    sources={detail.sources}
                    translate={translate}
                    view={view}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </section>
      </>
      )}

      <div className="ct-right-column">
        <ContractGeneratePanel
          detail={detail && !detail.parse_error ? detail : null}
          onChange={setSettings}
          onPendingHandled={() => setPendingFrame(null)}
          onSelectAll={(all) => setSelected(all && detail ? new Set(detail.frames.map((frame) => frame.id)) : new Set())}
          onSubmitted={setNotice}
          pendingFrame={pendingFrame}
          selected={selected}
          settings={settings}
        />
        <GenerationTasksPanel onOpenImage={setOpenImages} />
      </div>

      {drawerOpen && detail && !detail.parse_error ? (
        <ActionGroupDrawer detail={detail} onClose={() => setDrawerOpen(false)} onLocate={locateFrame} />
      ) : null}

      {promptModal ? (
        <div aria-label="要求 prompt" aria-modal="true" className="ct-modal" role="dialog">
          <div className="ct-modal-card">
            <header className="panel-title">
              <h2>{promptModal.kind === "tools" ? "工具版要求 prompt" : "自包含版要求 prompt"}</h2>
              <button aria-label="关闭" className="icon-button" onClick={() => setPromptModal(null)} type="button"><X size={16} /></button>
            </header>
            <p className="muted">
              {promptModal.kind === "tools"
                ? "给能访问 PromptAtelier 仓库和动作库的 agent：它直接编辑契约文件，写完把 status 改成 done，这里会自动刷新。"
                : "给纯对话的 agent：素材已内嵌。它输出帧内容后，点「导入」粘贴回来。"}
            </p>
            <div className="ct-row">
              <button className={promptModal.kind === "tools" ? "btn-sm primary" : "btn-sm"} onClick={() => detail && void showPrompt(detail.id, "tools")} type="button">工具版</button>
              <button className={promptModal.kind === "standalone" ? "btn-sm primary" : "btn-sm"} onClick={() => detail && void showPrompt(detail.id, "standalone")} type="button">自包含版</button>
              <button
                className="btn-sm"
                onClick={() => {
                  void navigator.clipboard?.writeText(promptModal.text);
                  setNotice("已复制要求 prompt");
                }}
                type="button"
              >
                <ClipboardCopy size={13} /> 复制
              </button>
            </div>
            <textarea className="ct-modal-text" readOnly value={promptModal.text} />
          </div>
        </div>
      ) : null}

      {importOpen ? (
        <div aria-label="导入帧内容" aria-modal="true" className="ct-modal" role="dialog">
          <div className="ct-modal-card">
            <header className="panel-title">
              <h2>导入帧内容</h2>
              <button aria-label="关闭" className="icon-button" onClick={() => setImportOpen(false)} type="button"><X size={16} /></button>
            </header>
            <p className="muted">粘贴外部 agent 输出的帧内容（从「## f01 …」开始；包在 ```markdown 里也可以）。会替换契约正文、写回文件并校验，status 改为 done。</p>
            <textarea className="ct-modal-text" onChange={(event) => setImportText(event.target.value)} placeholder="## f01 标题&#10;source: …" value={importText} />
            <div className="ct-row">
              <button className="primary" disabled={!importText.trim() || !detail} onClick={() => void submitImport()} type="button">导入并校验</button>
              <button onClick={() => setImportOpen(false)} type="button">取消</button>
            </div>
          </div>
        </div>
      ) : null}

      {openImages ? <ImageDetailDialog initialIndex={openImages.index} items={openImages.items} onClose={() => setOpenImages(null)} /> : null}
    </main>
  );
}
