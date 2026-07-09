type RenderParamsPanelProps = {
  width: number;
  height: number;
  nt: number;
  seed: string;
  onWidthChange: (value: number) => void;
  onHeightChange: (value: number) => void;
  onNtChange: (value: number) => void;
  onSeedChange: (value: string) => void;
};

export function RenderParamsPanel({
  width,
  height,
  nt,
  seed,
  onWidthChange,
  onHeightChange,
  onNtChange,
  onSeedChange,
}: RenderParamsPanelProps) {
  return (
    <div className="params-grid">
      <label className="field">
        <span>Width</span>
        <input
          aria-label="Width"
          min={64}
          onChange={(event) => onWidthChange(Number(event.target.value))}
          type="number"
          value={width}
        />
      </label>
      <label className="field">
        <span>Height</span>
        <input
          aria-label="Height"
          min={64}
          onChange={(event) => onHeightChange(Number(event.target.value))}
          type="number"
          value={height}
        />
      </label>
      <label className="field">
        <span>NT</span>
        <input
          aria-label="NT"
          min={1}
          onChange={(event) => onNtChange(Number(event.target.value))}
          type="number"
          value={nt}
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
