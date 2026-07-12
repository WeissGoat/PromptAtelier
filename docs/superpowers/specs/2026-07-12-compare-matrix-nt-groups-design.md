# Compare Matrix NT 分组执行设计

## 目标

让 Custom 页的 `NT` 同时适用于 Compare Generate。

Compare 中的 `NT` 不表示单次 NovelAI 请求的 `n_samples`，而表示完整 Compare Matrix 的执行组数：

```text
总任务数 = Artist 数量 × Character 数量 × Action 数量 × NT
```

每组完整执行一次 Matrix。组内所有组合共享同一个 seed，不同组使用不同 seed。每个底层生成请求继续固定为 `n_samples=1`。

## 非目标

- 不把 Compare 改成后端单 Job 批量执行。
- 不使用 `n_samples=NT`。
- 不改变普通 Generate 的现有 `NT` 语义。
- 不增加 NovelAI 并发；Compare 仍按单 worker 串行提交。
- 不修改 Matrix 的 Artist、Character、Action 笛卡尔积规则。

## 核心概念

### Matrix

由所有已选择的 Artist、Character、Action 节点展开的笛卡尔积。某类节点完全为空时，该维度按一个 `null` 因子计算。

### Group

一次完整 Matrix 执行称为一组。`NT` 是 Group 数量。

例如：

```text
Artist 2 × Character 2 × Action 3 = 每组 12 个任务
NT = 4
总任务数 = 12 × 4 = 48
```

### Group Seed

同一 Group 内所有组合共享一个 seed，从而确保不同节点组合之间可公平横向比较。不同 Group 必须使用不同 seed，用于观察不同随机样本下的稳定性。

Seed 规则：

- 界面 `Seed=-1`：为每组独立生成一个随机 seed，并确保本轮 Compare 内不重复。
- 界面指定非负整数 Seed：第一组使用该 Seed，后续组依次使用 `baseSeed + groupIndex - 1`。
- seed 超出渲染层允许范围时，按现有 seed 范围规则归一化；归一化后仍需保证本轮各组不同。

## 前端架构

### Compare Matrix

`buildCompareMatrix()` 继续只负责节点笛卡尔积，不感知 NT，也不复制组合。

这样 Matrix 的职责保持单一：回答“这一组有哪些节点组合”。

### CompareRunController

`CompareRunController.start(groups, params)` 负责：

1. 构建一次基础 Matrix。
2. 根据 `params.nt` 生成 Group 列表和 Group Seed。
3. 按 `Group -> Matrix Combination` 顺序展开运行项。
4. 为整次 Compare 创建父输出目录。
5. 为每组创建独立子目录。
6. 继续使用单 worker 串行执行所有任务。

展开顺序固定为：

```text
Group 1: Matrix combination 1..N
Group 2: Matrix combination 1..N
...
Group NT: Matrix combination 1..N
```

这保证结果顺序、图片左右切换顺序和磁盘归档顺序一致。

### 请求构造

每个运行项调用现有 `buildComposeRenderRequest()`，但传入当前 Group Seed。

Compare 请求继续强制：

```json
{
  "params": {
    "n_samples": 1
  }
}
```

因此 `NT` 只在 Controller 编排层展开，不下沉为 NovelAI 多样本参数。

## 数据结构

`CompareCombinationResult` 增加 Group 信息：

```ts
type CompareCombinationResult = {
  runId: string;
  groupIndex: number;
  groupSeed: number;
  combination: CompareCombination;
  labels: Record<NodeRole, string>;
  status: "queued" | "running" | "succeeded" | "failed";
  job: JobRecord | null;
  error: string;
};
```

`runId` 必须在整次 Compare 中唯一，不能继续只使用 Matrix 的 `combinationId`，因为同一组合会在不同 Group 中重复出现。固定格式：

```text
group-001::<combinationId>
```

Controller 汇总信息继续统计运行项总数，同时增加按组汇总所需的数据：

```ts
type CompareGroupSummary = {
  groupIndex: number;
  seed: number;
  total: number;
  queued: number;
  running: number;
  succeeded: number;
  failed: number;
};
```

## 输出目录

一次 Compare Generate 创建一个父目录：

```text
outputs/compare_<timestamp>_<id>/
```

每组使用独立子目录：

```text
outputs/compare_<timestamp>_<id>/
  group_001_seed_123456/
  group_002_seed_123457/
  group_003_seed_123458/
```

所有组合的 `GenerationResult` 和 PNG 继续由现有生成链路归档。Controller 只负责把对应 Group 子目录作为 `output_dir` 传给 `/generate`。

目录名中的 seed 使用最终实际发送的 seed。

## 界面

Compare Matrix 摘要显示：

```text
Artist 2 × Character 2 × Action 3 × Groups 4 = 48
```

按钮显示：

```text
Compare Generate · 48
```

结果区按 Group 分区：

```text
Group 1 · Seed 123456 · 成功 12 / 12
  Matrix 结果卡片...

Group 2 · Seed 123457 · 成功 11 / 12 · 失败 1
  Matrix 结果卡片...
```

全局进度仍显示全部运行项的排队、运行、成功和失败数量。

图片详情左右切换顺序使用 Controller 的运行项顺序：先遍历当前 Group 的 Matrix，再进入下一 Group。

## 失败与取消

- 单个组合失败：记录在所属 Group 中，继续执行该组剩余组合和后续 Group。
- compose-preview 失败：只标记当前运行项失败。
- generate 或轮询失败：只标记当前运行项失败。
- 用户清空 Compare 结果：沿用当前 `reset()` 取消 token，停止后续任务并清空前端运行结果。
- 某组部分失败时，该组目录保留已经成功的图片和生成结果。
- `NT` 非整数、小于 1 或超出界面允许范围时，在启动 Compare 前阻止执行并显示明确错误。

## 兼容性

- `NT=1` 时行为与当前 Compare 基本一致，只是输出目录增加 `group_001_seed_<seed>` 子目录。
- 普通 Generate 继续把 `NT` 映射为单次请求的 `n_samples`，不受本设计影响。
- Compare 仍通过现有 Composer、Renderer、Adapter 和 `/generate` 链路，不新增兼容分支。
- 已有节点临时编辑、Compare 节点矩阵和图片元数据功能不改变。

## 验收标准

### 编排验收

配置 `Artist 2 × Character 1 × Action 2，NT=3`：

- UI 总数显示 `12`。
- Controller 产生 12 个运行项。
- 每组包含相同顺序的 4 个 Matrix 组合。
- 三组 seed 两两不同。
- 每组内部四个请求 seed 完全一致。
- 每个请求的 `n_samples` 都是 `1`。

### 指定 Seed

配置 `Seed=42，NT=3`：

```text
Group 1 seed = 42
Group 2 seed = 43
Group 3 seed = 44
```

### 随机 Seed

配置 `Seed=-1，NT=3`：

- 生成三个不同的有效 seed。
- 每组 Matrix 共享对应 Group Seed。

### 输出归档

- 一次点击只产生一个 Compare 父目录。
- 父目录下产生三个 Group 子目录。
- 每张图片进入所属 Group 子目录。
- 图片详情顺序先组内、后组间。

### 真实业务验收

使用一个 Artist、两个 Character、两个 Action，设置 `NT=2`，真实调用 NovelAI：

- 共生成 8 张图片。
- 第一组 4 张 PNG 的 seed 相同。
- 第二组 4 张 PNG 的 seed 相同。
- 两组 seed 不同。
- PNG 元数据中的 seed 与界面 Group Seed 一致。
- 两个 Group 分别归档到独立目录。
