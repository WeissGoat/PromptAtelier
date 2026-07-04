# Tags Machine Core Five Stage Roadmap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `tags_machine_core` 按五个阶段推进成稳定的新内核：旧项目只作为素材和验收参考，core 负责提示词生成、NovelAI 生图适配、真实出图验收、批量任务和未来 UI 边界。

**Architecture:** `PromptBundle -> RenderRequest -> GenerationResult` 是主链路边界。阶段二把 `run-prompt` 固化为稳定主链路，并让 `AgentComposer` 通过 cache 支持“外部 agent 拼接、core 回填、零 token 复用”；后续 `run-action` 是新 composer 评估入口，不为了逐字还原旧 `formula` 引入硬编码。

**Tech Stack:** Python 3.11, argparse CLI, Pydantic contracts, PyYAML, unittest, uv, NovelAI adapter/client, JSON/YAML artifacts.

---

## 现状和约束

- 当前工作仓库是 `F:\my_project\new\tags_machine_core`。
- 旧仓库 `F:\my_project\new\tags_machine` 必须保持稳定，core 不 import 旧项目运行时代码。
- 旧 `design/` 不迁移，core 通过配置 `legacy.design_root: F:/my_project/new/tags_machine/design` 读取。
- 当前正式真实生图后端只确认 NovelAI；ComfyUI / SD 暂不进入阶段验收。
- `run-prompt` 是完整 prompt 生图主链路。
- `run-prompt --composer agent` 的业务语义按本计划阶段二冻结。
- 旧 `run_action` 对 core 的意义是评估参考，不是逐字还原目标。

## 文件结构

- Modify: `src/tags_machine_core/cli.py`
  - 阶段二：维护 `run-prompt --composer {full,agent}`。
  - 阶段三：新增 `run-action` CLI，复用 `compose_nodes -> build_novelai_request -> execute_render_request`。
  - 阶段四：挂接对比集归档和验收命令，不 import 旧项目代码。

- Modify: `src/tags_machine_core/composers/agent.py`
  - 维护 `AgentCompositionTask`、`AgentCompositionResult`、cache key 语义。
  - 保证 agent 输出 prompt 不进入 cache key。

- Modify: `src/tags_machine_core/composers/script.py`
  - 阶段三：维护 character/action 节点确定性拼接。
  - 将 `character_scope -> section include/suppress` 规则放在 composer policy，不写进 character yaml。

- Modify: `src/tags_machine_core/renderers/novelai.py`
  - 维护 NovelAI V4/V4.5 payload、reference/vibe 参数、旧 style 兼容。
  - 兼容旧项目行为只能放 adapter/compat 路径，不能反向污染 composer。

- Modify: `src/tags_machine_core/execution.py`
  - 真实执行 `RenderRequest`，保存图片，产出 `GenerationResult`。
  - 继续保证 `GenerationResult.images[].path`、`filename`、`png_info` 一致。

- Modify: `src/tags_machine_core/verification/acceptance.py`
  - 阶段四：验证对比集、最小 case 集、真实旧项目 evidence、visual result 字段。

- Modify: `src/tags_machine_core/verification/render_params.py`
  - 阶段四：归一化并比较 NovelAI 参数，包括 reference/vibe 数组。

- Modify: `src/tags_machine_core/verification/compare_report.py`
  - 阶段四：输出对比报告，记录参数 diff、图片 hash、尺寸、人工视觉结论字段。

- Modify: `src/tags_machine_core/services/json_api.py`
  - 阶段五：补齐批量任务和 UI 所需 JSON 状态入口。

- Modify: `src/tags_machine_core/services/json_api_models.py`
  - 阶段五：定义 batch item、batch result、UI 预览响应模型。

- Modify: `docs/development_plan_v1.md`
  - 总体架构文档，保持中文，记录模块职责、输入输出、阶段验收标准。

- Modify: `docs/json_api_contract_v1.md`
  - JSON API 契约，记录未来 UI/worker 能依赖的字段和状态分支。

- Test: `tests/test_cli_prompt.py`
  - 阶段二 `run-prompt --composer agent` 回归测试。

- Test: `tests/test_agent_composer.py`
  - AgentComposer task/cache/result 测试。

- Test: `tests/test_script_composer.py`
  - 阶段三新 composer policy 测试。

- Test: `tests/test_verification.py`
  - 阶段四对比集、参数 diff、PNG 参数 evidence 测试。

- Test: `tests/test_json_api.py`
  - 阶段五 JSON API 状态分支和批量边界测试。

---

## 阶段一：边界和兼容策略冻结

目标：固定 core 与旧项目、提示词生成层与生图层、adapter 与 execution 的边界。

