import { ChevronDown, RotateCcw } from "lucide-react";
import type { ReactNode } from "react";

import { ComfyTargetPanel } from "../components/ComfyTargetPanel";
import { CustomGeneratePanel } from "../components/CustomGeneratePanel";
import { NodeRoleGroup } from "../components/NodeRoleGroup";
import { NodeWorkspaceEditor } from "../components/NodeWorkspaceEditor";
import { PromptBehaviorGroupPanel } from "../components/PromptBehaviorGroupPanel";
import { RenderParamsPanel } from "../components/RenderParamsPanel";
import type { NodeDocument } from "../nodes/types";
import { useCustomWorkspace } from "../workspace/CustomWorkspaceProvider";
import { artistSizePresets, workspaceMayUseComfyUI } from "../workspace/requestBuilder";

function nodeSections(node: NodeDocument | null): string[] {
  if (!node) return [];
  const tags = node.tags;
  const tagSections = tags && typeof tags === "object" && !Array.isArray(tags)
    ? Object.keys(tags as Record<string, unknown>)
    : [];
  const promptSections = node.prompt.positive
    .map((fragment) => fragment.role || "")
    .filter(Boolean);
  return [...tagSections, ...promptSections];
}

/** 配方栏里的可折叠分区。 */
function RecipeSection({ title, hint, defaultOpen = true, children }: { title: string; hint?: string; defaultOpen?: boolean; children: ReactNode }) {
  return (
    <details className="recipe-section" open={defaultOpen}>
      <summary>
        <ChevronDown className="chevron" size={15} />
        <span className="recipe-section-title">{title}</span>
        {hint ? <small>{hint}</small> : null}
      </summary>
      <div className="recipe-section-body">{children}</div>
    </details>
  );
}

export function CustomStudio() {
  const workspace = useCustomWorkspace();
  const params = workspace.state.params;
  const groups = workspace.state.groups;
  const mayUseComfyUI = workspaceMayUseComfyUI([groups.artist.primary, ...groups.artist.compares]);
  const sizePresets = artistSizePresets(groups.artist.primary);
  const characterSections = [...new Set([
    ...nodeSections(groups.character.primary.draftNode),
    ...groups.character.compares.flatMap((slot) => nodeSections(slot.draftNode)),
  ])];

  // 没在编辑节点时编辑栏只留一句提示，把位置让给右边的出图任务。
  const editor = workspace.state.editor;
  const editorIdle = !editor.slotId || (editor.kind !== "random" && !editor.draftNode);

  return (
    <main className={editorIdle ? "studio-grid custom-studio editor-idle" : "studio-grid custom-studio"}>
      <section aria-label="配方" className="panel controls-panel recipe-panel">
        <div className="panel-title recipe-title">
          <div>
            <h2>Nodes</h2>
            <small className="muted">选节点或节点组，组合出这次要跑的画面</small>
          </div>
          <button
            aria-label="清空工作区"
            className="icon-button btn-ghost"
            onClick={() => {
              if (window.confirm("清空所有节点、参数和临时修改？")) workspace.resetWorkspace();
            }}
            title="清空工作区"
            type="button"
          >
            <RotateCcw size={15} />
          </button>
        </div>
        {workspace.storageWarning ? <div className="inline-warning">{workspace.storageWarning}</div> : null}
        <NodeRoleGroup onEditSlot={workspace.openEditor} role="artist" />
        <NodeRoleGroup onEditSlot={workspace.openEditor} role="character" />
        <NodeRoleGroup onEditSlot={workspace.openEditor} role="action" />

        <RecipeSection hint="尺寸 · 轮数 · 种子" title="出图参数">
          <label className="field compact">
            <span>Negative</span>
            <textarea aria-label="Negative prompt" onChange={(event) => workspace.setParams({ negative: event.target.value })} placeholder="附加的负面提示词" value={params.negative} />
          </label>
          <RenderParamsPanel
            height={params.height}
            n={params.n}
            nt={params.nt}
            onHeightChange={(height) => workspace.setParams({ height })}
            onNChange={(n) => workspace.setParams({ n })}
            onNtChange={(nt) => workspace.setParams({ nt })}
            onSeedChange={(seed) => workspace.setParams({ seed })}
            onWidthChange={(width) => workspace.setParams({ width })}
            onSizeChange={(size) => workspace.setParams({ size })}
            seed={params.seed}
            size={params.size ?? "random"}
            sizePresets={sizePresets}
            width={params.width}
          />
          {mayUseComfyUI ? (
            <ComfyTargetPanel
              onChange={(comfyuiTarget) => workspace.setParams({ comfyuiTarget })}
              value={params.comfyuiTarget}
            />
          ) : null}
        </RecipeSection>
        <RecipeSection defaultOpen={false} hint="身份精简 · 多角色 · 规则" title="提示词行为">
          <PromptBehaviorGroupPanel characterSections={characterSections} comfyuiArtists={mayUseComfyUI} />
        </RecipeSection>
      </section>
      <NodeWorkspaceEditor />
      <CustomGeneratePanel />
    </main>
  );
}
