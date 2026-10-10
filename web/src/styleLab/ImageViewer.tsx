/**
 * 图片详情：大图查看（适应窗口 / 原始大小）、前后切换、文件信息，以及在资源管理器里打开所在位置。
 * 页面里任何地方都通过 useImageViewer().open(items, index) 打开。
 */
import { ChevronLeft, ChevronRight, Copy, ExternalLink, FolderOpen, Maximize2, Minimize2, X } from "lucide-react";
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { errorMessage } from "../api/client";
import type { ImageRecord, WorkspaceFileInfo, WorkspaceFileRef } from "./api";
import { getFileInfo, revealFile, workspaceFileUrl } from "./api";
import { fileName, formatTime, modelLabel } from "./format";

export type ViewerItem = {
  file: WorkspaceFileRef;
  label: string;
  /** 完整路径；出图结果没有时用 file.path。 */
  path?: string;
  details?: Array<[string, string]>;
};

type ViewerApi = { open(items: ViewerItem[], index?: number): void };

const ViewerContext = createContext<ViewerApi>({ open: () => undefined });

export function useImageViewer(): ViewerApi {
  return useContext(ViewerContext);
}

export function sourceViewerItem(image: ImageRecord, label = "原图"): ViewerItem {
  const details: Array<[string, string]> = [["模型", modelLabel(image.model)]];
  if (image.seed !== null) details.push(["种子", String(image.seed)]);
  if (image.steps !== null) details.push(["步数", String(image.steps)]);
  if (image.scale !== null) details.push(["CFG", String(image.scale)]);
  if (image.sampler) details.push(["采样器", image.sampler]);
  if (image.post?.title) details.push(["投稿", image.post.title]);
  return { file: { imageId: image.id }, label, path: image.path, details };
}

export function runViewerItem(imagePath: string, label: string, seed?: number | null): ViewerItem {
  return { file: { path: imagePath }, label, details: seed === undefined || seed === null ? [] : [["种子", String(seed)]] };
}

export function ImageViewerProvider({ workspaceId, children }: { workspaceId: string; children: ReactNode }) {
  const [state, setState] = useState<{ items: ViewerItem[]; index: number } | null>(null);
  const api = useMemo<ViewerApi>(
    () => ({ open: (items, index = 0) => (items.length ? setState({ items, index: Math.min(index, items.length - 1) }) : undefined) }),
    [],
  );
  return (
    <ViewerContext.Provider value={api}>
      {children}
      {state ? (
        <ImageViewer
          index={state.index}
          items={state.items}
          onClose={() => setState(null)}
          onIndex={(index) => setState({ ...state, index })}
          workspaceId={workspaceId}
        />
      ) : null}
    </ViewerContext.Provider>
  );
}

