# Run Prompt Agent Mainline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `run-prompt` 固化为 core 的稳定生图主链路，并接入 `AgentComposer` 的节点缓存/回填流程，同时保持旧 tags_machine 只作为兼容输入和验收参考。

**Architecture:** `PromptBundle` 继续作为提示词层和生图层的边界。`run-prompt` 默认处理完整 prompt；显式 `--composer agent` 时读取 character/action/background 节点生成 agent cache key，带完整 prompt 则写缓存并继续生图，不带完整 prompt 则只读缓存，miss 时返回 `requires_agent` 状态或 CLI 友好错误。NovelAI 兼容行为留在 adapter/compat 路径，不把旧 `formula` 的 hardcode 带入 composer。

**Tech Stack:** Python 3, argparse CLI, Pydantic contracts, unittest, uv, NovelAI adapter/client, YAML/JSON artifacts.

---

## Scope

本计划按当前讨论落成 5 个阶段：

1. 固化边界和兼容策略。
2. 把 `run-prompt` 做成稳定主链路，并完善 `AgentComposer` 模式。
3. 做新 `run-action`/节点 composer 评估链路，但不追求旧 `formula` 逐字等价。
4. 建立兼容验收、composer 评估、视觉验收三类报告。
5. 准备批量任务和未来 UI 的 JSON 边界。

当前优先实现阶段 2。阶段 3-5 先落文档和接口边界，避免提前引入过多实现。

## File Structure

- Modify: `src/tags_machine_core/cli.py`
  - 增加 `run-prompt --composer {full,agent}`。
  - 允许 `--composer agent` 时 prompt 可选。
  - 增加 `--character`、`--action`、`--background`、`--extra-prompt`、`--character-scope`、`--body-scope`、`--instruction`、`--agent-model`、`--cache-dir`、`--agent-result`。
  - 将 `run-prompt` 构建逻辑拆成 full prompt 和 agent prompt 两条内部函数。

- Modify: `src/tags_machine_core/composers/agent.py`
  - 可选增强：增加 `result_from_prompt()` 小函数，把 CLI 的完整 prompt/negative 转成 `AgentCompositionResult`。
  - 保持 cache key 只由节点内容、style_ref、instructions、agent_model、scope、extra_prompt、negative 等输入决定，不包含 agent 输出 prompt。

- Modify: `src/tags_machine_core/services/generation_service.py`
  - 如果新增 helper，需要只做薄封装，不把 CLI 参数对象传进 service。

- Modify: `tests/test_cli_prompt.py`
  - 覆盖 `run-prompt --composer agent` 的 cache miss、prompt 回填写 cache、cache hit 继续生成 render request、真实执行复用 cache。

- Modify: `tests/test_agent_composer.py`
  - 如果新增 `result_from_prompt()`，覆盖 prompt 不进入 cache key、negative fallback 行为。

- Modify: `docs/development_plan_v1.md`
  - 更新阶段 2 说明和 CLI 示例。

- Modify: `docs/json_api_contract_v1.md`
  - 只补充 `run-prompt --composer agent` 是 CLI 业务入口；JSON API 仍以 `api-resolve-compose-render-plan` 为无联网状态入口。

---

### Task 1: 固化阶段边界文档

**Files:**
- Modify: `docs/development_plan_v1.md`

- [x] **Step 1: 更新迁移路线为 5 个阶段**

把 `## 迁移路线` 下的阶段调整为：

