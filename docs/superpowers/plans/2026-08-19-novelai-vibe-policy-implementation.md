# NovelAI Vibe Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变基础 artist prompt 和 AgentComposer 行为的前提下，通过现有 `prompt_policy.rules` 配置让 NovelAI Renderer 替换 vibe/reference 图片及其参数。

**Architecture:** 扩展现有 Policy 注册机制，使 prompt rule 与 renderer rule 共用配置和模板，但分别由各自 Pipeline 执行。`NovelAIRenderPolicyPipeline` 在基础 `RenderRequest` 构建完成后运行，只白名单覆盖 NovelAI reference/vibe 字段；artist source 和 image source 通过独立 resolver 解析，并把摘要写入请求和 PNG 元数据。

**Tech Stack:** Python 3.10+、Pydantic、PyYAML、现有 `GenerationService`、NovelAI Renderer/Client、unittest/pytest、现有 Mock Client 和真实 NovelAI 配置。

## 当前实施状态（2026-08-19）

已完成：

- Registry 已支持 `prompt` / `renderer` scope 和 NovelAI backend 筛选；原有 PromptPolicyPipeline 仍只执行 prompt rules。
- `NovelAIRenderPolicyPipeline` 已接入 `NovelAIRenderAdapter`，`novelai_vibe` 可从 artist 或本地图片替换三个 NovelAI reference 字段。
- `GenerationService`、CLI、Batch、JSON API、Web 已传递同一份 Policy 配置和路径上下文。
- AgentComposer 仍绕过 PromptPolicyPipeline；默认 `agent: false` 时也不执行该 Renderer Policy。
- PNG Core metadata 已加入不含 base64 的 `novelai_render_policy` 摘要。
- 已增加 artist/image 配置示例和业务级 Mock 集成验收。

验证结果：

- `47 passed`：NovelAI renderer policy、GenerationService、Batch mock、PNG metadata、CLI/Web 回归集成测试。
- `compileall`、CLI 根命令和相关入口 `--help` 通过。
- 已实际尝试 NovelAI 真实出图；当前环境在服务请求阶段发生代理 TLS `httpx.ConnectError`，因此真实图片验收保持未完成，不能标记为通过。

## Global Constraints

- 只修改 `refactor` 子模块，不修改父项目旧 `tags_machine`。
- 不改变 AgentComposer 的 prompt composition、cache 和 `PromptPolicyPipeline` bypass 语义。
- 外部配置继续使用 `prompt_policy.rules`，不新增 `render_policy` 顶层字段。
- `novelai_vibe` 只覆盖 `reference_image_multiple`、`reference_strength_multiple`、`reference_information_extracted_multiple`。
- 不把图片 base64 写入日志、Policy trace、PNG 摘要或错误信息。
- 注释使用中文；不对当前工作区其他未提交改动做回滚或格式化。
- 未配置 `novelai_vibe` 时，现有请求结构和默认行为保持不变。
- 业务验收优先于单元测试，最终必须包含 NovelAI Mock 参数验证和至少一组真实出图。

---

### Task 1: 扩展统一 Policy Catalog 的 scope/backend 能力

**Files:**
- Modify: `src/tags_machine_core/policies/rules/base.py`
- Modify: `src/tags_machine_core/policies/registry.py`
- Modify: `src/tags_machine_core/policies/provider.py`
- Modify: `src/tags_machine_core/policies/__init__.py`
- Modify: `src/tags_machine_core/policies/rules/__init__.py`
- Test: `tests/test_prompt_policy.py`
- Test: `tests/test_prompt_policy_external_config.py`

**Interfaces:**
- Existing `PromptPolicyPipeline.apply(...)` continues to build a prompt-only plan when no scope is passed.
- New registry method: `PromptPolicyRegistry.build_plan(config, *, scope="prompt", backend=None)`.
- New registry method: `PromptPolicyRegistry.rules_for(scope, backend=None)`.
- Renderer rules expose `scope="renderer"` and `backend="novelai"`; existing prompt rules retain implicit `scope="prompt"` and `backend=None` through compatibility defaults.

- [ ] **Step 1: Add scope/backend compatibility helpers**

在 `rules/base.py` 增加内部类型别名和读取 helper，兼容现有规则类没有显式 `scope/backend` 属性的情况：