通过线：
- core/test 不 import 旧 `tags_machine` 运行时代码。
- `PromptBundle` 不包含 NovelAI / ComfyUI / SD 专属字段。
- `RenderRequest` 是 adapter 输出，不执行网络。
- `GenerationResult` 是真实执行后的证据载体。
- `legacy.design_root` 是读取旧素材库的唯一正式路径。

### Task 1: 固化项目边界文档

**Files:**
- Modify: `docs/development_plan_v1.md`

- [ ] **Step 1: 更新项目边界说明**

在 `## 项目边界` 中确认以下内容存在：

```markdown
- 不在旧 `tags_machine` 里继续追加新架构代码。
- 不从 core import 旧项目的 `formula.py`、`tags_machine.py`、`blackboard.py`。
- 旧 `design/` 只作为数据源读取，通过配置里的 `legacy.design_root` 指向。
- 旧脚本可以提供旧项目基准结果，但不是运行时依赖。
- NovelAI 兼容行为放在 adapter/compat 路径，composer 不为了旧 `formula` 逐字等价引入 hardcode。
```

- [ ] **Step 2: 验证 import 边界**

Run:

```powershell
uv run python -m unittest tests.test_project_boundaries
```

Expected: PASS。

- [ ] **Step 3: Commit**

```powershell
git add docs/development_plan_v1.md tests/test_project_boundaries.py
git commit -m "docs: freeze core project boundaries"
```

### Task 2: 固化三层数据契约

**Files:**
- Modify: `docs/development_plan_v1.md`
- Modify: `docs/json_api_contract_v1.md`
- Test: `tests/test_contracts.py`

- [ ] **Step 1: 在文档里明确三层契约**

写入或确认以下定义：

```markdown
PromptBundle:
- 提示词生成模块输出。
- 包含 prompt.positive、prompt.negative、meta.character_ref、meta.action_ref、meta.style_ref、meta.composition、cache。
- 不包含 backend、params、style_payload、v4_prompt、reference_image_multiple、workflow_json。

RenderRequest:
- 生图适配层输出。
- 包含 backend、prompt、negative_prompt、model、seed、size、params、style_payload、meta。
- 可以序列化用于 dry-run、diff、worker 队列。

GenerationResult:
- 真实生图执行结果。
- 包含 backend、images、request_body、png_info、cache_hit、created_at。
- 对比集归档时必须保证 images[].path、images[].filename 和 png_info.images 一致。
```

- [ ] **Step 2: 补契约测试**

在 `tests/test_contracts.py` 增加或确认测试：

```python
def test_prompt_bundle_rejects_backend_specific_fields():
    bundle = PromptBundle.model_validate(
        {
            "prompt": {"positive": "akemi homura", "negative": ""},
            "meta": {"composer_type": "script", "composer_version": "v1"},
        }
    )
    payload = bundle.model_dump(mode="json")
    assert "backend" not in payload
    assert "params" not in payload
    assert "style_payload" not in payload
```

- [ ] **Step 3: 运行契约测试**

Run:

```powershell
uv run python -m unittest tests.test_contracts
```

Expected: PASS。

- [ ] **Step 4: Commit**

```powershell
git add docs/development_plan_v1.md docs/json_api_contract_v1.md tests/test_contracts.py
git commit -m "test: lock prompt and render contracts"
```

---

## 阶段二：`run-prompt` 主链路和 AgentComposer

目标：`run-prompt` 成为稳定真实生图入口；`run-prompt --composer agent` 支持外部 agent 拼接结果回填、缓存复用、cache miss 状态返回。

核心语义：
- `--composer full`：默认模式。必须携带 `--prompt` 或 `--prompt-file`，认为输入已经是完整角色+动作 prompt。core 只叠加 style、quality、negative、NovelAI 参数和 reference/vibe。
- `--composer agent` 且携带 `--prompt` / `--prompt-file`：认为外部 agent 已完成拼接，把 prompt 和 accompanying `--negative` 作为 agent 输出写入 `PromptBundle` cache，然后继续生成。
- `--composer agent` 且不携带 prompt：根据 character/action/background/style/instruction/model/scope 等输入读取 cache。命中则继续生成，未命中返回 `status: requires_agent` 和 `agent_task`，不调用 NovelAI。
- agent 输出 prompt 不进入 cache key。
- CLI 回填模式下随 prompt 传入的 `--negative` 也视为 agent 输出，不要求下一次 cache hit 重复传入。

通过线：
- cache miss 不联网。
- prompt 回填写 cache。
- cache hit 能继续生成 `RenderRequest`，非 dry-run 时能走 NovelAI execution。
- JSON API 的无联网状态入口仍是 `api-resolve-compose-render-plan`。

### Task 3: 固化 `run-prompt --composer agent` CLI 参数

**Files:**
- Modify: `src/tags_machine_core/cli.py`
- Test: `tests/test_cli_prompt.py`

- [x] **Step 1: 增加 CLI 参数**

`run-prompt` 支持：