```markdown
第一阶段：边界与兼容层冻结

- 保持旧项目稳定，core 不 import 旧项目运行时代码。
- 明确 `PromptBundle`、`RenderRequest`、`GenerationResult` 三个模块边界。
- 旧项目只提供设计素材、最终 prompt、PNG 参数和基准图。
- NovelAI adapter 可以做旧 style / 旧参数兼容；composer 不为了旧 `formula` 逐字等价引入 hardcode。

第二阶段：`run-prompt` 主链路与 AgentComposer

- `run-prompt` 成为完整 prompt 生图主入口。
- `run-prompt --composer agent` 支持节点输入、agent prompt 回填、PromptBundle cache 复用。
- 带完整 prompt 时认为 agent 已经拼接完成，写入 cache 后继续生成。
- 不带完整 prompt 时先读 cache；miss 时返回 `requires_agent` 状态或 CLI 友好错误，不调用后端。
- `legacy-final` 只作为旧 PNG / 旧 `run_action` 最终 prompt 的兼容模式。

第三阶段：新节点 composer 评估

- 实现 core 版 character + action + style composer 链路。
- 局部镜头通过统一 policy 过滤 character sections。
- 和旧 `run_action` 做评估对比，但不要求逐字等价。

第四阶段：NovelAI 真实验收闭环

- 兼容链路做参数级 diff。
- 新 composer 链路做语义、裁剪和视觉评估。
- 每个真实 case 输出 `GenerationResult`、PNG 参数、参数 diff、视觉结论和有意差异。

第五阶段：批量任务与 UI 边界

- 批量任务复用 `PromptBundle -> RenderRequest -> GenerationResult`。
- 前端只读 JSON API，不直接拼 NovelAI 参数。
- ComfyUI / SD 等后端等规范明确后再进入正式验收。
```

- [x] **Step 2: 运行文档 diff 检查**

Run:

```powershell
git diff -- docs/development_plan_v1.md
```

Expected: 只出现阶段描述调整，不出现代码文件变更。

- [x] **Step 3: Commit（合并提交）**

```powershell
git add docs/development_plan_v1.md docs/superpowers/plans/2026-05-27-run-prompt-agent-mainline.md
git commit -m "docs: plan run-prompt agent mainline"
```

---

### Task 2: 让 `run-prompt --composer agent` 支持无 prompt 的 cache miss 状态

**Files:**
- Modify: `src/tags_machine_core/cli.py`
- Test: `tests/test_cli_prompt.py`

- [x] **Step 1: 写失败测试**

在 `tests/test_cli_prompt.py` 的 `CliPromptTest` 中新增测试。使用已有 `_write_style_node()`，新增本地节点写入 helper：

```python
    def _write_agent_nodes(self, root: Path) -> tuple[Path, Path]:
        character = root / "homura"
        character.mkdir()
        (character / "meta.yaml").write_text(
            """
schema: tags-machine.character/v1
kind: character
id: homura
tags:
  identity:
    - akemi homura
  hair:
    - long black hair
  eyes:
    - purple eyes
  feet:
    - bare soles
negative_prompt:
  - extra toes
""".strip(),
            encoding="utf-8",
        )
        action = root / "foot_detail"
        action.mkdir()
        (action / "meta.yaml").write_text(
            """
schema: tags-machine.action/v1
kind: action
id: foot_detail
character_scope: foot_detail
tags:
  action:
    - foot focus
    - soles close-up
negative_prompt:
  - face focus
""".strip(),
            encoding="utf-8",
        )
        return character, action
```

再新增测试：

```python
    def test_run_prompt_agent_cache_miss_returns_agent_task_without_render_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action = self._write_agent_nodes(root)
            style = _write_style_node(root)
            cache_dir = root / "cache"

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "run-prompt",
                        "--dry-run",
                        "--composer",
                        "agent",
                        "--character",
                        str(character),
                        "--action",
                        str(action),
                        "--character-scope",
                        "foot_detail",
                        "--style-node",
                        str(style),
                        "--instruction",
                        "组合角色和动作，避免带入脸部细节",
                        "--agent-model",
                        "agent-model-v1",
                        "--cache-dir",
                        str(cache_dir),
                    ]
                )

            data = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(data["schema"], "tags-machine-core.run-prompt-result/v1")
            self.assertEqual(data["status"], "requires_agent")
            self.assertTrue(data["dry_run"])
            self.assertIn("agent_task", data)
            self.assertNotIn("prompt_bundle", data)
            self.assertNotIn("render_request", data)
            self.assertEqual(data["agent_task"]["schema"], "tags-machine-core.agent-composition-task/v1")
            self.assertEqual(data["agent_task"]["style_ref"], "prompt_style")
            self.assertFalse(any(cache_dir.glob("*.json")))
```