```python
PolicyScope = Literal["prompt", "renderer"]


def policy_scope(rule: object) -> str:
    return str(getattr(rule, "scope", "prompt"))


def policy_backend(rule: object) -> str | None:
    value = getattr(rule, "backend", None)
    return str(value) if value is not None else None
```

- [ ] **Step 2: 让 Registry 同时保存 prompt rules 和 renderer rules**

保留 `PromptPolicyRegistry` 公开类名，新增可选参数：

```python
def __init__(
    self,
    rules: Iterable[PromptRule] | None = None,
    renderer_rules: Iterable[object] | None = None,
):
    self.prompt_rules = list(rules or DEFAULT_RULES)
    self.renderer_rules = list(renderer_rules or DEFAULT_RENDER_RULES)
    self.rules = [*self.prompt_rules, *self.renderer_rules]
```

注册时继续检查全局 ID 唯一。`validate_config` 对两类规则都校验 `options_model`，未知 ID 仍然直接报错。

- [ ] **Step 3: 让 build_plan 按 scope/backend 筛选**

`build_plan` 先筛选：

```python
selected = [
    rule for rule in self.rules
    if policy_scope(rule) == scope
    and (backend is None or policy_backend(rule) in (None, backend))
]
```

prompt pipeline 使用 `scope="prompt"`；后续 renderer pipeline 使用 `scope="renderer", backend="novelai"`。排序只在筛选后的规则集合中执行，跨 scope 的 `order.before/after` 引用直接报错，避免 renderer rule 影响 prompt 顺序。

- [ ] **Step 4: 保持现有 PromptPolicy 行为**

`PromptPolicyPipeline` 明确调用 `build_plan(config, scope="prompt")`。已有 prompt rule 的默认顺序、Policy metadata、cache key 和 AgentComposer bypass 保持不变。

- [ ] **Step 5: 添加 registry 回归测试**

至少覆盖：

```python
def test_prompt_registry_ignores_renderer_rule_in_prompt_plan():
    config = PromptPolicyProvider().resolve({
        "enabled": True,
        "apply_to": {"script": True},
        "rules": {"novelai_vibe": {"enabled": True, "options": {"source": {"type": "image", "path": "x.png"}}}},
    })
    plan = PromptPolicyRegistry().build_plan(config, scope="prompt")
    assert all(getattr(rule, "id", "") != "novelai_vibe" for rule in plan.effective_rules)
```

同时验证未知 rule 仍然抛出 `ValueError`，避免 scope 扩展导致配置拼写错误被静默忽略。

- [ ] **Step 6: 运行 prompt policy 回归测试**

Run:

```powershell
uv run pytest tests/test_prompt_policy.py tests/test_prompt_policy_external_config.py -q
```

Expected: 现有测试全部通过，新增 scope 测试通过。

- [ ] **Step 7: Commit**

```powershell
git add src/tags_machine_core/policies tests/test_prompt_policy.py tests/test_prompt_policy_external_config.py
git commit -m "feat: add scoped policy registry"
```

### Task 2: 建立 Renderer Policy 契约和运行时路径上下文

**Files:**
- Create: `src/tags_machine_core/policies/rendering/__init__.py`
- Create: `src/tags_machine_core/policies/rendering/base.py`
- Create: `src/tags_machine_core/policies/rendering/sources.py`
- Modify: `src/tags_machine_core/services/generation_service.py`
- Modify: `src/tags_machine_core/policies/__init__.py`
- Test: `tests/test_novelai_render_policy.py`

**Interfaces:**
- New `RenderPolicyContext` contains `request`, `bundle`, `resolved_nodes`, `policy`, `target`, `design_root`, `policy_relative_to`.
- New `RenderPolicy` protocol contains `id`, `version`, `scope`, `backend`, `default_enabled`, `options_model`, and `apply(context)`.
- `GenerationService` accepts optional `design_root` and `policy_relative_to` constructor values.
- `GenerationService.build_novelai_request(...)` and `build_render_request(...)` accept `prompt_policy` and pass it to Renderer Policy execution.

- [ ] **Step 1: Create RenderPolicyContext**

在 `rendering/base.py` 定义：

```python
@dataclass
class RenderPolicyContext:
    request: RenderRequest
    bundle: PromptBundle
    resolved_nodes: ResolvedNodeSet | None
    policy: PromptPolicyConfig
    target: PolicyTarget
    design_root: Path | None = None
    policy_relative_to: Path | None = None
```

