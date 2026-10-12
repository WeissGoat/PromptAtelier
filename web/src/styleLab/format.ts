import type { CompareVerdict, ImageFlag, ImageRecord, RunStatus } from "./api";

export const flagLabels: Record<ImageFlag, string> = {
  no_metadata: "无元数据",
  inpaint: "局部重绘",
  img2img: "图生图",
  add_original: "叠加原图",
  vibe_missing: "缺 vibe 图",
  director_ref: "角色参考",
  model_unverified: "模型待确认",
};

/** nai-diffusion-4-5-full → V4.5 Full */
export function modelLabel(model: string | null): string {
  if (!model) {
    return "未知模型";
  }
  const match = /^nai-diffusion-(\d)(?:-(\d))?(?:-(curated|full))?(-inpainting)?$/.exec(model);
  if (!match) {
    return model.replace(/^nai-diffusion-/, "");
  }
  const version = match[2] ? `${match[1]}.${match[2]}` : match[1];
  const variant = match[3] ? ` ${match[3][0].toUpperCase()}${match[3].slice(1)}` : "";
  return `V${version}${variant}${match[4] ? " 重绘" : ""}`;
}

export function vibeKey(image: ImageRecord): string {
  return image.vibe.count > 0 ? image.vibe.hashes.join("+") : "";
}

export function vibeLabel(key: string): string {
  return key ? `vibe ${key.split("+").map((hash) => hash.slice(0, 4)).join("+")}` : "无 vibe";
}

/** 生成时的尺寸（放大过的图文件比它大）；没有元数据时用文件尺寸。 */
export function generationSize(image: ImageRecord): string | null {
  const width = image.gen_width || image.width;
  const height = image.gen_height || image.height;
  return width && height ? `${width}×${height}` : null;
}

export function fileName(path: string): string {
  return path.split(/[\\/]/).pop() ?? path;
}

export const verdictLabels: Record<CompareVerdict, string> = {
  match: "链路正常",
  drift: "参数一致，画面有差异",
  param_diff: "参数不一致",
  reference: "与原图对照",
};

export const runStatusLabels: Record<RunStatus, string> = {
  queued: "排队中",
  running: "生成中",
  succeeded: "完成",
  partial: "部分失败",
  failed: "失败",
  cancelled: "已取消",
  interrupted: "已中断",
};

export function formatTime(seconds: number): string {
  const date = new Date(seconds * 1000);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function formatValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "—";
  }
  if (typeof value === "string") {
    return value.length > 120 ? `${value.slice(0, 120)}…` : value;
  }
  const text = JSON.stringify(value);
  return text.length > 120 ? `${text.slice(0, 120)}…` : text;
}
