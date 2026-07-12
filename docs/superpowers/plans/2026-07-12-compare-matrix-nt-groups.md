# Compare Matrix NT Groups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Compare Generate 按 `NT` 重复执行完整 Matrix，每组共享一个 seed、不同组使用不同 seed，并按 Group 独立归档和展示结果。

**Architecture:** 保持 `buildCompareMatrix()` 只生成一组节点笛卡尔积；新增纯函数编排模块，将 Matrix、NT 和 Seed 展开为有序的 `CompareRunItem[]`。`CompareRunController` 串行执行运行项并写入 Group 子目录，`CustomGeneratePanel` 按 Group 展示进度和结果。

**Tech Stack:** React 18、TypeScript、Vitest、Testing Library、FastAPI 现有 Job API、NovelAI 现有 Renderer/Adapter 链路。

## Global Constraints

- `总任务数 = Artist × Character × Action × NT`。
- 每个底层生成请求固定 `n_samples=1`。
- 同组所有 Matrix 组合共享 seed，不同组 seed 不同。
- `Seed=-1` 时每组生成独立随机 seed；显式 Seed 时按 `baseSeed + groupIndex - 1`。
- Compare 继续使用单 worker 串行提交，不能增加 NovelAI 并发。
- 普通 Generate 的 `NT -> n_samples` 行为不能改变。
- 一次 Compare Generate 只创建一个父目录，每组使用独立子目录。
- 实现后必须完成真实 NovelAI 出图验收，不能只依赖接口或 mock 测试。

---

### Task 1: Compare Group 纯编排模型

**Files:**
- Create: `web/src/compare/runPlan.ts`
- Create: `web/src/compare/runPlan.test.ts`
- Read: `web/src/compare/matrix.ts`

**Interfaces:**
- Consumes: `CompareCombination` from `web/src/compare/matrix.ts`。
- Produces: `CompareRunItem`、`CompareGroupPlan`、`buildCompareRunPlan()`、`compareRunCount()`。

- [ ] **Step 1: 编写失败测试，覆盖显式 Seed 和运行顺序**

```ts
import { describe, expect, it, vi } from "vitest";

import type { CompareCombination } from "./matrix";
import { buildCompareRunPlan } from "./runPlan";

const matrix = [
  { combinationId: "a", artist: null, character: null, action: null },
  { combinationId: "b", artist: null, character: null, action: null },
] satisfies CompareCombination[];

describe("buildCompareRunPlan", () => {
  it("expands complete matrix groups in group-first order with explicit seeds", () => {
    const plan = buildCompareRunPlan(matrix, { nt: 3, seed: "42", randomSeed: vi.fn() });

    expect(plan.groups.map((group) => group.seed)).toEqual([42, 43, 44]);
    expect(plan.items.map((item) => item.runId)).toEqual([
      "group-001::a", "group-001::b",
      "group-002::a", "group-002::b",
      "group-003::a", "group-003::b",
    ]);
  });
});
```

- [ ] **Step 2: 编写失败测试，覆盖随机 Seed 去重和非法 NT**

```ts
it("creates a distinct random seed for every group", () => {
  const randomSeed = vi.fn()
    .mockReturnValueOnce(100)
    .mockReturnValueOnce(100)
    .mockReturnValueOnce(200);
  const plan = buildCompareRunPlan(matrix, { nt: 3, seed: "-1", randomSeed });

  expect(plan.groups.map((group) => group.seed)).toEqual([100, 101, 200]);
});

it.each([0, -1, 1.5, Number.NaN])("rejects invalid nt %s", (nt) => {
  expect(() => buildCompareRunPlan(matrix, { nt, seed: "-1", randomSeed: () => 1 }))
    .toThrow("Compare NT 必须是大于等于 1 的整数");
});
```

- [ ] **Step 3: 运行测试确认失败**

Run:

```powershell
cd web
npm run test -- --run src/compare/runPlan.test.ts
```

Expected: FAIL，提示 `./runPlan` 不存在。

- [ ] **Step 4: 实现纯编排模块**