Context 只在 Renderer Policy 层使用，不修改 `PromptBundle` schema。

- [ ] **Step 2: 创建 RenderPolicy protocol**

定义 renderer rule 的稳定契约，并使用 `PolicyScope` 的 `renderer` 值。Prompt rule 不需要实现新的方法，Registry 通过兼容 helper 读取属性。

- [ ] **Step 3: 创建 source resolver 的公共结果对象**

在 `sources.py` 定义：

```python
@dataclass(frozen=True)
class ResolvedVibeSource:
    source_type: Literal["artist", "image"]
    source_ref: str
    images: list[str]
    strengths: list[float]
    information_extracted: list[float]
    source_sha256: list[str]
    source_sizes: list[int]
```

增加 `resolve_policy_path(value, *, relative_to)`，绝对路径原样解析，相对路径相对 Policy 配置文件目录解析，不使用当前工作目录作为隐藏 fallback。

- [ ] **Step 4: 让 GenerationService 保存运行时路径**

在构造函数增加：

```python
design_root: str | Path | None = None
policy_relative_to: str | Path | None = None
```

保存为绝对 `Path` 或 `None`。现有 `GenerationService()` 调用不传参数时保持兼容。

- [ ] **Step 5: 为 render build API 增加 prompt_policy 参数**

新增参数放在现有关键字参数末尾：

```python
def build_novelai_request(..., params=None, prompt_policy=None) -> RenderRequest:
    policy = self.policy_provider.resolve(prompt_policy)
    return self.novelai_adapter.build_request(
        ...,
        prompt_policy=policy,
        design_root=self.design_root,
        policy_relative_to=self.policy_relative_to,
    )
```

`build_render_request` 对 NovelAI 走同样路径；ComfyUI/SD 接口继续忽略该参数，不改变其请求结构。

- [ ] **Step 6: 添加 context 和路径测试**

覆盖绝对路径、相对 Policy 配置目录解析，以及未传上下文时不执行任何 source resolver。

- [ ] **Step 7: 运行测试并提交**

Run:

```powershell
uv run pytest tests/test_novelai_render_policy.py -q
```

```powershell
git add src/tags_machine_core/policies/rendering src/tags_machine_core/services/generation_service.py tests/test_novelai_render_policy.py
git commit -m "feat: add renderer policy contracts"
```

### Task 3: 实现 NovelAI vibe source resolver 和规则

**Files:**
- Modify: `src/tags_machine_core/policies/rendering/sources.py`
- Create: `src/tags_machine_core/policies/rendering/novelai.py`
- Modify: `src/tags_machine_core/policies/rendering/__init__.py`
- Modify: `src/tags_machine_core/policies/registry.py`
- Modify: `src/tags_machine_core/policies/__init__.py`
- Test: `tests/test_novelai_render_policy.py`
- Test: `tests/test_novelai_artist_repository.py`

**Interfaces:**
- New rule ID: `novelai_vibe@v1`.
- New options model: `NovelAIVibeOptions`.
- New pipeline: `NovelAIRenderPolicyPipeline.apply(request, *, bundle, resolved_nodes, policy, target, design_root, policy_relative_to)`.
- Source resolver returns only the three whitelisted Vibe fields and source summaries.

- [ ] **Step 1: Define and validate NovelAI Vibe options**

`NovelAIVibeOptions` 字段：

```python
class NovelAIVibeOptions(BaseModel):
    source: NovelAIVibeSource
    strength: list[float] | float | None = None
    information_extracted: list[float] | float | None = None
```

`NovelAIVibeSource` 支持：

```python
class NovelAIVibeSource(BaseModel):
    type: Literal["artist", "image"]
    ref: str | None = None
    path: str | None = None
```

通过 model validator 强制：artist 必须有 `ref`，image 必须有 `path`，不允许同时填写两个 source 标识。

- [ ] **Step 2: 实现 artist source**

使用 `NovelAIArtistRepository(design_root)` 加载 `ref`。`design_root` 缺失且 `ref` 不是存在的绝对路径时抛出明确错误。

只复制：

```python
reference_image_multiple
reference_strength_multiple
reference_information_extracted_multiple
```

源 artist 没有图片时直接报错；源 artist 的 model、prompt、negative 和采样参数不能进入 resolved source。

- [ ] **Step 3: 实现 image source**

