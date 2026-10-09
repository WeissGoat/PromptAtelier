import { ImageOff, LoaderCircle, Plus, Search, Trash2, UserRound } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { errorMessage, nodePreviewUrl } from "../api/client";
import type { LibraryNode, LibraryNodeSummary, Recipe } from "./api";
import { getLibraryNode, searchLibrary } from "./api";
import {
  addTokens,
  cardOrigins,
  newTokenId,
  normalizeText,
  originCount,
  removeOrigin,
  removeOriginForText,
} from "./recipeModel";
import { useTranslations } from "./translations";

type Role = "character" | "action";
type Tab = Role | "added";

const nodeCache = new Map<string, Promise<LibraryNode>>();

function loadNode(ref: string, role: Role): Promise<LibraryNode> {
  const key = `${role}:${ref}`;
  if (!nodeCache.has(key)) {
    const promise = getLibraryNode(ref, role).catch((error) => {
      nodeCache.delete(key);
      throw error;
    });
    nodeCache.set(key, promise);
  }
  return nodeCache.get(key)!;
}

function originOf(role: Role, ref: string): string {
  return `${role}:${ref}`;
}

function originName(origin: string): string {
  const ref = origin.slice(origin.indexOf(":") + 1);
  return ref.split(/[\\/]/).pop() ?? ref;
}

type LibraryPanelProps = {
  draft: Recipe;
  translateOn: boolean;
  onChange: (recipe: Recipe) => void;
};