```text
--composer {full,agent}
--character
--action
--background
--extra-prompt
--character-scope
--body-scope
--instruction
--agent-model
--agent-result
--cache-dir
```

- [x] **Step 2: 验证 full 模式仍要求完整 prompt**

测试目标：

```python
with self.assertRaises(SystemExit):
    main(["run-prompt", "--dry-run"])
```

或者通过现有 CLI 错误分支验证 `--composer full` 下没有 prompt 会失败。

- [x] **Step 3: 验证 agent 模式允许无 prompt**

Run:

```powershell
uv run python -m unittest tests.test_cli_prompt.CliPromptTest.test_run_prompt_agent_cache_miss_returns_agent_task_without_render_request
```

Expected: PASS。

- [ ] **Step 4: Commit**

```powershell
git add src/tags_machine_core/cli.py tests/test_cli_prompt.py
git commit -m "feat: add run-prompt agent mode"
```

### Task 4: 固化 AgentComposer cache key 语义

**Files:**
- Modify: `src/tags_machine_core/composers/agent.py`
- Test: `tests/test_agent_composer.py`
- Test: `tests/test_cli_prompt.py`

- [x] **Step 1: cache key 输入清单**

cache key 必须包含：

```text
composer_version
character/action/background 的 id、kind、content_hash
extra_prompt
task negative
style_ref
character_scope
instructions
agent_model
```

cache key 不得包含：

```text
agent result positive
agent result negative
agent notes
```

- [x] **Step 2: 验证 prompt 回填不改变 cache key**

Run:

```powershell
uv run python -m unittest tests.test_cli_prompt.CliPromptTest.test_run_prompt_agent_prompt_writes_cache_and_cache_hit_reuses_bundle
```

Expected: PASS。

- [x] **Step 3: 验证 agent composer 单元测试**

Run:

```powershell
uv run python -m unittest tests.test_agent_composer
```

Expected: PASS。

- [ ] **Step 4: Commit**

```powershell
git add src/tags_machine_core/composers/agent.py tests/test_agent_composer.py tests/test_cli_prompt.py
git commit -m "test: lock agent composer cache keys"
```

### Task 5: 固化三种 `run-prompt --composer agent` 状态

**Files:**
- Modify: `src/tags_machine_core/cli.py`
- Test: `tests/test_cli_prompt.py`

- [x] **Step 1: cache miss 返回 agent task**

期望输出：

```json
{
  "schema": "tags-machine-core.run-prompt-result/v1",
  "status": "requires_agent",
  "dry_run": true,
  "agent_task": {}
}
```

不得包含：

```json
{
  "prompt_bundle": null,
  "render_request": null,
  "generation_result": null
}
```

- [x] **Step 2: prompt 回填返回 ready**

期望输出：

```json
{
  "schema": "tags-machine-core.run-prompt-result/v1",
  "status": "ready",
  "dry_run": true,
  "prompt_bundle": {},
  "render_request": {}
}
```

- [x] **Step 3: cache hit 可真实执行**

Run:

```powershell
uv run python -m unittest tests.test_cli_prompt.CliPromptTest.test_run_prompt_agent_cache_hit_executes_novelai
```

Expected: PASS。

- [ ] **Step 4: Commit**

```powershell
git add src/tags_machine_core/cli.py tests/test_cli_prompt.py
git commit -m "test: cover run-prompt agent states"
```

### Task 6: 固化阶段二文档和示例

**Files:**
- Modify: `docs/development_plan_v1.md`
- Modify: `docs/json_api_contract_v1.md`

- [x] **Step 1: 写 CLI 示例**

`docs/development_plan_v1.md` 应包含：

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

- [x] **Step 2: 写 JSON API 对应关系**

`docs/json_api_contract_v1.md` 应明确：

```markdown
CLI 的 `run-prompt --composer agent` 是 agent prompt 进入真实 NovelAI 生图的业务入口；JSON API 中对应的无联网状态入口仍是 `api-resolve-compose-render-plan`。二者必须共用同一套 `AgentComposer` cache key 语义。
```

- [ ] **Step 3: 文档 diff 检查**

Run:

```powershell
git diff -- docs/development_plan_v1.md docs/json_api_contract_v1.md
```

Expected: 只包含阶段二说明和 CLI/API 示例。

- [ ] **Step 4: Commit**

```powershell
git add docs/development_plan_v1.md docs/json_api_contract_v1.md
git commit -m "docs: document run-prompt agent workflow"
```

### Task 7: 阶段二回归门禁

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

Expected: 退出码为 0，输出 `result: pass`。

- [ ] **Step 5: Commit**

```powershell
git add src/tags_machine_core/cli.py src/tags_machine_core/composers/agent.py tests/test_cli_prompt.py tests/test_agent_composer.py docs/development_plan_v1.md docs/json_api_contract_v1.md
git commit -m "feat: stabilize run-prompt agent mainline"
```

