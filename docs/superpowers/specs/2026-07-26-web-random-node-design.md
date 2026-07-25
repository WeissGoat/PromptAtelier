# Web 随机节点设计

## 1. 背景

PromptAtelier Web 的 Custom 页面目前支持固定节点、Compare 节点和空白临时节点。新增“随机节点”后，用户可以把某个 Artist、Character、Action 或 Background 槽位配置为候选池，并在每个实际生成任务开始前随机选出一个普通节点。

随机节点属于 Web 输入层的未解析选择器，不是特殊 `NodeDocument`。进入 Composer 前必须解析成普通节点，AgentComposer、ScriptComposer、PromptPolicyPipeline 和 Renderer 均不感知随机逻辑。

## 2. 目标

- Custom 页面所有节点角色都支持随机节点。
- 候选池支持 Folder、Collection、Glob 三种来源。
- Action 随机池支持通过 `classify.yaml` 做可选的二次过滤。
- 选择来源后可以预览扫描结果、搜索候选并滚动分页加载。
- 普通 Generate、Compare Matrix 和 NT 都使用同一套任务规划与随机解析链路。
- 单次 Generate 内优先无重复抽取，候选耗尽后重新打乱。
- 随机配置保存在浏览器工作区，但不写入 `design` 节点源文件。
- AgentComposer 的输入、Hash 和缓存规则保持不变。

## 3. 非目标

- 不把候选数量展开为 Compare Matrix 的新维度。
- 不跨多次 Generate 记录节点使用历史。
- 不支持手工候选列表。
- 不支持一个随机节点同时组合多个来源；复杂来源通过 Collection 组合。
- 第一版不支持 OR 条件组、表达式语言或任意 YAML 查询。
- 不修改 `classify.yaml`，只读取它进行过滤。

## 4. 核心模型

### 4.1 槽位身份与节点来源分离

`Primary / Compare` 表示槽位在矩阵中的身份；固定、临时、随机表示槽位的节点来源。两者不能复用同一个枚举。

```text
NodeVariantSlot
├─ mode: primary | compare
└─ source
   ├─ fixed
   ├─ temporary
   └─ random
```

因此 Primary 和任意 Compare 槽位都可以配置为随机节点。

### 4.2 NodePoolSpec

随机节点保存未解析的候选池配置：

```yaml
kind: random
source:
  type: folder | collection | glob
  value: "..."
  recursive: false
  include_names: []
  exclude_names: []
filters:
  classify: {}
```

字段说明：

| 字段 | 含义 |
| --- | --- |
| `source.type` | 候选池来源类型。 |
| `source.value` | Folder 路径、Collection 名称或 Glob 表达式。 |
| `source.recursive` | Folder 是否递归扫描。 |
| `source.include_names` | 可选名称包含模式。 |
| `source.exclude_names` | 可选名称排除模式。 |
| `filters.classify` | 可选 `classify.yaml` 二次过滤条件。 |

Folder 和 Glob 默认相对 `legacy.design_root`，解析后的路径不得越过该目录。Collection 从 Web 工程配置加载。

## 5. 工程配置

`configs/local.yaml` 增加 Web 工程片段入口：

```yaml
web:
  project_requires:
    - examples/project/collections.yaml
    - examples/project/nai_const_action_groups.yaml
```

`ProjectCollectionLoader` 沿用现有 Batch `require` 的顺序合并规则，提供按角色分组的 Collection。Custom 和 Batch 共用同一套项目集合定义，不在 Web 中维护第二份 Collection 数据。

配置文件加载失败时，Collection 随机节点面板显示文件路径和错误原因；Folder、Glob 与普通节点功能仍可继续使用。

## 6. 候选池解析

### 6.1 通用输入层组件

候选池解析能力从 Batch 语义中抽离为输入层通用服务：

```text
NodePoolSpec
  -> ProjectCollectionLoader
  -> NodePoolResolver
  -> CandidateNode[]
  -> RandomNodeDeck
  -> NodeDocument
```

组件职责：

- `ProjectCollectionLoader`：读取 `web.project_requires` 并提供 Collection。
- `NodePoolResolver`：解析 Folder、Collection、Glob，校验路径、角色与节点可读性。
- `RandomNodeDeck`：管理一次 Generate 内的乱序队列和耗尽重置。
- `WebTaskPlanner`：展开 Generate、Compare Matrix 和 NT，并在 Composer 前解析随机节点。