- [x] **Step 2: 实现后回归验证**

Run:

```powershell
uv run python -m unittest tests.test_cli_prompt.CliPromptTest.test_run_prompt_agent_cache_miss_returns_agent_task_without_render_request
```

Expected: 当前实现已通过；原始失败态不再保留，阶段二门禁覆盖该行为。

- [x] **Step 3: 修改 CLI 参数**

在 `src/tags_machine_core/cli.py` 中修改 `_add_prompt_run_arguments()`。替换 prompt group 和新增 agent 参数：

```python
    parser.add_argument(
        "--composer",
        default="full",
        choices=("full", "agent"),
        help="Prompt composition mode; agent mode reads nodes and prompt cache",
    )
    prompt_group = parser.add_mutually_exclusive_group(required=False)
    prompt_group.add_argument("--prompt", help="Full character + action prompt / tags string")
    prompt_group.add_argument("--prompt-file", help="Read prompt from a UTF-8 text file")
    parser.add_argument("--character", help="Path to a character node when --composer agent")
    parser.add_argument("--action", help="Path to an action node when --composer agent")
    parser.add_argument("--background", help="Path to a background node when --composer agent")
    parser.add_argument("--extra-prompt", help="Additional positive prompt text for agent task")
    parser.add_argument("--character-scope", help="Override character_scope for agent composition")
    parser.add_argument("--body-scope", help="Compatibility alias for --character-scope")
    parser.add_argument(
        "--instruction",
        action="append",
        help="Instruction passed through to the external agent; can be repeated",
    )
    parser.add_argument(
        "--agent-model",
        help="External agent model/version identifier included in the prompt cache key",
    )
    parser.add_argument("--agent-result", help="Path to agent result JSON")
    parser.add_argument("--cache-dir", help="PromptBundle cache directory")
```

在 `_build_novelai_prompt_artifacts()` 开头加分发：

```python
def _build_novelai_prompt_artifacts(service: GenerationService, args):
    if getattr(args, "composer", "full") == "agent":
        return _build_novelai_agent_prompt_artifacts(service, args)
    if not _read_prompt_value(args):
        raise ValueError("run-prompt requires --prompt or --prompt-file unless --composer agent is used")
    style_ref, style = _load_novelai_style_for_prompt(args)
    bundle = service.compose_full_prompt(
        prompt=_read_prompt_value(args),
        negative=args.negative or "",
        style_ref=style_ref,
    )
    params = _load_json_arg(args.params_json)
    params["n_samples"] = args.nt
    request = service.build_novelai_request(
        bundle,
        seed=args.seed,
        style=style,
        width=args.width,
        height=args.height,
        model=args.model,
        params=params,
    )
    return bundle, request
```

导入 `AgentCompositionRequired`：

```python
from tags_machine_core.composers import AgentCompositionRequired, load_agent_result
```

新增 helper：

```python
def _build_novelai_agent_prompt_artifacts(service: GenerationService, args):
    style_ref, style = _load_novelai_style_for_prompt(args)
    character, action, background = _read_node_inputs(args)
    cache = PromptCache(args.cache_dir) if args.cache_dir else None
    result = load_agent_result(args.agent_result) if args.agent_result else None
    prompt = _read_prompt_value(args)
    if prompt and result is None:
        result = {
            "positive": prompt,
            "negative": args.negative or "",
            "character_scope": args.character_scope or args.body_scope,
        }
    bundle = service.compose_nodes_with_agent(
        character=character,
        action=action,
        background=background,
        extra_prompt=args.extra_prompt or "",
        negative=args.negative or "",
        style_ref=style_ref,
        character_scope=args.character_scope or args.body_scope,
        instructions=args.instruction or [],
        agent_model=args.agent_model,
        result=result,
        cache=cache,
    )
    params = _load_json_arg(args.params_json)
    params["n_samples"] = args.nt
    request = service.build_novelai_request(
        bundle,
        seed=args.seed,
        style=style,
        width=args.width,
        height=args.height,
        model=args.model,
        params=params,
    )
    return bundle, request
```

