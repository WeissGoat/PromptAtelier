import { GripVertical, ImageOff, Plus, Trash2, UserRound, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { errorMessage, nodePreviewUrl } from "../api/client";
import type { LibraryNode, MaterialRole, Recipe, RecipeMaterial } from "./api";
import { loadNode } from "./libraryNodes";
import { updateShelf, useMaterialShelf } from "./materialShelf";
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
const NO_FACETS: Record<string, string> = {};
/** 换配方时停在上次的页签。 */
let lastTab: MaterialRole = "character";

function sameMaterial(a: RecipeMaterial, b: RecipeMaterial): boolean {
  return a.role === b.role && a.ref === b.ref;
}

/** 素材架上放入或更新一块（筛选随之保存）。 */
function putOnShelf(material: RecipeMaterial) {
  updateShelf((shelf) => {
    const index = shelf.materials.findIndex((item) => sameMaterial(item, material));
    const materials = index < 0 ? [...shelf.materials, material] : shelf.materials.map((item, i) => (i === index ? material : item));
    return { ...shelf, materials };
  });
}

function takeOffShelf(material: RecipeMaterial) {
  updateShelf((shelf) => ({ ...shelf, materials: shelf.materials.filter((item) => !sameMaterial(item, material)) }));
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
 * 素材架：上面从下拉里搜角色/动作，选中的放进下面的素材块。素材架和每块的筛选、搜索的分类筛选
 * 全局保存，换配方也在；用进配方（加入主体、角色提示词）时才记进配方的 materials。
 */
export function LibraryPanel({ draft, translateOn, onChange }: LibraryPanelProps) {
  const [tab, setTabState] = useState<MaterialRole>(lastTab);
  const setTab = (role: MaterialRole) => {
    lastTab = role;
    setTabState(role);
  };
  const { shelf: globalShelf, ready, error: shelfError } = useMaterialShelf();
  const materials = materialsOf(draft);
  const editable = draft.stage === "edit";

  // 配方里用过、素材架上还没有的（旧配方、别处拿掉过的），放回素材架。
  useEffect(() => {
    if (!ready) return;
    materials.filter((item) => !globalShelf.materials.some((other) => sameMaterial(item, other))).forEach(putOnShelf);
  }, [ready, materials, globalShelf.materials]);

  // 配方在用的块以配方里的筛选为准（它决定了加进去的 tag）。
  const allMaterials = [
    ...globalShelf.materials,
    ...materials.filter((item) => !globalShelf.materials.some((other) => sameMaterial(item, other))),
  ].map((item) => materials.find((used) => sameMaterial(used, item)) ?? item);
  const shelf = allMaterials.filter((item) => item.role === tab);
  // 旧配方直接从卡片加进来、没有素材块的来源：可以放上素材架接着编辑，或一键移除。
  const loose = cardOrigins(draft).filter(
    (origin) => origin.startsWith(`${tab}:`) && !materials.some((item) => materialOrigin(item) === origin),
  );

  return (
    <aside className="sl-library" aria-label="素材库">
      <div className="sl-segmented sl-library-tabs" role="tablist">
        {(["character", "action"] as MaterialRole[]).map((role) => {
          const count = allMaterials.filter((item) => item.role === role).length;
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
        facets={globalShelf.facets[tab] ?? NO_FACETS}
        isPicked={(ref) => shelf.some((item) => item.ref === ref)}
        onFacetsChange={(facets) => updateShelf((current) => ({ ...current, facets: { ...current.facets, [tab]: facets } }))}
        onPick={(node) => putOnShelf({ role: tab, ref: node.ref, name: node.name, excluded: [] })}
        role={tab}
      />
      {shelfError ? <p className="sl-error">{shelfError}</p> : null}

      <div className="sl-shelf">
        <div className="sl-shelf-head">
          <span>已选{ROLE_LABELS[tab]}</span>
          <span className="sl-muted">所有配方共用；点 tag 筛掉不要的，再加入主体，或整块拖进主体、角色提示词</span>
        </div>
        {shelf.length === 0 ? (
          <p className="sl-muted sl-shelf-empty">从上面的下拉里选{ROLE_LABELS[tab]}，选过的会一直留在这里，换配方也在。</p>
        ) : null}
        {shelf.map((material) => (
          <MaterialBlock
            disabled={!editable}
            draft={draft}
            inRecipe={materials.some((item) => sameMaterial(item, material))}
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
  inRecipe,
  disabled,
  translateOn,
  onChange,
}: {
  material: RecipeMaterial;
  draft: Recipe;
  inRecipe: boolean;
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
  const drag: MaterialDrag = { origin, role: material.role, tags: included, material };
  // 用进配方：先把这块记进配方，再加 tag。
  const used = () => addMaterial(draft, material);
  // 素材架上的筛选全局保存；配方在用这块时同步增删配方里的 tag。
  const filterLocked = disabled && inRecipe;
  const toggleTag = (tag: string) => {
    const excluded = material.excluded.includes(tag)
      ? material.excluded.filter((value) => value !== tag)
      : [...material.excluded, tag];
    putOnShelf({ ...material, excluded });
    if (inRecipe) onChange(toggleMaterialTag(draft, origin, tag, allTags));
  };
  const setAll = (include: boolean) => {
    putOnShelf({ ...material, excluded: include ? [] : allTags });
    if (inRecipe) onChange(setMaterialTags(draft, origin, allTags, include));
  };

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
            {inSubject ? <span className="sl-pill ok">在主体</span> : null}
            {inCharacter ? <span className="sl-pill ok">角色提示词</span> : null}
          </span>
        </span>
        <button
          aria-label={`拿掉 ${material.name}`}
          className="sl-icon-btn"
          disabled={filterLocked}
          onClick={() => {
            takeOffShelf(material);
            if (inRecipe) onChange(removeMaterial(draft, origin));
          }}
          title="从素材架拿掉（这个配方里它加进主体、角色提示词的 tag 一起去掉）"
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
                disabled={filterLocked}
                key={tag}
                onClick={() => toggleTag(tag)}
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
              onClick={() => onChange(addTokens(used(), included, origin).recipe)}
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
              onClick={() => onChange(applyToCharacter(used(), drag))}
              title={material.role === "character" ? "替换角色提示词 #1" : "追加到角色提示词 #1 后面"}
              type="button"
            >
              <UserRound size={13} aria-hidden="true" />
              {material.role === "character" ? "作角色提示词" : "加到角色提示词"}
            </button>
          )}
          <span className="sl-bar-spacer" />
          <button className="sl-link-btn" disabled={filterLocked} onClick={() => setAll(true)} type="button">
            全选
          </button>
          <button className="sl-link-btn" disabled={filterLocked} onClick={() => setAll(false)} type="button">
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
