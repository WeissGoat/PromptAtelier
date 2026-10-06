import { saveTileSize, tileSizes, type TileSize } from "../generation/tileSize";

export function TileSizeToggle({ value, onChange }: { value: TileSize; onChange(size: TileSize): void }) {
  return (
    <div aria-label="缩略图大小" className="segmented-control tile-size-toggle" role="group">
      {(Object.keys(tileSizes) as TileSize[]).map((size) => (
        <button
          aria-pressed={value === size}
          className={value === size ? "active" : ""}
          key={size}
          onClick={() => {
            onChange(size);
            saveTileSize(size);
          }}
          title={`缩略图：${tileSizes[size].label}`}
          type="button"
        >
          {tileSizes[size].label}
        </button>
      ))}
    </div>
  );
}