```ts
import type { CompareCombination } from "./matrix";

const UINT32_SIZE = 0x1_0000_0000;

export type CompareRunItem = {
  runId: string;
  groupIndex: number;
  groupSeed: number;
  combination: CompareCombination;
};

export type CompareGroupPlan = {
  groupIndex: number;
  seed: number;
  items: CompareRunItem[];
};

export type CompareRunPlan = {
  groups: CompareGroupPlan[];
  items: CompareRunItem[];
};

function normalizeSeed(value: number): number {
  const integer = Number.isFinite(value) ? Math.trunc(value) : 0;
  return ((integer % UINT32_SIZE) + UINT32_SIZE) % UINT32_SIZE;
}

function distinctSeed(candidate: number, used: Set<number>): number {
  let seed = normalizeSeed(candidate);
  while (used.has(seed)) seed = normalizeSeed(seed + 1);
  used.add(seed);
  return seed;
}

export function buildCompareRunPlan(
  matrix: CompareCombination[],
  options: { nt: number; seed: string; randomSeed(): number },
): CompareRunPlan {
  if (!Number.isSafeInteger(options.nt) || options.nt < 1) {
    throw new Error("Compare NT 必须是大于等于 1 的整数");
  }
  const parsedSeed = Number(options.seed);
  const explicit = Number.isInteger(parsedSeed) && parsedSeed >= 0;
  const used = new Set<number>();
  const groups = Array.from({ length: options.nt }, (_, offset) => {
    const groupIndex = offset + 1;
    const seed = distinctSeed(explicit ? parsedSeed + offset : options.randomSeed(), used);
    const prefix = `group-${String(groupIndex).padStart(3, "0")}`;
    const items = matrix.map((combination) => ({
      runId: `${prefix}::${combination.combinationId}`,
      groupIndex,
      groupSeed: seed,
      combination,
    }));
    return { groupIndex, seed, items };
  });
  return { groups, items: groups.flatMap((group) => group.items) };
}

export function compareRunCount(matrixCount: number, nt: number): number {
  return Number.isSafeInteger(nt) && nt >= 1 ? matrixCount * nt : 0;
}
```

- [ ] **Step 5: 运行测试确认通过**

Run:

```powershell
cd web
npm run test -- --run src/compare/runPlan.test.ts
```

Expected: PASS，3 个测试全部通过。

- [ ] **Step 6: 提交纯编排模块**

```powershell
git add web/src/compare/runPlan.ts web/src/compare/runPlan.test.ts
git commit -m "feat: plan compare matrix nt groups"
```

---

### Task 2: Compare Controller 执行 Group 和分组目录

**Files:**
- Modify: `web/src/compare/useCompareRunController.ts`
- Modify: `web/src/compare/useCompareRunController.test.tsx`
- Use: `web/src/compare/runPlan.ts`

**Interfaces:**
- Consumes: `buildCompareRunPlan(matrix, { nt, seed, randomSeed })`。
- Produces: 带 `runId/groupIndex/groupSeed` 的 `CompareCombinationResult[]`、`groupSummaries`、Group 输出目录。

- [ ] **Step 1: 将现有串行测试改为两组 Matrix 的失败测试**

把测试参数改为 `nt: 2`，Matrix 保持 `2 Artist × 1 Character × 2 Action = 4`，断言：

```ts
expect(result.current.summary.total).toBe(8);
expect(result.current.summary.succeeded).toBe(8);
expect(generated).toHaveLength(8);
expect([...seeds]).toEqual([123456789, 123456790]);
expect([...outputDirs]).toEqual([
  "outputs/compare_test/group_001_seed_123456789",
  "outputs/compare_test/group_002_seed_123456790",
]);
expect(result.current.results.map((item) => item.runId)).toEqual([
  "group-001::primary-artist::primary-character::primary-action",
  "group-001::primary-artist::primary-character::action-0",
  "group-001::artist-0::primary-character::primary-action",
  "group-001::artist-0::primary-character::action-0",
  "group-002::primary-artist::primary-character::primary-action",
  "group-002::primary-artist::primary-character::action-0",
  "group-002::artist-0::primary-character::primary-action",
  "group-002::artist-0::primary-character::action-0",
]);
```

- [ ] **Step 2: 增加显式 Seed、组目录和组汇总测试**

```ts
expect(result.current.groupSummaries).toEqual([
  expect.objectContaining({ groupIndex: 1, seed: 42, total: 2, succeeded: 2 }),
  expect.objectContaining({ groupIndex: 2, seed: 43, total: 2, succeeded: 2 }),
]);
expect(generateDirs).toEqual([
  "outputs/compare_run/group_001_seed_42",
  "outputs/compare_run/group_001_seed_42",
  "outputs/compare_run/group_002_seed_43",
  "outputs/compare_run/group_002_seed_43",
]);
```

