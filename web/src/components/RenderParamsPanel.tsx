import type { SizeChoice, SizeOrientation } from "../workspace/types";

const orientationLabels: Record<SizeOrientation, string> = { portrait: "竖", landscape: "横", square: "方" };

type RenderParamsPanelProps = {
  width: number;
  height: number;
  nt: number;
  n: number;
  seed: string;
  /** 尺寸选择；Width / Height 只在「自定义」时生效。 */
  size: SizeChoice;
  /** 当前画风的竖横方尺寸，用来显示每个选项的实际大小。 */
  sizePresets: Partial<Record<SizeOrientation, { width: number; height: number }>>;
  onWidthChange: (value: number) => void;
  onHeightChange: (value: number) => void;
  onNtChange: (value: number) => void;
  onNChange: (value: number) => void;
  onSeedChange: (value: string) => void;
  onSizeChange: (value: SizeChoice) => void;
};

export function RenderParamsPanel({
  width,
  height,
  nt,
  n,
  seed,
  size,
  sizePresets,
  onWidthChange,
  onHeightChange,
  onNtChange,
  onNChange,
  onSeedChange,
  onSizeChange,
}: RenderParamsPanelProps) {
  const orientations = (Object.keys(orientationLabels) as SizeOrientation[]).filter((key) => sizePresets[key]);
  const custom = size === "custom";
  return (
    <div className="params-grid">
      <label className="field params-size">
        <span>尺寸</span>
        <select aria-label="尺寸" onChange={(event) => onSizeChange(event.target.value as SizeChoice)} value={size}>
          <option value="random">随机（{orientations.map((key) => orientationLabels[key]).join(" / ")}）</option>
          {orientations.map((key) => (
            <option key={key} value={key}>{orientationLabels[key]} · {sizePresets[key]!.width}×{sizePresets[key]!.height}</option>
          ))}
          {/* 选了画风没有的方向时也留着这个选项，出图会报错提示。 */}
          {size !== "random" && size !== "custom" && !sizePresets[size] ? <option value={size}>{orientationLabels[size]}（当前画风没有）</option> : null}
          <option value="custom">自定义宽高</option>
        </select>
      </label>
      <label className="field">
        <span>Width</span>
        <input
          aria-label="Width"
          disabled={!custom}
          min={64}
          onChange={(event) => onWidthChange(Number(event.target.value))}
          title={custom ? undefined : "选「自定义宽高」后生效"}
          type="number"
          value={width}
        />
      </label>
      <label className="field">
        <span>Height</span>
        <input
          aria-label="Height"
          disabled={!custom}
          min={64}
          onChange={(event) => onHeightChange(Number(event.target.value))}
          title={custom ? undefined : "选「自定义宽高」后生效"}
          type="number"
          value={height}
        />
      </label>
      <label className="field">
        <span title="每次生成张数 (n_samples)">NT</span>
        <input
          aria-label="NT"
          min={1}
          onChange={(event) => onNtChange(Number(event.target.value))}
          type="number"
          value={nt}
        />
      </label>
      <label className="field">
        <span title="轮数 (Random/Sequential/Compare Groups)">N</span>
        <input
          aria-label="N"
          min={1}
          onChange={(event) => onNChange(Number(event.target.value))}
          type="number"
          value={n}
        />
      </label>
      <label className="field">
        <span>Seed</span>
        <input
          aria-label="Seed"
          onChange={(event) => onSeedChange(event.target.value)}
          placeholder="-1"
          value={seed}
        />
      </label>
    </div>
  );
}