修改 `cmd_run_prompt()` 捕获 cache miss：

```python
def cmd_run_prompt(args) -> int:
    service = GenerationService()
    try:
        bundle, request = _build_novelai_prompt_artifacts(service, args)
    except AgentCompositionRequired as exc:
        result = {
            "schema": "tags-machine-core.run-prompt-result/v1",
            "status": "requires_agent",
            "dry_run": True,
            "agent_task": exc.task,
        }
        print_json(result, full=args.full)
        return 0
    result: dict[str, Any] = {
        "schema": "tags-machine-core.run-prompt-result/v1",
        "status": "ready",
        "dry_run": args.dry_run,
        "prompt_bundle": bundle,
        "render_request": request,
    }
    ...
```

- [x] **Step 4: 运行测试确认通过**

Run:

```powershell
uv run python -m unittest tests.test_cli_prompt.CliPromptTest.test_run_prompt_agent_cache_miss_returns_agent_task_without_render_request
```

Expected: PASS。

- [x] **Step 5: Commit（合并提交）**

```powershell
git add src/tags_machine_core/cli.py tests/test_cli_prompt.py
git commit -m "feat: resolve run-prompt agent cache misses"
```

---

### Task 3: `run-prompt --composer agent` 带完整 prompt 时写 cache 并继续生成 RenderRequest

**Files:**
- Modify: `tests/test_cli_prompt.py`
- Modify: `src/tags_machine_core/cli.py`

- [x] **Step 1: 写失败测试**

在 `CliPromptTest` 中新增：

```python
    def test_run_prompt_agent_prompt_writes_cache_and_cache_hit_reuses_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action = self._write_agent_nodes(root)
            style = _write_style_node(root)
            cache_dir = root / "cache"

            first_stdout = io.StringIO()
            with redirect_stdout(first_stdout):
                first_exit_code = main(
                    [
                        "run-prompt",
                        "--dry-run",
                        "--full",
                        "--composer",
                        "agent",
                        "--character",
                        str(character),
                        "--action",
                        str(action),
                        "--character-scope",
                        "foot_detail",
                        "--style-node",
                        str(style),
                        "--instruction",
                        "组合角色和动作，避免带入脸部细节",
                        "--agent-model",
                        "agent-model-v1",
                        "--cache-dir",
                        str(cache_dir),
                        "--prompt",
                        "akemi homura, bare soles, foot focus",
                        "--negative",
                        "extra toes, face focus",
                        "--seed",
                        "321",
                        "--nt",
                        "2",
                    ]
                )
            first = json.loads(first_stdout.getvalue())

            second_stdout = io.StringIO()
            with redirect_stdout(second_stdout):
                second_exit_code = main(
                    [
                        "run-prompt",
                        "--dry-run",
                        "--full",
                        "--composer",
                        "agent",
                        "--character",
                        str(character),
                        "--action",
                        str(action),
                        "--character-scope",
                        "foot_detail",
                        "--style-node",
                        str(style),
                        "--instruction",
                        "组合角色和动作，避免带入脸部细节",
                        "--agent-model",
                        "agent-model-v1",
                        "--cache-dir",
                        str(cache_dir),
                        "--seed",
                        "321",
                        "--nt",
                        "2",
                    ]
                )
            second = json.loads(second_stdout.getvalue())

            self.assertEqual(first_exit_code, 0)
            self.assertEqual(second_exit_code, 0)
            self.assertEqual(first["status"], "ready")
            self.assertEqual(second["status"], "ready")
            self.assertFalse(first["prompt_bundle"]["cache"]["cache_hit"])
            self.assertTrue(second["prompt_bundle"]["cache"]["cache_hit"])
            self.assertEqual(
                first["prompt_bundle"]["cache"]["cache_key"],
                second["prompt_bundle"]["cache"]["cache_key"],
            )
            self.assertEqual(
                second["prompt_bundle"]["prompt"]["positive"],
                "akemi homura, bare soles, foot focus",
            )
            self.assertEqual(second["prompt_bundle"]["meta"]["composer_type"], "agent")
            self.assertEqual(second["render_request"]["seed"], 321)
            self.assertEqual(second["render_request"]["params"]["n_samples"], 2)
            self.assertIn("style prefix", second["render_request"]["prompt"])
            self.assertIn("akemi homura, bare soles, foot focus", second["render_request"]["prompt"])
            self.assertTrue(any(cache_dir.glob("*.json")))
```

