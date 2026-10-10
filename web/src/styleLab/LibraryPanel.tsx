import { GripVertical, ImageOff, Plus, Trash2, UserRound, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { errorMessage, nodePreviewUrl } from "../api/client";
import type { LibraryNode, MaterialRole, Recipe, RecipeMaterial } from "./api";
import { getLibraryNode } from "./api";
import { MaterialSearch } from "./MaterialSearch";
import {
  addMaterial,
  addTokens,
  applyToCharacter,
  cardOrigins,
  characterHasOrigin,
  MATERIAL_DRAG_TYPE,
  materialOrigin,
  materialsOf,
  materialTags,
  originCount,
  removeMaterial,
  removeFromCharacter,
  removeMaterialTokens,
  removeOrigin,
  setMaterialTags,
  toggleMaterialTag,
  type MaterialDrag,
} from "./recipeModel";
import { useTranslations } from "./translations";

const ROLE_LABELS: Record<MaterialRole, string> = { character: "角色", action: "动作" };
const nodeCache = new Map<string, Promise<LibraryNode>>();

function loadNode(ref: string, role: MaterialRole): Promise<LibraryNode> {
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

export function originName(origin: string): string {
  const ref = origin.slice(origin.indexOf(":") + 1);
  return ref.split(/[\\/]/).pop() ?? ref;
}

type LibraryPanelProps = {
  draft: Recipe;
  translateOn: boolean;
  onChange: (recipe: Recipe) => void;
};

/**
 * 素材架：上面从下拉里搜角色/动作，选中的放进下面的素材块并随配方保存；
 * 每块先筛掉不要的 tag，再一键加入主体，或整块拖进主体、角色提示词。
 */
export function LibraryPanel({ draft, translateOn, onChange }: LibraryPanelProps) {
  const [tab, setTab] = useState<MaterialRole>("character");
  const materials = materialsOf(draft);
  const shelf = materials.filter((item) => item.role === tab);
  const editable = draft.stage === "edit";
  // 旧配方直接从卡片加进来、没有素材块的来源：可以放上素材架接着编辑，或一键移除。
  const loose = cardOrigins(draft).filter(
    (origin) => origin.startsWith(`${tab}:`) && !materials.some((item) => materialOrigin(item) === origin),
  );

  return (
    <aside className="sl-library" aria-label="素材库">
      <div className="sl-segmented sl-library-tabs" role="tablist">
        {(["character", "action"] as MaterialRole[]).map((role) => {
          const count = materials.filter((item) => item.role === role).length;
          return (
            <button aria-selected={tab === role} className={tab === role ? "on" : ""} key={role} onClick={() => setTab(role)} role="tab" type="button">
              {ROLE_LABELS[role]}
              {count ? <span className="sl-count">{count}</span> : null}
            </button>
          );
        })}
      </div>
      {!editable ? <p className="sl-hint warn">先在划分视图里锁定画风，再往主体里加素材。</p> : null}

      <MaterialSearch
        disabled={!editable}
        isPicked={(ref) => materials.some((item) => item.role === tab && item.ref === ref)}
        onPick={(node) => onChange(addMaterial(draft, { role: tab, ref: node.ref, name: node.name, excluded: [] }))}
        role={tab}
      />

      <div className="sl-shelf">
        <div className="sl-shelf-head">
          <span>已选{ROLE_LABELS[tab]}</span>
          <span className="sl-muted">点 tag 筛掉不要的，再加入主体；整块可以拖进主体或角色提示词</span>
        </div>
        {shelf.length === 0 ? (
          <p className="sl-muted sl-shelf-empty">从上面的下拉里选{ROLE_LABELS[tab]}，选过的会一直留在这里。</p>
        ) : null}
        {shelf.map((material) => (
          <MaterialBlock
            disabled={!editable}
            draft={draft}
            key={materialOrigin(material)}
            material={material}
            onChange={onChange}
            translateOn={translateOn}
          />
        ))}
        {loose.length ? (
          <div className="sl-shelf-loose">
            <span className="sl-muted">以前直接从卡片加进来的：</span>
            {loose.map((origin) => (
              <span className={`sl-added-row origin-${tab}`} key={origin}>
                <span title={origin}>{originName(origin)}</span>
                <span className="sl-count">
                  {[originCount(draft, origin) ? `主体 ${originCount(draft, origin)}` : "", characterHasOrigin(draft, origin) ? "角色提示词" : ""]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
                <button
                  className="sl-link-btn"
                  disabled={!editable}
                  onClick={() =>
                    onChange(addMaterial(draft, { role: tab, ref: origin.slice(tab.length + 1), name: originName(origin), excluded: [] }))
                  }
                  type="button"
                >
                  放上素材架
                </button>
                <button
                  aria-label="全部移出"
                  className="sl-icon-btn"
                  disabled={!editable}
                  onClick={() => onChange(removeMaterialTokens(draft, origin))}
                  title="主体和角色提示词里都去掉"
                  type="button"
                >
                  <Trash2 size={13} />
                </button>
              </span>
            ))}
          </div>
        ) : null}
      </div>
    </aside>
  );
}

function MaterialBlock({
  material,
  draft,
  disabled,
  translateOn,
  onChange,
}: {
  material: RecipeMaterial;
  draft: Recipe;
  disabled: boolean;
  translateOn: boolean;
  onChange: (recipe: Recipe) => void;
}) {
  const [detail, setDetail] = useState<LibraryNode | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [previewFailed, setPreviewFailed] = useState(false);
  const origin = materialOrigin(material);

  useEffect(() => {
    let cancelled = false;
    loadNode(material.ref, material.role)
      .then((data) => !cancelled && setDetail(data))
      .catch((exc) => !cancelled && setError(errorMessage(exc)));
    return () => {
      cancelled = true;
    };
  }, [material.ref, material.role]);

  const allTags = useMemo(() => [...new Set(detail?.sections.flatMap((section) => section.tags) ?? [])], [detail]);
  const included = materialTags(material, allTags);
  const { lookup } = useTranslations(allTags, translateOn);
  const inSubject = originCount(draft, origin);
  const inCharacter = characterHasOrigin(draft, origin);
  const drag: MaterialDrag = { origin, role: material.role, tags: included };

  return (
    <article
      className={`sl-mblock origin-${material.role}`}
      draggable={!disabled && Boolean(detail)}
      onDragStart={(event) => {
        event.dataTransfer.setData(MATERIAL_DRAG_TYPE, JSON.stringify(drag));
        event.dataTransfer.effectAllowed = "copy";
      }}
    >
      <header className="sl-mblock-head">
        <GripVertical className="sl-mblock-grip" size={14} aria-hidden="true" />
        <span className="sl-mblock-thumb">
          {detail?.has_preview && !previewFailed ? (
            <img alt="" loading="lazy" onError={() => setPreviewFailed(true)} src={nodePreviewUrl(material.ref, 96)} />
          ) : (
            <ImageOff size={14} aria-hidden="true" />
          )}
        </span>
        <span className="sl-mblock-title">
          <strong title={material.ref}>{material.name}</strong>
          <span className="sl-muted">
            {detail ? `选了 ${included.length} / ${allTags.length}` : error ? "读取失败" : "读取中…"}
            {inSubject ? <span className="sl-pill ok">主体 {inSubject}</span> : null}
            {inCharacter ? <span className="sl-pill ok">角色提示词</span> : null}
          </span>
        </span>
        <button
          aria-label={`拿掉 ${material.name}`}
          className="sl-icon-btn"
          disabled={disabled}
          onClick={() => onChange(removeMaterial(draft, origin))}
          title="拿掉这块素材（它加进主体、角色提示词的 tag 一起去掉）"
          type="button"
        >
          <X size={14} />
        </button>
      </header>
      {error ? <p className="sl-error">{error}</p> : null}
      {detail?.sections.map((section) => (
        <div className="sl-card-section" key={section.name}>
          <span className="sl-card-section-name">{section.name}</span>
          {section.tags.map((tag) => {
            const off = material.excluded.includes(tag);
            const zh = lookup(tag);
            return (
              <button
                aria-pressed={!off}
                className={`sl-card-tag ${off ? "off" : "on"}`}
                disabled={disabled}
                key={tag}
                onClick={() => onChange(toggleMaterialTag(draft, origin, tag))}
                title={off ? "点击选回来" : "点击筛掉（已加入时同步去掉）"}
                type="button"
              >
                {tag}
                {zh ? <span className="sl-chip-zh">{zh}</span> : null}
              </button>
            );
          })}
        </div>
      ))}
      {detail ? (
        <footer className="sl-mblock-actions">
          {inSubject ? (
            <button className="sl-ghost tiny" disabled={disabled} onClick={() => onChange(removeOrigin(draft, origin))} type="button">
              <Trash2 size={13} aria-hidden="true" />
              移出主体
            </button>
          ) : (
            <button
              className="sl-primary small"
              disabled={disabled || !included.length}
              onClick={() => onChange(addTokens(draft, included, origin).recipe)}
              type="button"
            >
              <Plus size={13} aria-hidden="true" />
              加入主体
            </button>
          )}
          {inCharacter ? (
            <button
              className="sl-ghost tiny"
              disabled={disabled}
              onClick={() => onChange(removeFromCharacter(draft, origin))}
              type="button"
            >
              <Trash2 size={13} aria-hidden="true" />
              移出角色提示词
            </button>
          ) : (
            <button
              className="sl-ghost tiny"
              disabled={disabled || !included.length}
              onClick={() => onChange(applyToCharacter(draft, drag))}
              title={material.role === "character" ? "替换角色提示词 #1" : "追加到角色提示词 #1 后面"}
              type="button"
            >
              <UserRound size={13} aria-hidden="true" />
              {material.role === "character" ? "作角色提示词" : "加到角色提示词"}
            </button>
          )}
          <span className="sl-bar-spacer" />
          <button className="sl-link-btn" disabled={disabled} onClick={() => onChange(setMaterialTags(draft, origin, allTags, true))} type="button">
            全选
          </button>
          <button className="sl-link-btn" disabled={disabled} onClick={() => onChange(setMaterialTags(draft, origin, allTags, false))} type="button">
            全不选
          </button>
          {inSubject || inCharacter ? (
            <button className="sl-link-btn" disabled={disabled} onClick={() => onChange(removeMaterialTokens(draft, origin))} title="主体和角色提示词里都去掉" type="button">
              全部移出
            </button>
          ) : null}
        </footer>
      ) : null}
    </article>
  );
}
