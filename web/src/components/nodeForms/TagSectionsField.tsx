import { Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { StructuredValueEditor } from "../StructuredValueEditor";

const SECTION_LABELS: Record<string, string> = {
  character: "角色名",
  copyright: "作品",
  role: "定位",
  hair: "发型",
  eyes: "眼睛",
  face: "表情",
  ears: "耳朵",
  headwear: "头饰",
  upper_clothes: "上衣",
  lower_clothes: "下装",
  full_body_clothes: "连身",
  clothes: "服装",
  legwear: "腿部",
  shoes: "鞋",
  feet: "脚",
  accessories: "配饰",
  weapons: "武器",
  props: "道具",
  wings: "翅膀",
  tail: "尾巴",
  body: "身体",
  extra: "其他",
};

function splitTags(text: string): string[] {
  return text.split(/[,\n]/).map((item) => item.trim()).filter(Boolean);
}

function isTagList(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function SectionInput({ name, tags, onChange }: { name: string; tags: string[]; onChange(tags: string[]): void }) {
  // 输入时保留原文（含末尾逗号），只有内容真的变了才用外部值覆盖。
  const [text, setText] = useState(tags.join(", "));
  useEffect(() => {
    setText((current) => (JSON.stringify(splitTags(current)) === JSON.stringify(tags) ? current : tags.join(", ")));
  }, [tags]);
  return (
    <textarea
      aria-label={`${name} 标签`}
      className="tag-section-input"
      onChange={(event) => {
        setText(event.target.value);
        onChange(splitTags(event.target.value));
      }}
      placeholder="逗号分隔，如 white shirt, pleated skirt"
      rows={1}
      spellCheck={false}
      value={text}
    />
  );
}

/**
 * 分区标签编辑：tags 是"分区 → 标签列表"，每个分区一行逗号分隔的标签。
 * 空分区收成下面的快捷按钮，点一下展开；不是字符串列表的分区退回通用结构编辑。
 */
export function TagSectionsField({
  label = "Tags",
  value,
  onChange,
  suggested = [],
}: {
  label?: string;
  value: Record<string, unknown>;
  onChange(value: Record<string, unknown>): void;
  suggested?: string[];
}) {
  const [revealed, setRevealed] = useState<string[]>([]);
  const [newSection, setNewSection] = useState("");
  const keys = Object.keys(value);
  const shown = keys.filter((key) => !isTagList(value[key]) || value[key].length > 0 || revealed.includes(key));
  const hidden = [...new Set([...keys, ...suggested])].filter((key) => !shown.includes(key));
  const tagCount = keys.reduce((sum, key) => sum + (isTagList(value[key]) ? value[key].length : 0), 0);

  function setSection(key: string, next: unknown) {
    onChange({ ...value, [key]: next });
  }

  function reveal(key: string) {
    if (!(key in value)) setSection(key, []);
    setRevealed((current) => [...new Set([...current, key])]);
  }

  function removeSection(key: string) {
    const next = { ...value };
    delete next[key];
    onChange(next);
    setRevealed((current) => current.filter((item) => item !== key));
  }

  return (
    <section className="node-form-section tag-sections">
      <div className="section-title-row">
        <h3>{label} <small className="muted">{tagCount} 个标签</small></h3>
      </div>
      <div className="tag-section-list">
        {shown.map((key) => (
          <div className="tag-section-row" key={key}>
            <span className="tag-section-name" title={key}>
              <span className="mono">{key}</span>
              {SECTION_LABELS[key] ? <small>{SECTION_LABELS[key]}</small> : null}
            </span>
            {isTagList(value[key]) ? (
              <SectionInput name={key} onChange={(tags) => setSection(key, tags)} tags={value[key] as string[]} />
            ) : (
              <div className="tag-section-structured">
                <StructuredValueEditor onChange={(next) => setSection(key, next)} path={[key]} value={value[key]} />
              </div>
            )}
            <button aria-label={`删除分区 ${key}`} className="icon-button btn-ghost btn-danger" onClick={() => removeSection(key)} title="删除这个分区" type="button"><Trash2 size={14} /></button>
          </div>
        ))}
        {!shown.length ? <div className="muted tag-section-empty">还没有标签，点下面的分区开始添加。</div> : null}
      </div>
      <div className="tag-section-add">
        {hidden.map((key) => (
          <button className="btn-sm btn-ghost" key={key} onClick={() => reveal(key)} title={`添加 ${key} 分区`} type="button">
            <Plus size={12} /> {SECTION_LABELS[key] ?? key}
          </button>
        ))}
        <form
          className="tag-section-new"
          onSubmit={(event) => {
            event.preventDefault();
            const key = newSection.trim();
            if (!key) return;
            reveal(key);
            setNewSection("");
          }}
        >
          <input aria-label="新分区名" onChange={(event) => setNewSection(event.target.value)} placeholder="自定义分区" value={newSection} />
          <button className="btn-sm" disabled={!newSection.trim()} type="submit">添加</button>
        </form>
      </div>
    </section>
  );
}

export const CLOTHING_SECTIONS = [
  "role", "upper_clothes", "lower_clothes", "full_body_clothes", "legwear", "shoes",
  "clothes", "headwear", "accessories", "hair", "props",
];
