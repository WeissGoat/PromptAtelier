# Batch Generation Follow-Up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 `docs/batch_generation_spec_v1.md` 中自动化批量跑图的剩余能力，并用真实 NovelAI 出图完成业务验收。

**Architecture:** 批量层只做任务选择、展开、调度、恢复、归档和报告，不拼接提示词规则，也不直接组 NovelAI payload。它复用现有 `GenerationService`、`AgentComposer`、`PromptPolicyPipeline`、`NovelAIRenderer` 和 `execute_render_request`，保持 AgentComposer 稳定链路不被 ScriptComposer / PromptPolicyPipeline 影响。

**Tech Stack:** Python 3.11、Pydantic v2、PyYAML、pytest、现有 `tags_machine_core` CLI、NovelAI 真实生图链路。

---

## Spec 和实现计划的区别

`spec` 回答“要做什么、为什么这样做、边界在哪里”。它面向架构和产品 review，重点是目标、非目标、模块职责、数据契约、命令入口、验收标准。当前对应文档是 `docs/batch_generation_spec_v1.md`。

`实现计划` 回答“怎么一步步落地”。它面向开发执行，重点是哪些文件要改、每一步怎么验证、何时提交、最后如何做真实业务验收。当前这份文档就是从现有实现状态继续推进的执行计划。

判断标准很简单：

| 文档 | 主要回答 | 不负责 |
| --- | --- | --- |
| `spec` | 目标、范围、边界、输入输出格式、验收口径 | 不规定每个提交怎么拆 |
| `实现计划` | 文件清单、任务顺序、测试命令、真实出图验收步骤 | 不重新争论架构方向 |

## 当前状态

已经完成并提交：

- `src/tags_machine_core/batch/` 核心包：models、spec_reader、selectors、planner、manifest、archive、report、executor、runner。
- CLI：`plan-batch`、`run-batch`、`resume-batch`、`inspect-batch`。
- 示例：`examples/batches/prompt_list_20260412.yaml`、`action_folder_20260412.yaml`、`agent_cache_miss.yaml`。
- 真实 NovelAI 验收记录：`docs/batch_generation_business_test_20260613.md`。
- 已验证 `prompt_list` 和 `agent cache miss -> agent result 回填 -> resume 出图` 两条业务链路。

当前未提交工作区里已经开始的改动：

- `src/tags_machine_core/batch/runner.py`
  - `run.max_images` 按剩余图片预算限制单任务 `nt`。
  - retry 记录写入 report entry。
- `src/tags_machine_core/batch/report.py`
  - `report.md` 展示 retry records。
- `src/tags_machine_core/cli.py`
  - `run-batch --resume/--no-resume`。
  - `run-batch --stop-on-error`。
  - `resume-batch --stop-on-error`。
  - `inspect-batch` 从 task `status.json` 回读最终状态，避免 manifest 旧事件遮蔽真实结果。

## 文件结构

继续修改：

```text
src/tags_machine_core/batch/runner.py     # max_images、retry、resume 主流程
src/tags_machine_core/batch/report.py     # report.md/report.json 输出
src/tags_machine_core/batch/selectors.py  # prompt_file、folder/collection 选择能力补强
src/tags_machine_core/batch/archive.py    # copy_images 验证和图片路径归档
src/tags_machine_core/cli.py              # batch CLI 和 JSON API CLI 入口
tests/test_batch_generation.py            # 当前 batch 集中测试文件
examples/batches/*.yaml                   # 最小业务示例
docs/batch_generation_business_test_*.md  # 真实 NovelAI 验收记录
```

可能新增：

```text
examples/batches/prompt_file_20260412.yaml
examples/batches/copy_images_20260412.yaml
docs/batch_generation_business_test_20260614.md
```

不要修改：

```text
F:/my_project/new/tags_machine/blackboard.py
F:/my_project/new/tags_machine/formula.py
F:/my_project/new/tags_machine/TagsMachine
```

父项目只在需要同步子模块时更新 `refactor` 指针。

## Task 1: 收束当前未提交 batch 改动

**Files:**

- Modify: `src/tags_machine_core/batch/runner.py`
- Modify: `src/tags_machine_core/batch/report.py`
- Modify: `src/tags_machine_core/cli.py`
- Modify: `tests/test_batch_generation.py`

- [ ] **Step 1: 查看当前 diff，确认只包含 batch 相关改动**

Run:

```powershell
cd F:\my_project\new\tags_machine\refactor
git diff -- src/tags_machine_core/batch/runner.py src/tags_machine_core/batch/report.py src/tags_machine_core/cli.py tests/test_batch_generation.py
```

Expected:

```text
Only batch runner/report/CLI/test changes are shown.
No legacy tags_machine files are modified.
```

- [ ] **Step 2: 为 `max_images` 限制单任务 `nt` 增加测试**