读取图片字节，使用标准 base64 编码，不增加 data URI 前缀，以符合现有 NovelAI Client 和测试的参数形态。计算 SHA-256 和字节长度，返回一张图片的结果。

image source 必须显式提供 `strength` 和 `information_extracted`。这样不会因为隐藏默认值改变 NovelAI 的实际行为。

- [ ] **Step 4: 实现数组规范化和长度校验**

规则：

- 标量转成单元素列表；
- 长度为 1 时广播到图片数量；
- 长度等于图片数量时原样使用；
- 其他长度抛出 `ValueError`；
- 数值范围按当前 NovelAI Render Adapter 的合法范围校验；
- artist source 未提供 `information_extracted_multiple` 时保留空列表，保持旧 artist 请求语义；
- image source 必须得到与图片数量一致的两个数组。

- [ ] **Step 5: 实现 `NovelAIVibePolicyRule.apply`**

规则执行：

1. 读取并校验 `NovelAIVibeOptions`；
2. 解析 source；
3. 深拷贝 `request.params`；
4. 替换三个 Vibe 字段；
5. 追加 `request.meta["novelai_render_policy"]` 摘要；
6. 返回新的 `RenderRequest`，不修改输入对象。

规则属性固定为：

```python
id = "novelai_vibe"
version = "v1"
scope = "renderer"
backend = "novelai"
default_enabled = False
options_model = NovelAIVibeOptions
```

- [ ] **Step 6: 实现 NovelAI Render Policy Pipeline**

Pipeline 使用 Registry 的：

```python
registry.build_plan(policy, scope="renderer", backend="novelai")
```

先检查 `policy.target_enabled(target)`。未启用、target 不匹配或 backend 不匹配时返回原始 request 并记录 trace；规则已启用但 source 无效时抛错，不回退基础 artist vibe。

- [ ] **Step 7: 注册 renderer rule 并添加 Mock 参数测试**

至少验证：

- 基础 artist 的 prompt/model/sampler/steps/scale 不变；
- artist source 只替换三类 Vibe 参数；
- image source 的 base64 进入请求参数；
- request meta 只有 hash、数量、来源和覆盖字段，没有 base64；
- source 缺失、文件不存在、数组长度错误都失败。

- [ ] **Step 8: 运行测试并提交**

```powershell
uv run pytest tests/test_novelai_render_policy.py tests/test_novelai_artist_repository.py -q
git add src/tags_machine_core/policies tests/test_novelai_render_policy.py tests/test_novelai_artist_repository.py
git commit -m "feat: add NovelAI vibe policy"
```

### Task 4: 接入 NovelAI Renderer、GenerationService 和现有入口

**Files:**
- Modify: `src/tags_machine_core/renderers/novelai.py`
- Modify: `src/tags_machine_core/services/generation_service.py`
- Modify: `src/tags_machine_core/cli.py`
- Modify: `src/tags_machine_core/batch/executor.py`
- Modify: `src/tags_machine_core/services/json_api.py`
- Modify: `src/tags_machine_core/web/app.py`
- Test: `tests/test_cli_prompt.py`
- Test: `tests/test_cli_nodes.py`
- Test: `tests/test_json_api.py`
- Test: `tests/test_batch_generation.py`

**Interfaces:**
- `NovelAIRenderAdapter.build_request(...)` receives optional resolved `prompt_policy`, `design_root`, and `policy_relative_to`.
- CLI/builders pass the same policy source/config to compose and render stages.
- Batch and JSON API preserve `prompt_policy` from task/request into render request construction.

- [ ] **Step 1: 在 NovelAIRenderAdapter 注入 Render Policy Pipeline**

Adapter 先构造当前 `RenderRequest`，再调用 `NovelAIRenderPolicyPipeline`。基础 `artist_payload` 保持当前 artist，不改写成 vibe source artist，确保审计信息仍表示实际画风 artist。

- [ ] **Step 2: 统一 CLI 的 policy 变量**

在 `_build_novelai_prompt_artifacts`、`_build_novelai_agent_prompt_artifacts`、`_build_novelai_action_artifacts`、通用 backend builder 中先生成：

```python
policy_source = _prompt_policy_from_args(args, target=target)
```

同一个 `policy_source` 同时传给 compose 和 `build_novelai_request/build_render_request`。Agent 仍由 `apply_to.agent` 默认关闭，不改变 agent composition。

- [ ] **Step 3: 给 CLI Render Service 注入 config path 上下文**

