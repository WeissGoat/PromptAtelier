import { Check, Copy, Pencil, Play, Star } from "lucide-react";
import { useMemo, useState } from "react";

import { thumbUrl } from "../api/client";
import { NodePreviewImage } from "../components/NodePreviewImage";
import { useTranslations } from "../styleLab/translations";
import {
  blockCharacters,
  buildOriginIndex,
  diffAgainstSource,
  flattenInlineCharacters,
  frameMember,
  markPrompt,
  orderBlockKeys,
  originClass,
  originLabel,
  parseBlockKey,
  segmentText,
  type MarkedTag,
} from "./analysis";
import { roundCount } from "./ContractStoryboard";
import type { ContractFrame, ContractIssue, ContractResultImage, ContractSources, TokenUsage } from "./types";

export type FrameView = "marked" | "raw" | "source";

const SIZE_LABELS: Record<string, string> = { portrait: "竖", landscape: "横", square: "方" };

type Props = {
  frame: ContractFrame;
  sources: ContractSources;
  issues: ContractIssue[];
  view: FrameView;
  showDiff: boolean;
  translate: boolean;
  selected: boolean;
  results: ContractResultImage[];
  saving: boolean;
  onToggleSelect(): void;
  onGenerate(): void;
  onSave(prompts: Record<string, string>): Promise<boolean>;
  onOpenImage(images: ContractResultImage[], index: number): void;
  onTogglePick(image: ContractResultImage): void;
  /** 打开结果故事板并定位到本帧。 */
  onViewAll(): void;
};

function tagTitle(tag: MarkedTag): string {
  if (tag.added) return "新增：来源中没有这个词";
  const lines = tag.origins.map((origin) => `${originLabel(origin)}：${origin.raw}${origin.weight !== 1 ? `（权重 ${origin.weight}）` : ""}`);
  if (tag.rewritten) lines.unshift("改写：与来源写法或权重不同");
  if (tag.misplaced) lines.unshift(`写错了块：这是 ${tag.misplaced} 的角色词，应写进 ${tag.misplaced} 的块`);
  return lines.join("\n");
}

/** 角色的短名：优先用节点的 character_id（如 kaname_madoka）。 */
export function characterName(sources: ContractSources, id: string): string {
  const node = sources.characters[id];
  return node ? node.character_id || node.name || node.ref : "";
}

/** 代码块标题：正向 / 负面，角色块带角色 id 和名字。 */
export function blockLabel(key: string, sources: ContractSources): string {
  const { kind, character } = parseBlockKey(key);
  const kindLabel = kind === "positive" ? "正向" : "负面";
  if (!character) return kind === "positive" ? "主提示词 · 正向" : "主提示词 · 负面";
  const name = characterName(sources, character);
  return `${character}${name ? ` · ${name}` : ""} · ${kindLabel}`;
}

function TagChip({ tag, text, zh }: { tag: MarkedTag; text: string; zh?: string }) {
  const classes = ["ct-tag"];
  if (tag.added) classes.push("origin-added");
  else if (tag.origins.length === 1) classes.push(originClass(tag.origins[0]));
  else classes.push("origin-multi");
  if (tag.rewritten) classes.push("is-rewritten");
  if (tag.misplaced) classes.push("is-misplaced");
  const stripes = tag.origins.length > 1 ? (
    <span aria-hidden="true" className="ct-tag-stripes">
      {tag.origins.map((origin, index) => <i className={originClass(origin)} key={index} />)}
    </span>
  ) : null;
  return (
    <span className={classes.join(" ")} title={tagTitle(tag)}>
      {text}
      {stripes}
      {zh ? <small className="ct-zh">〔{zh}〕</small> : null}
    </span>
  );
}

function MarkedText({ text, tags, lookup }: { text: string; tags: MarkedTag[]; lookup(tag: string): string | undefined }) {
  return (
    <pre className="ct-marked">
      {segmentText(text, tags).map((segment, index) =>
        segment.tag ? <TagChip key={index} tag={segment.tag} text={segment.text} zh={lookup(segment.tag.body)} /> : <span key={index}>{segment.text}</span>,
      )}
    </pre>
  );
}

