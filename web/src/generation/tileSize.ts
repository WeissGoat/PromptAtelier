/** 出图任务和出图历史共用的缩略图大小（小 / 中 / 大），记在浏览器里。 */
export type TileSize = "s" | "m" | "l";

export const tileSizes: Record<TileSize, { label: string; column: number; thumb: number }> = {
  s: { label: "小", column: 120, thumb: 240 },
  m: { label: "中", column: 180, thumb: 320 },
  l: { label: "大", column: 260, thumb: 480 },
};

const TILE_SIZE_KEY = "promptatelier.task-tile-size/v1";

export function loadTileSize(): TileSize {
  try {
    const saved = window.localStorage.getItem(TILE_SIZE_KEY);
    return saved === "s" || saved === "l" ? saved : "m";
  } catch {
    return "m";
  }
}

export function saveTileSize(size: TileSize): void {
  try {
    window.localStorage.setItem(TILE_SIZE_KEY, size);
  } catch {
    // 存储不可用时只在当前页面生效。
  }
}

export function tileGridStyle(size: TileSize): { gridTemplateColumns: string } {
  return { gridTemplateColumns: `repeat(auto-fill, minmax(${tileSizes[size].column}px, 1fr))` };
}
