import { FolderOpen, ImagePlus, Languages, LoaderCircle, RefreshCw, Undo2 } from "lucide-react";
import { useRef, useState } from "react";

import type { LLMStatus, TranslateProvider, WorkspaceInfo } from "./api";

export const IMAGE_ACCEPT = ".png,.webp,.jpg,.jpeg";

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
  onRescan: () => void;
  onRestoreImages: () => void;
  onToggleTranslate: () => void;
  onChangeProvider: (provider: TranslateProvider) => void;
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
  onRescan,
  onRestoreImages,
  onToggleTranslate,
  onChangeProvider,
}: WorkspaceBarProps) {
  const [path, setPath] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
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
