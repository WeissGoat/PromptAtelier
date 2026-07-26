# Web 随机节点角色根目录与二次过滤交互设计

**日期：** 2026-07-26
**状态：** 已确认
**范围：** PromptAtelier Web Custom 页随机节点

## 1. 背景

现有随机节点已支持 Folder、Collection、Glob、Action `classify.yaml` 二次过滤、候选预览、Compare Matrix 和 NT 出图，但存在两个业务问题：

1. Folder 和 Glob 当前相对整个 `legacy.design_root`，用户必须输入 `动作改2/new`、`角色/...` 等包含节点类型目录的路径。这与普通节点搜索“先确定节点类型，再在该类型根目录中搜索”的语义不一致。
2. 二次过滤使用浏览器原生 `multiple select`。该控件依赖 Ctrl/Shift 多选，已选项不直观，也缺少方便的单项取消、按字段清空和全部清空能力。

本次迭代只修正路径基准和过滤器交互，不改变随机抽取、Compare、NT、Composer、Policy、Renderer 或 PNG 元数据链路。

## 2. 目标

- Folder 和 Glob 的路径相对当前槽位对应的节点类型根目录。
- 普通节点搜索和随机节点共用同一份角色目录定义。
- 二次过滤支持直观的多选、取消、搜索、清空和已选摘要。
- 保持现有 `NodePoolSpec` 持久化结构与后端过滤语义。
- 没有选中任何分类值时，不启用 `classify.yaml` 过滤。
- 不影响 AgentComposer、AgentComposer Hash 或缓存行为。

## 3. 非目标

- 不改变 Collection 工程配置的路径语义。
- 不把随机候选数量加入 Compare Matrix 的乘积。
- 不增加新的 `classify.yaml` 字段或修改标注规范。
- 不让 AgentComposer 接收 `NodePoolSpec`。
- 不为旧的 design-root 相对路径增加长期兼容分支。
- 不修改 Batch Selector 的外部 YAML 格式。

## 4. 节点类型根目录

### 4.1 复用现有定义

普通节点搜索已经在 `NodeWorkspace` 中通过 `ROLE_DIRS` 定义节点类型与目录候选：

| 节点类型 | 首选目录 | 兼容候选目录 |
| --- | --- | --- |
| Artist | `画风` | `artist`、`artists` |
| Character | `角色` | `character`、`characters` |
| Action | `动作改2` | `动作`、`action`、`actions` |
| Background | `背景` | `background`、`backgrounds` |

实现时将该定义移动到公共节点路径模块，并提供以下能力：

- 返回某一节点类型的目录候选列表。
- 返回第一个实际存在的节点类型根目录。
- 当所有候选均不存在时，返回首选目录作为错误信息中的预期路径。
- 校验一个相对路径解析后仍位于节点类型根目录内。

`NodeWorkspace` 与 `NodePoolResolver` 必须调用该公共能力，不得各自保留目录名称副本。

### 4.2 Folder 语义

Folder 的 `source.value` 只接受相对当前节点类型根目录的路径。

示例：

```text
role = action
source.value = new
实际目录 = <design_root>/动作改2/new
```

```text
role = character
source.value = .
实际目录 = <design_root>/角色
```

Folder 不接受绝对路径。包含 `..` 且解析后越过当前节点类型根目录的路径必须拒绝。

### 4.3 Glob 语义

Glob 表达式同样相对当前节点类型根目录。

示例：

```text
role = action
source.value = new/*足部*
实际表达式 = <design_root>/动作改2/new/*足部*
```

Glob 不接受绝对表达式，也不得通过 `..` 越过当前节点类型根目录。

### 4.4 Collection 语义

Collection 继续使用现有 Web 工程配置和 Batch `require` 合并后的定义。Collection 内部已有的 Folder、Glob 和节点引用保持现有工程配置语义，不因 Web 随机槽位的直接 Folder/Glob 输入而改变。