Add to `tests/test_batch_generation.py`:

```python
def test_batch_runner_clamps_task_nt_to_remaining_max_images(tmp_path):
    task = _prompt_task(tmp_path, task_id="t1", nt=3)
    executor = RecordingExecutor(status="succeeded", image_paths=["image.png"])
    runner = BatchRunner(executor=executor)

    runner.run_tasks(
        run_dir=tmp_path / "run",
        tasks=[task],
        config=_app_config(tmp_path),
        run_config=RunConfig(max_images=1),
    )

    assert executor.calls[0].render.nt == 1
```

If helper names differ, use the existing helpers already present in `tests/test_batch_generation.py`; do not create a second duplicate helper set.

- [ ] **Step 3: 为 `inspect-batch` 状态回读增加测试**

Add to `tests/test_batch_generation.py`:

```python
def test_inspect_batch_reconciles_status_json_over_manifest(tmp_path, capsys):
    task = _prompt_task(tmp_path, task_id="t1")
    run_dir = tmp_path / "run"
    write_initial_manifest(run_dir, [task])
    BatchArchive().write_status(task, status="succeeded", attempt=1, image_paths=["image.png"])

    code = main(["inspect-batch", str(run_dir), "--full"])

    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["counts"]["succeeded"] == 1
```

- [ ] **Step 4: 为 retry records 增加测试**

Add to `tests/test_batch_generation.py`:

```python
def test_batch_report_contains_retry_records(tmp_path):
    report = write_report(
        tmp_path,
        [
            {
                "task_id": "t1",
                "status": "failed",
                "image_paths": [],
                "error": "502 Bad Gateway",
                "retry_records": [
                    {"attempt": 1, "error": "502 Bad Gateway", "retryable": True, "delay_seconds": 1},
                    {"attempt": 2, "error": "502 Bad Gateway", "retryable": False},
                ],
            }
        ],
    )

    assert report["counts"]["failed"] == 1
    assert "retry" in (tmp_path / "report.md").read_text(encoding="utf-8")
```

- [ ] **Step 5: 运行 focused tests**

Run:

```powershell
uv run --with pytest --with-editable . pytest tests\test_batch_generation.py -q
```

Expected:

```text
all tests in tests/test_batch_generation.py pass
```

- [ ] **Step 6: 运行语法和 whitespace 检查**

Run:

```powershell
uv run python -m compileall -q src tests
git diff --check
```

Expected:

```text
No output from git diff --check.
compileall exits with code 0.
```

- [ ] **Step 7: 提交 refactor 改动**

Run:

```powershell
git add src/tags_machine_core/batch/runner.py src/tags_machine_core/batch/report.py src/tags_machine_core/cli.py tests/test_batch_generation.py
git commit -m "Complete batch runner followups"
```

Expected:

```text
A new refactor commit is created.
```

## Task 2: 补强 prompt_file 和 copy_images

**Files:**

- Modify: `src/tags_machine_core/batch/selectors.py`
- Modify: `src/tags_machine_core/batch/archive.py`
- Modify: `tests/test_batch_generation.py`
- Create: `examples/batches/prompt_file_20260412.yaml`
- Create: `examples/batches/copy_images_20260412.yaml`

- [ ] **Step 1: 增加 prompt_file selector 测试**

Add to `tests/test_batch_generation.py`:

```python
def test_prompt_file_selector_reads_line_prompts(tmp_path):
    prompt_file = tmp_path / "prompts.txt"
    prompt_file.write_text("akemi_homura, 1girl, standing\n", encoding="utf-8")

    refs = expand_selector(
        role="prompt",
        spec=SelectorSpec(selector="prompt_file", path=str(prompt_file), format="lines"),
        context=SelectorContext(base_dir=tmp_path, collections={}),
    )

    assert refs == [{"id": "prompts_0001", "prompt": "akemi_homura, 1girl, standing"}]
```

- [ ] **Step 2: 实现 `prompt_file` 的 `lines/jsonl/json/csv`**

In `src/tags_machine_core/batch/selectors.py`, route `prompt_file`:

```python
if selector == "prompt_file":
    if not spec.path:
        raise ValueError("prompt_file selector requires path")
    return _read_prompt_file(resolve_path(spec.path, base_dir=context.base_dir), spec.format)
```

Add `_read_prompt_file()` with these exact behaviors:

- `lines`: skip empty lines and `#` comments; id format is `<stem>_<0001>`.
- `jsonl`: each non-empty line must contain `id` and `prompt`.
- `json`: file must be a list of objects with `id` and `prompt`.
- `csv`: requires `prompt`; optional `id` and `negative`.

- [ ] **Step 3: 增加 copy_images 业务归档测试**

Add to `tests/test_batch_generation.py`:

```python
def test_copy_images_archives_images_inside_task_dir(tmp_path):
    task = _prompt_task(tmp_path, task_id="t1")
    source_image = tmp_path / "source.png"
    source_image.write_bytes(b"png")
    result = _generation_result_with_image(source_image)

    archive = BatchArchive(ArchiveConfig(copy_images=True))
    archived = archive.archive_success(
        task=task,
        prompt_bundle=_prompt_bundle(),
        render_request=_render_request(),
        generation_result=result,
    )

    assert archived.images[0].path.parent.name == "images"
    assert archived.images[0].path.read_bytes() == b"png"
```

- [ ] **Step 4: 新增示例 spec**

Create `examples/batches/prompt_file_20260412.yaml`:

```yaml
schema: tags-machine-core.batch/v1
name: prompt-file-20260412
config: configs/local.example.yaml
output_root: outputs/batches

defaults:
  composer: full
  artist: 20260412
  nt: 1
  resolution: random_standard
  model: nai-diffusion-4-5-full

select:
  prompts:
    - selector: prompt_file
      path: examples/batches/prompts_20260412.txt
      format: lines

expand:
  mode: prompt_list

run:
  resume: true
  max_images: 1
```

Create `examples/batches/prompts_20260412.txt`:

```text
akemi_homura, 1girl, standing, looking at viewer
akemi_homura, 1girl, bare feet, foot focus, lower body
```

- [ ] **Step 5: 运行测试并提交**

Run:

```powershell
uv run --with pytest --with-editable . pytest tests\test_batch_generation.py -q
uv run python -m compileall -q src tests
git diff --check
git add src/tags_machine_core/batch/selectors.py src/tags_machine_core/batch/archive.py tests/test_batch_generation.py examples/batches/prompt_file_20260412.yaml examples/batches/prompts_20260412.txt
git commit -m "Complete batch prompt file and image archive support"
```

Expected:

```text
Focused tests pass and a new refactor commit is created.
```

## Task 3: 对齐 JSON API batch 入口

**Files:**

- Modify: `src/tags_machine_core/cli.py`
- Modify: `src/tags_machine_core/services/json_api_models.py`
- Modify: `src/tags_machine_core/services/json_api.py`
- Modify: `tests/test_batch_generation.py`

- [ ] **Step 1: 明确 API 命令语义**

新增 CLI 命令只做 JSON 输入输出，不绕开现有 batch 代码：

```text
api-plan-batch   -> load BatchSpec JSON/YAML -> BatchPlanner -> JSON result
api-run-batch    -> load BatchSpec JSON/YAML -> BatchRunner -> JSON result
api-resume-batch -> run_dir + optional batch_spec -> BatchRunner resume -> JSON result
api-inspect-batch -> run_dir -> inspect result JSON
```

- [ ] **Step 2: 增加最小 API 测试**

Add to `tests/test_batch_generation.py`:

```python
def test_api_plan_batch_returns_json_contract(tmp_path, capsys):
    spec = _write_prompt_list_spec(tmp_path, name="api-plan")

    code = main(["api-plan-batch", str(spec), "--full"])

    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schema"] == "tags-machine-core.api-plan-batch-result/v1"
    assert data["task_count"] == 1
```

- [ ] **Step 3: 实现 API 命令为现有命令薄封装**

In `src/tags_machine_core/cli.py`, reuse existing command functions instead of duplicating logic:

```python
def cmd_api_plan_batch(args) -> int:
    return cmd_plan_batch(args)


def cmd_api_run_batch(args) -> int:
    return cmd_run_batch(args)


def cmd_api_resume_batch(args) -> int:
    return cmd_resume_batch(args)


def cmd_api_inspect_batch(args) -> int:
    return cmd_inspect_batch(args)
```

Register parsers with the same arguments as non-API commands, but set schema names in output to API-specific schemas if the existing print helper supports it. If schema override would require broad refactor, keep payload identical and document that API commands are stable aliases in this phase.

- [ ] **Step 4: 运行测试并提交**

Run:

```powershell
uv run --with pytest --with-editable . pytest tests\test_batch_generation.py -q
uv run python -m compileall -q src tests
git diff --check
git add src/tags_machine_core/cli.py src/tags_machine_core/services/json_api_models.py src/tags_machine_core/services/json_api.py tests/test_batch_generation.py
git commit -m "Add batch JSON API entrypoints"
```

Expected:

```text
API batch commands are available and reuse the same batch core path.
```

## Task 4: 真实 NovelAI 业务验收

**Files:**

- Create: `docs/batch_generation_business_test_20260614.md`
- Read only: `F:/my_project/new/tags_machine/novelai/client.py`

- [ ] **Step 1: 设置 NovelAI token，不打印 token**

Run:

