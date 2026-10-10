/**
 * 共性分析：当前筛选出的一组图，哪些提示词和参数是大家共有的、哪些是个别图独有的，
 * 以及哪张图最"居中"，适合作为配方的起点。
 */
import type { ImageRecord } from "./api";
import { modelLabel } from "./format";
import { innerTags, tokenize } from "./tokens";

export type TagStat = {
  tag: string;
  count: number;
  /** 权重写法 -> 出现次数；只有一种写法时界面不提示。 */
  weights: Map<string, number>;
  imageIds: string[];
};

export type TagTiers = { all: TagStat[]; most: TagStat[]; few: TagStat[] };

export type ParamStat = {
  key: string;
  label: string;
  values: Array<{ value: string; count: number }>;
  consistent: boolean;
  majority: string;
};

export type ImageProfile = {
  image: ImageRecord;
  /** 和其他图提示词 tag 的平均重合度（Jaccard）。 */
  overlap: number;
  /** 多数图（≥ 一半）都有、这张没有的 tag。 */
  missing: string[];
  /** 只有这张有的 tag（三张以上才算）。 */
  unique: string[];
  /** 和多数不一致的参数。 */
  deviations: Array<{ label: string; value: string; majority: string }>;
};

export type Commonality = {
  count: number;
  prompt: TagTiers;
  character: TagTiers;
  params: ParamStat[];
  profiles: ImageProfile[];
};

const LEADING_WEIGHT = /^\s*(-?\d+(?:\.\d+)?)::/;

/** 一段提示词里的 tag -> 权重写法（数字权重取 token 开头的，没写为 "1"）。 */
export function tagWeights(text: string): Map<string, string> {
  const result = new Map<string, string>();
  for (const token of tokenize(text).tokens) {
    const weight = LEADING_WEIGHT.exec(token.text)?.[1];
    const label = weight === undefined ? "1" : String(Number(weight));
    for (const tag of innerTags(token.text)) {
      if (!result.has(tag)) result.set(tag, label);
    }
  }
  return result;
}

function tiers(maps: Array<{ id: string; tags: Map<string, string> }>): TagTiers {
  const stats = new Map<string, TagStat>();
  for (const { id, tags } of maps) {
    tags.forEach((weight, tag) => {
      const stat: TagStat = stats.get(tag) ?? { tag, count: 0, weights: new Map<string, number>(), imageIds: [] };
      stat.count += 1;
      stat.imageIds.push(id);
      stat.weights.set(weight, (stat.weights.get(weight) ?? 0) + 1);
      stats.set(tag, stat);
    });
  }
  const total = maps.length;
  const sorted = [...stats.values()].sort((a, b) => b.count - a.count || a.tag.localeCompare(b.tag));
  return {
    all: sorted.filter((stat) => stat.count === total),
    most: sorted.filter((stat) => stat.count < total && stat.count * 2 >= total),
    few: sorted.filter((stat) => stat.count * 2 < total),
  };
}

const PARAMS: Array<{ key: string; label: string; read: (image: ImageRecord) => string }> = [
  { key: "model", label: "模型", read: (image) => modelLabel(image.model) },
  { key: "sampler", label: "采样器", read: (image) => image.sampler ?? "—" },
  { key: "noise_schedule", label: "调度", read: (image) => image.noise_schedule ?? "—" },
  { key: "steps", label: "步数", read: (image) => String(image.steps ?? "—") },
  { key: "scale", label: "CFG", read: (image) => String(image.scale ?? "—") },
  { key: "cfg_rescale", label: "CFG rescale", read: (image) => String(image.cfg_rescale ?? "—") },
  { key: "size", label: "尺寸", read: (image) => (image.width && image.height ? `${image.width}×${image.height}` : "—") },
  { key: "vibe", label: "vibe", read: (image) => (image.vibe.count ? `${image.vibe.count} 张` : "无") },
  { key: "characters", label: "角色提示词", read: (image) => `${image.char_captions.length} 条` },
  { key: "negative", label: "负面", read: (image) => image.negative_prompt.trim() || "（空）" },
];

function jaccard(a: Map<string, string>, b: Map<string, string>): number {
  let shared = 0;
  a.forEach((_, tag) => {
    if (b.has(tag)) shared += 1;
  });
  const union = a.size + b.size - shared;
  return union ? shared / union : 1;
}

export function analyzeCommonality(images: ImageRecord[]): Commonality {
  const usable = images.filter((image) => image.has_metadata);
  const prompts = usable.map((image) => ({ id: image.id, tags: tagWeights(image.prompt) }));
  const characters = usable.map((image) => ({
    id: image.id,
    tags: tagWeights(image.char_captions.map((caption) => caption.positive).join(", ")),
  }));
  const prompt = tiers(prompts);
  const character = tiers(characters.filter((item) => item.tags.size));

  const params = PARAMS.map(({ key, label, read }) => {
    const counts = new Map<string, number>();
    usable.forEach((image) => counts.set(read(image), (counts.get(read(image)) ?? 0) + 1));
    const values = [...counts.entries()].map(([value, count]) => ({ value, count })).sort((a, b) => b.count - a.count);
    return { key, label, values, consistent: values.length <= 1, majority: values[0]?.value ?? "—" };
  });

  const common = new Set([...prompt.all, ...prompt.most].map((stat) => stat.tag));
  const singles = new Map(prompt.few.filter((stat) => stat.count === 1).map((stat) => [stat.tag, stat.imageIds[0]]));
  const profiles = usable.map((image, index) => {
    const tags = prompts[index].tags;
    const others = prompts.filter((_, other) => other !== index);
    const overlap = others.length ? others.reduce((sum, other) => sum + jaccard(tags, other.tags), 0) / others.length : 1;
    const deviations = PARAMS.flatMap(({ key, label, read }) => {
      const stat = params.find((item) => item.key === key)!;
      const value = read(image);
      return stat.consistent || value === stat.majority ? [] : [{ label, value, majority: stat.majority }];
    });
    return {
      image,
      overlap,
      missing: [...common].filter((tag) => !tags.has(tag)),
      unique: usable.length >= 3 ? [...tags.keys()].filter((tag) => singles.get(tag) === image.id) : [],
      deviations,
    };
  });
  // 重合度高、参数和多数一致的排前面：最适合当基准。
  profiles.sort((a, b) => b.overlap - a.overlap || a.deviations.length - b.deviations.length);
  return { count: usable.length, prompt, character, params, profiles };
}
