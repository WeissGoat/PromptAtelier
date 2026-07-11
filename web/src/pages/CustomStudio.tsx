import { CustomGeneratePanel } from "../components/CustomGeneratePanel";
import { NodeRoleGroup } from "../components/NodeRoleGroup";
import { editorHasChanges, NodeWorkspaceEditor } from "../components/NodeWorkspaceEditor";
import { RenderParamsPanel } from "../components/RenderParamsPanel";
import { useCustomWorkspace } from "../workspace/CustomWorkspaceProvider";

export function CustomStudio() {
  const workspace = useCustomWorkspace();
  const params = workspace.state.params;

  function openNodeEditor(slotId: string) {
    const editor = workspace.state.editor;
    if (
      editor.slotId
      && editor.slotId !== slotId
      && editorHasChanges(editor.draftNode, editor.baselineNode)
      && !window.confirm("当前节点编辑尚未应用，切换后会丢失这些修改。是否继续？")
    ) return;
    workspace.openEditor(slotId);
  }

  return (
    <main className="studio-grid">
      <section className="panel controls-panel">
        <div className="panel-title"><h2>Nodes</h2></div>
        <NodeRoleGroup onEditSlot={openNodeEditor} role="artist" />
        <NodeRoleGroup onEditSlot={openNodeEditor} role="character" />
        <NodeRoleGroup onEditSlot={openNodeEditor} role="action" />
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
