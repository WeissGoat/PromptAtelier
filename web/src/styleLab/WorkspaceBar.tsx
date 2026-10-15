import { Check, FolderOpen, ImagePlus, Languages, LoaderCircle, Pencil, RefreshCw, Trash2, Undo2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { LLMStatus, TranslateProvider, WorkspaceInfo } from "./api";

export const IMAGE_ACCEPT = ".png,.webp,.jpg,.jpeg";

/**
 * 新图片组的默认名字：文件名有共同开头（如 pixiv 投稿号 149600469_p0、_p1）就用它，否则用第一张的文件名，
 * 后面带张数和日期。建好后名字框会打开，可以马上改。
 */
export function suggestGroupName(files: Array<{ name: string }>, now = new Date()): string {
  const stems = files.map((file) => file.name.replace(/\.[^.]+$/, "").trim()).filter(Boolean);
  if (!stems.length) return "";
  let common = stems[0];
  for (const stem of stems.slice(1)) {
    let length = 0;
    while (length < common.length && length < stem.length && common[length] === stem[length]) length += 1;
    common = common.slice(0, length);
  }
  // 去掉末尾的分隔符和 pixiv 的 "_p"（149600469_p0、_p1 → 149600469）。
  common = common.replace(/(?:_p|[\s_\-.(（[])+$/i, "");
  const base = stems.length > 1 && common.length >= 4 ? common : stems[0];
  const short = base.length > 32 ? `${base.slice(0, 32)}…` : base;
  const date = `${now.getMonth() + 1}-${String(now.getDate()).padStart(2, "0")}`;
  return stems.length > 1 ? `${short}${base === common ? "" : " 等"} ${stems.length} 张 · ${date}` : `${short} · ${date}`;
}

type WorkspaceBarProps = {
  workspaces: WorkspaceInfo[];
  current: WorkspaceInfo | null;
  imageCount: number;
  busy: boolean;
  llm: LLMStatus | null;
  translateOn: boolean;
  translateProvider: TranslateProvider;
  translating: boolean;
  pretranslate: { done: number; total: number } | null;
  onOpenFolder: (path: string) => void;
  onCreateGroup: (files: File[]) => void;
  onSelectWorkspace: (id: string) => void;
  onRename: (name: string) => Promise<boolean>;
  /** 删除当前工作区（确认后调用）。 */
  onDelete: () => void;
  onRescan: () => void;
  onRestoreImages: () => void;
  onToggleTranslate: () => void;
  onChangeProvider: (provider: TranslateProvider) => void;
  /** 每加一，就打开当前工作区的改名框（新建图片组之后）。 */
  renameRequest?: number;
};

export function WorkspaceBar({
  workspaces,
  current,
  imageCount,
  busy,
  llm,
  translateOn,
  translateProvider,
  translating,
  pretranslate,
  onOpenFolder,
  onCreateGroup,
  onSelectWorkspace,
  onRename,
  onDelete,
  onRescan,
  onRestoreImages,
  onToggleTranslate,
  onChangeProvider,
  renameRequest = 0,
}: WorkspaceBarProps) {
  const [path, setPath] = useState("");
  // 正在改名时是输入框里的名字，否则 null。
  const [renaming, setRenaming] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const currentName = current?.name ?? null;
  useEffect(() => {
    if (renameRequest && currentName !== null) setRenaming(currentName);
    // 只响应新的请求；之后切换工作区不再自动打开。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [renameRequest]);
  const llmReady = Boolean(llm?.available);
  // 谷歌翻译不用配置；AI 翻译要先配好 LLM。
  const translateReady = translateProvider === "google" || llmReady;
  const excluded = current?.excluded?.length ?? 0;

  return (
    <header className="sl-bar">
      <form
        className="sl-bar-open"
        onSubmit={(event) => {
          event.preventDefault();
          if (path.trim()) {
            onOpenFolder(path.trim());
          }
        }}
      >
        <FolderOpen size={16} aria-hidden="true" />
        <input
          aria-label="文件夹路径"
          onChange={(event) => setPath(event.target.value)}
          placeholder="F:\my_project\new\tags_machine\artist_parse\20260717\105845157"
          value={path}
        />
        <button disabled={busy} type="submit">
          打开文件夹
        </button>
      </form>
      <button
        className="sl-ghost"
        disabled={busy}
        onClick={() => fileRef.current?.click()}
        title="选几张图片建一个新的图片组（也可以把图片拖进页面）"
        type="button"
      >
        <ImagePlus size={15} aria-hidden="true" />
        新建图片组
      </button>
      <input
        accept={IMAGE_ACCEPT}
        aria-label="选择图片新建图片组"
        hidden
        multiple
        onChange={(event) => {
          const files = [...(event.target.files ?? [])];
          event.target.value = "";
          if (files.length) onCreateGroup(files);
        }}
        ref={fileRef}
        type="file"
      />
      {current && renaming !== null ? (
        <form
          className="sl-bar-rename"
          onSubmit={(event) => {
            event.preventDefault();
            if (!renaming.trim() || renaming.trim() === current.name) {
              setRenaming(null);
              return;
            }
            void onRename(renaming.trim()).then((ok) => ok && setRenaming(null));
          }}
        >
          <input
            aria-label="工作区名称"
            autoFocus
            maxLength={80}
            onChange={(event) => setRenaming(event.target.value)}
            onFocus={(event) => event.target.select()}
            onKeyDown={(event) => event.key === "Escape" && setRenaming(null)}
            placeholder="给这组图片起个名字"
            value={renaming}
          />
          <button aria-label="保存名称" className="sl-icon-btn" disabled={busy || !renaming.trim()} title="保存（Enter）" type="submit">
            <Check size={15} />
          </button>
          <button aria-label="取消改名" className="sl-icon-btn" onClick={() => setRenaming(null)} title="取消（Esc）" type="button">
            <X size={15} />
          </button>
        </form>
      ) : (
        <select
          aria-label="最近的工作区"
          className="sl-bar-recent"
          onChange={(event) => event.target.value && onSelectWorkspace(event.target.value)}
          value={current?.id ?? ""}
        >
          <option value="">最近的工作区…</option>
          {workspaces.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      )}
      {current && renaming === null ? (
        <button
          aria-label="改名"
          className="sl-icon-btn"
          disabled={busy}
          onClick={() => setRenaming(current.name)}
          title={current.kind === "files" ? "给这个图片组改名" : "给这个工作区改名（文件夹本身不改）"}
          type="button"
        >
          <Pencil size={14} />
        </button>
      ) : null}
      {current && renaming === null ? (
        <button
          aria-label="删除工作区"
          className="sl-icon-btn danger"
          disabled={busy}
          onClick={() => {
            const message =
              current.kind === "files"
                ? `删除图片组「${current.name}」？

拖进来的图片副本、配方和出图会一起移到 runtime/stylelab/trash/（需要时还能找回），你电脑上的原图不受影响。`
                : `从列表移除「${current.name}」？

只是不再显示在列表里，文件夹和其中的 .stylelab（配方、出图）都不动，重新打开这个文件夹就回来。`;
            if (window.confirm(message)) onDelete();
          }}
          title={current.kind === "files" ? "删除这个图片组" : "从列表移除（文件夹不动）"}
          type="button"
        >
          <Trash2 size={14} />
        </button>
      ) : null}
      {current ? (
        <span className="sl-bar-meta" title={current.root}>
          {imageCount} 张
          {excluded ? (
            <button className="sl-link-btn" disabled={busy} onClick={onRestoreImages} title="把从工作区移除的图片放回来" type="button">
              <Undo2 size={13} aria-hidden="true" />
              恢复移除的 {excluded} 张
            </button>
          ) : null}
          <button aria-label="重新扫描" className="sl-icon-btn" disabled={busy} onClick={onRescan} title="重新扫描" type="button">
            {busy ? <LoaderCircle className="sl-spin" size={15} /> : <RefreshCw size={15} />}
          </button>
        </span>
      ) : null}
      <span className="sl-bar-spacer" />
      {pretranslate && pretranslate.done < pretranslate.total ? (
        <span className="sl-bar-progress">
          分析 {pretranslate.done}/{pretranslate.total}
        </span>
      ) : null}
      <select
        aria-label="翻译来源"
        className="sl-bar-provider"
        onChange={(event) => onChangeProvider(event.target.value as TranslateProvider)}
        title="谷歌翻译免费、不用配置；AI 翻译更懂 danbooru tag（画师名、角色名）"
        value={translateProvider}
      >
        <option value="google">谷歌翻译</option>
        <option disabled={!llmReady} value="llm">
          AI 翻译{llmReady ? "" : "（未配置）"}
        </option>
      </select>
      <button
        className={`sl-toggle ${translateOn && translateReady ? "on" : ""}`}
        disabled={!translateReady}
        onClick={onToggleTranslate}
        title={translateReady ? "显示 tag 的中文" : "没有配置 LLM（configs/local.yaml 的 llm 段）"}
        type="button"
      >
        {translating ? <LoaderCircle className="sl-spin" size={15} /> : <Languages size={15} />}
        译文{translateOn && translateReady ? "开" : "关"}
      </button>
    </header>
  );
}