- [x] **Step 2: 运行测试确认失败**

Run:

```powershell
uv run python -m unittest tests.test_cli_prompt.CliPromptTest.test_run_prompt_agent_prompt_writes_cache_and_cache_hit_reuses_bundle
```

Expected: FAIL，直到 Task 2 helper 完整实现。

- [x] **Step 3: 确认实现满足测试**

如果 Task 2 已按代码实现，此处通常只需要修正细节：

- `_read_prompt_value(args)` 在 agent 模式无 prompt 时必须返回 `""`，不能报错。
- `prompt` 回填成 result 时，result 不能影响 task cache key。
- `style_ref` 必须使用 `_load_novelai_style_for_prompt()` 解析后的值，例如 style node id 或 `--style-ref`。

关键断言：

```python
task = service.build_agent_composition_task(... style_ref=style_ref ...)
```

和：

```python
result = {"positive": prompt, "negative": args.negative or "", ...}
```

不能把 `prompt` 加进 `build_task()` 的入参。

- [x] **Step 4: 运行测试确认通过**

Run:

```powershell
uv run python -m unittest tests.test_cli_prompt.CliPromptTest.test_run_prompt_agent_prompt_writes_cache_and_cache_hit_reuses_bundle
```

Expected: PASS。

- [x] **Step 5: Commit（合并提交）**

```powershell
git add src/tags_machine_core/cli.py tests/test_cli_prompt.py
git commit -m "feat: cache agent prompts through run-prompt"
```

---

### Task 4: `run-prompt --composer agent` 支持真实执行复用 cache

**Files:**
- Modify: `tests/test_cli_prompt.py`
- Modify: `src/tags_machine_core/cli.py`

- [x] **Step 1: 写失败测试**

在 `CliPromptTest` 中新增：

```python
    def test_run_prompt_agent_cache_hit_executes_novelai(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action = self._write_agent_nodes(root)
            style = _write_style_node(root)
            config = self._write_config(root)
            cache_dir = root / "cache"
            output_dir = root / "outputs"

            with redirect_stdout(io.StringIO()):
                main(
                    [
                        "run-prompt",
                        "--dry-run",
                        "--composer",
                        "agent",
                        "--character",
                        str(character),
                        "--action",
                        str(action),
                        "--style-node",
                        str(style),
                        "--agent-model",
                        "agent-model-v1",
                        "--cache-dir",
                        str(cache_dir),
                        "--prompt",
                        "akemi homura, bare soles, foot focus",
                    ]
                )

            with (
                patch.dict("os.environ", {"NAI_ACCESS_TOKEN": "token"}),
                patch("tags_machine_core.execution.NovelAIClient") as client_cls,
            ):
                client = client_cls.return_value
                client.generate_images.return_value = [
                    SimpleNamespace(filename="nai_result.png", content=_png_bytes_with_text({}))
                ]
                client.build_payload.return_value = {
                    "input": "style prefix, akemi homura, bare soles, foot focus",
                    "parameters": {"seed": 222, "n_samples": 1},
                }

                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "run-prompt",
                            "--composer",
                            "agent",
                            "--character",
                            str(character),
                            "--action",
                            str(action),
                            "--style-node",
                            str(style),
                            "--agent-model",
                            "agent-model-v1",
                            "--cache-dir",
                            str(cache_dir),
                            "--config",
                            str(config),
                            "--output-dir",
                            str(output_dir),
                            "--seed",
                            "222",
                            "--nt",
                            "1",
                        ]
                    )

            data = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(data["status"], "ready")
            self.assertFalse(data["dry_run"])
            self.assertTrue(data["prompt_bundle"]["cache"]["cache_hit"])
            self.assertEqual(data["generation_result"]["backend"], "novelai")
            self.assertEqual(len(data["generation_result"]["images"]), 1)
            self.assertEqual(data["render_request"]["meta"]["prompt_cache_key"], data["prompt_bundle"]["cache"]["cache_key"])
```

