import { CustomGeneratePanel } from "../components/CustomGeneratePanel";
import { NodeRoleGroup } from "../components/NodeRoleGroup";
import { NodeWorkspaceEditor } from "../components/NodeWorkspaceEditor";
import { PromptBehaviorPanel } from "../components/PromptBehaviorPanel";
import { RenderParamsPanel } from "../components/RenderParamsPanel";
import type { NodeDocument } from "../nodes/types";
import { useCustomWorkspace } from "../workspace/CustomWorkspaceProvider";

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

export function CustomStudio() {
  const workspace = useCustomWorkspace();
  const params = workspace.state.params;
  const groups = workspace.state.groups;
  const characterSections = [...new Set([
    ...nodeSections(groups.character.primary.draftNode),
    ...groups.character.compares.flatMap((slot) => nodeSections(slot.draftNode)),
  ])];

  return (
    <main className="studio-grid">
      <section className="panel controls-panel">
        <div className="panel-title"><h2>Nodes</h2></div>
        <NodeRoleGroup onEditSlot={workspace.openEditor} role="artist" />
        <NodeRoleGroup onEditSlot={workspace.openEditor} role="character" />
        <NodeRoleGroup onEditSlot={workspace.openEditor} role="action" />
        <label className="field compact">
          <span>Negative</span>
          <textarea aria-label="Negative prompt" onChange={(event) => workspace.setParams({ negative: event.target.value })} value={params.negative} />
        </label>
        <RenderParamsPanel
          height={params.height}
          nt={params.nt}
          onHeightChange={(height) => workspace.setParams({ height })}
          onNtChange={(nt) => workspace.setParams({ nt })}
          onSeedChange={(seed) => workspace.setParams({ seed })}
          onWidthChange={(width) => workspace.setParams({ width })}
          seed={params.seed}
          width={params.width}
        />
        <PromptBehaviorPanel
          characterSections={characterSections}
          onChange={workspace.setPromptBehavior}
          value={workspace.state.promptBehavior}
        />
      </section>
      <NodeWorkspaceEditor />
      <CustomGeneratePanel />
    </main>
  );
}
