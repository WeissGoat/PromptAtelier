import { useEffect, useState } from "react";
import { errorMessage } from "../api/client";
import type { RecipeSummary, TestPlan } from "./api";
import { cancelJob, createTestPlan, getTestPlan, listTestPlans, runImageUrl, startTestPlan } from "./api";
import { preparationLabels } from "./customGroups";

type Props = { workspaceId: string; recipes: RecipeSummary[]; initialIds: string[]; onClose: () => void };
const labels: Record<string, string> = { draft: "待开始", awaiting_content: "待准备测试内容", queued: "排队中", running: "测试中", succeeded: "完成", partial: "部分完成，需检查", failed: "失败", cancelled: "已取消", interrupted: "已中断", pending: "待执行", skipped: "已跳过" };

export function TestPlansDialog({ workspaceId, recipes, initialIds, onClose }: Props) {
  const [selected, setSelected] = useState(initialIds);
  const [includeMaterials, setIncludeMaterials] = useState(true);
  const [plan, setPlan] = useState<TestPlan | null>(null);
  const [plans, setPlans] = useState<TestPlan[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let cancelled = false;
    void listTestPlans(workspaceId).then((result) => { if (!cancelled) setPlans(result.plans); }).catch((exc) => { if (!cancelled) setError(errorMessage(exc)); });
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", escape);
    return () => { cancelled = true; window.removeEventListener("keydown", escape); };
  }, [workspaceId, onClose]);
  useEffect(() => {
    if (!plan || !["queued", "running", "cancelling"].includes(plan.status)) return;
    let cancelled = false;
    const timer = window.setInterval(() => void getTestPlan(workspaceId, plan.id).then((next) => { if (!cancelled) setPlan(next); }).catch((exc) => { if (!cancelled) setError(errorMessage(exc)); }), 1500);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [workspaceId, plan?.id, plan?.status]);
  const submit = async (start: boolean) => {
    setBusy(true); setError(null);
    try { setPlan(start && plan ? await startTestPlan(workspaceId, plan.id) : await createTestPlan(workspaceId, selected, includeMaterials)); }
    catch (exc) { setError(errorMessage(exc)); }
    finally { setBusy(false); }
  };
  const task = `$style-lab 测试工作区 ${workspaceId} 的配方 ${selected.join("、")}。先准备当前素材架的角色与动作变体，使用原图种子和生成尺寸，通过 test-plans 创建快照计划并开始测试，不修改保存配方。`;

  return <div className="sl-workflow-overlay"><section aria-label="测试选定配方" aria-modal="true" className="sl-workflow-dialog" role="dialog">
    <header><h2>第二步：测试选定配方</h2><button onClick={onClose} type="button">关闭</button></header>
    <p>先选择配方并预览计划，再开始出图。原参重生、配方原图内容和素材变体均沿用原图种子与生成尺寸。</p>
    {error ? <p className="sl-error" role="alert">{error}</p> : null}
    <div className="sl-test-picks">{recipes.map((recipe) => <label className="sl-check" key={recipe.id}>
      <input checked={selected.includes(recipe.id)} disabled={recipe.preparation?.status !== undefined && recipe.preparation.status !== "ready"} onChange={(event) => {
        setSelected((current) => event.target.checked ? [...current, recipe.id] : current.filter((id) => id !== recipe.id)); setPlan(null);
      }} type="checkbox" />{recipe.name} · {recipe.preparation ? preparationLabels[recipe.preparation.status] : `v${recipe.version}`} {recipe.preparation?.reason}
    </label>)}</div>
    <label className="sl-check"><input checked={includeMaterials} onChange={(event) => { setIncludeMaterials(event.target.checked); setPlan(null); }} type="checkbox" />同时测试当前素材架的角色和动作（每配方最多 3 个组合）</label>
    <div className="sl-workflow-actions"><button disabled={busy || !selected.length} onClick={() => void submit(false)} type="button">预览测试计划</button></div>
    {plan ? <section aria-label="测试计划预览">
      <h3>{labels[plan.status] ?? plan.status} · {plan.estimated_count} 项 / 可复用 {plan.reuse_count} 项</h3>
      <p>素材快照：{plan.shelf.materials.map((material) => material.name).join("、") || "未选素材，只测试原参与配方原图"}</p>
      {plan.status === "awaiting_content" ? <div className="sl-banner"><p>角色/动作测试词尚未准备。将下面任务交给 Agent，或取消素材测试来运行前两项。</p><textarea aria-label="Agent 测试任务" readOnly value={task} /></div> : null}
      {plan.items.map((item) => <details className="sl-plan-item" key={item.id}>
        <summary>{plan.recipes[item.recipe_id]?.name} · {item.label} · {labels[item.status] ?? item.status}{item.reused ? " · 复用已有结果" : ""}</summary>
        <p>种子 {item.preview.seed} · {item.preview.size?.width}×{item.preview.size?.height} · {item.preview.model}</p>
        <pre>{item.preview.prompt}</pre><p>负面：{item.preview.negative_prompt}</p>
        {item.error ? <p role="alert">{item.error}</p> : null}
        {item.blocks_following ? <p>原参对照有差异，已暂停该源图的后续测试。</p> : null}
        {item.results?.map((result) => result.image_path ? <a href={runImageUrl(workspaceId, result.image_path)} key={result.index} rel="noreferrer" target="_blank"><img alt={item.label} src={runImageUrl(workspaceId, result.image_path, 320)} /></a> : <p key={result.index}>{result.error}</p>)}
      </details>)}
      <button className="sl-primary" disabled={busy || ["awaiting_content", "queued", "running", "succeeded"].includes(plan.status)} onClick={() => void submit(true)} type="button">{["partial", "failed", "interrupted", "cancelled"].includes(plan.status) ? "继续未完成的测试" : "开始测试生图"}</button>
      {plan.job_id && ["queued", "running"].includes(plan.status) ? <button onClick={() => void cancelJob(plan.job_id!).catch((exc) => setError(errorMessage(exc)))} type="button">停止测试</button> : null}
    </section> : null}
    {plans.length ? <section><h3>已有测试计划</h3>{plans.map((item) => <button className="sl-group-row" key={item.id} onClick={() => { setPlan(item); setSelected(item.recipe_ids); }} type="button">{item.id} · {labels[item.status] ?? item.status}</button>)}</section> : null}
  </section></div>;
}
