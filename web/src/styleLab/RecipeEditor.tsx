import { AlertTriangle, ChevronDown, ChevronRight, Combine, Plus, RotateCcw, Split, TextSelect, Unlock, UserRound, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type DragEvent } from "react";

import type { ImageRecord, Recipe, RecipeCaption, RecipePreview, TagCategory } from "./api";
import {
  addBlock,
  addTokens,
  applyToCharacter,
  canSplit,
  categoryLabels,
  characterTokens,
  editInList,
  editToken,
  findToken,
  findZone,
  MATERIAL_DRAG_TYPE,
  materialOrigin,
  materialsOf,
  mergeTokens,
  moveTokens,
  placeToken,
  removeOrigin,
  restoreSourceSubject,
  retokenize,
  SOURCE_ORIGIN,
  splitToken,
  textBlock,
  tokenCategory,
  tokenFrequency,
  tokensToText,
  type MaterialDrag,
  withDragMaterial,
  type Zone,
} from "./recipeModel";
import { MODELS, SAMPLERS, SCHEDULES } from "./RegenPanel";
import { SplitView } from "./SplitView";
import { blockTranslation, splitPromptTags, useTranslations } from "./translations";
import { BlockChips, ZoneBox, type BlockOptions } from "./ZoneBox";

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
  /** 划分时的热力图：tag 在整个工作区投稿里的出现率。 */
  heat?: { frequency: Map<string, number>; posts: number };
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
  heat,
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
        heat={heat}
        onCommit={onChange}
        recipe={draft}
        sourcePrompt={source?.prompt ?? null}
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
  // 一块里有好几个 tag：按 tag 查译文再拼起来。
  const allTexts = useMemo(
    () =>
      [...draft.prefix, ...draft.subject, ...draft.suffix, ...draft.dropped, ...characterTokens(draft)].flatMap((token) =>
        splitPromptTags(token.text),
      ),
    [draft],
  );
  const { lookup: lookupTag } = useTranslations(allTexts, translateOn);
  const lookup = useCallback((text: string) => blockTranslation(text, lookupTag), [lookupTag]);
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

  const edit = (id: string, text: string) => onChange(editToken(draft, id, text));
  const shared = { selected, lookup, hints, onSelect: select, onDropToken: dropToken, onEdit: edit };
  const single = selected.size === 1 ? findToken(draft, [...selected][0]) : null;

  return (
    <div className="sl-edit">
      {selected.size ? (
        <div className="sl-edit-tools" role="toolbar" aria-label="选中的块">
          <span>已选 {selected.size} 块</span>
          <button
            className="sl-ghost tiny"
            disabled={selected.size < 2}
            onClick={() => {
              onChange(mergeTokens(draft, [...selected]));
              setSelected(new Set());
            }}
            title="同一处选中的几块合成一块"
            type="button"
          >
            <Combine size={13} aria-hidden="true" />
            合并成一块
          </button>
          <button
            className="sl-ghost tiny"
            disabled={!canSplit(single)}
            onClick={() => {
              onChange(splitToken(draft, [...selected][0]));
              setSelected(new Set());
            }}
            title="这一块按逗号拆成一个个 tag（比如消融时想单独测某个画师）"
            type="button"
          >
            <Split size={13} aria-hidden="true" />
            按 tag 拆开
          </button>
          <span className="sl-muted">按 1 / S 进前缀，2 回主体，3 / Shift+S 进后缀，X 丢弃；Esc 取消选择。</span>
        </div>
      ) : (
        <p className="sl-hint">
          每块是一整组提示词，不分词。双击一块改文字（清空即删除）；点选后按 1 / S 划进前缀，2 回主体，3 / Shift+S 进后缀，X
          丢弃，也可以直接拖动。紫色区是画风，导出时写进 artist。
        </p>
      )}
      <ZoneBox
        {...shared}
        actions={
          <>
            <button
              className="sl-ghost tiny"
              onClick={() => onChange({ ...draft, stage: "split", locked: false })}
              title="回到原文上拖选，重新标前缀、后缀。主体里加的素材会保留，之前从主体删掉的原文显示为丢弃"
              type="button"
            >
              <TextSelect size={13} aria-hidden="true" />
              重新划分
            </button>
            {draft.locked ? (
              <button className="sl-ghost tiny" onClick={() => onChange({ ...draft, locked: false })} title="解锁后可以直接编辑画风文字" type="button">
                <Unlock size={13} aria-hidden="true" />
                解锁
              </button>
            ) : null}
          </>
        }
        editable={!draft.locked}
        hint="tags.txt 第 1 行"
        locked={draft.locked}
        onAdd={(text) => onChange(addBlock(draft, "prefix", text))}
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
        blocks={blocks}
        editable
        hint="只用于测试出图"
        locked={false}
        onAdd={(text) => onChange(addBlock(draft, "subject", text))}
        onDropMaterial={(drag, index) => onChange(addTokens(withDragMaterial(draft, drag), drag.tags, drag.origin, index).recipe)}
        title="主体"
        tokens={draft.subject}
        zone="subject"
      />
      <CharacterSection
        draft={draft}
        lookup={lookup}
        onChange={onChange}
        onSelect={select}
        preview={preview}
        selected={selected}
        source={source}
      />
      <ZoneBox
        {...shared}
        editable={!draft.locked}
        hint="tags.txt 第 3 行"
        locked={draft.locked}
        onAdd={(text) => onChange(addBlock(draft, "suffix", text))}
        title="画风后缀"
        tokens={draft.suffix}
        zone="suffix"
      />
      {draft.dropped.length ? (
        <ZoneBox {...shared} editable={false} hint="不进提示词" locked={false} removable title="丢弃" tokens={draft.dropped} zone="dropped" />
      ) : null}
      <NegativeSection draft={draft} onChange={onChange} />
      <StyleParams draft={draft} onChange={onChange} source={source} />
      <PreviewBox error={previewError} preview={preview} />
    </div>
  );
}

