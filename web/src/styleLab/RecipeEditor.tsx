import { AlertTriangle, ChevronDown, ChevronRight, RotateCcw, Unlock, UserRound } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { ImageRecord, Recipe, RecipePreview, TagCategory } from "./api";
import {
  addTokens,
  applyToCharacter,
  categoryLabels,
  findZone,
  MATERIAL_DRAG_TYPE,
  materialOrigin,
  materialsOf,
  moveTokens,
  placeToken,
  removeOrigin,
  restoreSourceSubject,
  retokenize,
  setSubjectText,
  tokenCategory,
  tokenFrequency,
  tokensToText,
  type MaterialDrag,
  withDragMaterial,
  type Zone,
} from "./recipeModel";
import { MODELS, SAMPLERS, SCHEDULES } from "./RegenPanel";
import { SplitView } from "./SplitView";
import { useTranslations } from "./translations";
import { ZoneBox, type BlockOptions } from "./ZoneBox";

const KEY_TARGETS: Record<string, { zone: Zone; position: "start" | "end" }> = {
  "1": { zone: "prefix", position: "end" },
  s: { zone: "prefix", position: "end" },
  "2": { zone: "subject", position: "end" },
  "3": { zone: "suffix", position: "start" },
  S: { zone: "suffix", position: "start" },
  x: { zone: "dropped", position: "end" },
  X: { zone: "dropped", position: "end" },
  Delete: { zone: "dropped", position: "end" },
};

type RecipeEditorProps = {
  draft: Recipe;
  source: ImageRecord | null;
  categories: Record<string, TagCategory>;
  frequency: Map<string, number>;
  analysisReady: boolean;
  translateOn: boolean;
  preview: RecipePreview | null;
  previewError: string | null;
  onChange: (recipe: Recipe) => void;
};

export function RecipeEditor({
  draft,
  source,
  categories,
  frequency,
  analysisReady,
  translateOn,
  preview,
  previewError,
  onChange,
}: RecipeEditorProps) {
  if (draft.stage === "split") {
    return (
      <SplitView
        analysisReady={analysisReady}
        categories={categories}
        frequency={frequency}
        onCommit={onChange}
        recipe={draft}
        translateOn={translateOn}
      />
    );
  }
  return (
    <EditView
      analysisReady={analysisReady}
      categories={categories}
      draft={draft}
      frequency={frequency}
      onChange={onChange}
      preview={preview}
      previewError={previewError}
      source={source}
      translateOn={translateOn}
    />
  );
}

