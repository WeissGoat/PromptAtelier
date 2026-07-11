# NovelAI Artist Vibe Parameter Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复旧 artist 同时包含 `gen_param` 和 `gen_json` 时 vibe 参数丢失的问题，并验证两个 NovelAI 执行器构造相同 payload。

**Architecture:** 参数来源优先级在 artist 输入层统一为 `第一个 gen_json > 第一个 gen_param > 空参数`。Renderer 继续只消费结构化 artist node，`core_novelai_client` 与 `ai_image_gateway_raw` 继续发送同一 `RenderRequest`，不增加执行器兼容逻辑。

**Tech Stack:** Python 3.12、Pydantic、pytest/unittest、NovelAI raw HTTP payload。

## Global Constraints

- 不修改 Renderer 的 artist/vibe 推断职责。
- 不在 ai-image-gateway 中补齐 vibe 参数。
- 多个 `gen_json` 只使用第一个。
- 没有 `gen_json` 时保留 `gen_param` 兼容。
- 不触碰当前工作区中 Web 控制台相关未提交改动。

---

### Task 1: 统一运行时 artist 参数优先级

**Files:**
- Modify: `src/tags_machine_core/nodes/novelai_artist.py`
- Test: `tests/test_novelai_artist_repository.py`

**Interfaces:**
- Consumes: `NovelAIArtistRepository.load(artist_ref: str) -> NovelAIArtist`
- Produces: `NovelAIArtist.params`，按 `gen_json > gen_param` 选择完整参数字典。

- [ ] **Step 1: 添加同时存在两种参数块的失败测试**

在 `tests/test_novelai_artist_repository.py` 增加：

```python
def test_runtime_loader_prefers_first_gen_json_over_gen_param(self):
    with tempfile.TemporaryDirectory() as temp_dir:
        design_root = Path(temp_dir)
        artist_dir = design_root / "画风" / "vibe_artist"
        artist_dir.mkdir(parents=True)
        (artist_dir / "tags.txt").write_text(
            "style prefix\n"
            "=\n"
            "gen_param, 'model': 'nai-diffusion-4-5-full', "
            "'reference_strength_multiple': [0.13, 0.14]\n"
            'gen_json, {"model":"nai-diffusion-4-5-full",'
            '"reference_image_multiple":["vibe-a","vibe-b"],'
            '"reference_strength_multiple":[0.13,0.14]}\n',
            encoding="utf-8",
        )

        artist = NovelAIArtistRepository(design_root).load("vibe_artist")

        self.assertEqual(artist.params["reference_image_multiple"], ["vibe-a", "vibe-b"])
        self.assertEqual(artist.params["reference_strength_multiple"], [0.13, 0.14])
```

- [ ] **Step 2: 运行测试并确认当前实现失败**

Run:

```powershell
$env:PYTHONPATH='src'
uv run pytest tests/test_novelai_artist_repository.py::NovelAIArtistRepositoryTest::test_runtime_loader_prefers_first_gen_json_over_gen_param -q
```

Expected: FAIL，`reference_image_multiple` 不存在。

- [ ] **Step 3: 最小化修改运行时解析器**

在 `_parse_tags_txt` 中分别缓存参数来源，遍历结束后统一选择：

```python
gen_json_params: dict[str, Any] | None = None
gen_param_params: dict[str, Any] | None = None

for line in ext_lines:
    key, value = self._split_ext_line(line)
    # 其他 extension 处理保持不变
    if key == "gen_json" and gen_json_params is None:
        gen_json_params = self._parse_json_value(value, tags_path)
    elif key == "gen_param" and gen_param_params is None:
        gen_param_params = self._parse_json_value(value, tags_path)

artist.params.update(gen_json_params or gen_param_params or {})
```

- [ ] **Step 4: 运行 artist repository 全部测试**

Run:

```powershell
$env:PYTHONPATH='src'
uv run pytest tests/test_novelai_artist_repository.py -q
```

Expected: PASS；已有“第一个 gen_json”和“只有 gen_param”用例继续通过。

- [ ] **Step 5: 提交运行时解析修复**

```powershell
git add src/tags_machine_core/nodes/novelai_artist.py tests/test_novelai_artist_repository.py
git commit -m "fix: prefer artist gen json vibe parameters"
```

---

### Task 2: 统一 artist migration 参数优先级

**Files:**
- Modify: `src/tags_machine_core/nodes/migration.py`
- Test: `tests/test_novelai_artist_repository.py`

**Interfaces:**
- Consumes: `migrate_legacy_artist_tags(source, ...) -> dict[str, Any]`
- Produces: `renderers.novelai.params`，与运行时 repository 采用相同优先级。

- [ ] **Step 1: 添加 migration 回归测试**

复用包含 `gen_param` 和 `gen_json` 的临时 artist，断言：

