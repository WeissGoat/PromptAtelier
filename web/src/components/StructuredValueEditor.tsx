import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";

type JsonContainer = Record<string, unknown> | unknown[];

type StructuredValueEditorProps = {
  value: unknown;
  path?: Array<string | number>;
  onChange(next: unknown): void;
  onRemove?: () => void;
};

type ValueKind = "string" | "number" | "boolean" | "object" | "array" | "null";

function valueKind(value: unknown): ValueKind {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  if (typeof value === "number") return "number";
  if (typeof value === "boolean") return "boolean";
  if (typeof value === "string") return "string";
  return "object";
}

function hasOwn(value: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(value, key);
}

function emptyValue(kind: ValueKind): unknown {
  if (kind === "number") return 0;
  if (kind === "boolean") return false;
  if (kind === "object") return {};
  if (kind === "array") return [];
  if (kind === "null") return null;
  return "";
}

function pathLabel(path: Array<string | number>): string {
  return path.length ? path.join(".") : "value";
}

export function StructuredValueEditor({ value, path = [], onChange, onRemove }: StructuredValueEditorProps) {
  const kind = valueKind(value);
  const [newKey, setNewKey] = useState("");
  const [newKind, setNewKind] = useState<ValueKind>("string");

  function replaceContainer(container: JsonContainer, key: string | number, next: unknown) {
    if (Array.isArray(container)) {
      const copy = [...container];
      copy[Number(key)] = next;
      onChange(copy);
      return;
    }
    onChange({ ...container, [key]: next });
  }

  function removeContainerEntry(container: JsonContainer, key: string | number) {
    if (Array.isArray(container)) {
      onChange(container.filter((_, index) => index !== Number(key)));
      return;
    }
    const copy = { ...container };
    delete copy[String(key)];
    onChange(copy);
  }

  if (kind === "object" || kind === "array") {
    const container = value as JsonContainer;
    const entries = Array.isArray(container)
      ? container.map((entry, index) => [index, entry] as const)
      : Object.entries(container);
    return (
      <div className="structured-value-group" data-path={pathLabel(path)}>
        {entries.map(([key, entry]) => (
          <div className="structured-value-row" key={String(key)}>
            <code className="structured-value-key">{String(key)}</code>
            <StructuredValueEditor
              onChange={(next) => replaceContainer(container, key, next)}
              onRemove={() => removeContainerEntry(container, key)}
              path={[...path, key]}
              value={entry}
            />
          </div>
        ))}
        <div className="structured-add-row">
          {kind === "object" ? (
            <input
              aria-label={`${pathLabel(path)} new property`}
              onChange={(event) => setNewKey(event.target.value)}
              placeholder="字段名"
              value={newKey}
            />
          ) : null}
          <select aria-label={`${pathLabel(path)} new value type`} onChange={(event) => setNewKind(event.target.value as ValueKind)} value={newKind}>
            <option value="string">文本</option>
            <option value="number">数字</option>
            <option value="boolean">布尔</option>
            <option value="object">对象</option>
            <option value="array">数组</option>
            <option value="null">空值</option>
          </select>
          <button
            aria-label={`添加 ${pathLabel(path)} 项`}
            className="icon-button"
            disabled={kind === "object" && (!newKey.trim() || hasOwn(container as Record<string, unknown>, newKey.trim()))}
            onClick={() => {
              if (Array.isArray(container)) {
                onChange([...container, emptyValue(newKind)]);
              } else {
                const key = newKey.trim();
                if (!key || hasOwn(container, key)) return;
                onChange({ ...container, [key]: emptyValue(newKind) });
                setNewKey("");
              }
            }}
            title="添加字段"
            type="button"
          >
            <Plus size={15} />
          </button>
        </div>
        {onRemove ? (
          <button className="structured-remove-container" onClick={onRemove} type="button">
            <Trash2 size={14} /> 删除此项
          </button>
        ) : null}
      </div>
    );
  }

  return (
    <div className="structured-scalar">
      <select
        aria-label={`${pathLabel(path)} type`}
        onChange={(event) => onChange(emptyValue(event.target.value as ValueKind))}
        value={kind}
      >
        <option value="string">文本</option>
        <option value="number">数字</option>
        <option value="boolean">布尔</option>
        <option value="object">对象</option>
        <option value="array">数组</option>
        <option value="null">空值</option>
      </select>
      {kind === "boolean" ? (
        <input aria-label={pathLabel(path)} checked={Boolean(value)} onChange={(event) => onChange(event.target.checked)} type="checkbox" />
      ) : null}
      {kind === "number" ? (
        <input aria-label={pathLabel(path)} onChange={(event) => onChange(Number(event.target.value))} type="number" value={String(value)} />
      ) : null}
      {kind === "string" ? (
        String(value).length > 80
          ? <textarea aria-label={pathLabel(path)} onChange={(event) => onChange(event.target.value)} value={String(value)} />
          : <input aria-label={pathLabel(path)} onChange={(event) => onChange(event.target.value)} value={String(value)} />
      ) : null}
      {kind === "null" ? <span className="field-hint">null</span> : null}
      {onRemove ? (
        <button aria-label={`删除 ${pathLabel(path)}`} className="icon-button" onClick={onRemove} title="删除" type="button"><Trash2 size={15} /></button>
      ) : null}
    </div>
  );
}
