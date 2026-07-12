# Web 临时草稿与 Compare 参数一致性设计

## 目标

Custom 工作台中的节点编辑应立即成为下一次 Preview/Generate 的运行输入，不再需要“应用到本次运行”。临时节点和临时修改节点需要明确的星号标记。Compare Generate 启动时冻结一份共享生图参数，确保所有组合使用相同 seed、尺寸、Negative 和 Renderer 参数。

## 节点编辑

- Form 中每次产生合法 `NodeDocument` 后，同时更新编辑器草稿和对应槽位的 `draftNode`。
- JSON 文本只有在语法与基本结构合法时才更新对应槽位；无效 JSON 保留在编辑器中并显示错误，运行节点继续使用最后一个合法草稿。
- 删除“应用到本次运行”按钮和 `/nodes/preview` 调用。
- `Save` 仍是唯一写入节点库的操作；保存前继续调用后端校验。
- 槽位 `role` 是运行时节点角色的权威来源。旧 Artist `tags.txt` 迁移节点允许 `kind: unknown`，不再要求 `node.kind === slot.role`。

## 临时标记

- 原始节点显示原名称。
- 已修改节点显示 `名称 *`。
- 无源临时节点显示 `名称 *`；若没有名称，使用节点 `id` 后加 ` *`。
- 状态标签继续显示“原始节点”“临时修改”“空白临时节点”。

## Compare 参数快照

- 点击 Compare Generate 时复制当前 `RenderWorkspaceParams`，之后界面参数变化不影响本轮任务。
- 若 seed 是非负整数，所有组合使用该 seed。
- 若 seed 是 `-1` 或无效值，启动时只生成一个 32 位随机 seed，所有组合共用。
- 所有组合共用 Negative、宽高和其他渲染参数；每个组合仍固定 `n_samples=1`。
- Artist、Character、Action 节点按矩阵变化，参数快照不随组合变化。

## 验收

- 修改节点后不点击额外按钮，下一次 Preview/Generate 请求已经携带 inline 草稿。
- 临时修改和临时节点的搜索框名称带 `*`，原始节点不带。
- Compare 使用 `seed=-1` 时，所有 `/compose-preview` 请求携带同一个非负 seed。
- 指定 seed 时，所有组合使用指定值。
- 真实 NovelAI Compare 生成的结果卡 seed 相同。