---

## 阶段三：新 `run-action` 和节点 composer 评估链路

目标：建立 core 新节点 composer 路径，输入 character/action/style，输出 `PromptBundle`、`RenderRequest`、可选 `GenerationResult` 和 composer evaluation report。

重要约束：
- `run-action` 是新 composer 入口，不复刻旧 `formula`。
- character 只描述角色事实，不写通用过滤规则。
- action 只描述动作事实和 `character_scope`。
- `character_scope -> included/suppressed sections` 由 composer policy 统一维护。
- 和旧 `run_action` 的差异必须记录，但差异本身不是失败。

通过线：
- 普通动作保留角色核心外观。
- `foot_detail` 过滤 hair / eyes / upper_clothes 等不相关 section。
- `hand_detail` 使用手部相关 section，不误带 feet。
- complex character 在默认 scope 下不误删 hair / eyes / upper_clothes。

### Task 8: 为脚本 composer policy 写失败测试

**Files:**
- Modify: `tests/test_script_composer.py`

- [ ] **Step 1: 添加 foot detail 测试**

新增测试：

```python
def test_foot_detail_suppresses_unrelated_character_sections():
    character = NodeDocument.model_validate(
        {
            "kind": "character",
            "id": "homura",
            "tags": {
                "identity": ["akemi homura"],
                "hair": ["long black hair"],
                "eyes": ["purple eyes"],
                "upper_clothes": ["school uniform"],
                "feet": ["bare soles"],
            },
        }
    )
    action = NodeDocument.model_validate(
        {
            "kind": "action",
            "id": "foot_detail",
            "character_scope": "foot_detail",
            "tags": {"action": ["foot focus", "soles close-up"]},
        }
    )

    bundle = ScriptComposer().compose_nodes(character=character, action=action)

    assert "bare soles" in bundle.prompt.positive
    assert "long black hair" not in bundle.prompt.positive
    assert "purple eyes" not in bundle.prompt.positive
    assert "school uniform" not in bundle.prompt.positive
    assert bundle.meta.composition.character_scope == "foot_detail"
    assert "feet" in bundle.meta.composition.included_character_sections
    assert "hair" in bundle.meta.composition.suppressed_character_sections
    assert "eyes" in bundle.meta.composition.suppressed_character_sections
    assert "upper_clothes" in bundle.meta.composition.suppressed_character_sections
```

- [ ] **Step 2: 运行测试确认失败或已有行为通过**

Run:

```powershell
uv run python -m unittest tests.test_script_composer
```

Expected: 如果当前 policy 未覆盖，FAIL；如果已覆盖，PASS。

- [ ] **Step 3: Commit 测试**

如果测试先失败：

```powershell
git add tests/test_script_composer.py
git commit -m "test: define foot detail composer policy"
```

### Task 9: 实现 composer section policy

**Files:**
- Modify: `src/tags_machine_core/composers/script.py`
- Test: `tests/test_script_composer.py`

- [ ] **Step 1: 增加 scope policy 常量**

在 `script.py` 增加：

```python
SCOPE_SECTION_POLICY = {
    "foot_detail": {
        "include": {"identity", "copyright", "body", "feet", "legwear"},
        "suppress": {"hair", "eyes", "headwear", "upper_clothes"},
    },
    "hand_detail": {
        "include": {"identity", "copyright", "body", "hands", "sleeves", "accessories"},
        "suppress": {"feet", "legwear"},
    },
}
```

- [ ] **Step 2: 应用 section policy**

在 character tags 拼接前，按 `character_scope` 过滤 section：

```python
policy = SCOPE_SECTION_POLICY.get(character_scope or "")
if policy:
    include = policy["include"]
    suppress = policy["suppress"]
    selected_sections = [
        section
        for section in character_sections
        if section in include and section not in suppress
    ]
    suppressed_sections = [
        section
        for section in character_sections
        if section in suppress or section not in include
    ]
else:
    selected_sections = list(character_sections)
    suppressed_sections = []
```

- [ ] **Step 3: 写入 PromptBundle meta**

保证 `PromptCompositionMeta` 填写：

```python
PromptCompositionMeta(
    character_scope=character_scope,
    included_character_sections=selected_sections,
    suppressed_character_sections=suppressed_sections,
)
```

- [ ] **Step 4: 运行脚本 composer 测试**

Run:

```powershell
uv run python -m unittest tests.test_script_composer
```

Expected: PASS。

- [ ] **Step 5: Commit**

```powershell
git add src/tags_machine_core/composers/script.py tests/test_script_composer.py
git commit -m "feat: apply character scope composer policy"
```

### Task 10: 新增 `run-action` CLI

**Files:**
- Modify: `src/tags_machine_core/cli.py`
- Test: `tests/test_cli_prompt.py`