function CharacterSection({
  draft,
  source,
  preview,
  lookup,
  selected,
  onSelect,
  onChange,
}: {
  draft: Recipe;
  source: ImageRecord | null;
  preview: RecipePreview | null;
  lookup: (text: string) => string | undefined;
  selected: Set<string>;
  onSelect: (id: string, event: React.MouseEvent) => void;
  onChange: (recipe: Recipe) => void;
}) {
  const [adding, setAdding] = useState<number | null>(null);
  const sourceCaptions = source?.char_captions ?? [];
  const { captions } = draft.character;
  const predicted = preview?.char_captions ?? [];
  const sent = draft.character.enabled ? captions.filter((caption) => tokensToText(caption.tokens).trim()).length : 0;
  const extraPredicted = predicted.slice(sent);
  const setCharacter = (patch: Partial<Recipe["character"]>) => onChange({ ...draft, character: { ...draft.character, ...patch } });
  const setCaption = (index: number, patch: Partial<RecipeCaption>) =>
    setCharacter({ captions: captions.map((caption, at) => (at === index ? { ...caption, ...patch } : caption)) });
  const useSource = () =>
    setCharacter({
      enabled: true,
      captions: sourceCaptions.map((caption) => ({
        tokens: textBlock(caption.positive, SOURCE_ORIGIN),
        negative: textBlock(caption.negative, SOURCE_ORIGIN),
        center: caption.centers?.[0] ?? null,
      })),
    });
  const sameAsSource =
    sourceCaptions.length === captions.length &&
    sourceCaptions.every(
      (caption, index) =>
        tokensToText(captions[index].tokens) === caption.positive.trim() &&
        tokensToText(captions[index].negative) === caption.negative.trim(),
    );
  // 拖到某一条上放进那一条，拖到区域其他地方新加一条。
  const [dropping, setDropping] = useState<number | "new" | null>(null);
  const dropHandlers = (target: number | "new") => ({
    onDragOver: (event: DragEvent) => {
      if (!event.dataTransfer.types.includes(MATERIAL_DRAG_TYPE)) return;
      event.preventDefault();
      event.stopPropagation();
      setDropping(target);
    },
    onDrop: (event: DragEvent) => {
      const raw = event.dataTransfer.getData(MATERIAL_DRAG_TYPE);
      setDropping(null);
      if (!raw) return;
      event.preventDefault();
      event.stopPropagation();
      const drag = JSON.parse(raw) as MaterialDrag;
      onChange(applyToCharacter(withDragMaterial(draft, drag), drag, target === "new" ? captions.length : target));
    },
  });

  return (
    <section
      className={`sl-zone zone-character ${dropping === "new" ? "drop-target" : ""}`}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node)) setDropping(null);
      }}
      {...dropHandlers("new")}
    >
      <header className="sl-zone-head">
        <span className="sl-zone-title">
          <UserRound size={13} aria-hidden="true" />
          角色提示词
          <span className="sl-count">{captions.length}</span>
        </span>
        <span className="sl-muted">只用于测试出图；素材块拖到某一条上替换那一条，拖到空白处新加一条</span>
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
          {sameAsSource ? (
            <span className="sl-muted">（和原图一致）</span>
          ) : (
            <button className="sl-ghost tiny" onClick={useSource} type="button">
              用原图的 {sourceCaptions.length} 条
            </button>
          )}
        </div>
      ) : (
        <p className="sl-muted">原图没有角色提示词。</p>
      )}

      {draft.character.enabled ? (
        <>
          {captions.map((caption, index) => (
            <div
              className={`sl-char-caption ${dropping === index ? "drop-target" : ""}`}
              key={index}
              {...dropHandlers(index)}
            >
              <div className="sl-char-caption-head">
                <span>#{index + 1}</span>
                {caption.center ? (
                  <span className="sl-muted" title="原图里的位置；勾选“按位置摆放”时才起作用">
                    位置 {caption.center.x.toFixed(1)}, {caption.center.y.toFixed(1)}
                  </span>
                ) : null}
                <span className="sl-bar-spacer" />
                <button
                  aria-label={`角色提示词 #${index + 1} 加一块`}
                  className="sl-icon-btn"
                  onClick={() => setAdding(index)}
                  title="加一块（整段是一块，不分词）"
                  type="button"
                >
                  <Plus size={13} aria-hidden="true" />
                </button>
                <button
                  aria-label={`删除角色提示词 #${index + 1}`}
                  className="sl-icon-btn danger"
                  onClick={() => setCharacter({ captions: captions.filter((_, at) => at !== index) })}
                  title="删除这一条"
                  type="button"
                >
                  <X size={13} aria-hidden="true" />
                </button>
              </div>
              <BlockChips
                adding={adding === index}
                editable
                empty="（空，点 + 加一块，或把素材块拖到这里）"
                label={`角色提示词 #${index + 1}`}
                lookup={lookup}
                onAdd={(text) => setCaption(index, { tokens: [...caption.tokens, ...textBlock(text)] })}
                onAddDone={() => setAdding(null)}
                onEdit={(id, text) => setCaption(index, { tokens: editInList(caption.tokens, id, text) })}
                onSelect={onSelect}
                selected={selected}
                tokens={caption.tokens}
                zone="character"
              />
              <label className="sl-field">
                <span>负面</span>
                <TokenText
                  label={`角色提示词 #${index + 1} 负面`}
                  onCommit={(text) => setCaption(index, { negative: textBlock(text) })}
                  rows={1}
                  value={tokensToText(caption.negative)}
                />
              </label>
            </div>
          ))}
          <div className="sl-char-options">
            <button
              className="sl-ghost tiny"
              onClick={() => setCharacter({ captions: [...captions, { tokens: [], negative: [] }] })}
              type="button"
            >
              <Plus size={13} aria-hidden="true" />
              加一条
            </button>
            <label className="sl-check">
              <input
                checked={Boolean(draft.character.use_coords)}
                onChange={(event) => setCharacter({ use_coords: event.target.checked })}
                type="checkbox"
              />
              按位置摆放（原图的 use_coords）
            </label>
            <label className="sl-check">
              <input
                checked={draft.character.add_male_caption}
                onChange={(event) => setCharacter({ add_male_caption: event.target.checked })}
                type="checkbox"
              />
              主体里有 1boy 等男性计数时自动补男角色提示词
            </label>
          </div>
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
          {sourceCaptions.length && predicted.length !== sourceCaptions.length && !preview.character_prompts?.male_caption_added ? (
            <p className="sl-hint warn">
              <AlertTriangle size={13} aria-hidden="true" /> 原图有 {sourceCaptions.length} 条角色提示词，现在发送 {predicted.length}{" "}
              条，和原图对照时会有差异。
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
