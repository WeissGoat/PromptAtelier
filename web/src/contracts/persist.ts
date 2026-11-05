/**
 * Agent 拼接页的本地记忆：刷新后恢复左栏草稿、生图设置（含画风）、视图开关和每份契约勾选的帧。
 * 只存在本机浏览器里；读写失败（隐私模式、存储被禁）时退回默认值，不影响使用。
 */
const PREFIX = "promptatelier.agent-studio";
const SELECTED_LIMIT = 50;

export const STORAGE_KEYS = {
  draft: `${PREFIX}.draft/v1`,
  settings: `${PREFIX}.settings/v1`,
  view: `${PREFIX}.view/v1`,
  selected: `${PREFIX}.selected/v1`,
} as const;

export function readStored<T extends object>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage?.getItem(key);
    if (!raw) return fallback;
    const value = JSON.parse(raw) as unknown;
    // 新版本加的字段用默认值补齐。
    return value && typeof value === "object" && !Array.isArray(value) ? { ...fallback, ...(value as Partial<T>) } : fallback;
  } catch {
    return fallback;
  }
}

export function writeStored(key: string, value: unknown): void {
  try {
    window.localStorage?.setItem(key, JSON.stringify(value));
  } catch {
    // 记不住也不影响使用。
  }
}

type SelectedMap = Record<string, string[]>;

/** 这份契约上次勾选的帧；没记录时返回 null（调用方按全选处理）。 */
export function readSelectedFrames(contractId: string): string[] | null {
  const map = readStored<SelectedMap>(STORAGE_KEYS.selected, {});
  const value = map[contractId];
  return Array.isArray(value) ? value.filter((item) => typeof item === "string") : null;
}

export function writeSelectedFrames(contractId: string, frameIds: string[]): void {
  const map = readStored<SelectedMap>(STORAGE_KEYS.selected, {});
  delete map[contractId];
  map[contractId] = frameIds;
  // 只留最近用过的几十份，按写入顺序淘汰最早的。
  const keys = Object.keys(map);
  keys.slice(0, Math.max(0, keys.length - SELECTED_LIMIT)).forEach((key) => delete map[key]);
  writeStored(STORAGE_KEYS.selected, map);
}