- [ ] **Step 3: 运行 Controller 测试确认失败**

Run:

```powershell
cd web
npm run test -- --run src/compare/useCompareRunController.test.tsx
```

Expected: FAIL，当前 Controller 只执行一组且结果没有 Group 字段。

- [ ] **Step 4: 更新结果类型和目录函数**

在 `useCompareRunController.ts` 中：

```ts
import { buildCompareRunPlan, type CompareRunItem } from "./runPlan";

export type CompareCombinationResult = {
  runId: string;
  groupIndex: number;
  groupSeed: number;
  combination: CompareCombination;
  labels: Record<NodeRole, string>;
  status: CompareCombinationStatus;
  job: JobRecord | null;
  error: string;
};

export function createCompareOutputDir(): string {
  const timestamp = new Date().toISOString().replace(/\D/g, "").slice(0, 14);
  const suffix = globalThis.crypto?.randomUUID
    ? globalThis.crypto.randomUUID().slice(0, 8)
    : Math.random().toString(16).slice(2, 10).padEnd(8, "0");
  return `outputs/compare_${timestamp}_${suffix}`;
}

export function createCompareGroupOutputDir(parent: string, groupIndex: number, seed: number): string {
  return `${parent}/group_${String(groupIndex).padStart(3, "0")}_seed_${seed}`;
}
```

`initialResult()` 改为接收 `CompareRunItem`，并复制 `runId/groupIndex/groupSeed`。

- [ ] **Step 5: 按 Run Plan 串行执行**

在 `start()` 中替换单 Matrix 执行：

```ts
const matrix = buildCompareMatrix(groups);
const plan = buildCompareRunPlan(matrix, {
  nt: params.nt,
  seed: params.seed,
  randomSeed,
});
const outputDir = outputDirFactory();
setResults(plan.items.map(initialResult));

async function runItem(item: CompareRunItem) {
  updateResult(token, item.runId, { status: "running", error: "" });
  try {
    const runParams = { ...params, seed: String(item.groupSeed) };
    const request = buildComposeRenderRequest(item.combination, runParams, { compare: true });
    const preview = await post("/compose-preview", request) as ComposePreviewResponse;
    if (!preview.render_request) throw new Error("该组合需要外部 Agent 先完成提示词拼接。");
    const queued = await post("/generate", {
      render_request: preview.render_request,
      output_dir: createCompareGroupOutputDir(outputDir, item.groupIndex, item.groupSeed),
    }) as JobRecord;
    updateResult(token, item.runId, { job: queued });
    const completed = await pollJob(token, queued);
    if (completed.status !== "succeeded") {
      throw new Error(completed.error || `Job ${completed.status}`);
    }
    updateResult(token, item.runId, { status: "succeeded", job: completed });
  } catch (runError) {
    if (runToken.current !== token) return;
    updateResult(token, item.runId, { status: "failed", error: errorMessage(runError) });
  }
}
```

`updateResult()` 的匹配键从 `combination.combinationId` 改为 `runId`；worker 遍历 `plan.items`。

- [ ] **Step 6: 增加 Group 汇总**

```ts
function summarizeGroups(results: CompareCombinationResult[]) {
  const indexes = [...new Set(results.map((item) => item.groupIndex))];
  return indexes.map((groupIndex) => {
    const items = results.filter((item) => item.groupIndex === groupIndex);
    return {
      groupIndex,
      seed: items[0].groupSeed,
      ...summarize(items),
    };
  });
}
```

Hook 返回值增加 `groupSummaries`。

- [ ] **Step 7: 运行 Controller 测试确认通过**

Run:

```powershell
cd web
npm run test -- --run src/compare/useCompareRunController.test.tsx
```

Expected: PASS；确认 8 个任务串行执行、两组 seed 不同、目录按组划分。

- [ ] **Step 8: 提交 Controller 改动**

```powershell
git add web/src/compare/useCompareRunController.ts web/src/compare/useCompareRunController.test.tsx
git commit -m "feat: execute compare matrix in nt groups"
```

---

### Task 3: Compare UI 显示总量和分组结果

**Files:**
- Modify: `web/src/components/CustomGeneratePanel.tsx`
- Modify: `web/src/pages/CustomStudio.test.tsx`
- Modify: `web/src/styles.css`

**Interfaces:**
- Consumes: `compare.groupSummaries` 和带 `groupIndex/groupSeed/runId` 的结果。
- Produces: `Matrix × Groups` 总量、分组标题、组内结果卡和正确的图片切换顺序。