function EditView({ draft, source, categories, frequency, translateOn, preview, previewError, onChange }: RecipeEditorProps) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const allTexts = useMemo(
    () => [...draft.prefix, ...draft.subject, ...draft.suffix, ...draft.dropped, ...draft.character.tokens].map((token) => token.text),
    [draft],
  );
  const { lookup } = useTranslations(allTexts, translateOn);
  const hints = useMemo(() => {
    const result: Record<string, string> = {};
    for (const token of [...draft.prefix, ...draft.subject, ...draft.suffix, ...draft.dropped]) {
      const category = tokenCategory(token.text, categories);
      const percent = Math.round(tokenFrequency(token.text, frequency) * 100);
      result[token.id] = `${category ? categoryLabels[category] : "未分类"} · 同组 ${percent}%`;
    }
    return result;
  }, [draft, categories, frequency]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      if (event.key === "Escape") {
        setSelected(new Set());
        return;
      }
      const move = KEY_TARGETS[event.key];
      if (!move || !selected.size || event.ctrlKey || event.metaKey || event.altKey) return;
      event.preventDefault();
      onChange(moveTokens(draft, [...selected], move.zone, move.position));
      setSelected(new Set());
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [draft, selected, onChange]);

  const select = (id: string, event: React.MouseEvent) => {
    const multi = event.ctrlKey || event.metaKey || event.shiftKey;
    setSelected((current) => {
      if (!multi) return current.has(id) && current.size === 1 ? new Set() : new Set([id]);
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const dropToken = (id: string, zone: Zone, index: number) => {
    if (findZone(draft, id)) onChange(placeToken(draft, id, zone, index));
  };

  const materials = materialsOf(draft);
  const blocks: BlockOptions = {
    label: (origin) => materials.find((item) => materialOrigin(item) === origin)?.name ?? null,
    onRemove: (origin) => onChange(removeOrigin(draft, origin)),
  };

  const shared = { selected, lookup, hints, onSelect: select, onDropToken: dropToken };

  return (
    <div className="sl-edit">
      <p className="sl-hint">选中 token 后按 1 / S 划进前缀，2 回主体，3 / Shift+S 进后缀，X 丢弃；也可以直接拖动。紫色区是画风，导出时写进 artist。</p>
      <ZoneBox
        {...shared}
        actions={
          draft.locked ? (
            <button className="sl-ghost tiny" onClick={() => onChange({ ...draft, locked: false })} title="解锁后可以编辑画风文字、重新划分" type="button">
              <Unlock size={13} aria-hidden="true" />
              解锁
            </button>
          ) : null
        }
        allowText={!draft.locked}
        hint="tags.txt 第 1 行"
        locked={draft.locked}
        onTextChange={(text) => onChange({ ...draft, prefix: retokenize(draft.prefix, text) })}
        title="画风前缀"
        tokens={draft.prefix}
        zone="prefix"
      />
      <ZoneBox
        {...shared}
        actions={
          source ? (
            <button
              className="sl-ghost tiny"
              onClick={() => onChange(restoreSourceSubject(draft, source.prompt))}
              title="主体换回原图里的主体内容；画风区不受影响"
              type="button"
            >
              <RotateCcw size={13} aria-hidden="true" />
              恢复原图主体
            </button>
          ) : null
        }
        allowText
        blocks={blocks}
        hint="只用于测试出图"
        locked={false}
        onDropMaterial={(drag, index) => onChange(addTokens(withDragMaterial(draft, drag), drag.tags, drag.origin, index).recipe)}
        onTextChange={(text) => onChange(setSubjectText(draft, text))}
        title="主体"
        tokens={draft.subject}
        zone="subject"
      />
      <CharacterSection draft={draft} lookup={lookup} onChange={onChange} preview={preview} source={source} />
      <ZoneBox
        {...shared}
        allowText={!draft.locked}
        hint="tags.txt 第 3 行"
        locked={draft.locked}
        onTextChange={(text) => onChange({ ...draft, suffix: retokenize(draft.suffix, text) })}
        title="画风后缀"
        tokens={draft.suffix}
        zone="suffix"
      />
      {draft.dropped.length ? (
        <ZoneBox {...shared} allowText={false} hint="不进提示词" locked={false} title="丢弃" tokens={draft.dropped} zone="dropped" />
      ) : null}
      <NegativeSection draft={draft} onChange={onChange} />
      <StyleParams draft={draft} onChange={onChange} source={source} />
      <PreviewBox error={previewError} preview={preview} />
      {!draft.locked ? (
        <button className="sl-link-btn" onClick={() => onChange({ ...draft, stage: "split", locked: false })} type="button">
          回到划分视图重新划分
        </button>
      ) : null}
    </div>
  );
}

function CharacterSection({
  draft,
  source,
  preview,
  lookup,
  onChange,
}: {
  draft: Recipe;
  source: ImageRecord | null;
  preview: RecipePreview | null;
  lookup: (text: string) => string | undefined;
  onChange: (recipe: Recipe) => void;
}) {
  const sourceCaptions = source?.char_captions ?? [];
  const editable = tokensToText(draft.character.tokens);
  const predicted = preview?.char_captions ?? [];
  const extraPredicted = predicted.slice(draft.character.enabled && editable ? 1 : 0);
  const setCharacter = (patch: Partial<Recipe["character"]>) => onChange({ ...draft, character: { ...draft.character, ...patch } });
  const [dropping, setDropping] = useState(false);

  return (
    <section
      className={`sl-zone zone-character ${dropping ? "drop-target" : ""}`}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node)) setDropping(false);
      }}
      onDragOver={(event) => {
        if (!event.dataTransfer.types.includes(MATERIAL_DRAG_TYPE)) return;
        event.preventDefault();
        setDropping(true);
      }}
      onDrop={(event) => {
        const raw = event.dataTransfer.getData(MATERIAL_DRAG_TYPE);
        setDropping(false);
        if (!raw) return;
        event.preventDefault();
        const drag = JSON.parse(raw) as MaterialDrag;
        onChange(applyToCharacter(withDragMaterial(draft, drag), drag));
      }}
    >
      <header className="sl-zone-head">
        <span className="sl-zone-title">
          <UserRound size={13} aria-hidden="true" />
          角色提示词
        </span>
        <span className="sl-muted">单角色，只用于测试出图；可以把素材块拖到这里</span>
        <span className="sl-bar-spacer" />
        <label className="sl-check">
          <input checked={draft.character.enabled} onChange={(event) => setCharacter({ enabled: event.target.checked })} type="checkbox" />
          启用
        </label>
      </header>

      {sourceCaptions.length ? (
        <div className="sl-char-ref">
          <span className="sl-muted">原图 {sourceCaptions.length} 条：</span>
          {sourceCaptions.map((caption, index) => (
            <span className="sl-char-ref-item" key={index} title={caption.negative ? `负面：${caption.negative}` : undefined}>
              #{index + 1} {caption.positive}
            </span>
          ))}
          <button
            className="sl-ghost tiny"
            onClick={() =>
              setCharacter({
                enabled: true,
                tokens: retokenize([], sourceCaptions[0].positive),
                negative: retokenize([], sourceCaptions[0].negative),
              })
            }
            type="button"
          >
            用原图 #1
          </button>
        </div>
      ) : (
        <p className="sl-muted">原图没有角色提示词。</p>
      )}

      {draft.character.enabled ? (
        <>
          <label className="sl-field">
            <span>#1 正向</span>
            <TokenText
              onCommit={(text) => setCharacter({ tokens: retokenize(draft.character.tokens, text) })}
              placeholder="girl, silver hair, red eyes"
              rows={2}
              value={editable}
            />
          </label>
          {draft.character.tokens.length && lookup(draft.character.tokens[0].text) !== undefined ? (
            <p className="sl-muted sl-char-zh">{draft.character.tokens.map((token) => lookup(token.text) ?? token.text).join("，")}</p>
          ) : null}
          <label className="sl-field">
            <span>#1 负面</span>
            <TokenText
              onCommit={(text) => setCharacter({ negative: retokenize(draft.character.negative, text) })}
              rows={1}
              value={tokensToText(draft.character.negative)}
            />
          </label>
          <label className="sl-check">
            <input
              checked={draft.character.add_male_caption}
              onChange={(event) => setCharacter({ add_male_caption: event.target.checked })}
              type="checkbox"
            />
            主体里有 1boy 等男性计数时自动补男角色提示词
          </label>
        </>
      ) : null}

      {preview ? (
        <div className="sl-char-predict">
          <span className="sl-muted">实际发送 {predicted.length} 条</span>
          {predicted.map((caption, index) => (
            <span className="sl-char-ref-item" key={index}>
              #{index + 1} {caption || "（空）"}
            </span>
          ))}
          {extraPredicted.length && preview.character_prompts?.male_caption_added ? (
            <p className="sl-hint warn">
              <AlertTriangle size={13} aria-hidden="true" /> 渲染器按主体里的男性计数自动加了 {extraPredicted.length} 条男角色提示词。
            </p>
          ) : null}
          {sourceCaptions.length && !draft.character.enabled ? (
            <p className="sl-hint warn">
              <AlertTriangle size={13} aria-hidden="true" /> 原图有角色提示词但当前没启用，和原图对照时会有差异。
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function NegativeSection({ draft, onChange }: { draft: Recipe; onChange: (recipe: Recipe) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <section className="sl-zone zone-negative">
      <header className="sl-zone-head">
        <button className="sl-section-toggle" onClick={() => setOpen(!open)} type="button">
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          画风负面
          <span className="sl-count">{draft.negative.length}</span>
        </button>
        <span className="sl-muted">导出为 origin_uc；为空时用项目默认负面</span>
      </header>
      {open ? (
        <TokenText
          label="画风负面"
          onCommit={(text) => onChange({ ...draft, negative: retokenize(draft.negative, text) })}
          rows={4}
          value={tokensToText(draft.negative)}
        />
      ) : null}
    </section>
  );
}

function StyleParams({ draft, source, onChange }: { draft: Recipe; source: ImageRecord | null; onChange: (recipe: Recipe) => void }) {
  const [open, setOpen] = useState(false);
  const setParam = (key: string, value: unknown) => {
    const params = { ...draft.params };
    if (value === undefined || value === "" || (typeof value === "number" && Number.isNaN(value))) delete params[key];
    else params[key] = value;
    onChange({ ...draft, params });
  };
  const num = (key: string) => (typeof draft.params[key] === "number" ? (draft.params[key] as number) : "");
  const str = (key: string) => (typeof draft.params[key] === "string" ? (draft.params[key] as string) : "");
  const qualityOff = draft.flags.includes("not_quailty_prompts");

  return (
    <section className="sl-zone zone-params">
      <header className="sl-zone-head">
        <button className="sl-section-toggle" onClick={() => setOpen(!open)} type="button">
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          画风参数
        </button>
        <span className="sl-muted">
          {[draft.model, str("sampler"), `${num("steps") || "—"} 步`, `CFG ${num("scale") || "—"}`].filter(Boolean).join(" · ")}
        </span>
      </header>
      {open ? (
        <div className="sl-overrides">
          <label className="sl-override">
            <span>模型</span>
            <select onChange={(event) => onChange({ ...draft, model: event.target.value || null })} value={draft.model ?? ""}>
              <option value="">默认</option>
              {MODELS.map((model) => (
                <option key={model} value={model}>
                  {model}
                </option>
              ))}
            </select>
          </label>
          <label className="sl-override">
            <span>采样器</span>
            <select onChange={(event) => setParam("sampler", event.target.value)} value={str("sampler")}>
              <option value="">默认</option>
              {SAMPLERS.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
          <label className="sl-override">
            <span>调度</span>
            <select onChange={(event) => setParam("noise_schedule", event.target.value)} value={str("noise_schedule")}>
              <option value="">默认</option>
              {SCHEDULES.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
          <label className="sl-override">
            <span>步数</span>
            <input onChange={(event) => setParam("steps", event.target.value === "" ? undefined : Number(event.target.value))} step={1} type="number" value={num("steps")} />
          </label>
          <label className="sl-override">
            <span>CFG</span>
            <input onChange={(event) => setParam("scale", event.target.value === "" ? undefined : Number(event.target.value))} step={0.1} type="number" value={num("scale")} />
          </label>
          <label className="sl-override">
            <span>CFG rescale</span>
            <input onChange={(event) => setParam("cfg_rescale", event.target.value === "" ? undefined : Number(event.target.value))} step={0.02} type="number" value={num("cfg_rescale")} />
          </label>
          <label className="sl-check sl-span2">
            <input
              checked={draft.use_source_vibe}
              disabled={!source?.vibe.count}
              onChange={(event) => onChange({ ...draft, use_source_vibe: event.target.checked })}
              type="checkbox"
            />
            使用原图的 vibe{source?.vibe.count ? `（${source.vibe.count} 张）` : "（原图没有内嵌 vibe）"}
          </label>
          <label className="sl-check sl-span2">
            <input
              checked={!qualityOff}
              onChange={(event) =>
                onChange({
                  ...draft,
                  flags: event.target.checked
                    ? draft.flags.filter((flag) => flag !== "not_quailty_prompts")
                    : [...draft.flags, "not_quailty_prompts"],
                })
              }
              type="checkbox"
            />
            末尾自动追加项目默认质量词（复刻时通常关掉）
          </label>
        </div>
      ) : null}
    </section>
  );
}

function PreviewBox({ preview, error }: { preview: RecipePreview | null; error: string | null }) {
  const [showNegative, setShowNegative] = useState(false);
  return (
    <section className="sl-zone zone-preview">
      <header className="sl-zone-head">
        <span className="sl-zone-title">实际发送</span>
        {preview ? (
          <span className="sl-muted">
            {preview.model} · {preview.size ? `${preview.size.width}×${preview.size.height}` : ""} · {String(preview.params.sampler ?? "")}{" "}
            {String(preview.params.steps ?? "")} 步 · CFG {String(preview.params.scale ?? "")}
            {preview.vibe_count ? ` · vibe ${preview.vibe_count}` : ""}
          </span>
        ) : null}
      </header>
      {error ? <p className="sl-error">{error}</p> : null}
      {preview ? (
        <>
          <p className="sl-preview-text">{preview.prompt}</p>
          <button className="sl-link-btn" onClick={() => setShowNegative(!showNegative)} type="button">
            {showNegative ? "收起负面" : "看负面"}
          </button>
          {showNegative ? <p className="sl-preview-text muted">{preview.negative_prompt}</p> : null}
        </>
      ) : !error ? (
        <p className="sl-muted">计算中…</p>
      ) : null}
    </section>
  );
}

/** 文本框用本地草稿，失去焦点时才重新分词提交，避免打字时逗号被吞掉。 */
function TokenText({
  value,
  rows,
  label,
  placeholder,
  onCommit,
}: {
  value: string;
  rows: number;
  label?: string;
  placeholder?: string;
  onCommit: (text: string) => void;
}) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  return (
    <textarea
      aria-label={label}
      onBlur={() => {
        if (text !== value) onCommit(text);
      }}
      onChange={(event) => setText(event.target.value)}
      placeholder={placeholder}
      rows={rows}
      value={text}
    />
  );
}