export function LibraryPanel({ draft, translateOn, onChange }: LibraryPanelProps) {
  const [tab, setTab] = useState<Tab>("character");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<LibraryNodeSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const origins = cardOrigins(draft);

  useEffect(() => {
    if (tab === "added") return;
    let cancelled = false;
    const timer = setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await searchLibrary(tab, query);
        if (!cancelled) setResults(data.nodes);
      } catch (exc) {
        if (!cancelled) setError(errorMessage(exc));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [tab, query]);

  const editable = draft.stage === "edit";

  return (
    <aside className="sl-library" aria-label="素材库">
      <div className="sl-segmented sl-library-tabs" role="tablist">
        {(
          [
            ["character", "角色"],
            ["action", "动作"],
            ["added", `已加入 ${origins.length}`],
          ] as Array<[Tab, string]>
        ).map(([key, label]) => (
          <button aria-selected={tab === key} className={tab === key ? "on" : ""} key={key} onClick={() => setTab(key)} role="tab" type="button">
            {label}
          </button>
        ))}
      </div>
      {!editable ? <p className="sl-hint warn">先在划分视图里锁定画风，再往主体里加素材。</p> : null}

      {tab === "added" ? (
        <div className="sl-library-list">
          {origins.length === 0 ? <p className="sl-muted">主体里还没有来自素材卡片的 tag。</p> : null}
          {origins.map((origin) => (
            <div className={`sl-added-row origin-${origin.split(":")[0]}`} key={origin}>
              <span title={origin}>{originName(origin)}</span>
              <span className="sl-count">{originCount(draft, origin)}</span>
              <button aria-label="从主体移除" className="sl-icon-btn" onClick={() => onChange(removeOrigin(draft, origin))} title="从主体移除" type="button">
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
      ) : (
        <>
          <label className="sl-search">
            <Search size={14} aria-hidden="true" />
            <input
              aria-label="搜索素材"
              onChange={(event) => setQuery(event.target.value)}
              placeholder={tab === "character" ? "角色名 / 作品" : "动作关键字"}
              value={query}
            />
            {loading ? <LoaderCircle className="sl-spin" size={14} /> : null}
          </label>
          {error ? <p className="sl-error">{error}</p> : null}
          <div className="sl-library-list">
            {results.map((node) => (
              <LibraryCard disabled={!editable} draft={draft} key={node.ref} node={node} onChange={onChange} role={tab} translateOn={translateOn} />
            ))}
            {!loading && !results.length && !error ? <p className="sl-muted">没有找到。</p> : null}
          </div>
        </>
      )}
    </aside>
  );
}

function LibraryCard({
  node,
  role,
  draft,
  disabled,
  translateOn,
  onChange,
}: {
  node: LibraryNodeSummary;
  role: Role;
  draft: Recipe;
  disabled: boolean;
  translateOn: boolean;
  onChange: (recipe: Recipe) => void;
}) {
  const [detail, setDetail] = useState<LibraryNode | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [previewFailed, setPreviewFailed] = useState(false);
  const origin = originOf(role, node.ref);

  useEffect(() => {
    let cancelled = false;
    loadNode(node.ref, role)
      .then((data) => !cancelled && setDetail(data))
      .catch((exc) => !cancelled && setError(errorMessage(exc)));
    return () => {
      cancelled = true;
    };
  }, [node.ref, role]);

  const allTags = useMemo(() => detail?.sections.flatMap((section) => section.tags) ?? [], [detail]);
  const { lookup } = useTranslations(allTags, translateOn);
  const subjectKeys = useMemo(() => {
    const map = new Map<string, string[]>();
    draft.subject.forEach((token) => map.set(normalizeText(token.text), token.origins));
    return map;
  }, [draft.subject]);
  const added = originCount(draft, origin);

  const toggleTag = (tag: string) => {
    const origins = subjectKeys.get(normalizeText(tag));
    if (origins?.includes(origin)) onChange(removeOriginForText(draft, tag, origin));
    else onChange(addTokens(draft, [tag], origin).recipe);
  };

  const fillCharacter = () => {
    const tags = allTags.some((tag) => /^(girl|boy|1girl|1boy)$/.test(tag)) ? allTags : ["girl", ...allTags];
    onChange({
      ...draft,
      character: {
        ...draft.character,
        enabled: true,
        tokens: tags.map((tag) => ({ id: newTokenId(), text: tag, sep: "", origins: [origin] })),
      },
    });
  };

  return (
    <article className={`sl-card origin-${role}`}>
      <div className="sl-card-head">
        <div className="sl-card-thumb">
          {node.has_preview && !previewFailed ? (
            <img alt="" loading="lazy" onError={() => setPreviewFailed(true)} src={nodePreviewUrl(node.ref, 160)} />
          ) : (
            <ImageOff size={16} aria-hidden="true" />
          )}
        </div>
        <div className="sl-card-info">
          <strong title={node.relative ?? node.ref}>{node.name}</strong>
          <span className="sl-muted">
            {detail ? `已加入 ${added} / ${allTags.length}` : error ? "读取失败" : "读取中…"}
          </span>
          <div className="sl-card-actions">
            <button className="sl-ghost tiny" disabled={disabled || !detail} onClick={() => onChange(addTokens(draft, allTags, origin).recipe)} type="button">
              <Plus size={13} aria-hidden="true" />
              全部
            </button>
            {added ? (
              <button className="sl-ghost tiny" disabled={disabled} onClick={() => onChange(removeOrigin(draft, origin))} title="从主体移除这张卡加入的 tag" type="button">
                <Trash2 size={13} aria-hidden="true" />
                移除
              </button>
            ) : null}
            {role === "character" ? (
              <button className="sl-ghost tiny" disabled={disabled || !detail} onClick={fillCharacter} title="把这张卡的 tag 填成角色提示词 #1" type="button">
                <UserRound size={13} aria-hidden="true" />
                作角色提示词
              </button>
            ) : null}
          </div>
        </div>
      </div>
      {error ? <p className="sl-error">{error}</p> : null}
      {detail?.sections.map((section) => (
        <div className="sl-card-section" key={section.name}>
          <span className="sl-card-section-name">{section.name}</span>
          {section.tags.map((tag) => {
            const on = subjectKeys.get(normalizeText(tag))?.includes(origin) ?? false;
            const present = subjectKeys.has(normalizeText(tag));
            const zh = lookup(tag);
            return (
              <button
                aria-pressed={on}
                className={`sl-card-tag ${on ? "on" : present ? "present" : ""}`}
                disabled={disabled}
                key={tag}
                onClick={() => toggleTag(tag)}
                title={on ? "点击从主体移除" : present ? "主体里已有（来自别处），点击也记到这张卡" : "点击加入主体"}
                type="button"
              >
                {tag}
                {zh ? <span className="sl-chip-zh">{zh}</span> : null}
              </button>
            );
          })}
        </div>
      ))}
    </article>
  );
}
