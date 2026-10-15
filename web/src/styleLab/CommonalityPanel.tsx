import { ChevronDown, ChevronRight, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { ImageRecord } from "./api";
import { sourceImageUrl } from "./api";
import { analyzeCommonality, diffAgainst, type ImageProfile, type TagDiff, type TagStat, type TagTiers } from "./commonality";
import { useTranslations } from "./translations";

const RECOMMEND = 3;
const FEW_PREVIEW = 24;
const LIST_LIMIT = 12;

type CommonalityPanelProps = {
  workspaceId: string;
  images: ImageRecord[];
  selectedId: string | null;
  translateOn: boolean;
  onSelect: (id: string) => void;
};

/** 图片网格下方：当前筛选的图里提示词和参数的共性与差异，帮着挑配方的起点。 */
export function CommonalityPanel({ workspaceId, images, selectedId, translateOn, onSelect }: CommonalityPanelProps) {
  const [open, setOpen] = useState(true);
  const result = useMemo(() => analyzeCommonality(images), [images]);
  const tags = useMemo(
    () => [...result.prompt.all, ...result.prompt.most, ...result.prompt.few, ...result.character.all, ...result.character.most].map((stat) => stat.tag),
    [result],
  );
  const { lookup } = useTranslations(open ? tags : [], translateOn);

  if (result.count < 2) {
    return (
      <section className="sl-common">
        <header className="sl-common-head">
          <Sparkles size={14} aria-hidden="true" />
          <span className="sl-zone-title">共性分析</span>
          <span className="sl-muted">至少要有两张带元数据的图才能比较；可以在左栏换个分组或清除筛选。</span>
        </header>
      </section>
    );
  }

  const recommended = result.profiles.slice(0, RECOMMEND);
  const usable = result.profiles.map((profile) => profile.image);
  const focused = usable.find((image) => image.id === selectedId) ?? null;
  return (
    <section className="sl-common" aria-label="共性分析">
      <header className="sl-common-head">
        <button className="sl-section-toggle" onClick={() => setOpen(!open)} type="button">
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <Sparkles size={14} aria-hidden="true" />
          共性分析
        </button>
        <span className="sl-muted">
          当前筛选的 {result.count} 张 · 共有 {result.prompt.all.length} 个 tag · 参数不一致 {result.params.filter((item) => !item.consistent).length} 项
        </span>
      </header>
      {open ? (
        <div className="sl-common-body">
          {focused ? (
            <FocusDiff image={focused} images={usable} lookup={lookup} onSelect={onSelect} workspaceId={workspaceId} />
          ) : (
            <p className="sl-hint">在上面选中一张图，这里会列出它和其他图的差异。</p>
          )}
          <div className="sl-common-block">
            <h3>推荐作为基准</h3>
            <p className="sl-muted">和其他图的提示词重合度最高、参数和多数一致的图，划分出的画风最有代表性。点图片选中它，再在右栏新建配方。</p>
            <div className="sl-common-recommend">
              {recommended.map((profile, index) => (
                <button
                  className={`sl-common-pick ${profile.image.id === selectedId ? "on" : ""}`}
                  key={profile.image.id}
                  onClick={() => onSelect(profile.image.id)}
                  type="button"
                >
                  <img alt="" loading="lazy" src={sourceImageUrl(workspaceId, profile.image.id, 240)} />
                  <span className="sl-common-pick-text">
                    <strong>
                      {index === 0 ? "首选" : `备选 ${index}`} · 重合 {Math.round(profile.overlap * 100)}%
                    </strong>
                    <span className="sl-muted">{profileReason(profile)}</span>
                  </span>
                </button>
              ))}
            </div>
          </div>

          <TierBlock lookup={lookup} title="提示词" tiers={result.prompt} total={result.count} />
          {result.character.all.length + result.character.most.length + result.character.few.length ? (
            <TierBlock lookup={lookup} title="角色提示词" tiers={result.character} total={result.count} />
          ) : null}

          <div className="sl-common-block">
            <h3>参数</h3>
            <table className="sl-common-params">
              <tbody>
                {result.params.map((param) => (
                  <tr className={param.consistent ? "" : "diff"} key={param.key}>
                    <th>{param.label}</th>
                    <td>
                      {param.consistent ? (
                        <span className="sl-common-value" title={param.majority}>
                          {param.majority}
                        </span>
                      ) : (
                        param.values.map((item) => (
                          <span className="sl-common-value" key={item.value} title={item.value}>
                            {item.value}
                            <span className="sl-count">×{item.count}</span>
                          </span>
                        ))
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="sl-common-block">
            <h3>逐张差异</h3>
            <table className="sl-common-images">
              <thead>
                <tr>
                  <th>图</th>
                  <th>重合</th>
                  <th>缺少多数图都有的</th>
                  <th>只有这张有的</th>
                  <th>参数和多数不同</th>
                </tr>
              </thead>
              <tbody>
                {result.profiles.map((profile) => (
                  <tr
                    className={profile.image.id === selectedId ? "on" : ""}
                    key={profile.image.id}
                    onClick={() => onSelect(profile.image.id)}
                  >
                    <td>
                      <img alt="" loading="lazy" src={sourceImageUrl(workspaceId, profile.image.id, 120)} />
                    </td>
                    <td className="num">{Math.round(profile.overlap * 100)}%</td>
                    <td>
                      <TagList tags={profile.missing} tone="missing" />
                    </td>
                    <td>
                      <TagList tags={profile.unique} tone="unique" />
                    </td>
                    <td>
                      {profile.deviations.length ? (
                        profile.deviations.map((item) => (
                          <span className="sl-common-dev" key={item.label} title={`多数是 ${item.majority}`}>
                            {item.label} {item.value}
                          </span>
                        ))
                      ) : (
                        <span className="sl-muted">一致</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function profileReason(profile: ImageProfile): string {
  const parts = [];
  parts.push(profile.missing.length ? `缺 ${profile.missing.length} 个常见 tag` : "常见 tag 都有");
  parts.push(profile.deviations.length ? `${profile.deviations.length} 项参数和多数不同` : "参数和多数一致");
  return parts.join("，");
}

function TierBlock({
  title,
  tiers,
  total,
  lookup,
}: {
  title: string;
  tiers: TagTiers;
  total: number;
  lookup: (text: string) => string | undefined;
}) {
  const [showFew, setShowFew] = useState(false);
  const few = showFew ? tiers.few : tiers.few.slice(0, FEW_PREVIEW);
  return (
    <div className="sl-common-block">
      <h3>{title}</h3>
      <TierRow label="全部共有" lookup={lookup} stats={tiers.all} total={total} tone="all" />
      <TierRow label="多数有（≥ 一半）" lookup={lookup} stats={tiers.most} total={total} tone="most" />
      <TierRow label="少数有" lookup={lookup} stats={few} total={total} tone="few" />
      {tiers.few.length > FEW_PREVIEW ? (
        <button className="sl-link-btn" onClick={() => setShowFew(!showFew)} type="button">
          {showFew ? "收起" : `还有 ${tiers.few.length - FEW_PREVIEW} 个`}
        </button>
      ) : null}
    </div>
  );
}

function TierRow({
  label,
  stats,
  total,
  tone,
  lookup,
}: {
  label: string;
  stats: TagStat[];
  total: number;
  tone: "all" | "most" | "few";
  lookup: (text: string) => string | undefined;
}) {
  if (!stats.length) return null;
  return (
    <div className="sl-common-tier">
      <span className="sl-common-tier-label">
        {label} <span className="sl-count">{stats.length}</span>
      </span>
      <div className="sl-common-tags">
        {stats.map((stat) => {
          const weights = [...stat.weights.keys()];
          const mixed = weights.length > 1;
          const zh = lookup(stat.tag);
          return (
            <span
              className={`sl-common-tag tier-${tone} ${mixed ? "mixed" : ""}`}
              key={stat.tag}
              title={[
                `${stat.count}/${total} 张`,
                mixed ? `权重不一：${[...stat.weights.entries()].map(([weight, count]) => `${weight}×${count}`).join("，")}` : null,
              ]
                .filter(Boolean)
                .join("\n")}
            >
              {weights.length === 1 && weights[0] !== "1" ? <span className="sl-common-weight">{weights[0]}</span> : null}
              {stat.tag}
              {tone !== "all" ? <span className="sl-common-frac">{stat.count}/{total}</span> : null}
              {mixed ? <span className="sl-common-weight">权重不一</span> : null}
              {zh ? <span className="sl-chip-zh">{zh}</span> : null}
            </span>
          );
        })}
      </div>
    </div>
  );
}

function TagList({ tags, tone }: { tags: string[]; tone: "missing" | "unique" }) {
  if (!tags.length) return <span className="sl-muted">—</span>;
  return (
    <span className={`sl-common-list ${tone}`} title={tags.join(", ")}>
      {tags.slice(0, LIST_LIMIT).join(", ")}
      {tags.length > LIST_LIMIT ? ` 等 ${tags.length} 个` : ""}
    </span>
  );
}

/** 选中的图和其他图比：默认和"多数"比，也可以挑一张一对一比。 */
function FocusDiff({
  image,
  images,
  workspaceId,
  lookup,
  onSelect,
}: {
  image: ImageRecord;
  images: ImageRecord[];
  workspaceId: string;
  lookup: (text: string) => string | undefined;
  onSelect: (id: string) => void;
}) {
  const [target, setTarget] = useState<string | null>(null);
  const others = images.filter((item) => item.id !== image.id);
  const against = others.find((item) => item.id === target) ?? null;
  useEffect(() => setTarget(null), [image.id]);
  const diff = useMemo(() => diffAgainst(image, against ? [against] : others), [image, against, others]);
  const single = Boolean(against);
  const empty =
    !diff.params.length &&
    [diff.prompt, diff.character].every((item) => !item.added.length && !item.missing.length && !item.weights.length);

  return (
    <div className="sl-common-block sl-common-focus">
      <h3>选中的图和{single ? "另一张" : `其他 ${others.length} 张的多数`}比</h3>
      <div className="sl-common-targets">
        <span className="sl-common-target mine" title="选中的图">
          <img alt="选中的图" src={sourceImageUrl(workspaceId, image.id, 160)} />
        </span>
        <span className="sl-muted">对比</span>
        <button className={`sl-common-target-all ${single ? "" : "on"}`} onClick={() => setTarget(null)} type="button">
          多数
        </button>
        {others.map((other) => (
          <button
            aria-label={`和 ${other.rel_path} 比`}
            aria-pressed={other.id === target}
            className={`sl-common-target ${other.id === target ? "on" : ""}`}
            key={other.id}
            onClick={() => setTarget(other.id)}
            onDoubleClick={() => onSelect(other.id)}
            title={`${other.rel_path}
单击对比，双击改为选中它`}
            type="button"
          >
            <img alt="" loading="lazy" src={sourceImageUrl(workspaceId, other.id, 120)} />
          </button>
        ))}
      </div>
      {empty ? <p className="sl-muted">提示词和参数完全一致（不比尺寸）。</p> : null}
      <DiffRows diff={diff.prompt} lookup={lookup} single={single} title="提示词" />
      <DiffRows diff={diff.character} lookup={lookup} single={single} title="角色提示词" />
      {diff.params.length ? (
        <div className="sl-common-diff-row">
          <span className="sl-common-tier-label">参数</span>
          <div className="sl-common-tags">
            {diff.params.map((item) => (
              <span className="sl-common-dev" key={item.label} title={`${item.mine} → ${single ? "对比图" : "多数"} ${item.theirs}`}>
                {item.label} {item.mine} → {item.theirs}
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function DiffRows({
  title,
  diff,
  single,
  lookup,
}: {
  title: string;
  diff: TagDiff;
  single: boolean;
  lookup: (text: string) => string | undefined;
}) {
  const rows: Array<[string, string[], "added" | "missing"]> = [
    [single ? `${title} · 只有选中的有` : `${title} · 多出（其他图大多没有）`, diff.added, "added"],
    [single ? `${title} · 只有对比图有` : `${title} · 缺少（其他图大多有）`, diff.missing, "missing"],
  ];
  return (
    <>
      {rows.map(([label, tags, tone]) =>
        tags.length ? (
          <div className="sl-common-diff-row" key={tone}>
            <span className="sl-common-tier-label">
              {label} <span className="sl-count">{tags.length}</span>
            </span>
            <div className="sl-common-tags">
              {tags.map((tag) => (
                <span className={`sl-common-tag diff-${tone}`} key={tag}>
                  {tone === "added" ? "+ " : "− "}
                  {tag}
                  {lookup(tag) ? <span className="sl-chip-zh">{lookup(tag)}</span> : null}
                </span>
              ))}
            </div>
          </div>
        ) : null,
      )}
      {diff.weights.length ? (
        <div className="sl-common-diff-row">
          <span className="sl-common-tier-label">
            {title} · 权重不同 <span className="sl-count">{diff.weights.length}</span>
          </span>
          <div className="sl-common-tags">
            {diff.weights.map((item) => (
              <span className="sl-common-tag mixed" key={item.tag}>
                {item.tag}
                <span className="sl-common-weight">
                  {item.mine} → {item.theirs}
                </span>
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </>
  );
}
