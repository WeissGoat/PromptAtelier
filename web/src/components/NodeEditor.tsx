type NodeEditorProps = {
  value: string;
  onChange: (value: string) => void;
};

export function NodeEditor({ value, onChange }: NodeEditorProps) {
  return (
    <section className="panel editor-panel">
      <div className="panel-title">
        <h2>Node Editor</h2>
      </div>
      <textarea
        aria-label="Node draft"
        onChange={(event) => onChange(event.target.value)}
        spellCheck={false}
        value={value}
      />
    </section>
  );
}