当 `args.config` 存在时，先加载 config，并使用：

```python
GenerationService(
    design_root=config.legacy.design_root,
    policy_relative_to=Path(args.config).resolve().parent,
)
```

避免相对 artist ref 和相对图片路径依赖当前工作目录。真实执行继续复用同一份 config，不重复选择 source。

- [ ] **Step 4: 接入 BatchExecutor**

BatchExecutor 在有 `config` 时使用 `GenerationService` 的运行时路径上下文。`task.policy` 同时传给 `_compose` 和 `build_render_request`。Mock 与真实执行共享同一个最终 `RenderRequest`。

- [ ] **Step 5: 接入 JSON API 和 Web Service**

`render_plan` 接收并传递 `prompt_policy`；`compose_render_plan` 从 compose request 复制 policy 到 render request。Web app 创建 `GenerationService` 时注入 `config.legacy.design_root` 和配置文件目录。

- [ ] **Step 6: 验证 AgentComposer 不受影响**

增加业务测试：构造带 `novelai_vibe` 的 Agent 请求，确认 prompt 未经过 PromptPolicyPipeline，且默认 `apply_to.agent=false` 时 RenderRequest 不含 `novelai_render_policy`。

- [ ] **Step 7: 运行入口回归测试并提交**

```powershell
uv run pytest tests/test_cli_prompt.py tests/test_cli_nodes.py tests/test_json_api.py tests/test_batch_generation.py -q
git add src/tags_machine_core/renderers/novelai.py src/tags_machine_core/services/generation_service.py src/tags_machine_core/cli.py src/tags_machine_core/batch/executor.py src/tags_machine_core/services/json_api.py src/tags_machine_core/web/app.py tests/test_cli_prompt.py tests/test_cli_nodes.py tests/test_json_api.py tests/test_batch_generation.py
git commit -m "feat: route vibe policy through render entrypoints"
```

### Task 5: 完善 PNG 元数据、请求签名和归档摘要

**Files:**
- Modify: `src/tags_machine_core/execution.py`
- Modify: `src/tags_machine_core/json_tools.py` if needed for safe summaries
- Modify: `src/tags_machine_core/verification/render_params.py` if needed for reference summaries
- Test: `tests/test_execution.py`
- Test: `tests/test_verification.py`

**Interfaces:**
- `build_core_png_text(request)` includes only sanitized `novelai_render_policy` metadata.
- Existing request body retains actual NovelAI reference data where required for execution; display/compare normalization uses hashes and lengths.

- [ ] **Step 1: 写入 NovelAI Policy PNG 摘要**

把 `request.meta["novelai_render_policy"]` 放入 Core PNG info。若字段不存在，输出结构保持与旧请求一致。

- [ ] **Step 2: 设计安全摘要**

对 policy metadata 做白名单复制，只允许：

```text
enabled
rules
source_type
source_ref
image_count
source_sha256
source_sizes
strength
information_extracted
replaced_fields
```

不把 `request.params.reference_image_multiple` 原始 base64复制到 Core PNG info。

- [ ] **Step 3: 确认请求签名包含 source 内容 hash**

把 renderer policy signature 写入 `RenderRequest.meta`，并让现有请求归档/指纹逻辑读取它。图片内容变化必须导致签名变化，单纯路径未变化不能复用旧 vibe 结果。

- [ ] **Step 4: 添加 PNG 和归档测试**

验证：

- `build_core_png_text` 包含 `novelai_render_policy`；
- PNG 文本不含测试 base64；
- 两个不同图片内容产生不同 source hash；
- `GenerationResult.request_body` 的实际 reference 参数仍可被现有比较器读取。

- [ ] **Step 5: 运行测试并提交**

```powershell
uv run pytest tests/test_execution.py tests/test_verification.py -q
git add src/tags_machine_core/execution.py src/tags_machine_core/json_tools.py src/tags_machine_core/verification/render_params.py tests/test_execution.py tests/test_verification.py
git commit -m "feat: archive NovelAI vibe policy metadata"
```

### Task 6: 添加配置示例和业务级 Mock 验收

**Files:**
- Create: `examples/prompt_policies/novelai_vibe_artist.yaml`
- Create: `examples/prompt_policies/novelai_vibe_image.yaml`
- Modify: `docs/prompt_policy_configuration.md`
- Create: `docs/superpowers/reports/2026-08-19-novelai-vibe-policy-mock-validation.md`
- Test: `tests/test_novelai_render_policy.py`