现有 Batch Selector 的外部 YAML 格式保持不变。实现时把 Folder、Collection、Glob 的公共扫描内核抽到输入层，Batch 通过现有入口委托该内核；Custom 不直接依赖 `batch` 模块。

### 6.2 来源语义

- `Folder`：扫描一个目录，可配置递归、名称包含与排除。
- `Collection`：引用一个现有项目集合；需要组合多个目录时由 Collection 完成。
- `Glob`：在 `legacy.design_root` 下按表达式匹配节点目录。

候选结果按节点角色读取为 Artist、Character、Action 或 Background。节点类型不匹配或节点不可读时不进入最终候选池，并计入扫描警告。

## 7. classify.yaml 二次过滤

### 7.1 启用条件

只有 `filters.classify` 至少配置一个字段时才读取 `classify.yaml`。未配置任何分类条件时，节点是否存在 `classify.yaml` 均不影响原始候选池。

启用过滤后：

- 缺失 `classify.yaml` 的节点被排除。
- YAML 无效或字段结构非法的节点被排除。
- 排除原因和数量在候选预览中单独显示。

### 7.2 归一化

所有可过滤字段统一归一化为字符串集合：

```text
phase       -> [core]
species     -> [human]
cast        -> [1boy1girl]
domain      -> [foot, sex]
subtype     -> [footjob, barefoot, sole_focus, cum]
pose        -> [sitting]
environment -> []
tone        -> [normal]
flags       -> []
clothing    -> [specific_outfit]
```

`subtype` 不按 domain 暴露嵌套查询，而是把所有 subtype 值合并为一个集合。`schema_version` 和 `node_id` 不作为业务过滤字段。

第一版仅允许 Action 随机节点配置 `classify.yaml` 过滤；其他角色提交分类过滤条件时直接返回校验错误。

### 7.3 匹配规则

可过滤字段：

```text
phase, species, cast, domain, subtype,
pose, environment, tone, flags, clothing
```

规则统一为“包含任意一个”：

- 同字段选择多个值：节点命中任意一个即可。
- 不同字段之间：使用 AND。
- 未指定字段：完全不参与过滤。

示例：

```yaml
filters:
  classify:
    cast: [1boy1girl, 1boy2girls]
    domain: [foot]
    subtype: [footjob, sole_focus]
    tone: [normal, affectionate]
```

含义：

```text
cast 命中 1boy1girl 或 1boy2girls
AND domain 包含 foot
AND subtype 命中 footjob 或 sole_focus
AND tone 命中 normal 或 affectionate
```

## 8. Web 交互

每个节点槽位增加骰子图标。点击后，在确认替换未保存临时修改后，把当前槽位切换为随机节点。

随机节点编辑区显示：

- 来源类型选择：Folder / Collection / Glob。
- 与来源类型对应的输入控件。
- Folder 的递归、名称包含与排除配置。
- Action 的可选 `classify.yaml` 过滤字段。
- 扫描和重新扫描按钮。
- 原始扫描数、过滤后数量、未标注排除数、条件不匹配数、无效文件数。
- 候选节点列表，支持搜索和滚动分页加载。
- Preview 当前样例抽中的节点名称。

槽位摘要示例：

```text
Random · Folder · 179 nodes
样例：akemi_homura
```

随机配置随 Custom Workspace 保存到浏览器持久化状态。候选列表和扫描结果不持久化；页面刷新后根据配置重新扫描，避免使用过期候选。

## 9. API

建议新增：

```text
GET  /api/node-pools/collections?role=character
POST /api/node-pools/scan
POST /api/node-pools/sample
```

扫描请求包含角色、`NodePoolSpec`、搜索词、游标和分页大小。响应示例：

```json
{
  "scan_id": "scan_123",
  "total": 179,
  "raw_total": 240,
  "items": [
    {
      "ref": "角色/example",
      "name": "akemi_homura",
      "role": "character"
    }
  ],
  "next_cursor": "20",
  "stats": {
    "missing_classify": 31,
    "invalid_classify": 2,
    "classify_mismatch": 28
  },
  "warnings": []
}
```

服务端使用仅限当前进程的短期扫描索引缓存支持分页，默认五分钟失效。Generate 开始时不直接复用分页缓存，必须按当前配置重新解析一次候选池，并把实际候选快照摘要写入任务元数据。

## 10. Preview 语义

Preview 从当前候选池中做一次样例抽取，显示：