- [x] **Step 2: 实现后回归验证**

Run:

```powershell
uv run python -m unittest tests.test_cli_prompt.CliPromptTest.test_run_prompt_agent_cache_hit_executes_novelai
```

Expected: 当前实现已通过；原始失败态不再保留，阶段二门禁覆盖该行为。

- [x] **Step 3: 确认 `cmd_run_prompt` 执行逻辑**

`cmd_run_prompt()` 的 ready 分支必须保留：

```python
    if not args.dry_run:
        if not args.config:
            raise ValueError("run-prompt without --dry-run requires --config")
        config = load_config(Path(args.config))
        result["generation_result"] = _execute_render_request(
            config,
            request,
            output_dir=args.output_dir,
            image_format=args.format,
            allow_experimental_backend=False,
        )
```

cache miss 的 `requires_agent` 分支必须在这里之前返回，避免没 prompt 时误联网。

- [x] **Step 4: 运行测试确认通过**

Run:

```powershell
uv run python -m unittest tests.test_cli_prompt.CliPromptTest.test_run_prompt_agent_cache_hit_executes_novelai
```

Expected: PASS。

- [x] **Step 5: Commit（合并提交）**

```powershell
git add src/tags_machine_core/cli.py tests/test_cli_prompt.py
git commit -m "test: execute run-prompt from cached agent bundle"
```

---

### Task 5: 增加 agent 模式的 JSON/文档示例

**Files:**
- Modify: `docs/development_plan_v1.md`
- Modify: `docs/json_api_contract_v1.md`

- [x] **Step 1: 更新 CLI 示例**

在 `docs/development_plan_v1.md` 当前 CLI 示例中加入：

```powershell
uv run python -m tags_machine_core run-prompt --dry-run --composer agent `
  --character examples\nodes\characters\homura `
  --action examples\nodes\actions\foot_closeup `
  --style-node examples\nodes\styles\anime_comfy `
  --agent-model agent-model-v1 `
  --instruction "组合角色和动作，局部镜头不要带入无关角色外观" `
  --cache-dir cache\prompt

uv run python -m tags_machine_core run-prompt --composer agent `
  --character examples\nodes\characters\homura `
  --action examples\nodes\actions\foot_closeup `
  --style-ref 20260412_2 `
  --agent-model agent-model-v1 `
  --cache-dir cache\prompt `
  --prompt-file agent_prompt.txt `
  --config configs\local.example.yaml `
  --output-dir outputs
```

- [x] **Step 2: 更新说明**

在 `run-prompt` 说明下加入：

```markdown
- `run-prompt --composer agent` 是 agent 拼接进入真实生图的业务入口。它要求输入 character/action/background 节点，并使用节点内容 hash、style_ref、instructions、agent_model、scope 等生成 cache key。带 `--prompt` / `--prompt-file` 时，core 认为这是 agent 已完成的完整 prompt，会写入 `PromptBundle` cache 并继续生成；不带完整 prompt 时，只读取 cache，命中则继续生成，未命中则返回 `status: requires_agent` 和 `agent_task`，不会调用 NovelAI。
```