- [ ] **Step 1: 写 CLI dry-run 测试**

在 `tests/test_cli_prompt.py` 新增：

```python
def test_run_action_dry_run_builds_prompt_bundle_and_render_request(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        character, action = self._write_agent_nodes(root)
        style = _write_style_node(root)

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = main(
                [
                    "run-action",
                    "--dry-run",
                    "--full",
                    "--character",
                    str(character),
                    "--action",
                    str(action),
                    "--style-node",
                    str(style),
                    "--seed",
                    "123",
                    "--nt",
                    "1",
                ]
            )

        data = json.loads(stdout.getvalue())
        assert exit_code == 0
        assert data["schema"] == "tags-machine-core.run-action-result/v1"
        assert data["status"] == "ready"
        assert data["prompt_bundle"]["meta"]["composer_type"] == "script"
        assert data["render_request"]["backend"] == "novelai"
        assert data["render_request"]["seed"] == 123
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
uv run python -m unittest tests.test_cli_prompt.CliPromptTest.test_run_action_dry_run_builds_prompt_bundle_and_render_request
```

Expected: FAIL，`run-action` 命令不存在。

- [ ] **Step 3: 实现 `cmd_run_action`**

在 `cli.py` 增加：

```python
def cmd_run_action(args) -> int:
    service = GenerationService()
    style_ref, style = _load_novelai_style_for_prompt(args)
    character, action, background = _read_node_inputs(args)
    bundle = service.compose_nodes(
        character=character,
        action=action,
        background=background,
        extra_prompt=args.extra_prompt or "",
        negative=args.negative or "",
        style_ref=style_ref,
        character_scope=args.character_scope or args.body_scope,
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
    result = {
        "schema": "tags-machine-core.run-action-result/v1",
        "status": "ready",
        "dry_run": args.dry_run,
        "prompt_bundle": bundle,
        "render_request": request,
    }
    if not args.dry_run:
        if not args.config:
            raise ValueError("run-action without --dry-run requires --config")
        config = load_config(Path(args.config))
        result["generation_result"] = _execute_render_request(
            config,
            request,
            output_dir=args.output_dir,
            image_format=args.format,
            allow_experimental_backend=False,
        )
    print_json(result, full=args.full)
    return 0
```

- [ ] **Step 4: 注册 parser**

新增 parser：

```python
run_action = subparsers.add_parser(
    "run-action",
    parents=[output_parent],
    help="Compose character/action nodes and run NovelAI",
)
_add_node_compose_arguments(run_action)
_add_novelai_render_arguments(run_action)
run_action.set_defaults(func=cmd_run_action)
```

- [ ] **Step 5: 运行测试确认通过**

Run:

```powershell
uv run python -m unittest tests.test_cli_prompt.CliPromptTest.test_run_action_dry_run_builds_prompt_bundle_and_render_request
```

Expected: PASS。

- [ ] **Step 6: Commit**

```powershell
git add src/tags_machine_core/cli.py tests/test_cli_prompt.py
git commit -m "feat: add run-action composer entrypoint"
```

### Task 11: 增加 composer evaluation report

**Files:**
- Create: `src/tags_machine_core/verification/composer_eval.py`
- Modify: `src/tags_machine_core/cli.py`
- Test: `tests/test_verification.py`

- [ ] **Step 1: 写报告生成函数测试**

在 `tests/test_verification.py` 新增：

```python
def test_build_composer_evaluation_report_records_scope_sections():
    bundle = PromptBundle.model_validate(
        {
            "prompt": {"positive": "akemi homura, bare soles", "negative": ""},
            "meta": {
                "composer_type": "script",
                "composer_version": "v1",
                "composition": {
                    "character_scope": "foot_detail",
                    "included_character_sections": ["identity", "feet"],
                    "suppressed_character_sections": ["hair", "eyes", "upper_clothes"],
                },
            },
        }
    )

    report = build_composer_evaluation_report(
        case_id="foot_detail_homura_001",
        prompt_bundle=bundle,
        legacy_prompt="akemi homura, long black hair, purple eyes, school uniform, bare soles",
    )

    assert report["schema"] == "tags-machine-core.composer-evaluation/v1"
    assert report["case_id"] == "foot_detail_homura_001"
    assert report["composition"]["character_scope"] == "foot_detail"
    assert "hair" in report["composition"]["suppressed_character_sections"]
    assert report["intentional_differences"]
```

- [ ] **Step 2: 实现 `composer_eval.py`**

创建文件：

