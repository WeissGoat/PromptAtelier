import { FolderOpen, Languages, LoaderCircle, RefreshCw } from "lucide-react";
import { useState } from "react";

import type { LLMStatus, WorkspaceInfo } from "./api";

type WorkspaceBarProps = {
  workspaces: WorkspaceInfo[];
  current: WorkspaceInfo | null;
  imageCount: number;
  busy: boolean;
  llm: LLMStatus | null;
  translateOn: boolean;
  translating: boolean;
  pretranslate: { done: number; total: number } | null;
  onOpenFolder: (path: string) => void;
  onSelectWorkspace: (id: string) => void;
  onRescan: () => void;
  onToggleTranslate: () => void;
};

export function WorkspaceBar({
  workspaces,
  current,
  imageCount,
  busy,
  llm,
  translateOn,
  translating,
  pretranslate,
  onOpenFolder,
  onSelectWorkspace,
  onRescan,
  onToggleTranslate,
}: WorkspaceBarProps) {
  const [path, setPath] = useState("");
  const llmReady = Boolean(llm?.available);

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
          <button aria-label="重新扫描" className="sl-icon-btn" disabled={busy} onClick={onRescan} title="重新扫描" type="button">
            {busy ? <LoaderCircle className="sl-spin" size={15} /> : <RefreshCw size={15} />}
          </button>
        </span>
      ) : null}
      <span className="sl-bar-spacer" />
      {pretranslate && pretranslate.done < pretranslate.total ? (
        <span className="sl-bar-progress">
          预翻译 {pretranslate.done}/{pretranslate.total}
        </span>
      ) : null}
      <button
        className={`sl-toggle ${translateOn && llmReady ? "on" : ""}`}
        disabled={!llmReady}
        onClick={onToggleTranslate}
        title={llmReady ? `翻译：${llm?.models.text ?? ""}` : "没有配置 LLM（configs/local.yaml 的 llm 段）"}
        type="button"
      >
        {translating ? <LoaderCircle className="sl-spin" size={15} /> : <Languages size={15} />}
        译文{translateOn && llmReady ? "开" : "关"}
      </button>
    </header>
  );
}