function issueClass(issue: ContractIssue): string {
  return `ct-issue ct-issue-${issue.severity}`;
}

/** 「n / 上限」：估算时带 ≈；超限红色，超过 90% 黄色。 */
export function TokenBadge({ usage, label = "" }: { usage: TokenUsage | null | undefined; label?: string }) {
  if (!usage || !usage.limit) return null;
  const ratio = usage.total / usage.limit;
  const tone = usage.over ? "ct-pill-err" : ratio > 0.9 ? "ct-pill-warn" : "ct-pill-ok";
  const parts = usage.blocks ? Object.entries(usage.blocks).map(([key, count]) => `${key}: ${count}`) : [];
  const title = [
    `${usage.tokenizer.toUpperCase()} 分词${usage.exact ? "，和 NovelAI 官网计数一致" : "不可用，当前是估算"}`,
    usage.shared && usage.characters.length ? `主提示词 ${usage.base} + 角色提示词 ${usage.characters.join(" + ")}，共用上限 ${usage.limit}` : `上限 ${usage.limit}`,
    ...parts,
  ].join("\n");
  return (
    <span className={`ct-pill ct-tokens ${tone}`} title={title}>
      {label}{usage.exact ? "" : "≈"}{usage.total} / {usage.limit}
    </span>
  );
}

