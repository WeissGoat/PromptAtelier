# Prompt Compare Studio (提示词对比工坊) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建 PromptAtelier Web 端的独立顶级模块 `CompareStudio`，支持导入图片参数建立基础模板、横向复制变体编辑提示词、实时 Tag Diff 计算、往下新增多轮批次对比（Downward New Round）、调用 NovelAI 进行真实生图及双图深度视觉对比（Split Slider 卷帘与 Flicker 切帧）。

**Architecture:** 前后端解耦设计。后端在 FastAPI 中提供 `POST /api/image-meta/inspect` 接口，复用现有 PNG chunk 解析能力提取元数据；前端采用 `CompareWorkspaceProvider` 状态机管理 `BaseTemplate`、多轮 `CompareRound` 及 `PromptVariant`；纯前端正则/词条比对引擎实时生成 Tag Diff；执行层通过 `useCompareBatchRunner` 对接现有的 `/api/generate` 与 `JobManager`；展示层提供卡片流布局与全屏双图 `DeepCompareModal`。

**Tech Stack:** Python 3.11+, FastAPI, React 18, TypeScript, Lucide React, Vitest, Pytest.

**Spec:** [docs/superpowers/specs/2026-09-07-prompt-compare-studio-design.md](file:///f:/my_project/new/tags_machine/refactor/docs/superpowers/specs/2026-09-07-prompt-compare-studio-design.md)

## Global Constraints

- **Architecture Paradigms**: Strict Decoupling (Headless Backend + Data-Driven MVC), Event-Driven, Visual Queue.
- **Pure Logic**: Pure C# / Pure Python / Pure TypeScript for core algorithms; no UI-entangled logic.
- **TDD Requirement**: Write failing tests before minimal implementation for every task.
- **Control Variables**: By default, all variants in a round inherit BaseTemplate's seed, steps, scale, width, height, and negative prompt unless explicitly overridden.

---

### Task 1: Backend Image Metadata Inspect Endpoint (`POST /api/image-meta/inspect`)

**Files:**
- Create: `src/tags_machine_core/web/routes/image_meta.py`
- Modify: `src/tags_machine_core/web/app.py`
- Test: `tests/test_web_image_meta.py`

**Interfaces:**
- Produces:
  - `POST /api/image-meta/inspect`: accepts multipart `file: UploadFile` or JSON `{"path": str}`.
  - Returns:
    ```json
    {
      "filename": str,
      "dimensions": {"width": int, "height": int},
      "prompt": str,
      "negative_prompt": str,
      "seed": int | null,
      "steps": int | null,
      "scale": float | null,
      "sampler": str | null,
      "model": str | null,
      "raw_parameters": dict
    }
    ```

- [ ] **Step 1: Write failing tests for image metadata endpoint**
Create `tests/test_web_image_meta.py` with test cases:
1. `test_inspect_image_meta_with_server_path`: inspect an existing PNG with Comment metadata.
2. `test_inspect_image_meta_with_upload_file`: upload bytes of a PNG with Comment metadata.
3. `test_inspect_image_meta_fallback_non_metadata`: upload an empty or non-metadata image, expecting dimensions and empty strings, no 500 crash.

- [ ] **Step 2: Run test to verify it fails**
Run: `uv run pytest tests/test_web_image_meta.py -v`
Expected: FAIL with 404 or import error (route does not exist yet).

- [ ] **Step 3: Implement minimal route and register in FastAPI app**
Implement `src/tags_machine_core/web/routes/image_meta.py` using `read_image_parameters` and `read_png_dimensions`. Include FastAPI `APIRouter` with support for both `UploadFile` and JSON body. Register in `create_app` in `src/tags_machine_core/web/app.py`.

- [ ] **Step 4: Run test to verify it passes**
Run: `uv run pytest tests/test_web_image_meta.py -v`
Expected: PASS all 3 test cases.

- [ ] **Step 5: Commit**
```bash
git add src/tags_machine_core/web/routes/image_meta.py src/tags_machine_core/web/app.py tests/test_web_image_meta.py
git commit -m "feat(api): add image metadata inspect endpoint"
```

---

### Task 2: Frontend Tag Diff Engine & Core Types

**Files:**
- Create: `web/src/compare/types.ts`
- Create: `web/src/compare/tagDiff.ts`
- Test: `web/src/compare/tagDiff.test.ts`

**Interfaces:**
- Produces:
  - `types.ts`: `BaseTemplate`, `PromptVariant`, `CompareRound`, `CompareWorkspaceState`, `TagDiffResult`, `TagDiffToken`.
  - `tagDiff.ts`:
    - `tokenizePrompt(prompt: string): string[]`: splits by commas/newlines, trims, normalizes.
    - `computeTagDiff(basePrompt: string, variantPrompt: string): TagDiffResult`: returns `{ added: string[], removed: string[], tokens: TagDiffToken[] }`.

- [ ] **Step 1: Write failing tests for tag diff engine**
Create `web/src/compare/tagDiff.test.ts` testing:
1. Tokenize prompt handles commas, full-width commas, extra whitespace, newlines.
2. `computeTagDiff` correctly identifies added tags (e.g. adding `film grain, 1980s`).
3. `computeTagDiff` correctly identifies removed tags (e.g. removing `smile`).
4. `computeTagDiff` preserves weighted tags like `(masterpiece:1.2)`, `{detailed eyes}`.

- [ ] **Step 2: Run test to verify it fails**
Run: `npm --prefix web test web/src/compare/tagDiff.test.ts`
Expected: FAIL (files do not exist).

- [ ] **Step 3: Implement types and tag diff function**
Create `web/src/compare/types.ts` with all shared contracts.
Create `web/src/compare/tagDiff.ts` implementing `tokenizePrompt` and `computeTagDiff`.

- [ ] **Step 4: Run test to verify it passes**
Run: `npm --prefix web test web/src/compare/tagDiff.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add web/src/compare/types.ts web/src/compare/tagDiff.ts web/src/compare/tagDiff.test.ts
git commit -m "feat(compare): add tag diff engine and core types"
```

---

### Task 3: Compare Workspace State Management (`useCompareWorkspace`)

**Files:**
- Create: `web/src/compare/useCompareWorkspace.ts`
- Create: `web/src/compare/CompareWorkspaceProvider.tsx`
- Test: `web/src/compare/useCompareWorkspace.test.tsx`

**Interfaces:**
- Consumes: `BaseTemplate`, `PromptVariant`, `CompareRound`, `computeTagDiff` from Task 2.
- Produces:
  - React hook `useCompareWorkspace` providing:
    - `state`: `{ template, rounds, deepCompare }`
    - `setBaseTemplate(template: BaseTemplate)`
    - `addVariant(roundId: string, name?: string, prompt?: string)`
    - `duplicateVariant(roundId: string, variantId: string)`
    - `updateVariant(roundId: string, variantId: string, patch: Partial<PromptVariant>)`
    - `removeVariant(roundId: string, variantId: string)`
    - `resetVariantToTemplate(roundId: string, variantId: string)`
    - `addNewRound(basePrompt?: string, name?: string)`: 往下新增新的一批对比
    - `forkVariantToNewRound(roundId: string, variantId: string)`: 以此变体为新起点往下派生
    - `openDeepCompare(leftVariantId: string, rightVariantId: string, mode?: "split" | "flicker")`
    - `closeDeepCompare()`

- [ ] **Step 1: Write failing tests for workspace hook**
Create `web/src/compare/useCompareWorkspace.test.tsx` testing:
1. Setting base template automatically creates Round 1 with Variant 1 matching template prompt.
2. Adding and duplicating variant in a round updates diff automatically.
3. `addNewRound` appends a new round below the existing rounds.
4. `forkVariantToNewRound` appends a new round below with `basePrompt` initialized to the selected variant's prompt.
5. Deep compare open/close state transitions.

- [ ] **Step 2: Run test to verify it fails**
Run: `npm --prefix web test web/src/compare/useCompareWorkspace.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement useCompareWorkspace and CompareWorkspaceProvider**
Write `useCompareWorkspace.ts` and `CompareWorkspaceProvider.tsx` implementing all required actions, state updates, and React Context.

- [ ] **Step 4: Run test to verify it passes**
Run: `npm --prefix web test web/src/compare/useCompareWorkspace.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add web/src/compare/useCompareWorkspace.ts web/src/compare/CompareWorkspaceProvider.tsx web/src/compare/useCompareWorkspace.test.tsx
git commit -m "feat(compare): add compare workspace state provider"
```

---

### Task 4: Compare Batch Generation Runner Controller

**Files:**
- Create: `web/src/compare/useCompareBatchRunner.ts`
- Test: `web/src/compare/useCompareBatchRunner.test.tsx`

**Interfaces:**
- Consumes: `apiPost`, `apiGet` from `../api/client`, `BaseTemplate`, `PromptVariant` from `types.ts`.
- Produces:
  - `useCompareBatchRunner(options?: { concurrency?: number })`:
    - `runVariant(variant: PromptVariant, template: BaseTemplate, onUpdate: (patch) => void): Promise<void>`
    - `runRound(variants: PromptVariant[], template: BaseTemplate, onUpdate: (variantId, patch) => void): Promise<void>`
    - `isBusy: boolean`

- [ ] **Step 1: Write failing tests for batch runner**
Create `web/src/compare/useCompareBatchRunner.test.tsx` with mock `apiPost` and `apiGet`:
1. Constructs correct `render_request` inheriting `template.seed` unless `seedOverride` is set.
2. Calls `/generate`, polls `/jobs/{id}` until `succeeded`, returns result image and seed.
3. Handles failure gracefully: sets `status: "failed"` and `error` message without breaking the runner.

- [ ] **Step 2: Run test to verify it fails**
Run: `npm --prefix web test web/src/compare/useCompareBatchRunner.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement useCompareBatchRunner**
Write `web/src/compare/useCompareBatchRunner.ts`, with concurrency queue handling, payload construction matching NovelAI requirements (`prompt`, `negative_prompt`, `parameters: { seed, width, height, steps, scale }`), and job status polling.

- [ ] **Step 4: Run test to verify it passes**
Run: `npm --prefix web test web/src/compare/useCompareBatchRunner.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add web/src/compare/useCompareBatchRunner.ts web/src/compare/useCompareBatchRunner.test.tsx
git commit -m "feat(compare): add batch runner controller for compare variants"
```

---

### Task 5: UI Components & Compare Studio Page

**Files:**
- Create: `web/src/components/CompareTemplateBar.tsx`
- Create: `web/src/components/VariantCard.tsx`
- Create: `web/src/components/CompareRoundSection.tsx`
- Create: `web/src/components/DeepCompareModal.tsx`
- Create: `web/src/pages/CompareStudio.tsx`
- Modify: `web/src/components/Layout.tsx` (add "compare" tab)
- Modify: `web/src/App.tsx` (mount CompareStudio)
- Modify: `web/src/styles.css` (add compare-specific styling)
- Test: `web/src/pages/CompareStudio.test.tsx`

**Interfaces:**
- Produces:
  - Complete Compare Studio page integrated into PromptAtelier Web.
  - Template Bar with file drag/drop, paste listener, parameter badges.
  - Multi-round layout with `[➕ 往下新增新的一批对比]` button.
  - Variant cards with real-time tag diff pills (green for added, red strikethrough for removed), inline generate button, image thumbnail, and "以此变体往下派生 ⬇" button.
  - Deep Compare modal with Split Slider (interactive draggable partition) and Flicker mode (keyboard toggle).

- [ ] **Step 1: Write failing integration test for CompareStudio**
Create `web/src/pages/CompareStudio.test.tsx` asserting:
1. Renders Template Bar and initial empty state.
2. Drag/drop or file import populates template.
3. Renders Variant Cards and displays Tag Diff chips when prompt is modified.
4. Clicking "往下新增新的一批对比" appends a new round.
5. Clicking "对比" on two cards opens the Deep Compare Modal.

- [ ] **Step 2: Run test to verify it fails**
Run: `npm --prefix web test web/src/pages/CompareStudio.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement components and page**
1. Implement `CompareTemplateBar.tsx` (file dropzone, clipboard paste listener, parameter chips, reset).
2. Implement `VariantCard.tsx` (editable name, prompt textarea, tag diff pills, seed lock/unlock toggle, generate button, result preview, compare checkbox, fork downward button).
3. Implement `CompareRoundSection.tsx` (round title, run round button, horizontal scroll of variant cards, `[+] 新增变体` button).
4. Implement `DeepCompareModal.tsx` (Split Slider with draggable divider, Flicker mode with keyboard left/right listeners, sync zoom/pan).
5. Implement `CompareStudio.tsx`, wire up in `Layout.tsx` and `App.tsx`, and add necessary CSS rules in `web/src/styles.css`.

- [ ] **Step 4: Run test to verify it passes**
Run: `npm --prefix web test web/src/pages/CompareStudio.test.tsx`
Expected: PASS.

- [ ] **Step 5: Run full frontend test suite & type check**
Run: `npm --prefix web test` and `npm --prefix web run build`
Expected: PASS with 0 type errors.

- [ ] **Step 6: Commit**
```bash
git add web/src/components/CompareTemplateBar.tsx web/src/components/VariantCard.tsx web/src/components/CompareRoundSection.tsx web/src/components/DeepCompareModal.tsx web/src/pages/CompareStudio.tsx web/src/pages/CompareStudio.test.tsx web/src/components/Layout.tsx web/src/App.tsx web/src/styles.css
git commit -m "feat(web): implement Compare Studio UI and deep compare modal"
```

---

### Task 6: Real Generation End-to-End Verification

**Files:**
- Test/Script: `tests/test_live_compare_generation.py` or interactive verification.

**Verification Steps:**
- [ ] **Step 1: Run automated backend test suite**
Run: `uv run pytest tests/test_web_image_meta.py -v`
Expected: All backend tests PASS.

- [ ] **Step 2: Run automated frontend test suite**
Run: `npm --prefix web test`
Expected: All frontend tests PASS.

- [ ] **Step 3: Execute real NovelAI image generation test**
1. Start backend server: `uv run python -m tags_machine_core.web`
2. In Compare Studio:
   - Load a sample PNG (from existing `acceptance_compare` or `outputs/` or upload via dropzone).
   - Verify BaseTemplate extracts prompt, seed, dimensions correctly.
   - Variant 1: Original prompt.
   - Variant 2: Add `cinematic lighting, dramatic shadows`.
   - Click "运行本批" -> verify real generation job runs via NovelAI.
   - Verify image files are generated on disk under `outputs/`.
   - Verify images render in Variant 1 and Variant 2 cards.
3. Test "以此变体往下派生 ⬇":
   - Click fork on Variant 2 -> verify Round 2 appears below with Variant 2's prompt as base.
   - Add Variant 2-B with `from behind`.
   - Click generate -> verify real image generation succeeds.
4. Test Deep Compare Modal:
   - Select Variant 1 and Variant 2.
   - Open Deep Compare Modal -> test Split Slider (drag dividing line left and right).
   - Switch to Flicker Mode -> press arrow keys to toggle between the two images.
   - Verify visual difference is clearly observable.

- [ ] **Step 4: Final commit and cleanup**
```bash
git add .
git commit -m "test: verify live compare generation and visual comparison workflow"
```