- [x] **Step 3: 更新 JSON API 文档**

在 `docs/json_api_contract_v1.md` 的验收或入口说明中加入：

```markdown
CLI 的 `run-prompt --composer agent` 是真实出图入口；JSON API 中对应的无联网状态入口仍是 `api-resolve-compose-render-plan`。二者必须共用同一套 `AgentComposer` cache key 语义：agent 输出 prompt 不进入 cache key，节点内容、style_ref、instructions、agent_model 和 scope 进入 cache key。
```

- [x] **Step 4: 文档 diff 检查**

Run:

```powershell
git diff -- docs/development_plan_v1.md docs/json_api_contract_v1.md
```

Expected: 只包含 CLI 示例和 agent 模式说明。

- [x] **Step 5: Commit（合并提交）**

```powershell
git add docs/development_plan_v1.md docs/json_api_contract_v1.md
git commit -m "docs: document run-prompt agent mode"
```

---

### Task 6: 阶段 2 回归门禁

**Files:**
- No code files.

- [x] **Step 1: 跑 CLI prompt 测试**

```powershell
uv run python -m unittest tests.test_cli_prompt
```

Expected: PASS。

- [x] **Step 2: 跑 agent composer 测试**

```powershell
uv run python -m unittest tests.test_agent_composer
```

Expected: PASS。

- [x] **Step 3: 跑 JSON API 测试**

```powershell
uv run python -m unittest tests.test_json_api
```

Expected: PASS。

- [x] **Step 4: 跑核心门禁**

```powershell
uv run python -m tags_machine_core verify-core
```

Expected: `result` 为 `pass` 或命令退出码为 0。

- [x] **Step 5: Commit（合并提交）**

如果前面任务已经分别提交，本任务不需要新 commit。若有测试修正：

```powershell
git add src tests docs
git commit -m "test: pass run-prompt agent regression gate"
```

---

### Task 7: 阶段 3 设计落点，新 `run-action` 不复刻旧 formula

**Files:**
- Modify: `docs/development_plan_v1.md`

- [x] **Step 1: 写阶段 3 具体方案**

在阶段 3 下补充：

```markdown
阶段 3 的 `run-action` 是新 composer 入口，不以旧 `formula` 逐字一致为目标。

输入：
- character `meta.yaml`
- action `meta.yaml`
- style ref / style node
- optional background
- seed / size / params

输出：
- `PromptBundle`
- `RenderRequest`
- 可选 `GenerationResult`
- composer evaluation report

规则：
- character 只描述角色事实。
- action 只描述动作事实和 `character_scope`。
- scope 到 character section 的过滤规则由 composer policy 统一维护。
- 与旧 `run_action` 的差异必须记录，但差异本身不代表失败。
```

- [x] **Step 2: 增加后续任务列表**

补充后续实现任务：

```markdown
后续实现任务：
1. 新增 `run-action` CLI，复用 `compose_nodes -> build_novelai_request -> execute_render_request`。
2. 新增 composer evaluation report，记录 included/suppressed sections、旧 prompt 差异和 intentional differences。
3. 至少用普通动作、脚部局部特写、reference style 三个真实 case 评估。
```

- [x] **Step 3: Commit（合并提交）**

```powershell
git add docs/development_plan_v1.md
git commit -m "docs: define new run-action evaluation path"
```

---

### Task 8: 阶段 4 验收报告分层

**Files:**
- Modify: `docs/development_plan_v1.md`

- [x] **Step 1: 写三类验收**

在验收标准中明确三类验收：