这一区分是明确的：

- Web 随机槽位直接填写 Folder/Glob：相对节点类型根目录。
- Collection 内部选择器：保持现有项目配置语义。

### 4.5 候选展示

随机候选的 `relative` 字段改为相对节点类型根目录：

```text
new/20260506_3P后入趴卧
```

界面主要显示文件夹名称，路径作为辅助信息，不再重复显示 `动作改2`、`角色` 等已由槽位类型确定的前缀。

## 5. 二次过滤交互

### 5.1 总体布局

Action 随机节点编辑器默认只显示：

```text
classify.yaml 二次过滤
[+ 添加筛选]
```

未选择任何分类值时，不显示十个空字段，也不启用后端分类过滤。

### 5.2 添加字段

点击“添加筛选”后显示尚未启用的分类字段：

```text
phase, species, cast, domain, subtype,
pose, environment, tone, flags, clothing
```

用户选择字段后，该字段加入已启用字段列表。一个字段在尚未选值时仅属于当前界面的临时状态，不写入 Workspace 持久化数据。

### 5.3 值选择器

每个已启用字段使用可搜索的复选下拉框：

- 点击选项即可选中或取消，不要求 Ctrl/Shift。
- 下拉框在连续多选时保持打开。
- 支持按文本搜索可用值。
- 可用值来自规范枚举、扫描 Facet 和当前已保存值的并集。
- 未出现在当前扫描结果中的已保存值仍须显示，用户可以看到并取消它。

### 5.4 已选标签

字段已选值显示为可删除标签：

```text
Domain
[foot ×] [body ×] [+ 选择值]
```

交互规则：

- 点击标签的 `×` 只取消该值。
- 点击字段“清空”取消该字段全部值。
- 最后一个值被取消后，该字段自动从已启用列表移除。
- 点击“清空全部”移除所有分类条件。

### 5.5 过滤语义

后端匹配语义保持不变：

- 同一字段多个值使用 OR。
- 不同字段之间使用 AND。
- 未指定字段不参与过滤。

示例：

```yaml
domain: [foot, body]
subtype: [sole_focus, footjob]
```

含义为：

```text
(domain 包含 foot 或 body)
AND
(subtype 包含 sole_focus 或 footjob)
```

### 5.6 扫描刷新

分类值发生变化后，前端进行短延迟扫描，避免连续点击时为每次状态变化都发送请求。刷新后继续显示：

- 原始候选数量。
- 过滤后可用数量。
- 缺少 `classify.yaml` 的数量。
- 分类不匹配数量。
- 无效分类文件和无效节点数量。

候选为空时保留用户当前过滤条件，并显示参与过滤的字段和值，便于定位条件是否过严。

## 6. 状态模型

后端和 Workspace 持久化结构保持不变：

```ts
type NodePoolSpec = {
  source: {
    type: "folder" | "collection" | "glob";
    value: string;
    recursive: boolean;
    include_names: string[];
    exclude_names: string[];
  };
  filters: {
    classify: Record<string, string[]>;
  };
};
```

新增的“已打开但尚未选值的字段”和“当前打开的下拉框”属于组件局部状态，不进入 `NodePoolSpec`。

页面刷新后：

- 已经选值的字段从 `NodePoolSpec.filters.classify` 恢复。
- 没有选值的临时字段不恢复。
- 固定节点、Compare、随机来源和其他 Workspace 数据保持现有持久化行为。

## 7. 组件边界

### 7.1 公共节点路径模块

负责角色目录定义、根目录解析和路径边界校验。它不负责节点读取、随机抽取或 Web 状态。

### 7.2 NodeWorkspace

普通节点搜索继续支持目录候选和分页，但改为调用公共节点路径模块。外部 API 与返回结构保持不变。

### 7.3 NodePoolResolver

负责在解析直接 Folder/Glob 前取得角色根目录，并验证输入是合法相对路径。Collection 分支保持当前解析链路。