function ImageViewer({
  workspaceId,
  items,
  index,
  onIndex,
  onClose,
}: {
  workspaceId: string;
  items: ViewerItem[];
  index: number;
  onIndex: (index: number) => void;
  onClose: () => void;
}) {
  const item = items[index];
  const [actual, setActual] = useState(false);
  const [natural, setNatural] = useState<{ width: number; height: number } | null>(null);
  const [status, setStatus] = useState<{ text: string; error?: boolean } | null>(null);
  const [info, setInfo] = useState<WorkspaceFileInfo | null>(null);
  const path = info?.path ?? item.path ?? ("path" in item.file ? item.file.path : "");
  const fullUrl = workspaceFileUrl(workspaceId, item.file);

  useEffect(() => {
    setNatural(null);
    setStatus(null);
    setInfo(null);
    let alive = true;
    // 出图结果在记录里是相对路径；这里换成绝对路径，顺带拿文件大小和修改时间。
    getFileInfo(workspaceId, item.file)
      .then((result) => alive && setInfo(result))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [workspaceId, item.file]);

  useEffect(() => {
    // 捕获阶段处理并拦下，页面上 ← / → 切换选中图片的快捷键不会同时触发。
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
      else if (event.key === "ArrowLeft" && index > 0) onIndex(index - 1);
      else if (event.key === "ArrowRight" && index < items.length - 1) onIndex(index + 1);
      else return;
      event.preventDefault();
      event.stopPropagation();
    }
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [index, items.length, onClose, onIndex]);

  async function reveal() {
    setStatus({ text: "正在打开…" });
    try {
      await revealFile(workspaceId, item.file);
      setStatus({ text: "已在资源管理器中打开" });
    } catch (error) {
      setStatus({ text: errorMessage(error), error: true });
    }
  }

  async function copyPath() {
    try {
      await navigator.clipboard.writeText(path);
      setStatus({ text: "路径已复制" });
    } catch {
      setStatus({ text: "复制失败，请手动选中路径复制", error: true });
    }
  }

  return (
    <div className="sl-viewer" onClick={onClose} role="presentation">
      <section aria-label="图片详情" aria-modal="true" className="sl-viewer-panel" onClick={(event) => event.stopPropagation()} role="dialog">
        <header className="sl-viewer-bar">
          <strong>{item.label}</strong>
          {items.length > 1 ? (
            <span className="sl-muted">
              {index + 1} / {items.length}
            </span>
          ) : null}
          <span className="sl-viewer-name" title={path}>
            {fileName(path)}
          </span>
          <span className="sl-bar-spacer" />
          <button className="sl-ghost" onClick={() => setActual(!actual)} title="切换适应窗口 / 原始大小（也可以点图片）" type="button">
            {actual ? <Minimize2 size={14} aria-hidden="true" /> : <Maximize2 size={14} aria-hidden="true" />}
            {actual ? "适应窗口" : "原始大小"}
          </button>
          <button className="sl-ghost" onClick={() => void reveal()} type="button">
            <FolderOpen size={14} aria-hidden="true" />
            打开所在位置
          </button>
          <button className="sl-ghost" disabled={!path} onClick={() => void copyPath()} type="button">
            <Copy size={14} aria-hidden="true" />
            复制路径
          </button>
          <a aria-label="在新标签页打开" className="sl-icon-btn" href={fullUrl} rel="noreferrer" target="_blank" title="在新标签页打开">
            <ExternalLink size={15} />
          </a>
          <button aria-label="关闭" className="sl-icon-btn" onClick={onClose} title="关闭（Esc）" type="button">
            <X size={16} />
          </button>
        </header>

        <div className="sl-viewer-stage">
          <div className={`sl-viewer-scroll ${actual ? "actual" : ""}`}>
            <img
              alt={item.label}
              onClick={() => setActual(!actual)}
              onLoad={(event) => setNatural({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })}
              src={fullUrl}
            />
          </div>
          {index > 0 ? (
            <button aria-label="上一张" className="sl-viewer-nav prev" onClick={() => onIndex(index - 1)} title="上一张（←）" type="button">
              <ChevronLeft size={22} />
            </button>
          ) : null}
          {index < items.length - 1 ? (
            <button aria-label="下一张" className="sl-viewer-nav next" onClick={() => onIndex(index + 1)} title="下一张（→）" type="button">
              <ChevronRight size={22} />
            </button>
          ) : null}
        </div>

        <footer className="sl-viewer-info">
          {natural ? <span>{`${natural.width}×${natural.height}`}</span> : null}
          {info ? <span>{formatBytes(info.size_bytes)}</span> : null}
          {info ? (
            <span>
              <span className="sl-muted">修改</span> {formatTime(info.modified_at)}
            </span>
          ) : null}
          {(item.details ?? []).map(([label, value]) => (
            <span key={label}>
              <span className="sl-muted">{label}</span> {value}
            </span>
          ))}
          <span className="sl-viewer-path" title={path}>
            {path}
          </span>
          {status ? <span className={status.error ? "sl-error-text" : "sl-ok-text"}>{status.text}</span> : null}
        </footer>
      </section>
    </div>
  );
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}
