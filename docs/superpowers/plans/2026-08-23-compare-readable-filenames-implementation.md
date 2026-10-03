# Compare 可读文件名 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 当前直接在本会话执行，不使用子 agent。

**Goal:** 让 Web Compare 同一生成组内的图片按矩阵顺序使用可读文件名，并同步保持 GenerationResult、PNG 信息和前端路径一致。

**Architecture:** Compare 控制器在每次 `/generate` 请求中携带组内序号、组信息、节点标签和 Prompt Behavior 标签。Web 后端把这部分数据放入 `RenderRequest.meta.output_naming`；core 的统一图片归档函数读取该元信息生成文件名，格式为“序号 + 节点标签 + 原有 hash/seed/index”。未携带该元信息的普通 Generate、Batch 和其他后端继续使用原命名。

**Tech Stack:** React 18, TypeScript, FastAPI, Pydantic, Python pathlib, Vitest, unittest。

## Global Constraints

- 只修改 `refactor`，不修改旧 `tags_machine`。
- 不改变 NovelAI 原始请求参数、生成顺序、seed、目录结构或重试逻辑。
- Compare 序号以 Compare Matrix 的展开顺序为准，每个 group 从 `001` 开始。
- 保留原有 hash、seed 和单图 index，避免文件重名并保留追溯信息。
- 普通 Generate、Batch、随机主模式和不携带命名元信息的调用保持旧文件名。
- 所有路径字段同步更新，不能只改磁盘文件名。

---

### Task 1: Compare 控制器携带组内顺序和标签

**Files:**
- Modify: `web/src/compare/runPlan.ts`
- Modify: `web/src/compare/useCompareRunController.ts`
- Test: `web/src/compare/runPlan.test.ts`
- Test: `web/src/compare/useCompareRunController.test.tsx`

**Interfaces:**
- `CompareRunItem` 增加 `matrixIndex: number` 和 `matrixCount: number`。
- `/generate` 请求增加：

```ts
output_naming: {
  mode: "compare";
  sequence: number;
  total: number;
  group_index: number;
  group_seed: number;
  labels: { artist: string; character: string; action: string };
  behavior: string;
}
```

- [ ] **Step 1: 添加计划序号测试**

断言 `buildCompareRunPlan` 对每个 group 产生 `matrixIndex` 从 1 到 `matrix.length`，`matrixCount` 等于矩阵总数，且每个 group 重新从 1 开始。

- [ ] **Step 2: 实现 runPlan 序号**

将矩阵映射改为：

```ts
const items = matrix.map((combination, index) => ({
  runId: `${prefix}::${combination.combinationId}`,
  groupIndex,
  groupSeed: seed,
  matrixIndex: index + 1,
  matrixCount: matrix.length,
  combination,
}));
```

- [ ] **Step 3: 在 Compare 控制器提交命名信息**

增加安全的显示标签函数，复用当前 `slotLabel`，并在 `runItem` 的 `/generate` body 中加入：

```ts
output_naming: {
  mode: "compare",
  sequence: item.matrixIndex,
  total: item.matrixCount,
  group_index: item.groupIndex,
  group_seed: item.groupSeed,
  labels: {
    artist: slotLabel(item.combination.artist),
    character: slotLabel(item.combination.character),
    action: slotLabel(item.combination.action),
  },
  behavior: item.combination.promptBehavior.label,
},
```

- [ ] **Step 4: 运行 Web Compare 测试**

Run: `npm --prefix web test -- --run src/compare/runPlan.test.ts src/compare/useCompareRunController.test.tsx`

Expected: PASS，并验证每组请求的 `output_naming.sequence` 为 `1..matrixCount`。

### Task 2: Web API 传递命名元信息

**Files:**
- Modify: `src/tags_machine_core/web/routes/generate.py`
- Test: `tests/test_web_compose.py`

**Interfaces:**
- 新增 `_attach_output_naming(payload)`，校验 `output_naming` 是对象，`mode` 为 `compare`，`sequence` 为正整数，`labels` 为对象。
- 校验后写入 `render_request.meta.output_naming`，原 payload 其他字段不改变。