```python
from __future__ import annotations

from typing import Any

from tags_machine_core.contracts import PromptBundle


def build_composer_evaluation_report(
    *,
    case_id: str,
    prompt_bundle: PromptBundle,
    legacy_prompt: str | None = None,
) -> dict[str, Any]:
    composition = prompt_bundle.meta.composition
    suppressed = composition.suppressed_character_sections
    intentional = []
    if composition.character_scope in {"foot_detail", "hand_detail"} and suppressed:
        intentional.append(
            {
                "scope": composition.character_scope,
                "reason": "按统一 composer policy 过滤局部镜头无关角色 section",
                "suppressed_character_sections": suppressed,
            }
        )
    return {
        "schema": "tags-machine-core.composer-evaluation/v1",
        "case_id": case_id,
        "prompt": prompt_bundle.prompt.model_dump(mode="json"),
        "composition": composition.model_dump(mode="json"),
        "legacy": {"prompt": legacy_prompt or ""},
        "intentional_differences": intentional,
        "visual": {"result": "pending", "notes": ""},
    }
```

- [ ] **Step 3: 运行验证测试**

Run:

```powershell
uv run python -m unittest tests.test_verification
```

Expected: PASS。

- [ ] **Step 4: Commit**

```powershell
git add src/tags_machine_core/verification/composer_eval.py tests/test_verification.py
git commit -m "feat: add composer evaluation reports"
```

---

## 阶段四：NovelAI 真实对比集和验收闭环

目标：把旧项目真实出图结果和 core 真实出图结果归档成对比集，覆盖图片视觉对比和生成图片参数对比。

对比集结构：

```text
acceptance_compare/<case_id>/
  legacy/
    old.png
    old_params.json
    old_request.json
  core/
    new.png
    prompt_bundle.json
    render_request.json
    generation_result.json
  compare_report.json
  record.yaml
```

通过线：
- 参数 diff 为 0，或差异有明确白名单说明。
- 旧图和 core 图都能读取 PNG 参数或明确记录读取错误。
- core `GenerationResult.request_body` 与 core 图片 PNG 参数一致。
- 视觉人工检查字段存在，并最终可以记录 `visual.result: pass`。
- reference/vibe 相关字段必须比较数组长度、图片摘要、strength、information_extracted。

### Task 12: 扩展参数归一化 diff

**Files:**
- Modify: `src/tags_machine_core/verification/render_params.py`
- Test: `tests/test_verification.py`

- [ ] **Step 1: 写 reference/vibe diff 测试**

新增测试：

```python
def test_normalized_render_params_include_reference_arrays():
    params = normalize_render_params(
        {
            "parameters": {
                "reference_image_multiple": ["base64-a"],
                "reference_strength_multiple": [0.6],
                "reference_information_extracted_multiple": [0.8],
                "director_reference_images": ["base64-b"],
            }
        }
    )

    assert params["reference_image_multiple_count"] == 1
    assert params["reference_strength_multiple"] == [0.6]
    assert params["reference_information_extracted_multiple"] == [0.8]
    assert params["director_reference_images_count"] == 1
```

- [ ] **Step 2: 实现归一化字段**

在 `render_params.py` 中对 base64 数组输出摘要字段：

```python
def _summarize_base64_array(values: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "index": index,
            "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
            "length": len(value),
        }
        for index, value in enumerate(values)
    ]
```

并把 `reference_image_multiple`、`director_reference_images` 归一化为 count + hashes。

- [ ] **Step 3: 运行验证测试**

Run:

```powershell
uv run python -m unittest tests.test_verification
```

Expected: PASS。

- [ ] **Step 4: Commit**

```powershell
git add src/tags_machine_core/verification/render_params.py tests/test_verification.py
git commit -m "test: compare reference image render params"
```

### Task 13: 对比报告补视觉字段

**Files:**
- Modify: `src/tags_machine_core/verification/compare_report.py`
- Test: `tests/test_verification.py`

- [ ] **Step 1: 写报告字段测试**

新增测试：

```python
def test_compare_report_includes_visual_review_fields(tmp_path):
    old_image = tmp_path / "old.png"
    core_image = tmp_path / "core.png"
    old_image.write_bytes(b"old")
    core_image.write_bytes(b"core")

    report = build_compare_report(
        old_image=old_image,
        core_image=core_image,
        params_diff={"normalized_equal": True, "diffs": []},
    )

    assert report["visual"]["result"] == "pending"
    assert report["visual"]["notes"] == ""
    assert report["images"]["legacy"]["sha256"]
    assert report["images"]["core"]["sha256"]
```

- [ ] **Step 2: 实现 visual 字段**

报告中加入：

```python
"visual": {
    "result": "pending",
    "notes": "",
    "checked_at": None,
}
```

- [ ] **Step 3: 运行验证测试**

Run:

```powershell
uv run python -m unittest tests.test_verification
```

Expected: PASS。

- [ ] **Step 4: Commit**

```powershell
git add src/tags_machine_core/verification/compare_report.py tests/test_verification.py
git commit -m "feat: include visual review in compare reports"
```

### Task 14: 跑真实 NovelAI 对比 case

