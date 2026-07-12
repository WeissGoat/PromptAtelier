import { CustomGeneratePanel } from "../components/CustomGeneratePanel";
import { NodeRoleGroup } from "../components/NodeRoleGroup";
import { NodeWorkspaceEditor } from "../components/NodeWorkspaceEditor";
import { RenderParamsPanel } from "../components/RenderParamsPanel";
import { useCustomWorkspace } from "../workspace/CustomWorkspaceProvider";

export function CustomStudio() {
  const workspace = useCustomWorkspace();
  const params = workspace.state.params;

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
      </section>
      <NodeWorkspaceEditor />
      <CustomGeneratePanel />
    </main>
  );
}