- [ ] **Step 1: 添加接口测试**

向 `/api/generate` 发送 `output_naming`，注入 executor，断言：

```python
self.assertEqual(captured["request"].meta["output_naming"]["sequence"], 3)
self.assertEqual(captured["request"].meta["output_naming"]["labels"]["action"], "foot_detail")
```

同时测试非法 `sequence: 0` 返回 400。

- [ ] **Step 2: 实现元信息注入**

在 `generate()` 中按顺序调用随机选择和命名信息注入；命名信息写入 render request 的 meta，不改变 `random_selections` 顶层回传。

- [ ] **Step 3: 运行后端接口测试**

Run: `uv run pytest tests/test_web_compose.py -q`

Expected: PASS。

### Task 3: core 归档阶段生成可读文件名

**Files:**
- Modify: `src/tags_machine_core/execution.py`
- Test: `tests/test_execution.py`

**Interfaces:**
- `save_generated_images()` 从 `request.meta.output_naming` 读取 Compare 命名信息。
- 未携带命名信息时继续生成当前格式：`<hash>_<seed>_<index>.<ext>`。
- Compare 文件名格式：

```text
<sequence:03d>_<role-labels>_<behavior>_<hash>_<seed>_<index:02d>.<ext>
```

例如：

```text
001_artist-109841329_character-homura_action-foot-detail_behavior-default_8205183a_533701294_01.png
```

实际实现去掉示例中的空格，并对标签做文件名安全化、长度截断和空值处理。

- [ ] **Step 1: 添加归档测试**

覆盖：

1. Compare 元信息生成 `001_...png`。
2. 标签包含 `/`, `\\`, `:`, `*`, `?` 时不会生成子目录或非法 Windows 文件名。
3. 两张同组图片序号不同，路径不同。
4. `GenerationResult.images[].filename/path` 使用新文件名。
5. 没有 `output_naming` 时旧命名测试仍通过。

- [ ] **Step 2: 实现命名函数**

新增内部函数：

```python
def _read_output_naming(request: RenderRequest) -> dict[str, Any] | None: ...
def _safe_output_component(value: Any, *, fallback: str, max_length: int = 48) -> str: ...
def _archive_filename(image: Any, request: RenderRequest, *, batch_id: str, index: int, suffix: str) -> str: ...
```

`_archive_filename` 在 Compare 模式下构造可读前缀，再拼接原 `batch_id/seed/index`；其他模式返回旧格式。

- [ ] **Step 3: 确保 PNG 信息同步**

`collect_png_info()` 继续从 `GeneratedImage` 读取 path/filename，因此只要归档后再调用它，PNG 信息路径自然一致。`build_core_png_text()` 增加受控的 `output_naming` 摘要，便于通过图片元数据追溯 Compare 顺序。

- [ ] **Step 4: 运行执行层测试**

Run: `uv run pytest tests/test_execution.py -q`

Expected: PASS。

### Task 4: 全链路验证

**Files:**
- Modify: `web/src/compare/useCompareRunController.test.tsx`
- Modify: `tests/test_web_compose.py`

- [ ] **Step 1: 运行 Web 完整测试**

Run: `npm --prefix web test -- --run`

Expected: 全部通过。

- [ ] **Step 2: 运行后端相关测试**

Run: `uv run pytest tests/test_web_compose.py tests/test_execution.py -q`

Expected: 全部通过。

- [ ] **Step 3: 运行构建**

Run: `npm --prefix web run build`

Expected: TypeScript 和 Vite 构建成功。

- [ ] **Step 4: 业务验证结果**

使用当前 Web Compare 配置生成至少一组真实或已有结果，确认目录形如：

```text
outputs/compare_20260823030836_032d1e14/
  group_001_seed_533701294/
    001_*.png
    002_*.png
```

并确认 `generation_result.json`、PNG 参数详情和前端图片路径都指向编号后的文件。