export function FrameCard(props: Props) {
  const { frame, sources, issues, view, showDiff, translate, selected, results } = props;
  const member = frameMember(frame, sources);
  const reference = frame.inspired_by.map((ref) => sources.references[ref]).find(Boolean) ?? null;
  const [diffBase, setDiffBase] = useState<"member" | "reference">("member");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const characterOrder = Object.keys(sources.characters);
  const blockKeys = orderBlockKeys(Object.keys(frame.prompts), characterOrder);
  const splitCharacters = blockCharacters(frame.prompts, characterOrder);

  const marked = useMemo(() => {
    const result: Record<string, MarkedTag[]> = {};
    for (const key of blockKeys) {
      const { kind, character } = parseBlockKey(key);
      const index = buildOriginIndex(frame, sources, kind);
      result[key] = markPrompt(frame.prompts[key], index, { character, splitCharacters });
    }
    return result;
  }, [frame, sources, blockKeys.join("|")]);

  // Diff 比较本帧全部正向（主提示词 + 各角色块）和来源动作（行内角色块展开），词挪进角色块不算删除。
  const finalPositive = [frame.prompts.positive ?? "", ...splitCharacters.map((id) => frame.prompts[`positive ${id}`] ?? "")].join(",\n");
  const diffSource = diffBase === "reference" || !member ? reference : member;
  const diff = useMemo(
    () => (diffSource ? diffAgainstSource(finalPositive, flattenInlineCharacters(diffSource.positive)) : []),
    [finalPositive, diffSource],
  );
  const allTags = useMemo(() => {
    const tags = new Set<string>();
    Object.values(marked).forEach((list) => list.forEach((tag) => tags.add(tag.body)));
    diff.forEach((entry) => {
      if (entry.type === "removed") tags.add(entry.from.replace(/^[{[(]+|[}\])]+$/g, ""));
    });
    return [...tags];
  }, [marked, diff]);
  const { lookup } = useTranslations(allTags, translate);

  const previewTarget = member ?? reference;
  const sourceLabel = frame.is_custom
    ? `自定义${reference ? ` · 参考 ${reference.ref}` : ""}`
    : member
      ? `#${member.index} ${member.title}`
      : `未找到来源 ${frame.source ?? ""}`;
  const currentImages = results.filter((image) => image.current);
  const picked = results.filter((image) => image.picked).length;

  function startEdit() {
    setDraft({ positive: "", negative: "", ...frame.prompts });
    setEditing(true);
  }

  // 编辑时可以给本帧的角色（没有 characters 时用契约全部角色）补上角色块。
  const draftCharacters = blockCharacters(draft, characterOrder);
  const addableCharacters = (frame.characters.length ? frame.characters : characterOrder).filter((id) => !draftCharacters.includes(id));

  function addCharacterBlock(id: string) {
    setDraft((current) => ({ ...current, [`positive ${id}`]: "", [`negative ${id}`]: current[`negative ${id}`] ?? "" }));
  }

  async function save() {
    if (await props.onSave(draft)) setEditing(false);
  }

  return (
    <article className={selected ? "ct-frame is-selected" : "ct-frame"} id={`frame-${frame.id}`}>
      <header className="ct-frame-head">
        <label className="ct-frame-check" title="选中后参与批量生图">
          <input checked={selected} onChange={props.onToggleSelect} type="checkbox" />
        </label>
        {previewTarget ? (
          <NodePreviewImage className="ct-frame-preview" name={previewTarget.title} nodeRef={previewTarget.path} size={160} />
        ) : (
          <span className="node-preview node-preview-empty ct-frame-preview" />
        )}
        <div className="ct-frame-title">
          <div>
            <strong className="mono">{frame.id}</strong> <strong>{frame.title}</strong>
            {frame.size ? <span className="chip">{SIZE_LABELS[frame.size] ?? frame.size}</span> : null}
            {frame.characters.map((id) => <span className={`chip ct-char origin-${id}`} key={id}>{id}</span>)}
            <TokenBadge usage={frame.token_usage} />
          </div>
          <small className={frame.is_custom ? "ct-source ct-source-custom" : "ct-source"} title={member?.ref ?? frame.source ?? ""}>
            {sourceLabel}
          </small>
        </div>
        <div className="ct-frame-actions">
          <button className="btn-sm" onClick={startEdit} title="编辑本帧提示词，保存写回契约文件" type="button"><Pencil size={13} /> 编辑</button>
          <button className="btn-sm primary" onClick={props.onGenerate} type="button"><Play size={13} /> 生成此帧</button>
        </div>
      </header>

      {issues.length ? (
        <ul className="ct-issues">
          {issues.map((issue, index) => (
            <li className={issueClass(issue)} key={index}>
              <b>{issue.validator}</b> {issue.message}
              {issue.fix_hint ? <small>（{issue.fix_hint}）</small> : null}
            </li>
          ))}
        </ul>
      ) : null}

      {editing ? (
        <div className="ct-edit">
          {orderBlockKeys(Object.keys(draft), characterOrder).map((key) => {
            const { kind, character } = parseBlockKey(key);
            return (
              <label className={character ? `field ct-block-char origin-${character}` : "field"} key={key}>
                <span>{blockLabel(key, sources)}</span>
                <textarea
                  onChange={(event) => setDraft((current) => ({ ...current, [key]: event.target.value }))}
                  rows={kind === "positive" ? (character ? 3 : 6) : 2}
                  value={draft[key]}
                />
              </label>
            );
          })}
          {addableCharacters.length ? (
            <div className="ct-row">
              {addableCharacters.map((id) => (
                <button className="btn-sm" key={id} onClick={() => addCharacterBlock(id)} type="button">
                  + 添加 {id}{characterName(sources, id) ? ` · ${characterName(sources, id)}` : ""} 角色块
                </button>
              ))}
              <small className="muted">角色块写这个角色自己的身份、服装和动作部分；主提示词写画面共用的内容。留空的块保存时会被删掉。</small>
            </div>
          ) : null}
          <div className="ct-row">
            <button className="btn-sm primary" disabled={props.saving} onClick={() => void save()} type="button"><Check size={13} /> 保存到契约</button>
            <button className="btn-sm" onClick={() => setEditing(false)} type="button">取消</button>
            <small className="muted">只替换本帧的代码块；文件在此期间被修改时会提示冲突。</small>
          </div>
        </div>
      ) : (
        <div className="ct-blocks">
          {view === "source" ? (
            previewTarget ? (
              <div className="ct-block">
                <div className="ct-block-label">
                  {frame.is_custom ? "参考动作" : "来源动作"}原文 · 读取自 <span className="mono">{previewTarget.source_file}</span>
                </div>
                <pre className="ct-raw">{previewTarget.positive || "（空）"}</pre>
                <div className="ct-block-label">负面</div>
                <pre className="ct-raw">{previewTarget.negative || "（空）"}</pre>
              </div>
            ) : <p className="muted">自定义帧没有引用参考动作。</p>
          ) : (
            blockKeys.map((key) => (
              <div className={parseBlockKey(key).character ? `ct-block ct-block-char origin-${parseBlockKey(key).character}` : "ct-block"} key={key}>
                <div className="ct-block-label">
                  {blockLabel(key, sources)}
                  <button
                    aria-label={`复制 ${key}`}
                    className="icon-button btn-ghost btn-sm"
                    onClick={() => void navigator.clipboard?.writeText(frame.prompts[key])}
                    type="button"
                  >
                    <Copy size={12} />
                  </button>
                </div>
                {view === "raw" ? <pre className="ct-raw">{frame.prompts[key]}</pre> : <MarkedText lookup={lookup} tags={marked[key] ?? []} text={frame.prompts[key]} />}
              </div>
            ))
          )}
        </div>
      )}

      {showDiff && !editing ? (
        <div className="ct-diff">
          <div className="ct-block-label">
            Diff {diffSource ? `相对${diffSource === member ? "来源动作" : "参考动作"}` : ""}
            {member && reference ? (
              <button className="btn-sm btn-ghost" onClick={() => setDiffBase(diffBase === "member" ? "reference" : "member")} type="button">
                切换为{diffBase === "member" ? "参考动作" : "来源动作"}
              </button>
            ) : null}
          </div>
          {!diffSource ? (
            <p className="muted">自定义帧，没有来源动作：全部为新增。</p>
          ) : diff.length === 0 ? (
            <p className="muted">与来源一致。</p>
          ) : (
            <ul className="ct-diff-list">
              {diff.map((entry, index) => {
                if (entry.type === "removed") {
                  const zh = lookup(entry.from.replace(/^[{[(]+|[}\])]+$/g, ""));
                  return <li className="diff-removed" key={index}><del>{entry.from}</del>{zh ? <small className="ct-zh">〔{zh}〕</small> : null}</li>;
                }
                if (entry.type === "rewrite") {
                  return <li className="diff-rewrite" key={index}><del>{entry.from}</del> → <ins>{entry.to}</ins></li>;
                }
                const markedTag = (marked.positive ?? []).find((tag) => tag.key === entry.key);
                return (
                  <li className="diff-added" key={index}>
                    {markedTag ? <TagChip tag={markedTag} text={entry.to} zh={lookup(markedTag.body)} /> : <ins>{entry.to}</ins>}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      ) : null}

      {frame.notes ? <p className="ct-notes">{frame.notes}</p> : null}

      <div className="ct-results">
        <div className="ct-results-head">
          <span className="ct-results-summary">
            {results.length
              ? `${results.length} 张 · ${roundCount(results)} 轮 · 当前提示词 ${currentImages.length} 张${picked ? ` · 已采用 ${picked}` : ""}`
              : "还没有出图"}
          </span>
          {results.length ? (
            <button className="btn-sm btn-ghost" onClick={props.onViewAll} title="在结果故事板里看这一帧的全部结果" type="button">
              查看全部
            </button>
          ) : null}
        </div>
        <div className="ct-results-strip">
          {results.slice(0, 12).map((image, index) => (
            <figure className={`ct-result${image.current ? "" : " is-old"}${image.picked ? " is-picked" : ""}`} key={image.path}>
              <button
                aria-label={`查看 ${frame.id} 第 ${index + 1} 张`}
                className="ct-result-image"
                onClick={() => props.onOpenImage(results, index)}
                title={`${image.artist ?? ""}${image.current ? "" : " · 提示词已改"}`}
                type="button"
              >
                <img alt="" loading="lazy" src={thumbUrl(image.path, 160)} />
              </button>
              <button
                aria-label={image.picked ? "取消采用" : "采用"}
                aria-pressed={image.picked}
                className="ct-pick icon-button btn-sm"
                onClick={() => props.onTogglePick(image)}
                title={image.picked ? "取消采用" : "采用（每帧可采用多张）"}
                type="button"
              >
                <Star size={12} />
              </button>
            </figure>
          ))}
        </div>
      </div>
    </article>
  );
}
