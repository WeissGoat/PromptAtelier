import { useEffect, useState } from "react";
import { errorMessage } from "../api/client";
import type { CustomGroup, CustomGroups, ImageRecord } from "./api";
import { saveCustomGroups, sourceImageUrl } from "./api";
import { cleanRepresentatives, customImageIds, newCustomGroup } from "./customGroups";

type Props = {
  workspaceId: string;
  document: CustomGroups;
  images: ImageRecord[];
  initialGroup: string | null;
  onSaved: (doc: CustomGroups) => void;
  onClose: () => void;
};

export function CustomGroupsDialog({ workspaceId, document, images, initialGroup, onSaved, onClose }: Props) {
  const [draft, setDraft] = useState<CustomGroups>(() => structuredClone(document));
  const [selected, setSelected] = useState(initialGroup ?? document.groups[0]?.id ?? "");
  const [name, setName] = useState("");
  const [target, setTarget] = useState("");
  const [checked, setChecked] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [onlyMembers, setOnlyMembers] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const group = draft.groups.find((item) => item.id === selected);
  const hasChildren = draft.groups.some((item) => item.parent_id === selected);
  const leaves = draft.groups.filter((item) => !draft.groups.some((child) => child.parent_id === item.id));
  const memberIds = customImageIds(draft, selected);
  const shown = images.filter((image) => (!onlyMembers || memberIds.includes(image.id))
    && `${image.rel_path} ${image.prompt}`.toLowerCase().includes(query.toLowerCase()));
  useEffect(() => {
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", escape);
    return () => window.removeEventListener("keydown", escape);
  }, [onClose]);

  const change = (patch: Partial<CustomGroup>) => setDraft((current) => ({
    ...current, groups: current.groups.map((item) => item.id === selected ? { ...item, ...patch, updated_by: "user" } : item),
  }));
  const assign = (ids: string[], destination: string) => {
    setDraft((current) => {
      const membership = { ...current.membership };
      ids.forEach((id) => { if (destination) membership[id] = destination; else delete membership[id]; });
      const next = { ...current, membership, locked_image_ids: current.locked_image_ids.filter((id) => membership[id]) };
      return { ...next, groups: next.groups.map((item) => item.representative_image_id
        && !customImageIds(next, item.id).includes(item.representative_image_id) ? { ...item, representative_image_id: null } : item) };
    });
  };
  const add = (parentId: string | null, split = false) => {
    if (!name.trim()) { setError("填写新组名称。"); return; }
    const created = newCustomGroup(name.trim(), parentId);
    setDraft((current) => cleanRepresentatives({ ...current, groups: [...current.groups, { ...created, order: current.groups.length }],
      membership: split ? { ...current.membership, ...Object.fromEntries(checked.map((id) => [id, created.id])) } : current.membership }));
    setSelected(created.id); setName(""); setError(null);
  };
  const remove = () => {
    const removed = new Set([selected, ...draft.groups.filter((item) => item.parent_id === selected).map((item) => item.id)]);
    const membership = Object.fromEntries(Object.entries(draft.membership).filter(([, id]) => !removed.has(id)));
    setDraft({ ...draft, groups: draft.groups.filter((item) => !removed.has(item.id)), membership,
      locked_image_ids: draft.locked_image_ids.filter((id) => membership[id]) });
    setSelected("");
  };
  const merge = () => {
    if (!target || target === selected || hasChildren) return;
    setDraft((current) => cleanRepresentatives({ ...current, groups: current.groups.filter((item) => item.id !== selected),
      membership: Object.fromEntries(Object.entries(current.membership).map(([id, value]) => [id, value === selected ? target : value])) }));
    setSelected(target);
  };
  const save = async () => {
    setSaving(true); setError(null);
    try { const saved = await saveCustomGroups(workspaceId, draft); onSaved(saved); onClose(); }
    catch (exc) { setError(errorMessage(exc)); }
    finally { setSaving(false); }
  };

  return <div className="sl-workflow-overlay"><section aria-label="管理自定义分组" aria-modal="true" className="sl-workflow-dialog" role="dialog">
    <header><h2>管理自定义分组</h2><button onClick={onClose} type="button">关闭</button></header>
    <p className="sl-muted">维护图片归属与分析依据。保存分组不会生成图片。</p>
    {error ? <p className="sl-error" role="alert">{error}</p> : null}
    <div className="sl-custom-manager">
      <aside>
        <label>新组名称<input onChange={(event) => setName(event.target.value)} value={name} /></label>
        <div className="sl-workflow-actions">
          <button onClick={() => add(null)} type="button">新建组</button>
          <button disabled={!group || Boolean(group.parent_id) || memberIds.length > 0 && !hasChildren} onClick={() => add(selected)} type="button">新增子组</button>
        </div>
        {draft.groups.filter((item) => !item.parent_id).sort((a, b) => a.order - b.order).flatMap((parent) => [parent,
          ...draft.groups.filter((item) => item.parent_id === parent.id).sort((a, b) => a.order - b.order)]).map((item) => <button
          aria-pressed={item.id === selected} className={`sl-group-row ${item.parent_id ? "child" : ""} ${item.id === selected ? "on" : ""}`}
          key={item.id} onClick={() => setSelected(item.id)} type="button">{item.name}{item.locked ? " 🔒" : ""}</button>)}
      </aside>
      <div>
        {group ? <div className="sl-custom-fields">
          <label>组名<input onChange={(event) => change({ name: event.target.value })} value={group.name} /></label>
          <label>父组<select disabled={hasChildren} onChange={(event) => change({ parent_id: event.target.value || null })} value={group.parent_id ?? ""}>
            <option value="">顶层</option>{draft.groups.filter((item) => item.id !== selected && !item.parent_id
              && (!customImageIds(draft, item.id).length || draft.groups.some((child) => child.parent_id === item.id)))
              .map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select></label>
          <label>类型<select onChange={(event) => change({ kind: event.target.value as CustomGroup["kind"] })} value={group.kind}>
            <option value="style">画风</option><option value="review">待判断</option><option value="archive">特殊来源归档</option>
          </select></label>
          <label>顺序<input type="number" onChange={(event) => change({ order: Number(event.target.value) })} value={group.order} /></label>
          <label>分析依据<textarea onChange={(event) => change({ reason: event.target.value })} value={group.reason} /></label>
          <label>备注<textarea onChange={(event) => change({ notes: event.target.value })} value={group.notes} /></label>
          <label>证据强度<select onChange={(event) => change({ evidence_strength: event.target.value as CustomGroup["evidence_strength"] })} value={group.evidence_strength}>
            <option value="strong">充分</option><option value="limited">有限</option><option value="review">待判断</option>
          </select></label>
          <label>代表图<select onChange={(event) => change({ representative_image_id: event.target.value || null })} value={group.representative_image_id ?? ""}>
            <option value="">未指定</option>{images.filter((image) => memberIds.includes(image.id)).map((image) => <option key={image.id} value={image.id}>{image.rel_path}</option>)}
          </select></label>
          <label className="sl-check"><input checked={group.locked} onChange={(event) => change({ locked: event.target.checked })} type="checkbox" />锁定组与成员，Agent 重新分析时保留</label>
          <button disabled={!checked.length} onClick={() => change({ evidence_image_ids: checked })} type="button">将勾选图片设为证据</button>
          <button onClick={remove} type="button">删除组并将成员移回未分组</button>
        </div> : <p>选择一个组，或先建立画风家族。</p>}
        <div className="sl-workflow-actions">
          <label>目标组<select onChange={(event) => setTarget(event.target.value)} value={target}><option value="">未分组</option>
            {leaves.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <button disabled={!checked.length} onClick={() => assign(checked, target)} type="button">移动勾选的 {checked.length} 张</button>
          <button disabled={!checked.length} onClick={() => add(group?.parent_id ?? null, true)} type="button">将勾选图片拆成新组</button>
          <button disabled={!group || hasChildren || !target || target === selected} onClick={merge} type="button">将当前组合并到目标组</button>
          <button disabled={!checked.some((id) => draft.membership[id])} onClick={() => setDraft((current) => ({ ...current,
            locked_image_ids: [...new Set([...current.locked_image_ids, ...checked.filter((id) => current.membership[id])])] }))} type="button">锁定勾选图片归属</button>
          <button disabled={!checked.length} onClick={() => setDraft((current) => ({ ...current,
            locked_image_ids: current.locked_image_ids.filter((id) => !checked.includes(id)) }))} type="button">解除勾选图片锁定</button>
        </div>
        <div className="sl-workflow-actions">
          <input aria-label="搜索分组图片" onChange={(event) => setQuery(event.target.value)} placeholder="搜索文件名或提示词" value={query} />
          <label className="sl-check"><input checked={onlyMembers} onChange={(event) => setOnlyMembers(event.target.checked)} type="checkbox" />只看当前组</label>
          <button onClick={() => setChecked(shown.map((image) => image.id))} type="button">全选当前列表</button>
          <button onClick={() => setChecked([])} type="button">清空选择</button>
        </div>
        <div className="sl-members-list">{shown.map((image) => <div className="sl-member" key={image.id}>
          <label><input aria-label={`选择 ${image.rel_path}`} checked={checked.includes(image.id)} onChange={(event) => setChecked((current) => event.target.checked ? [...current, image.id] : current.filter((id) => id !== image.id))} type="checkbox" />
            <img alt="" loading="lazy" src={sourceImageUrl(workspaceId, image.id, 80)} /><span>{image.rel_path}<small>{draft.groups.find((item) => item.id === draft.membership[image.id])?.name ?? "未分组"}</small></span>
          </label>
          {image.post ? <button onClick={() => setChecked((current) => [...new Set([...current, ...images.filter((item) => item.post?.dir_name === image.post?.dir_name).map((item) => item.id)])])} type="button">选同投稿</button> : null}
        </div>)}</div>
      </div>
    </div>
    <footer><span>尚未保存的修改只在本次编辑中保留。</span><button className="sl-primary" disabled={saving} onClick={() => void save()} type="button">{saving ? "保存中…" : "保存自定义分组"}</button></footer>
  </section></div>;
}
