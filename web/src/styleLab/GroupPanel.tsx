import { FlaskConical, LoaderCircle } from "lucide-react";

import type { Analysis, RecipeSummary } from "./api";
import { modelLabel, vibeLabel } from "./format";

type GroupPanelProps = {
  analysis: Analysis | null;
  llmAvailable: boolean;
  analyzing: { done: number; total: number } | null;
  selectedGroup: string | null;
  recipes: RecipeSummary[];
  onSelectGroup: (id: string | null) => void;
  onOpenRecipe: (id: string) => void;
};

function vibeText(vibe: string): string {
  if (vibe === "no_vibe") return "无 vibe";
  if (vibe === "missing") return "缺 vibe 图";
  return vibeLabel(vibe.replace(/^vibe_/, "").split("_").join("+"));
}

function dateRange(from: string | null, to: string | null): string {
  if (!from) return "";
  return from === to ? from : `${from} → ${to}`;
}

/** 左栏：自动分组（画风家族 → 稳定变体 / vibe / 模型，按投稿计数）和配方列表。 */
export function GroupPanel({ analysis, llmAvailable, analyzing, selectedGroup, recipes, onSelectGroup, onOpenRecipe }: GroupPanelProps) {
  const groups = analysis?.groups ?? [];
  return (
    <section className="sl-groups">
      <div className="sl-groups-head">
        <h3>分组</h3>
        {analyzing ? (
          <span className="sl-muted" title="翻译和 tag 分类在后台进行，分组会逐步变准">
            <LoaderCircle className="sl-spin" size={12} /> 分析 {analyzing.done}/{analyzing.total}
          </span>
        ) : analysis ? (
          <span className="sl-muted" title="已分类的 tag / 全部 tag">
            {analysis.classified}/{analysis.total_tags} tag
          </span>
        ) : null}
      </div>
      {!llmAvailable ? <p className="sl-hint">没有配置 LLM，只能按规则识别画师（artist: 前缀）。</p> : null}
      <button className={`sl-group-row ${selectedGroup === null ? "on" : ""}`} onClick={() => onSelectGroup(null)} type="button">
        <span>全部图片</span>
      </button>
      {groups.map((group) => (
        <div className="sl-group" key={group.id}>
          <button
            className={`sl-group-row main ${selectedGroup === group.id ? "on" : ""}`}
            onClick={() => onSelectGroup(group.id)}
            title={group.signature.map((item) => `${item.tag}（${item.posts}）`).join("\n")}
            type="button"
          >
            <span className="sl-group-name">{group.name}</span>
            <span className="sl-count">{group.post_count}</span>
          </button>
          <span className="sl-group-dates">{dateRange(group.date_from, group.date_to)}</span>
          {group.children.length > 1 || group.children[0]?.variant ? (
            group.children.map((child) => (
              <button
                className={`sl-group-row child ${selectedGroup === child.id ? "on" : ""}`}
                key={child.id}
                onClick={() => onSelectGroup(child.id)}
                type="button"
              >
                <span className="sl-group-name">
                  {[child.variant, vibeText(child.vibe), modelLabel(child.model)].filter(Boolean).join(" · ")}
                </span>
                <span className="sl-count">{child.post_count}</span>
              </button>
            ))
          ) : group.children[0] ? (
            <span className="sl-group-dates">
              {vibeText(group.children[0].vibe)} · {modelLabel(group.children[0].model)}
            </span>
          ) : null}
        </div>
      ))}

      <div className="sl-groups-head">
        <h3>配方</h3>
        <span className="sl-muted">{recipes.length}</span>
      </div>
      {recipes.length === 0 ? <p className="sl-hint">选一张图，在右侧点“从这张图新建配方”。</p> : null}
      {recipes.map((recipe) => (
        <button className="sl-recipe-link" key={recipe.id} onClick={() => onOpenRecipe(recipe.id)} type="button">
          <FlaskConical size={13} aria-hidden="true" />
          <span>{recipe.name}</span>
          <span className="sl-count">{recipe.stage === "split" ? "待划分" : `v${recipe.version}`}</span>
        </button>
      ))}
    </section>
  );
}

/** 选中的分组（或子分组）包含的图片 id；null 表示不按分组筛选。 */
export function groupImageIds(analysis: Analysis | null, groupId: string | null): Set<string> | null {
  if (!analysis || !groupId) return null;
  for (const group of analysis.groups) {
    if (group.id === groupId) return new Set(group.image_ids);
    const child = group.children.find((item) => item.id === groupId);
    if (child) return new Set(child.image_ids);
  }
  return null;
}

/** 一张图所在的最细分组 id（新建配方时记下来，用于同组词频）。 */
export function groupOfImage(analysis: Analysis | null, imageId: string): string | null {
  for (const group of analysis?.groups ?? []) {
    const child = group.children.find((item) => item.image_ids.includes(imageId));
    if (child) return child.id;
    if (group.image_ids.includes(imageId)) return group.id;
  }
  return null;
}