- [ ] **Step 1: 添加不含硬编码真实路径的配置示例**

示例使用用户替换的相对路径说明，并明确 image source 必须配置 strength 和 information_extracted。示例不作为默认项目 Policy，避免在没有图片时污染现有批量任务。

- [ ] **Step 2: 更新 Policy 配置文档**

说明：

- `novelai_vibe` 是 renderer scope；
- `apply_to` 仍控制 script/full_prompt/agent；
- artist source 只取 vibe 参数；
- image source 只读图片并编码；
- source 无效直接报错；
- 没有该 rule 时完全兼容旧链路。

- [ ] **Step 3: 运行 Mock 业务链路**

使用现有 `execute_mock_generation` 或 Mock Client，至少验证两条完整链路：

```powershell
uv run pytest tests/test_novelai_render_policy.py -q
uv run python -m tags_machine_core inspect-artist --config configs/local.yaml --artist "20260412" --full
```

测试必须从 `GenerationService` 构建 PromptBundle 和 RenderRequest，再交给现有 Mock 执行器；不能只调用 source resolver，也不能新增只用于测试的旁路链路。真实配置需要启用规则时，使用现有 Batch YAML 的 `defaults.prompt_policy` 入口。

- [ ] **Step 4: 记录参数结果**

报告必须包含：

- 基础 artist ref；
- vibe source 类型和 ref/path；
- prompt、negative、model、sampler、steps、scale、seed、尺寸；
- 三类 reference 参数的 hash/长度/数值；
- `novelai_render_policy` metadata；
- AgentComposer 未被修改的证据。

- [ ] **Step 5: 提交配置和 Mock 报告**

```powershell
git add examples/prompt_policies docs/prompt_policy_configuration.md docs/superpowers/reports/2026-08-19-novelai-vibe-policy-mock-validation.md tests/test_novelai_render_policy.py
git commit -m "docs: add NovelAI vibe policy examples and validation"
```

### Task 7: 真实 NovelAI 出图和最终验收

**Files:**
- Create: `docs/superpowers/reports/2026-08-19-novelai-vibe-policy-real-validation.md`
- Create: `examples/acceptance/novelai_vibe_policy_001/` runtime artifacts only if project convention requires them

- [ ] **Step 1: 准备三组单图请求**

固定 prompt、negative、model、sampler、steps、scale、seed 和尺寸，只改变 vibe source：

1. 基础 artist 自带 vibe；
2. 基础 artist + 另一个 artist source；
3. 基础 artist + 外部图片 source。

每次 `n_samples=1`，避免批量消耗额外点数。

- [ ] **Step 2: 执行真实 NovelAI 请求**

使用当前正式 config 和 `NAI_ACCESS_TOKEN`，不使用 dry-run 代替业务验证。保存实际图片路径、`generation_result.json`、`render_request.json` 和 PNG 参数。

- [ ] **Step 3: 做参数对比**

使用现有参数读取和比较工具，确认：

- prompt/negative/model/sampler/steps/scale/seed/尺寸除预期外一致；
- 三类 Vibe 参数和 Policy metadata 一致；
- PNG 参数与 `GenerationResult.request_body` 一致；
- source 内容 hash 与归档记录一致。

- [ ] **Step 4: 做人工视觉验收**

记录主体、动作、构图和基础画风是否保持；新 vibe 是否只改变预期的风格/质感；不能把源 artist 的人物或模型参数误带入。

- [ ] **Step 5: 写入真实业务报告并提交**

报告记录图片路径、参数 diff、视觉结论、异常和 Anlas 影响。真实 token 不写入报告。

```powershell
git add docs/superpowers/reports/2026-08-19-novelai-vibe-policy-real-validation.md
git commit -m "test: validate NovelAI vibe policy with real generation"
```

## 最终验证命令

实现完成后依次执行：

```powershell
uv run pytest tests/test_prompt_policy.py tests/test_prompt_policy_external_config.py tests/test_novelai_render_policy.py -q
uv run pytest tests/test_cli_prompt.py tests/test_cli_nodes.py tests/test_json_api.py tests/test_batch_generation.py -q
uv run python -m tags_machine_core verify-core
```

最后必须补充真实 NovelAI 出图报告，不能只用单元测试或 dry-run 作为完成依据。