```markdown
验收分三类：

1. 兼容验收
   - 输入旧项目最终 prompt / negative。
   - 目标是 NovelAI 参数归一化 diff 为 0 或只有白名单差异。
   - 证明 adapter 和 execution 没退化。

2. Composer 评估
   - 输入 character/action/style。
   - 目标是语义正确、scope 裁剪合理、差异可解释。
   - 不要求和旧 `formula` 逐字一致。

3. 视觉验收
   - 记录旧图、core 图、参数 diff、图片 sha256、尺寸和人工结论。
   - 参数一致但像素不同，优先记录后端非确定性或服务端差异。
```

- [x] **Step 2: 写 case record 目标格式**

加入：

```yaml
case_id: foot_detail_homura_001
acceptance_kind: composer_evaluation
legacy:
  image: legacy/old.png
  params: legacy/old_params.json
core:
  image: core/new.png
  prompt_bundle: core/prompt_bundle.json
  render_request: core/render_request.json
  generation_result: core/generation_result.json
diff:
  params_diff_count: 0
  whitelisted_differences: []
visual:
  result: pending
  notes: ""
intentional_differences:
  - scope: foot_detail
    reason: "过滤 hair/eyes/upper_clothes，避免局部脚部镜头割裂"
```

- [x] **Step 3: Commit（合并提交）**

```powershell
git add docs/development_plan_v1.md
git commit -m "docs: split compatibility and composer acceptance"
```

---

### Task 9: 阶段 5 批量和 UI 边界

**Files:**
- Modify: `docs/development_plan_v1.md`
- Modify: `docs/json_api_contract_v1.md`

- [x] **Step 1: 写批量任务边界**

在阶段 5 下补充：

```markdown
批量任务只编排现有契约：

BatchItem input:
- node refs 或 full prompt
- composer mode
- style ref
- render params
- output policy

BatchItem output:
- PromptBundle
- RenderRequest
- GenerationResult
- acceptance/evaluation report path

批量层不得直接拼 NovelAI payload，也不得直接调用 agent；agent 缺失时记录 `requires_agent` 状态，由外部 worker 补 prompt 后重试。
```

- [x] **Step 2: 写 UI 边界**

在 `docs/json_api_contract_v1.md` 加：

```markdown
未来 UI 只依赖 JSON API：
- 节点浏览和选择读取 node refs。
- prompt 预览读取 `PromptBundle`。
- 参数预览读取 `RenderRequest`。
- 结果页读取 `GenerationResult` 和 acceptance/evaluation report。
- UI 不直接拼 prompt，不直接修改 NovelAI V4 payload。
```

- [x] **Step 3: Commit（合并提交）**

```powershell
git add docs/development_plan_v1.md docs/json_api_contract_v1.md
git commit -m "docs: define batch and UI boundaries"
```

---

## Final Validation

执行完整阶段 2 后运行：

```powershell
uv run python -m unittest tests.test_cli_prompt
uv run python -m unittest tests.test_agent_composer
uv run python -m unittest tests.test_json_api
uv run python -m tags_machine_core verify-core
git diff --check
```

Expected:

- 所有 unittest 通过。
- `verify-core` 退出码为 0。
- `git diff --check` 无 trailing whitespace。
- `run-prompt --composer agent` 的三种状态清晰：
  - 带 prompt：写 cache，生成 `PromptBundle + RenderRequest`，非 dry-run 时真实出图。
  - 不带 prompt 且 cache hit：复用 cached `PromptBundle`，继续生成。
  - 不带 prompt 且 cache miss：返回 `status: requires_agent` 和 `agent_task`，不联网。

## Self-Review

- Spec coverage: 覆盖了 5 个阶段，并把阶段 2 的 `run-prompt` 主链路、agent prompt 回填、cache hit/miss、真实执行和文档更新拆成可执行任务。
- Placeholder scan: 没有使用占位式任务描述；每个代码任务都包含具体测试和实现片段。
- Type consistency: 使用现有 `AgentCompositionRequired`、`PromptCache`、`GenerationService.compose_nodes_with_agent()`、`RenderRequest`、`PromptBundle` 命名；新 CLI 参数和现有节点参数保持一致。