### 7.4 RandomNodeEditor

继续负责随机来源、扫描状态、候选预览和统计，但把分类字段编辑委托给独立的 `ClassifyFilterEditor`。

### 7.5 ClassifyFilterEditor

负责：

- 已启用字段列表。
- 添加字段菜单。
- 可搜索多选下拉框。
- 已选标签与单项取消。
- 字段清空和全部清空。

该组件只通过完整的 `ClassifyFilter` 输入和 `onChange(nextFilter)` 输出与外部通信。

## 8. 数据流

```text
用户选择 Action 随机槽位
  -> Folder: new
  -> 公共角色目录解析：design/动作改2
  -> NodePoolResolver 扫描 design/动作改2/new
  -> 可选 ClassifyFilterEditor 更新 classify 条件
  -> NodePoolResolver 过滤候选
  -> Preview / Generate 抽取普通 NodeDocument
  -> Composer / Policy / Renderer
  -> Generation Result 与 PNG 随机节点元数据
```

AgentComposer 只接收最终抽中的普通 `NodeDocument`，不接收相对路径基准、过滤器 UI 状态或 `NodePoolSpec`。

## 9. 错误处理

- Folder/Glob 使用绝对路径：返回“请输入相对 `<节点类型>` 根目录的路径”。
- 路径越过角色根目录：拒绝扫描并显示角色根目录。
- 角色根目录不存在：显示节点类型和预期候选目录。
- 分类条件启用后缺少 `classify.yaml`：排除并计数，不作为请求级错误。
- 分类文件无效：排除、计数并保留现有警告上限。
- 过滤后候选为空：禁用 Preview/Generate，并显示当前有效条件摘要。

## 10. 兼容边界

- `NodePoolSpec` Schema 不升级。
- 已保存的分类数组可以直接恢复到新筛选器。
- 旧的 design-root 相对 Folder/Glob 值，例如 `动作改2/new`，不增加长期兼容解析；界面提示用户改为 `new`。
- Collection、Batch 配置和普通固定节点引用不受影响。
- AgentComposer Hash、缓存键和缺失缓存行为不变。

## 11. 验收标准

### 11.1 路径业务验收

1. Action Folder 输入 `new`，实际扫描 `<design_root>/动作改2/new`。
2. Character Folder 输入 `.`，实际扫描 `<design_root>/角色`。
3. Action Glob 输入 `new/*足部*`，不得匹配其他节点类型目录。
4. 绝对路径和越界路径被明确拒绝。
5. Collection 随机节点保持现有候选结果。

### 11.2 过滤交互验收

1. 默认不显示十个空字段。
2. `Domain` 可以同时选择 `foot` 和 `body`。
3. 点击标签 `×` 可以单独取消一个值。
4. 字段清空后该字段消失。
5. 清空全部后，不读取 `classify.yaml`，缺少分类文件的节点重新进入候选池。
6. `Domain` 与 `Subtype` 同时启用时使用字段间 AND。
7. 刷新页面后已选字段和值恢复，空字段不恢复。
8. 候选为空时显示当前条件摘要。

### 11.3 真实链路验收

1. 使用一个固定 Artist、固定 Character 和 Folder 随机 Action 真实生成一张 NovelAI 图片。
2. 从实际 PNG 读取 `tags_machine_core.random_nodes`，确认最终 Action ref 与本次角色根目录扫描结果一致。
3. 再启用至少两个分类字段生成一张图片，确认抽中的 Action 满足过滤条件。
4. 固定节点 AgentComposer 链路执行一次 Preview/Generate 回归，确认 Hash、缓存和最终 Prompt 行为未改变。

## 12. 实施约束

- 直接在当前 `main` 开发，不创建新分支。
- 不修改或提交工作区中与本功能无关的现有变更。
- 中文文档和必要的中文注释。
- 先完成完整功能，再集中执行业务验收。
- NovelAI 真实出图优先于大量接口或单元测试。
