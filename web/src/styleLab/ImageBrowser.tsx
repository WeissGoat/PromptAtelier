import { Search } from "lucide-react";
import { useMemo } from "react";

import type { ImageFlag, ImageRecord } from "./api";
import { sourceImageUrl } from "./api";
import { flagLabels, modelLabel, vibeKey, vibeLabel } from "./format";

export type ImageFilters = {
  query: string;
  models: string[];
  vibes: string[];
  flags: ImageFlag[];
  hideSpecial: boolean;
};

export const emptyFilters: ImageFilters = { query: "", models: [], vibes: [], flags: [], hideSpecial: false };

const SPECIAL_FLAGS: ImageFlag[] = ["no_metadata", "inpaint", "img2img"];

export function filterImages(images: ImageRecord[], filters: ImageFilters): ImageRecord[] {
  const query = filters.query.trim().toLowerCase();
  return images.filter((image) => {
    if (filters.models.length && !filters.models.includes(image.model ?? "")) {
      return false;
    }
    if (filters.vibes.length && !filters.vibes.includes(vibeKey(image))) {
      return false;
    }
    if (filters.flags.length && !filters.flags.some((flag) => image.flags.includes(flag))) {
      return false;
    }
    if (filters.hideSpecial && image.flags.some((flag) => SPECIAL_FLAGS.includes(flag))) {
      return false;
    }
    if (query) {
      const haystack = `${image.prompt}\n${image.rel_path}\n${image.post?.title ?? ""}`.toLowerCase();
      if (!haystack.includes(query)) {
        return false;
      }
    }
    return true;
  });
}

function countBy(images: ImageRecord[], keyOf: (image: ImageRecord) => string[]): Array<[string, number]> {
  const counts = new Map<string, number>();
  for (const image of images) {
    for (const key of keyOf(image)) {
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]);
}

function toggle<T>(values: T[], value: T): T[] {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
}

type FilterPanelProps = {
  images: ImageRecord[];
  filters: ImageFilters;
  onChange: (filters: ImageFilters) => void;
};

export function FilterPanel({ images, filters, onChange }: FilterPanelProps) {
  const models = useMemo(() => countBy(images, (image) => [image.model ?? ""]), [images]);
  const vibes = useMemo(() => countBy(images, (image) => [vibeKey(image)]), [images]);
  const flags = useMemo(() => countBy(images, (image) => image.flags), [images]);
  const posts = useMemo(() => new Set(images.map((image) => image.post?.dir_name ?? image.rel_path)).size, [images]);

  return (
    <aside className="sl-filters" aria-label="筛选">
      <label className="sl-search">
        <Search size={14} aria-hidden="true" />
        <input
          aria-label="搜索提示词或文件名"
          onChange={(event) => onChange({ ...filters, query: event.target.value })}
          placeholder="搜索提示词 / 文件名"
          value={filters.query}
        />
      </label>
      <p className="sl-filter-summary">
        {images.length} 张 · {posts} 个投稿
      </p>

      <FilterGroup title="模型">
        {models.map(([model, count]) => (
          <FilterChip
            active={filters.models.includes(model)}
            count={count}
            key={model || "none"}
            label={modelLabel(model || null)}
            onClick={() => onChange({ ...filters, models: toggle(filters.models, model) })}
          />
        ))}
      </FilterGroup>

      <FilterGroup title="Vibe">
        {vibes.map(([key, count]) => (
          <FilterChip
            active={filters.vibes.includes(key)}
            count={count}
            key={key || "none"}
            label={vibeLabel(key)}
            onClick={() => onChange({ ...filters, vibes: toggle(filters.vibes, key) })}
          />
        ))}
      </FilterGroup>

      {flags.length ? (
        <FilterGroup title="标记">
          {flags.map(([flag, count]) => (
            <FilterChip
              active={filters.flags.includes(flag as ImageFlag)}
              count={count}
              key={flag}
              label={flagLabels[flag as ImageFlag] ?? flag}
              onClick={() => onChange({ ...filters, flags: toggle(filters.flags, flag as ImageFlag) })}
            />
          ))}
        </FilterGroup>
      ) : null}

      <label className="sl-check">
        <input
          checked={filters.hideSpecial}
          onChange={(event) => onChange({ ...filters, hideSpecial: event.target.checked })}
          type="checkbox"
        />
        隐藏重绘、图生图和无元数据
      </label>
      {filters.query || filters.models.length || filters.vibes.length || filters.flags.length || filters.hideSpecial ? (
        <button className="sl-link-btn" onClick={() => onChange(emptyFilters)} type="button">
          清除筛选
        </button>
      ) : null}
    </aside>
  );
}

function FilterGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="sl-filter-group">
      <h3>{title}</h3>
      <div className="sl-filter-chips">{children}</div>
    </section>
  );
}

function FilterChip({ label, count, active, onClick }: { label: string; count: number; active: boolean; onClick: () => void }) {
  return (
    <button aria-pressed={active} className={`sl-filter-chip ${active ? "on" : ""}`} onClick={onClick} type="button">
      <span>{label}</span>
      <span className="sl-count">{count}</span>
    </button>
  );
}

type ImageGridProps = {
  workspaceId: string;
  images: ImageRecord[];
  selectedId: string | null;
  onSelect: (id: string) => void;
};

/** 按投稿分段显示；一个投稿算一个单位，和 skill 的统计口径一致。 */
export function ImageGrid({ workspaceId, images, selectedId, onSelect }: ImageGridProps) {
  const sections = useMemo(() => {
    const result: Array<{ key: string; title: string; subtitle: string; images: ImageRecord[] }> = [];
    for (const image of images) {
      const key = image.post?.dir_name ?? "__loose__";
      let section = result[result.length - 1];
      if (!section || section.key !== key) {
        section = {
          key,
          title: image.post?.title || image.post?.dir_name || "散图",
          subtitle: [image.post?.date, image.post?.post_id].filter(Boolean).join(" · "),
          images: [],
        };
        result.push(section);
      }
      section.images.push(image);
    }
    return result;
  }, [images]);

  if (!images.length) {
    return <div className="sl-empty">没有符合筛选条件的图片。</div>;
  }

  return (
    <div className="sl-grid-scroll">
      {sections.map((section, index) => (
        <section className="sl-post" key={`${section.key}-${index}`}>
          <header className="sl-post-head">
            <span className="sl-post-title">{section.title}</span>
            <span className="sl-post-sub">
              {section.subtitle}
              {section.subtitle ? " · " : ""}
              {section.images.length} 张
            </span>
          </header>
          <div className="sl-grid">
            {section.images.map((image) => (
              <button
                aria-label={image.rel_path}
                aria-pressed={image.id === selectedId}
                className={`sl-tile ${image.id === selectedId ? "selected" : ""}`}
                data-image-id={image.id}
                key={image.id}
                onClick={() => onSelect(image.id)}
                type="button"
              >
                <img alt="" decoding="async" loading="lazy" src={sourceImageUrl(workspaceId, image.id, 320)} />
                <span className="sl-tile-badges">
                  <span className="sl-badge">{modelLabel(image.model)}</span>
                  {image.vibe.count ? <span className="sl-badge accent">vibe {image.vibe.count}</span> : null}
                  {image.flags
                    .filter((flag) => flag !== "add_original")
                    .map((flag) => (
                      <span className={`sl-badge ${flag === "no_metadata" ? "danger" : "warn"}`} key={flag}>
                        {flagLabels[flag]}
                      </span>
                    ))}
                </span>
              </button>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