- 抽中的节点名称和 ref。
- 解析后的完整节点内容摘要。
- 最终 Prompt 与生图参数预览。

Preview 样例不消耗 Generate 的随机队列。点击 Generate 时，每个实际任务重新抽取，因此 Preview 不承诺下一张图使用同一节点。界面必须明确标记“样例抽取”。

## 11. Generate 与 Compare Matrix

随机节点不把候选数量加入矩阵维度。一个随机槽位无论包含多少候选，都只算一个节点变体。

例如：

```text
2 Artist 槽位 × 3 Character 槽位 × 1 Action 槽位 × NT 2
= 12 个实际生成任务
```

每次 Generate：

1. 校验所有随机候选池非空。
2. 按现有 Compare Matrix 和 NT 展开实际任务。
3. 为每个随机槽位建立独立乱序队列。
4. 每个实际任务从对应队列取出一个节点。
5. 候选耗尽后重新打乱；候选多于一个时避免重置边界连续重复。
6. 把选中节点读取为普通 `NodeDocument`。
7. 继续执行现有 Composer、Policy、Renderer 链路。
8. 每项固定 `n_samples=1`。

每个 NT 轮次使用不同 seed，同轮 Compare 组合继续共享 seed。随机槽位按实际任务独立抽取，因此使用随机节点时，同轮不同组合的节点内容可以不同；结果详情必须清楚显示每张图最终选择的节点。

“无重复”只约束一次 Generate 调用，不跨多次点击保存历史。

## 12. AgentComposer 边界

随机节点必须在 AgentComposer 调用前解析。AgentComposer 只接收最终选中的普通 `NodeDocument`：

- 不接收 `NodePoolSpec`。
- Hash 不加入随机来源、过滤条件或 `scan_id`。
- Hash 继续由实际输入节点和现有参数生成。
- 缓存命中与缺失行为保持不变。

如果随机选中的节点组合没有 AgentComposer 缓存，按现有缓存缺失规则处理，不新增隐式 Agent 调用或降级逻辑。

## 13. 结果记录

每个实际任务至少记录：

- 随机槽位 ID 和角色。
- `NodePoolSpec` 快照。
- 原始候选数和过滤后候选数。
- 最终选中的节点 ref、名称和节点来源。
- 候选队列轮次及任务内抽取序号。

这些信息写入 Generation Result 的业务元数据，并随现有 PNG 附加元数据机制写入实际 PNG，方便从结果详情追溯随机选择。不得只记录在前端内存中。

## 14. 错误处理

- 候选池为空：禁用 Preview 和 Generate，并指出具体槽位。
- Collection 不存在：显示可用 Collection 来源和加载文件。
- Folder/Glob 越过 `legacy.design_root`：拒绝请求。
- 节点角色不匹配：排除并显示扫描警告。
- 分类过滤启用后缺失或无效 `classify.yaml`：排除并计数。
- 节点在扫描后被删除：Generate 开始时重新解析；仍不可读则明确终止对应任务。
- 单个生成任务失败：沿用现有 Job 和错误展示机制，不吞掉随机解析上下文。

## 15. 验收计划

业务验收优先于接口级单元测试。

1. Folder 随机 Character，`NT=3`，候选充足时三张使用不同角色。
2. Collection 随机 Action，验证 `project_requires`、候选预览和实际节点记录。
3. Glob 随机 Artist，验证模式匹配和实际画风节点。
4. Action Folder 启用 `classify.yaml`：筛选 `domain=foot` 和多个 subtype，确认只有匹配节点进入随机池。
5. 同一来源关闭分类过滤，确认缺失 `classify.yaml` 的节点仍可进入候选池。
6. 候选少于 NT，验证耗尽后重置及边界不连续重复。
7. Random + Compare Matrix + `NT=2`，验证任务数量、每轮 seed 和每张图的选中节点记录。
8. 刷新页面，确认随机配置保留、表单和 JSON 一致、候选池重新扫描。
9. NovelAI 真实出图，检查 PNG 参数、最终 Prompt、节点 ref 和随机元数据。
10. 固定节点 AgentComposer 回归，确认调用链、Hash 和缓存行为没有变化。

## 16. 实施约束

- 不创建新的分支，除非用户另行要求。
- 不修改或提交工作区中与本功能无关的现有变更。
- 中文文档和必要的中文代码注释。
- 开发完成后必须执行 Web 业务流程和 NovelAI 真实出图验收。
- 不以大量 smoke test 或纯接口单元测试代替业务结果验证。