**Files:**
- No source file required unless发现真实问题。
- Output: `acceptance_compare/<case_id>/`

- [ ] **Step 1: 选择 case**

至少选择：

```text
run_prompt_default_001
run_action_final_prompt_001
foot_detail_001
reference_style_001
```

- [ ] **Step 2: 旧项目生成基准图**

在旧项目里只运行已有功能，不落 core 架构文件。产出旧图和旧 PNG 参数。

Expected evidence:

```text
legacy/old.png
legacy/old_params.json
legacy/old_request.json
```

- [ ] **Step 3: core 用同 prompt 同参数出图**

Run:

```powershell
uv run python -m tags_machine_core run-prompt `
  --prompt-file acceptance_compare\<case_id>\legacy\old_prompt.txt `
  --style-ref <style_ref> `
  --seed <seed> `
  --width <width> `
  --height <height> `
  --params-json acceptance_compare\<case_id>\legacy\old_params_for_core.json `
  --config configs\local.example.yaml `
  --output-dir acceptance_compare\<case_id>\core
```

Expected: 输出 `GenerationResult`，并保存 core 图。

- [ ] **Step 4: 生成对比报告**

Run:

```powershell
uv run python -m tags_machine_core compare-render-params `
  acceptance_compare\<case_id>\legacy\old.png `
  acceptance_compare\<case_id>\core\generation_result.json `
  --show-normalized
```

Expected: 参数 diff 为 0，或只有白名单差异。

- [ ] **Step 5: 人工视觉记录**

更新 `record.yaml`：

```yaml
visual:
  result: pass
  notes: "主体、动作、镜头、画风一致；像素差异记录为 NovelAI 服务端非确定性。"
```

- [ ] **Step 6: Commit 对比集索引**

只提交轻量 record 和报告；真实图片是否提交按仓库策略决定。

```powershell
git add acceptance_compare\<case_id>\record.yaml acceptance_compare\<case_id>\compare_report.json
git commit -m "test: archive novelai acceptance case <case_id>"
```

---

## 阶段五：批量任务和未来 UI 边界

目标：把未来批量跑图和前端 UI 都约束在 JSON API 上，不让 UI 或批量层直接拼 NovelAI payload，不直接调用 agent。

通过线：
- BatchItem input 只描述 node refs/full prompt、composer mode、style ref、render params、output policy。
- BatchItem output 只引用 `PromptBundle`、`RenderRequest`、`GenerationResult`、acceptance/evaluation report path。
- agent 缺失时返回 `requires_agent`，由外部 worker 补 prompt 后重试。
- UI 只读取节点、预览 prompt、预览参数、查看结果，不理解 NovelAI V4 payload 细节。

### Task 15: 定义 batch JSON 模型

**Files:**
- Modify: `src/tags_machine_core/services/json_api_models.py`
- Test: `tests/test_json_api.py`

- [ ] **Step 1: 写 batch 模型测试**

新增测试：

```python
def test_batch_item_model_accepts_full_prompt_input():
    item = BatchItemRequest.model_validate(
        {
            "id": "case_001",
            "compose": {
                "composer": "full",
                "prompt": "akemi homura, foot focus",
                "negative": "bad anatomy",
            },
            "render": {
                "backend": "novelai",
                "style": "examples/nodes/styles/anime_comfy",
                "seed": 123,
            },
            "output": {"dir": "outputs/case_001"},
        }
    )

    assert item.id == "case_001"
    assert item.compose.composer == "full"
```

- [ ] **Step 2: 实现 Pydantic 模型**

在 `json_api_models.py` 增加：

```python
class BatchOutputPolicy(BaseModel):
    dir: str
    archive_acceptance: bool = False


class BatchItemRequest(BaseModel):
    id: str
    compose: ComposeRequest
    render: RenderPlanRequest
    output: BatchOutputPolicy


class BatchItemResult(BaseModel):
    id: str
    status: Literal["ready", "requires_agent", "failed"]
    prompt_bundle: dict[str, Any] | None = None
    render_request: dict[str, Any] | None = None
    generation_result: dict[str, Any] | None = None
    agent_task: dict[str, Any] | None = None
    report_path: str | None = None
    error: str | None = None
