type NodePickerProps = {
  label: string;
  value: string;
  placeholder: string;
  onChange: (value: string) => void;
};

export function NodePicker({ label, value, placeholder, onChange }: NodePickerProps) {
  return (
    <label className="field">
      <span>{label}</span>
      <input
        aria-label={label}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        value={value}
      />
    </label>
  );
}