- [ ] **Step 1: 修改页面测试，要求 NT=2 时显示 8 个任务**

```ts
fireEvent.click(screen.getByText("configure matrix"));
fireEvent.change(screen.getByLabelText("NT"), { target: { value: "2" } });
const compareButton = await screen.findByRole("button", { name: "Compare Generate · 8" });
fireEvent.click(compareButton);

await waitFor(() => expect(generateCalls()).toHaveLength(8));
expect(screen.getByText("Artist 2 × Character 1 × Action 2 × Groups 2 = 8")).toBeTruthy();
expect(screen.getByText("Group 1 · Seed 123456")).toBeTruthy();
expect(screen.getByText("Group 2 · Seed 123457")).toBeTruthy();
```

Mock 的 compose-preview 需要把请求 seed 写入返回的 `render_request`，generate Mock 再把该 seed 写入图片 meta，确保 UI 测试验证的是真实请求数据流。

- [ ] **Step 2: 运行页面测试确认失败**

Run:

```powershell
cd web
npm run test -- --run src/pages/CustomStudio.test.tsx
```

Expected: FAIL，按钮仍显示 4，且没有 Group 标题。

- [ ] **Step 3: 更新 Compare 数量和按钮**

在 `CustomGeneratePanel.tsx` 中：

```ts
const matrixTotal = dimensions.artist * dimensions.character * dimensions.action;
const compareTotal = matrixTotal * (Number.isSafeInteger(params.nt) && params.nt >= 1 ? params.nt : 0);
```

摘要改为：

```tsx
<small>
  Artist {dimensions.artist} × Character {dimensions.character} × Action {dimensions.action}
  {" × "}Groups {params.nt} = {compareTotal}
</small>
```

- [ ] **Step 4: 按 Group 渲染结果**

```tsx
<div className="compare-groups">
  {compare.groupSummaries.map((group) => (
    <section className="compare-group" key={group.groupIndex}>
      <div className="compare-group-title">
        <strong>Group {group.groupIndex} · Seed {group.seed}</strong>
        <span>成功 {group.succeeded} / {group.total}{group.failed ? ` · 失败 ${group.failed}` : ""}</span>
      </div>
      <div className="compare-result-grid">
        {compare.results.filter((item) => item.groupIndex === group.groupIndex).map(renderCompareResult)}
      </div>
    </section>
  ))}
</div>
```

卡片 React key 使用 `result.runId`。`compareImagePaths` 继续从 `compare.results` 顺序展开，保证图片详情先组内、后组间。

- [ ] **Step 5: 添加克制的分组样式**

```css
.compare-groups {
  display: grid;
  gap: 18px;
}

.compare-group {
  border-top: 1px solid var(--border);
  padding-top: 12px;
}

.compare-group-title {
  align-items: center;
  display: flex;
  justify-content: space-between;
  margin-bottom: 10px;
}
```

不新增嵌套卡片；Group 只使用分隔线和标题，结果卡继续使用现有样式。

- [ ] **Step 6: 运行页面和完整前端测试**

Run:

```powershell
cd web
npm run test -- --run src/pages/CustomStudio.test.tsx
npm run test
npm run build
```

Expected: CustomStudio 测试通过；完整前端测试全部通过；Vite build 成功。

- [ ] **Step 7: 提交 UI 改动**

```powershell
git add web/src/components/CustomGeneratePanel.tsx web/src/pages/CustomStudio.test.tsx web/src/styles.css
git commit -m "feat: show grouped compare matrix runs"
```

---

### Task 4: 更新 Web 使用文档

**Files:**
- Modify: `docs/web_control_console_readme.md`
- Reference: `docs/superpowers/specs/2026-07-12-compare-matrix-nt-groups-design.md`

**Interfaces:**
- Consumes: 最终 UI 文案、seed 规则和目录结构。
- Produces: 用户可直接理解的 Compare NT 使用说明。

- [ ] **Step 1: 更新 Compare Generate 章节**

写明：

```markdown
Compare 中 `NT` 表示完整 Matrix 的执行组数，不是单次请求的图片数。

总图片数 = Artist × Character × Action × NT

每组内部共享 seed，不同组使用不同 seed；每个 NovelAI 请求仍固定 `n_samples=1`。
`Seed=-1` 时每组随机；指定 Seed 时各组依次使用 `Seed + 0`、`Seed + 1`……。
```