```python
migrated = migrate_legacy_artist_tags(tags_path)
params = migrated["renderers"]["novelai"]["params"]
self.assertEqual(params["reference_image_multiple"], ["vibe-a", "vibe-b"])
```

并增加仅包含 `gen_param` 的断言：

```python
self.assertEqual(params["model"], "nai-diffusion-4-5-full")
```

- [ ] **Step 2: 运行两个 migration 用例并确认 gen_param 回退用例失败**

Run:

```powershell
$env:PYTHONPATH='src'
uv run pytest tests/test_novelai_artist_repository.py -k "migration and (prefers or gen_param)" -q
```

Expected: 当前 migration 忽略 `gen_param`，回退测试 FAIL。

- [ ] **Step 3: 修改 migration 选择逻辑**

把 `gen_json_seen` 改为两个独立缓存：

```python
gen_json_params: dict[str, Any] | None = None
gen_param_params: dict[str, Any] | None = None
```

解析时分别记录第一个值，并在循环后执行：

```python
novelai["params"].update(gen_json_params or gen_param_params or {})
```

同时让 `_parse_json_value` 支持 `gen_param` 的 Python 字面量片段，行为与 `NovelAIArtistRepository._parse_json_value` 一致。

- [ ] **Step 4: 运行 repository 与 migration 测试**

Run:

```powershell
$env:PYTHONPATH='src'
uv run pytest tests/test_novelai_artist_repository.py tests/test_cli_nodes.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交 migration 修复**

```powershell
git add src/tags_machine_core/nodes/migration.py tests/test_novelai_artist_repository.py
git commit -m "fix: align migrated artist parameter precedence"
```

---

### Task 3: 验证真实 artist 与双执行器 payload

**Files:**
- Modify: `tests/test_execution.py`
- Modify: `docs/batch_generation_readme.md`

**Interfaces:**
- Consumes: `NovelAIClient.build_payload(request)`、`GatewayNovelAIRawClient.build_payload(request)`。
- Produces: 两个执行器 payload 相等的验收证据，以及明确的切换文档。

- [ ] **Step 1: 添加双执行器 payload 一致性测试**

构造包含 vibe 参数的 `RenderRequest`：

```python
request = RenderRequest(
    backend="novelai",
    prompt="1girl",
    negative_prompt="lowres",
    model="nai-diffusion-4-5-full",
    params={
        "width": 832,
        "height": 1216,
        "reference_image_multiple": ["vibe-a", "vibe-b"],
        "reference_strength_multiple": [0.13, 0.14],
        "reference_information_extracted_multiple": [],
    },
)
self.assertEqual(
    NovelAIClient(access_token="test").build_payload(request),
    GatewayNovelAIRawClient(access_token="test", base_url="https://example.invalid").build_payload(request),
)
```

- [ ] **Step 2: 运行 payload 测试**

Run:

```powershell
$env:PYTHONPATH='src'
uv run pytest tests/test_execution.py -k "gateway and payload" -q
```

Expected: PASS，且不发送网络请求。

- [ ] **Step 3: 更新执行器切换文档**

在 `docs/batch_generation_readme.md` 说明：

```yaml
generation:
  executor: core_novelai_client  # 原 refactor client
```

以及：

```yaml
generation:
  executor: ai_image_gateway_raw  # gateway raw client
```

注明切换不影响 Renderer 和 artist 参数解析。

- [ ] **Step 4: 用真实 artist 做参数验收**

Run:

```powershell
$env:PYTHONPATH='src'
uv run python -m tags_machine_core inspect-artist --config configs/local.yaml --artist "109841329_01_official_typemoon_main_vibe_7682_aafa_koyama_cg_v45_latest_stable" --full
```

Expected: `renderers.novelai.params.reference_image_multiple` 包含 2 项，`reference_strength_multiple` 为 `[0.13, 0.14]`。

- [ ] **Step 5: 运行最终回归测试**

Run:

```powershell
$env:PYTHONPATH='src'
uv run pytest tests/test_novelai_artist_repository.py tests/test_execution.py tests/test_cli_nodes.py tests/test_cli_config.py -q
```

Expected: 全部 PASS。

- [ ] **Step 6: 选择一个执行器进行单张真实出图**

在 `configs/local.yaml` 设置目标 executor 后执行现有 batch：

```powershell
$env:PYTHONPATH='src'
uv run python -m tags_machine_core run-batch examples/batches/blackboard_action_new_manga_monochrome.yaml --limit 1 --fresh --full
```

Expected: 输出一张图片；其归档请求参数包含两项 `reference_image_multiple`。遇到 NovelAI `429` 时记录为外部限流，不连续重试另一执行器。

- [ ] **Step 7: 提交验收与文档**

```powershell
git add tests/test_execution.py docs/batch_generation_readme.md
git commit -m "test: verify novelai executor vibe payloads"
```