```

- [ ] **Step 3: 运行 JSON API 测试**

Run:

```powershell
uv run python -m unittest tests.test_json_api
```

Expected: PASS。

- [ ] **Step 4: Commit**

```powershell
git add src/tags_machine_core/services/json_api_models.py tests/test_json_api.py
git commit -m "feat: define batch json contracts"
```

### Task 16: 增加 batch resolve API

**Files:**
- Modify: `src/tags_machine_core/services/json_api.py`
- Modify: `src/tags_machine_core/cli.py`
- Test: `tests/test_json_api.py`

- [ ] **Step 1: 写 requires_agent batch 测试**

新增测试：

```python
def test_api_resolve_batch_item_returns_requires_agent():
    api = GenerationJsonApi()
    response = api.resolve_batch_item(
        {
            "id": "foot_detail_001",
            "compose": {
                "composer": "agent",
                "nodes": {
                    "character": "examples/nodes/characters/homura",
                    "action": "examples/nodes/actions/foot_closeup",
                },
                "agent": {"model": "agent-model-v1"},
                "cache": {"cache_dir": "cache/test-missing"},
            },
            "render": {
                "backend": "novelai",
                "style": "examples/nodes/styles/anime_comfy",
            },
            "output": {"dir": "outputs/foot_detail_001"},
        }
    )

    assert response["status"] == "requires_agent"
    assert response["agent_task"]["schema"] == "tags-machine-core.agent-composition-task/v1"
```

- [ ] **Step 2: 实现 service 方法**

在 `GenerationJsonApi` 增加：

```python
def resolve_batch_item(self, request: Mapping[str, Any]) -> dict[str, Any]:
    item = BatchItemRequest.model_validate(request)
    resolution = self.resolve_compose_render_plan(
        {
            "compose": item.compose.model_dump(mode="json", exclude_none=True),
            "render": item.render.model_dump(mode="json", exclude_none=True),
        }
    )
    if resolution["status"] == "requires_agent":
        return {
            "schema": "tags-machine-core.batch-item-result/v1",
            "id": item.id,
            "status": "requires_agent",
            "agent_task": resolution["agent_task"],
        }
    return {
        "schema": "tags-machine-core.batch-item-result/v1",
        "id": item.id,
        "status": "ready",
        "prompt_bundle": resolution["prompt_bundle"],
        "render_request": resolution["render_request"],
    }
```

- [ ] **Step 3: 注册 CLI**

新增：

```text
api-resolve-batch-item <request.json> --output <result.json>
```

- [ ] **Step 4: 运行 JSON API 测试**

Run:

```powershell
uv run python -m unittest tests.test_json_api
```

Expected: PASS。

- [ ] **Step 5: Commit**

```powershell
git add src/tags_machine_core/services/json_api.py src/tags_machine_core/cli.py tests/test_json_api.py
git commit -m "feat: resolve batch items through json api"
```

### Task 17: 文档化 UI 边界

**Files:**
- Modify: `docs/json_api_contract_v1.md`
- Modify: `docs/development_plan_v1.md`

- [ ] **Step 1: 写 UI 职责**

加入：

```markdown
未来 UI 只依赖 JSON API：
- 节点浏览和选择读取 node refs。
- prompt 预览读取 `PromptBundle`。
- 参数预览读取 `RenderRequest`。
- 结果页读取 `GenerationResult` 和 acceptance/evaluation report。
- UI 不直接拼 prompt，不直接修改 NovelAI V4 payload。
```

- [ ] **Step 2: 写批量职责**

加入：

```markdown
批量层只编排 JSON 契约，不直接调用 agent，不直接拼 NovelAI payload。agent 缺失时记录 `requires_agent`，由外部 worker 补 prompt 后重试。
```

- [ ] **Step 3: 文档检查**

Run:

```powershell
git diff -- docs/json_api_contract_v1.md docs/development_plan_v1.md
```

Expected: 只包含 batch/UI 边界说明。

- [ ] **Step 4: Commit**

```powershell
git add docs/json_api_contract_v1.md docs/development_plan_v1.md
git commit -m "docs: define batch and ui boundaries"
```

---

## 最终验证

每个阶段结束后运行：

```powershell
uv run python -m unittest tests.test_cli_prompt
uv run python -m unittest tests.test_agent_composer
uv run python -m unittest tests.test_script_composer
uv run python -m unittest tests.test_json_api
uv run python -m unittest tests.test_verification
uv run python -m tags_machine_core verify-core
git diff --check
```

Expected:

- 所有 unittest 通过。
- `verify-core` 退出码为 0。
- `git diff --check` 无 trailing whitespace。
- `run-prompt --composer agent` 三种状态稳定。
- `run-action` 输出 `PromptBundle + RenderRequest`，不复刻旧 `formula` hardcode。
- NovelAI 对比集包含图片视觉和参数 diff 两类证据。

## 自检

- Spec coverage: 覆盖五个阶段，并把阶段二按最新讨论明确为 `run-prompt` 主链路、AgentComposer cache miss/cache hit/prompt 回填流程。
- Red-flag scan: 没有使用占位式任务描述；每个任务都有明确文件、步骤、命令和期望。
- Type consistency: 统一使用 `PromptBundle`、`RenderRequest`、`GenerationResult`、`AgentCompositionTask`、`AgentCompositionResult`、`PromptCache`、`GenerationService`。
- Boundary consistency: NovelAI 兼容放 adapter/execution；新 composer 不为了旧 `formula` 逐字一致引入 hardcode。