- [ ] **Step 2: 补充分组目录示例**

```text
outputs/compare_<timestamp>_<id>/
  group_001_seed_123456/
  group_002_seed_123457/
```

- [ ] **Step 3: 检查文档和提交**

Run:

```powershell
git diff --check -- docs/web_control_console_readme.md
```

Expected: exit code 0。

```powershell
git add docs/web_control_console_readme.md
git commit -m "docs: explain compare nt groups"
```

---

### Task 5: 真实 NovelAI Compare NT 业务验收

**Files:**
- No source changes required unless acceptance reveals a defect.
- Inspect: `outputs/compare_<timestamp>_<id>/group_*/`

**Interfaces:**
- Consumes: 完整 Web、Composer、NovelAI Renderer/Adapter、Job 和结果归档链路。
- Produces: 真实 PNG、PNG seed 元数据和分组目录验收结论。

- [ ] **Step 1: 启动最新 Web 服务**

Run:

```powershell
uv run python scripts/dev_web.py --backend-port 23455 --frontend-port 53173 --no-install
```

Expected: 后端和前端启动成功，终端显示实际访问地址。

- [ ] **Step 2: 配置真实 Compare Matrix**

在 Custom 页选择：

```text
Artist:
  109841329_03_manga_monochrome_yabuki_rance_no_vibe_latest_stable

Character:
  主节点 danbooru_akemi_homura_晓
  Compare 节点 akuma_homura

Action:
  主节点 20260502_夜外强奸_5star
  Compare 节点 20260504_传教士强制按压强奸

NT: 2
Seed: -1
```

Expected: UI 显示 `Artist 1 × Character 2 × Action 2 × Groups 2 = 8`，按钮显示 `Compare Generate · 8`。

- [ ] **Step 3: 执行一次 Compare Generate**

点击一次 `Compare Generate · 8`，等待全部任务结束。

Expected:

- 总计 8 个 Job。
- Group 1 和 Group 2 各 4 个结果。
- 同组四个结果显示同一 seed。
- 两组 seed 不同。
- 失败任务不会阻止后续任务执行。

- [ ] **Step 4: 检查实际输出目录和 PNG 元数据**

Run:

```powershell
Get-ChildItem outputs -Directory -Filter 'compare_*' |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1 -ExpandProperty FullName
```

在最新父目录中确认存在：

```text
group_001_seed_<seed1>
group_002_seed_<seed2>
```

使用 `inspect-image-params` 读取最新 Compare 父目录中的全部 PNG：

```powershell
$latest = Get-ChildItem outputs -Directory -Filter 'compare_*' |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1
Get-ChildItem -LiteralPath $latest.FullName -Recurse -Filter '*.png' |
  ForEach-Object {
    uv run python -m tags_machine_core inspect-image-params $_.FullName --normalized
  }
```

Expected:

- Group 1 四张 PNG 的实际 seed 都等于 `<seed1>`。
- Group 2 四张 PNG 的实际 seed 都等于 `<seed2>`。
- `<seed1> != <seed2>`。
- PNG 数量总计为 8。

- [ ] **Step 5: 检查图片详情顺序**

从 Group 1 第一张图片打开详情，连续点击右箭头。

Expected: 先浏览 Group 1 的四张，再浏览 Group 2 的四张；Diff 使用实际 PNG 参数。

- [ ] **Step 6: 最终验证**

Run:

```powershell
uv run python -m unittest tests.test_web_app tests.test_web_jobs tests.test_web_nodes tests.test_web_node_save tests.test_web_compose tests.test_web_results -v
cd web
npm run test
npm run build
cd ..
git diff --check
```

Expected:

- 后端测试全部通过。
- 前端测试全部通过。
- 前端生产构建成功。
- `git diff --check` exit code 0，仅允许已有 CRLF 提示。

- [ ] **Step 7: 提交验收中产生的必要修复**

如果真实验收未发现缺陷，不创建空提交。若发现并修复缺陷，重新运行对应 Task 的测试，并只暂存 Compare NT 涉及的文件：

```powershell
git add web/src/compare/runPlan.ts web/src/compare/runPlan.test.ts web/src/compare/useCompareRunController.ts web/src/compare/useCompareRunController.test.tsx web/src/components/CustomGeneratePanel.tsx web/src/pages/CustomStudio.test.tsx web/src/styles.css
git commit -m "fix: stabilize compare nt group generation"
```