```powershell
cd F:\my_project\new\tags_machine\refactor
$tokenText = Get-Content -Path 'F:\my_project\new\tags_machine\novelai\client.py' -Raw
$env:NAI_ACCESS_TOKEN = [regex]::Match($tokenText, 'return\s+"([^"]+)"').Groups[1].Value
```

Expected:

```text
No token is printed.
```

- [ ] **Step 2: prompt_list 真实出图**

Run:

```powershell
uv run python -m tags_machine_core run-batch examples\batches\prompt_list_20260412.yaml --limit 2 --full
uv run python -m tags_machine_core inspect-batch outputs\batches\prompt-list-20260412 --full
```

Expected:

```text
At least 2 succeeded tasks or already-succeeded skipped tasks with existing image paths.
Each succeeded task has generation_result.json and png_params.json.
```

- [ ] **Step 3: prompt_file 真实出图**

Run:

```powershell
uv run python -m tags_machine_core run-batch examples\batches\prompt_file_20260412.yaml --limit 1 --full
uv run python -m tags_machine_core inspect-batch outputs\batches\prompt-file-20260412 --full
```

Expected:

```text
One real NovelAI image is generated or skipped because the task already succeeded.
PNG params can be read.
```

- [ ] **Step 4: action folder / collection 业务链路**

Run:

```powershell
uv run python -m tags_machine_core run-batch examples\batches\action_folder_20260412.yaml --limit 3 --full
uv run python -m tags_machine_core inspect-batch outputs\batches\action-folder-20260412 --full
```

Expected:

```text
Selector/planner expands old design action folders.
Agent cache misses are recorded as requires_agent.
Any cache-hit or backfilled task generates a real image.
```

- [ ] **Step 5: 参数一致性检查**

For every newly succeeded image:

```powershell
uv run python -m tags_machine_core compare-render-params <image.png> <task_dir>\generation_result.json --show-normalized --full
```

Expected:

```text
diff_count=0
```

If `diff_count` is not zero, record every differing field and whether it is expected NovelAI metadata drift.

- [ ] **Step 6: 记录人工视觉结论**

Create `docs/batch_generation_business_test_20260614.md`:

```markdown
# Batch Generation 真实出图验收 2026-06-14

## 范围

- prompt_list
- prompt_file
- action folder / collection
- resume
- max_images
- PNG 参数对比

## 结果

| Case | Status | Image | GenerationResult | PNG Params | Parameter Diff | Visual Result |
| --- | --- | --- | --- | --- | --- | --- |
| prompt-list-20260412 / standing_001 | succeeded | F:/...png | F:/...json | F:/...json | 0 | pass |

## 结论

- BatchRunner 可以真实调用 NovelAI。
- 每个成功任务保存 GenerationResult 和 PNG 参数。
- report.md 能看到图片路径、prompt 摘要、retry 信息和人工视觉检查字段。
- 如存在 requires_agent，说明 cache miss 正常进入外部 agent 协作流程。
```

- [ ] **Step 7: 提交业务验收文档**

Run:

```powershell
git add docs/batch_generation_business_test_20260614.md
git commit -m "Record batch generation business validation"
```

Expected:

```text
Business validation evidence is committed in refactor.
```

## Task 5: 更新父项目子模块指针

**Files:**

- Modify: `F:/my_project/new/tags_machine/refactor`

- [ ] **Step 1: 确认 refactor 工作区干净**

Run:

```powershell
cd F:\my_project\new\tags_machine\refactor
git status --short
```

Expected:

```text
No output.
```

- [ ] **Step 2: 回到父项目，只提交子模块指针**

Run:

```powershell
cd F:\my_project\new\tags_machine
git status --short
git add refactor
git commit -m "Update refactor batch generation followups"
```

Expected:

```text
Only the refactor submodule pointer is staged and committed.
Existing unrelated dirty files remain unstaged.
```

## Final Verification Gate

Run from `F:\my_project\new\tags_machine\refactor`:

```powershell
uv run --with pytest --with-editable . pytest tests\test_batch_generation.py -q
uv run python -m compileall -q src tests
git diff --check
```

Expected:

```text
Focused batch tests pass.
compileall exits with code 0.
git diff --check has no output.
```

Run at least one real business check:

```powershell
$tokenText = Get-Content -Path 'F:\my_project\new\tags_machine\novelai\client.py' -Raw
$env:NAI_ACCESS_TOKEN = [regex]::Match($tokenText, 'return\s+"([^"]+)"').Groups[1].Value
uv run python -m tags_machine_core run-batch examples\batches\prompt_file_20260412.yaml --limit 1 --full
```

Expected:

```text
A real NovelAI image path is produced or the task is skipped because it already succeeded.
The task has generation_result.json and png_params.json.
compare-render-params reports diff_count=0 or the difference is documented.
```

Do not claim the batch feature is complete without at least one fresh or existing real NovelAI image path, readable PNG params, and a written business conclusion.
