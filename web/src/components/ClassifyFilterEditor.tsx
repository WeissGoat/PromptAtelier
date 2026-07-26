import { Check, ChevronDown, Plus, Search, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { CLASSIFY_FIELDS, CLASSIFY_OPTIONS, createEmptyClassifyFilter } from "../randomNodes/spec";
import type { ClassifyFilter } from "../workspace/types";

type ClassifyField = keyof ClassifyFilter;

type ClassifyFilterEditorProps = {
  value: ClassifyFilter;
  facets: Partial<Record<ClassifyField, string[]>>;
  onChange: (value: ClassifyFilter) => void;
};

const labels: Record<ClassifyField, string> = {
  phase: "Phase",
  species: "Species",
  cast: "Cast",
  domain: "Domain",
  subtype: "Subtype",
  pose: "Pose",
  environment: "Environment",
  tone: "Tone",
  flags: "Flags",
  clothing: "Clothing",
};

function unique(values: string[]): string[] {
  return [...new Set(values)].sort();
}

export function ClassifyFilterEditor({ value, facets, onChange }: ClassifyFilterEditorProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [draftFields, setDraftFields] = useState<ClassifyField[]>([]);
  const [addOpen, setAddOpen] = useState(false);
  const [openField, setOpenField] = useState<ClassifyField | null>(null);
  const [search, setSearch] = useState("");
  const persistedFields = useMemo(
    () => CLASSIFY_FIELDS.filter((field) => value[field].length > 0),
    [value],
  );
  const activeFields = useMemo(
    () => [...new Set([...persistedFields, ...draftFields])],
    [draftFields, persistedFields],
  );
  const availableFields = CLASSIFY_FIELDS.filter((field) => !activeFields.includes(field));

  useEffect(() => {
    if (!addOpen && !openField) return;
    function closeOnOutside(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) closePopovers();
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") closePopovers();
    }
    document.addEventListener("pointerdown", closeOnOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [addOpen, openField]);

  function closePopovers() {
    setAddOpen(false);
    setOpenField(null);
    setSearch("");
  }

  function optionsFor(field: ClassifyField): string[] {
    const needle = openField === field ? search.trim().toLowerCase() : "";
    return unique([
      ...CLASSIFY_OPTIONS[field],
      ...(facets[field] ?? []),
      ...value[field],
    ]).filter((option) => !needle || option.toLowerCase().includes(needle));
  }

  function addField(field: ClassifyField) {
    setDraftFields((current) => current.includes(field) ? current : [...current, field]);
    setAddOpen(false);
    setOpenField(field);
    setSearch("");
  }

  function updateField(field: ClassifyField, values: string[]) {
    onChange({ ...value, [field]: values });
    if (!values.length) {
      setDraftFields((current) => current.filter((item) => item !== field));
      if (openField === field) setOpenField(null);
    }
  }

  function toggleValue(field: ClassifyField, option: string) {
    const selected = value[field];
    updateField(
      field,
      selected.includes(option)
        ? selected.filter((item) => item !== option)
        : [...selected, option],
    );
  }

  function clearAll() {
    onChange(createEmptyClassifyFilter());
    setDraftFields([]);
    closePopovers();
  }

  return (
    <div className="classify-filter-editor" ref={rootRef}>
      <div className="classify-filter-toolbar">
        <div className="classify-add-wrap">
          <button
            aria-expanded={addOpen}
            aria-label="添加筛选"
            className="secondary-button compact-button"
            disabled={!availableFields.length}
            onClick={() => {
              setAddOpen((current) => !current);
              setOpenField(null);
              setSearch("");
            }}
            type="button"
          >
            <Plus size={14} />添加筛选
          </button>
          {addOpen ? (
            <div aria-label="可添加的分类字段" className="classify-field-menu" role="menu">
              {availableFields.map((field) => (
                <button key={field} onClick={() => addField(field)} role="menuitem" type="button">
                  <span>{labels[field]}</span><small>{field}</small>
                </button>
              ))}
            </div>
          ) : null}
        </div>
        {activeFields.length ? (
          <button className="text-button classify-clear-all" onClick={clearAll} type="button">清空全部</button>
        ) : <span className="classify-disabled-note">未启用过滤</span>}
      </div>

      {activeFields.length ? (
        <div className="classify-filter-list">
          {activeFields.map((field) => {
            const selected = value[field];
            const options = optionsFor(field);
            const isOpen = openField === field;
            return (
              <section className="classify-filter-row" key={field}>
                <div className="classify-filter-row-title">
                  <div><strong>{labels[field]}</strong><small>{field}</small></div>
                  <button aria-label={`清空 ${labels[field]}`} className="text-button" onClick={() => updateField(field, [])} type="button">清空</button>
                </div>
                <div className="classify-chip-list">
                  {selected.map((option) => (
                    <span className="classify-filter-chip" key={option}>
                      {option}
                      <button aria-label={`移除 ${labels[field]} ${option}`} onClick={() => toggleValue(field, option)} type="button"><X size={12} /></button>
                    </span>
                  ))}
                  <div className="classify-value-picker">
                    <button
                      aria-expanded={isOpen}
                      aria-label={`选择 ${labels[field]} 值`}
                      className="classify-value-trigger"
                      onClick={() => {
                        setOpenField(isOpen ? null : field);
                        setAddOpen(false);
                        setSearch("");
                      }}
                      type="button"
                    >
                      {selected.length ? "继续选择" : "选择值"}<ChevronDown size={13} />
                    </button>
                    {isOpen ? (
                      <div className="classify-option-popover">
                        <label className="classify-option-search"><Search size={14} /><input aria-label={`搜索 ${labels[field]} 值`} autoFocus onChange={(event) => setSearch(event.target.value)} placeholder="搜索值" value={search} /></label>
                        <div className="classify-option-list">
                          {options.map((option) => {
                            const checked = selected.includes(option);
                            return (
                              <label className="classify-option" key={option}>
                                <input checked={checked} onChange={() => toggleValue(field, option)} type="checkbox" />
                                <span>{option}</span>
                                {checked ? <Check size={13} /> : null}
                              </label>
                            );
                          })}
                          {!options.length ? <div className="classify-no-options">没有匹配值</div> : null}
                        </div>
                      </div>
                    ) : null}
                  </div>
                </div>
              </section>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
