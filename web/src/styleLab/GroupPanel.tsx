import { FlaskConical, GitCompareArrows, LoaderCircle } from "lucide-react";

import type { Analysis, ImageRecord, RecipeSummary } from "./api";
import { modelLabel, vibeLabel } from "./format";

/** 分组方式：画风（自动分析出的画风家族），或者按投稿、按月份（作者投稿文件夹才有）。 */
export type GroupMode = "style" | "post" | "month";

/** 按投稿或月份分出的一组图；id 带上方式前缀（post: / month:），和画风分组的 id 区分开。 */
export type ImageBucket = { id: string; name: string; sub: string; imageIds: string[]; posts: number };

const GROUP_MODES: Array<[GroupMode, string]> = [
  ["style", "画风"],
  ["post", "投稿"],
  ["month", "月份"],
];

type GroupPanelProps = {
  analysis: Analysis | null;
  llmAvailable: boolean;
  analyzing: { done: number; total: number } | null;
  mode: GroupMode;
  /** 投稿 / 月份分组；空数组表示不是投稿文件夹，不显示切换。 */
  postBuckets: ImageBucket[];
  monthBuckets: ImageBucket[];
  selectedGroup: string | null;
  recipes: RecipeSummary[];
  onChangeMode: (mode: GroupMode) => void;
  onSelectGroup: (id: string | null) => void;
  onOpenRecipe: (id: string) => void;
  /** 打开配方对比（两个以上配方时显示）。 */
  onCompareRecipes?: () => void;
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

/** 左栏：分组（画风家族 → 稳定变体 / vibe / 模型，按投稿计数；或按投稿、按月份）和配方列表。 */
export function GroupPanel({
  analysis,
  llmAvailable,
  analyzing,
  mode,
  postBuckets,
  monthBuckets,
  selectedGroup,
  recipes,
  onChangeMode,
  onSelectGroup,
  onOpenRecipe,
  onCompareRecipes,
}: GroupPanelProps) {
  const groups = analysis?.groups ?? [];
  const hasPosts = postBuckets.length > 0;
  const shown: GroupMode = hasPosts ? mode : "style";
  const buckets = shown === "post" ? postBuckets : monthBuckets;
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
      {hasPosts ? (
        <div className="sl-segmented small sl-group-modes" role="radiogroup" aria-label="分组方式">
          {GROUP_MODES.map(([key, label]) => (
            <button
              aria-checked={shown === key}
              className={shown === key ? "on" : ""}
              key={key}
              onClick={() => onChangeMode(key)}
              role="radio"
              type="button"
            >
              {label}
            </button>
          ))}
        </div>
      ) : null}
      {shown === "style" && !llmAvailable ? <p className="sl-hint">没有配置 LLM，只能按规则识别画师（artist: 前缀）。</p> : null}
      <button className={`sl-group-row ${selectedGroup === null ? "on" : ""}`} onClick={() => onSelectGroup(null)} type="button">
        <span>全部图片</span>
      </button>
      {shown !== "style" ? (
        <div className="sl-bucket-list">
          {buckets.map((bucket) => (
            <button
              className={`sl-group-row bucket ${selectedGroup === bucket.id ? "on" : ""}`}
              key={bucket.id}
              onClick={() => onSelectGroup(bucket.id)}
              title={[bucket.name, bucket.sub].filter(Boolean).join("\n")}
              type="button"
            >
              <span className="sl-bucket-text">
                <span className="sl-group-name">{bucket.name}</span>
                {bucket.sub ? <span className="sl-group-dates">{bucket.sub}</span> : null}
              </span>
              <span className="sl-count" title={`${bucket.imageIds.length} 张`}>
                {bucket.imageIds.length}
              </span>
            </button>
          ))}
        </div>
      ) : null}
      {(shown === "style" ? groups : []).map((group) => (
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
        {onCompareRecipes && recipes.length > 1 ? (
          <button className="sl-link-btn" onClick={onCompareRecipes} title="两个配方逐区对比 tag 和参数" type="button">
            <GitCompareArrows size={13} aria-hidden="true" />
            对比
          </button>
        ) : null}
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

/** 按投稿分组，顺序和图片网格一致；没有投稿信息（散图、拖进来的图片组）时返回空数组。 */
export function postBuckets(images: ImageRecord[]): ImageBucket[] {
  if (!images.some((image) => image.post)) return [];
  const buckets = new Map<string, ImageBucket>();
  for (const image of images) {
    const key = image.post?.dir_name ?? "";
    let bucket = buckets.get(key);
    if (!bucket) {
      bucket = {
        id: `post:${key}`,
        name: image.post ? image.post.title || image.post.dir_name : "散图",
        sub: [image.post?.date, image.post?.post_id].filter(Boolean).join(" · "),
        imageIds: [],
        posts: 1,
      };
      buckets.set(key, bucket);
    }
    bucket.imageIds.push(image.id);
  }
  return [...buckets.values()];
}

/** 按投稿日期的月份分组，从早到晚；没有日期的放最后。 */
export function monthBuckets(images: ImageRecord[]): ImageBucket[] {
  if (!images.some((image) => image.post)) return [];
  const buckets = new Map<string, ImageBucket & { dirs: Set<string> }>();
  for (const image of images) {
    const key = /^\d{4}-\d{2}/.test(image.post?.date ?? "") ? image.post!.date!.slice(0, 7) : "";
    let bucket = buckets.get(key);
    if (!bucket) {
      const [year, month] = key.split("-");
      bucket = { id: `month:${key}`, name: key ? `${year} 年 ${Number(month)} 月` : "没有日期", sub: "", imageIds: [], posts: 0, dirs: new Set() };
      buckets.set(key, bucket);
    }
    bucket.imageIds.push(image.id);
    bucket.dirs.add(image.post?.dir_name ?? image.rel_path);
  }
  return [...buckets.entries()]
    .sort(([a], [b]) => (a && b ? a.localeCompare(b) : a ? -1 : b ? 1 : 0))
    .map(([, { dirs, ...bucket }]) => ({ ...bucket, posts: dirs.size, sub: `${dirs.size} 个投稿` }));
}

/** 选中的分组（画风分组、子分组、投稿或月份）包含的图片 id；null 表示不按分组筛选。 */
export function groupImageIds(analysis: Analysis | null, groupId: string | null, buckets: ImageBucket[] = []): Set<string> | null {
  if (!groupId) return null;
  const bucket = buckets.find((item) => item.id === groupId);
  if (bucket) return new Set(bucket.imageIds);
  if (!analysis) return null;
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
