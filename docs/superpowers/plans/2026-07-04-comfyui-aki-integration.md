# ComfyUI Aki Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote ComfyUI from a pre-v1 experimental backend into a real opt-in generation backend, using the Aki ComfyUI package and the exported `cunyfunky_api.json` workflow as the first business acceptance target.

**Architecture:** Keep prompt generation unchanged: AgentComposer and ScriptComposer still output backend-neutral `PromptBundle`. The ComfyUI renderer consumes an artist node's `renderers.comfyui` block, loads an API workflow, applies explicit input bindings for prompt, negative prompt, size, and seed, and produces a `RenderRequest`. The ComfyUI client remains the raw API boundary for `/prompt`, `/history/{prompt_id}`, `/view`, and optional `/object_info` preflight.

**Tech Stack:** Python 3.11+, Pydantic, requests, existing `tags_machine_core` CLI/batch/execution architecture, ComfyUI standard HTTP API, Aki portable ComfyUI at `D:/AI/ComfyUI-aki/ComfyUI-aki-v1.6/ComfyUI`.

---

## 1. Current Findings

The benchmark workflow source is:

```text
C:/Downloads/cunyfunky_api.json
```

This file is a valid ComfyUI API workflow. It is not the UI workflow previously inspected at:

```text
D:/AI/ComfyUI-aki/ComfyUI-aki-v1.6/ComfyUI/user/default/workflows/cunyfunky.json
```

The API workflow node mapping confirmed from `C:/Downloads/cunyfunky_api.json` is:

| Semantic input | Workflow path |
| --- | --- |
| positive prompt | `218.inputs.wildcard_text` |
| negative prompt | `153.inputs.text` |
| width | `23.inputs.width` |
| height | `23.inputs.height` |
| seed | `202.inputs.seed` |
| main sampler steps | `3.inputs.steps`, `17.inputs.steps` |
| main sampler cfg | `3.inputs.cfg`, `17.inputs.cfg` |
| main sampler sampler | `3.inputs.sampler_name`, `17.inputs.sampler_name` |
| main sampler scheduler | `3.inputs.scheduler`, `17.inputs.scheduler` |
| final image save nodes | `77`, `212` |

Positive prompt should be patched into `218.inputs.wildcard_text` instead of `165.inputs.text`. The workflow uses this chain:

```text
218 ImpactWildcardProcessor
-> 219 OldNAIToComfyUI
-> 165 CLIPTextEncode
-> KSampler 3 / KSampler 17 / UltimateSDUpscale / FaceDetailer
```

This preserves the workflow's own wildcard and old NovelAI prompt conversion logic.

Risk: node `181 Preview Chooser` is configured as `Always pause` in the UI workflow. If this behavior remains in the API export, automation can block. The first implementation must surface this as a business acceptance risk and must record whether the API run completes without manual UI interaction.

Do not write or print sensitive values from the Aki `.env` file.

---

## 2. Target Artist Node Contract

Create the first ComfyUI artist node under examples. The workflow remains the source of truth for checkpoint, VAE, LoRA, upscalers, ControlNet, and custom nodes. The artist node only declares workflow selection and externally patched inputs.

```yaml
schema: tags-machine-core.node/v1
kind: artist
id: comfyui_cunyfunky
description: "ComfyUI Aki cunyfunky API workflow preset."

renderers:
  comfyui:
    workflow: cunyfunky
    workflow_path: workflows/cunyfunky_api.json

    inputs:
      positive_prompt: "218.inputs.wildcard_text"
      negative_prompt: "153.inputs.text"
      width: "23.inputs.width"
      height: "23.inputs.height"
      seed: "202.inputs.seed"

    optional_inputs:
      steps:
        - "3.inputs.steps"
        - "17.inputs.steps"
      cfg:
        - "3.inputs.cfg"
        - "17.inputs.cfg"
      sampler:
        - "3.inputs.sampler_name"
        - "17.inputs.sampler_name"
      scheduler:
        - "3.inputs.scheduler"
        - "17.inputs.scheduler"

    output_nodes:
      - "212"

    node_overrides: {}
```

`output_nodes` defaults to all image-producing outputs when absent. For `cunyfunky`, set it to `["212"]` first so one batch task does not unexpectedly archive both the upscale branch and face-detail branch. A user can later change this field to `["77", "212"]` when both outputs are desired.

`optional_inputs` only patch when the user or batch explicitly provides the corresponding key. If the user does not pass `steps`, `cfg`, `sampler`, or `scheduler`, the workflow defaults remain intact.

---

## 3. Server Deployment Contract

The local Aki path is only a development environment detail. Runtime should be controlled by config:

```yaml
comfyui:
  base_url: "http://127.0.0.1:8188"
  timeout: 300
  poll_interval: 1.0
  max_wait_seconds: 600
  retry: 3
  retry_interval: 2.0
```

When ComfyUI is deployed on a server, users only change:

```yaml
comfyui:
  base_url: "http://server-ip:8188"
```

The core process reads the local API workflow JSON and submits the full workflow to the remote `/prompt` endpoint. The remote ComfyUI server must have the same required custom nodes, checkpoint files, LoRA files, VAE files, and upscaler files installed under names referenced by the workflow.

First implementation should add a preflight mode that calls `/object_info` and compares the workflow's `class_type` values with server-supported node classes. This catches missing custom nodes before queueing a long generation.

---

## 4. File Structure

Create:

- `examples/nodes/artists/comfyui_cunyfunky/node.yaml`  
  First formal ComfyUI artist node.

- `examples/nodes/artists/comfyui_cunyfunky/workflows/cunyfunky_api.json`  
  Version-controlled copy of `C:/Downloads/cunyfunky_api.json`.

- `docs/comfyui_artist_node_spec_v1.md`  
  Chinese field reference for `renderers.comfyui`.

- `docs/comfyui_aki_cunyfunky_business_test_20260704.md`  
  Real generation acceptance record with image paths, `GenerationResult`, and visual conclusion.

- `src/tags_machine_core/renderers/comfyui_workflow.py`  
  Focused workflow validation and binding helpers.

Modify:

- `src/tags_machine_core/renderers/comfyui.py`  
  Apply `inputs`, `optional_inputs`, `output_nodes`, workflow hash, and explicit input metadata.

- `src/tags_machine_core/clients/comfyui.py`  
  Add retry, object-info preflight helper, output node filtering, and clearer errors.

- `src/tags_machine_core/config.py`  
  Add ComfyUI retry and polling config.

- `src/tags_machine_core/execution.py`  
  Split ComfyUI `n_samples` into repeated prompt submissions with seed offsets.

- `src/tags_machine_core/backends.py`  
  Promote ComfyUI to opt-in executable backend without the experimental flag.

- `src/tags_machine_core/cli.py`  
  Add backend-aware `run-prompt` and `run-action` generation path.

- `src/tags_machine_core/batch/executor.py`  
  Ensure batch can execute ComfyUI tasks using the same path as NovelAI.

- `src/tags_machine_core/batch/parameter_image.py`  
  Show compact ComfyUI details in parameter image.

- `configs/local.example.yaml`  
  Document ComfyUI local/server settings.

Test files to update:

- `tests/test_multi_backend_renderers.py`
- `tests/test_multi_backend_clients.py`
- `tests/test_execution.py`
- `tests/test_cli_nodes.py`
- `tests/test_backend_support.py`
- `tests/test_batch_generation.py`

Business validation is mandatory and has higher priority than isolated tests for this feature.

---

## 5. Implementation Tasks

### Task 1: Add ComfyUI Cunyfunky Example Assets

**Files:**
- Create: `F:/my_project/new/tags_machine/refactor/examples/nodes/artists/comfyui_cunyfunky/node.yaml`
- Create: `F:/my_project/new/tags_machine/refactor/examples/nodes/artists/comfyui_cunyfunky/workflows/cunyfunky_api.json`
- Create: `F:/my_project/new/tags_machine/refactor/docs/comfyui_artist_node_spec_v1.md`

- [ ] **Step 1: Copy the exported API workflow**

Run:

```powershell
New-Item -ItemType Directory -Force F:\my_project\new\tags_machine\refactor\examples\nodes\artists\comfyui_cunyfunky\workflows
Copy-Item -LiteralPath C:\Downloads\cunyfunky_api.json -Destination F:\my_project\new\tags_machine\refactor\examples\nodes\artists\comfyui_cunyfunky\workflows\cunyfunky_api.json
```

Expected: `cunyfunky_api.json` exists under the new example artist node.

- [ ] **Step 2: Create the artist node**

Write `examples/nodes/artists/comfyui_cunyfunky/node.yaml`:

```yaml
schema: tags-machine-core.node/v1
kind: artist
id: comfyui_cunyfunky
description: "ComfyUI Aki cunyfunky API workflow preset."

renderers:
  comfyui:
    workflow: cunyfunky
    workflow_path: workflows/cunyfunky_api.json

    inputs:
      positive_prompt: "218.inputs.wildcard_text"
      negative_prompt: "153.inputs.text"
      width: "23.inputs.width"
      height: "23.inputs.height"
      seed: "202.inputs.seed"

    optional_inputs:
      steps:
        - "3.inputs.steps"
        - "17.inputs.steps"
      cfg:
        - "3.inputs.cfg"
        - "17.inputs.cfg"
      sampler:
        - "3.inputs.sampler_name"
        - "17.inputs.sampler_name"
      scheduler:
        - "3.inputs.scheduler"
        - "17.inputs.scheduler"

    output_nodes:
      - "212"

    node_overrides: {}
```

- [ ] **Step 3: Create the Chinese spec document**

Write `docs/comfyui_artist_node_spec_v1.md` with these sections:

```markdown
# ComfyUI Artist Node Spec v1

## 定位

ComfyUI artist node 是 workflow 预设节点。它不保存 checkpoint、VAE、LoRA、ControlNet、upscale 等 workflow 内部配置；这些配置以 API workflow JSON 为准。

## 字段

| 字段 | 必填 | 含义 |
| --- | --- | --- |
| `renderers.comfyui.workflow` | 是 | 给日志、UI、归档看的 workflow 名称。 |
| `renderers.comfyui.workflow_path` | 是 | API workflow JSON 路径。相对路径基于 artist node 目录解析。 |
| `renderers.comfyui.inputs.positive_prompt` | 是 | 正向提示词写入路径。 |
| `renderers.comfyui.inputs.negative_prompt` | 是 | 负向提示词写入路径。 |
| `renderers.comfyui.inputs.width` | 是 | 宽度写入路径。 |
| `renderers.comfyui.inputs.height` | 是 | 高度写入路径。 |
| `renderers.comfyui.inputs.seed` | 是 | seed 写入路径。 |
| `renderers.comfyui.optional_inputs` | 否 | 只有外部显式传参时才覆盖的路径映射。 |
| `renderers.comfyui.output_nodes` | 否 | 只下载指定输出节点的图片。为空时下载所有图片输出。 |
| `renderers.comfyui.node_overrides` | 否 | 高级固定覆盖，用于 workflow 特殊节点。 |

## Workflow 格式

`workflow_path` 必须指向 ComfyUI `File -> Export (API)` 导出的 API workflow。UI workflow 的顶层通常包含 `nodes` 和 `links`，不能直接提交给 `/prompt`。

## Cunyfunky 基准

`comfyui_cunyfunky` 使用 `218.inputs.wildcard_text` 注入正向提示词，保留 workflow 自带的 `ImpactWildcardProcessor -> OldNAIToComfyUI -> CLIPTextEncode` 链路。
```

- [ ] **Step 4: Verify assets load**

Run:

```powershell
uv run python -m tags_machine_core inspect-node examples\nodes\artists\comfyui_cunyfunky --full
```

Expected: output contains `kind: artist`, `id: comfyui_cunyfunky`, and `renderers.comfyui.inputs.positive_prompt`.

- [ ] **Step 5: Commit**

```powershell
git add examples/nodes/artists/comfyui_cunyfunky docs/comfyui_artist_node_spec_v1.md
git commit -m "docs: add comfyui cunyfunky artist spec"
```

---

### Task 2: Add Workflow Validation and Binding Helpers

**Files:**
- Create: `F:/my_project/new/tags_machine/refactor/src/tags_machine_core/renderers/comfyui_workflow.py`
- Test: `F:/my_project/new/tags_machine/refactor/tests/test_multi_backend_renderers.py`

- [ ] **Step 1: Add tests for workflow format and binding paths**

Append tests to `tests/test_multi_backend_renderers.py`:

```python
def test_comfyui_workflow_rejects_ui_workflow():
    from tags_machine_core.renderers.comfyui_workflow import validate_api_workflow

    workflow = {"nodes": [], "links": [], "version": 0.4}

    with self.assertRaises(ValueError) as raised:
        validate_api_workflow(workflow, source="ui.json")

    self.assertIn("ComfyUI API workflow", str(raised.exception))
    self.assertIn("File -> Export (API)", str(raised.exception))


def test_comfyui_workflow_builds_overrides_from_bindings():
    from tags_machine_core.renderers.comfyui_workflow import (
        build_bound_overrides,
        validate_api_workflow,
    )

    workflow = {
        "3": {"class_type": "KSampler", "inputs": {"seed": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}},
    }
    validate_api_workflow(workflow, source="api.json")

    overrides = build_bound_overrides(
        inputs={"positive_prompt": "6.inputs.text", "seed": "3.inputs.seed"},
        values={"positive_prompt": "akemi homura", "seed": 123},
        source="artist.renderers.comfyui.inputs",
    )

    self.assertEqual(
        overrides,
        {
            "6.inputs.text": "akemi homura",
            "3.inputs.seed": 123,
        },
    )
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
uv run python -m unittest tests.test_multi_backend_renderers.ComfyUIRendererTest.test_comfyui_workflow_rejects_ui_workflow tests.test_multi_backend_renderers.ComfyUIRendererTest.test_comfyui_workflow_builds_overrides_from_bindings
```

Expected: tests fail because `tags_machine_core.renderers.comfyui_workflow` does not exist.

- [ ] **Step 3: Implement helper module**

Create `src/tags_machine_core/renderers/comfyui_workflow.py`:

```python
from __future__ import annotations

import hashlib
import json
from typing import Any


def workflow_hash(workflow: dict[str, Any]) -> str:
    text = json.dumps(workflow, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_api_workflow(workflow: dict[str, Any], *, source: str) -> None:
    if not isinstance(workflow, dict):
        raise ValueError(f"ComfyUI workflow must be a mapping: {source}")
    if isinstance(workflow.get("nodes"), list) and isinstance(workflow.get("links"), list):
        raise ValueError(
            "ComfyUI workflow must be a ComfyUI API workflow exported with "
            f"File -> Export (API), got UI workflow: {source}"
        )
    if not workflow:
        raise ValueError(f"ComfyUI API workflow cannot be empty: {source}")
    invalid_nodes = [
        str(node_id)
        for node_id, node in workflow.items()
        if not isinstance(node, dict) or not isinstance(node.get("class_type"), str)
    ]
    if invalid_nodes:
        raise ValueError(
            "ComfyUI API workflow nodes must contain class_type; "
            f"invalid nodes in {source}: {', '.join(invalid_nodes[:10])}"
        )


def build_bound_overrides(
    *,
    inputs: dict[str, Any],
    values: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for key, value in values.items():
        if key not in inputs:
            continue
        for path in normalize_binding_paths(inputs[key], source=f"{source}.{key}"):
            overrides[path] = value
    return overrides


def normalize_binding_paths(value: Any, *, source: str) -> list[str]:
    if isinstance(value, str):
        path = value.strip()
        if path:
            return [path]
        raise ValueError(f"ComfyUI binding path cannot be empty: {source}")
    if isinstance(value, list):
        paths: list[str] = []
        for index, item in enumerate(value):
            paths.extend(normalize_binding_paths(item, source=f"{source}[{index}]"))
        return paths
    raise ValueError(f"ComfyUI binding path must be string or list of strings: {source}")


def required_input_paths(payload: dict[str, Any]) -> dict[str, Any]:
    inputs = payload.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("ComfyUI artist node requires renderers.comfyui.inputs")
    required = ["positive_prompt", "negative_prompt", "width", "height", "seed"]
    missing = [key for key in required if key not in inputs]
    if missing:
        raise ValueError(
            "ComfyUI artist node missing required input bindings: "
            + ", ".join(missing)
        )
    return inputs


def optional_input_paths(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("optional_inputs") or {}
    if not isinstance(value, dict):
        raise ValueError("ComfyUI renderers.comfyui.optional_inputs must be a mapping")
    return value


def output_node_ids(payload: dict[str, Any]) -> list[str]:
    value = payload.get("output_nodes") or []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    raise ValueError("ComfyUI renderers.comfyui.output_nodes must be a string or list")
```

- [ ] **Step 4: Run helper tests**

Run:

```powershell
uv run python -m unittest tests.test_multi_backend_renderers.ComfyUIRendererTest.test_comfyui_workflow_rejects_ui_workflow tests.test_multi_backend_renderers.ComfyUIRendererTest.test_comfyui_workflow_builds_overrides_from_bindings
```

Expected: both tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/tags_machine_core/renderers/comfyui_workflow.py tests/test_multi_backend_renderers.py
git commit -m "feat: add comfyui workflow binding helpers"
```

---

### Task 3: Apply Artist Input Bindings in ComfyUI Renderer

**Files:**
- Modify: `F:/my_project/new/tags_machine/refactor/src/tags_machine_core/renderers/comfyui.py`
- Test: `F:/my_project/new/tags_machine/refactor/tests/test_multi_backend_renderers.py`

- [ ] **Step 1: Add renderer test for `cunyfunky` bindings**

Append to `tests/test_multi_backend_renderers.py`:

```python
def test_comfyui_adapter_applies_artist_input_bindings(self):
    artist = NodeDocument(
        kind="artist",
        id="comfyui_cunyfunky",
        renderers={
            "comfyui": {
                "workflow": "cunyfunky",
                "workflow_json": {
                    "3": {"class_type": "KSampler", "inputs": {"steps": 34, "cfg": 7}},
                    "17": {"class_type": "KSampler", "inputs": {"steps": 50, "cfg": 7}},
                    "23": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1536}},
                    "153": {"class_type": "CLIPTextEncode", "inputs": {"text": "old negative"}},
                    "202": {"class_type": "CR Seed", "inputs": {"seed": 1}},
                    "218": {"class_type": "ImpactWildcardProcessor", "inputs": {"wildcard_text": "old positive"}},
                },
                "inputs": {
                    "positive_prompt": "218.inputs.wildcard_text",
                    "negative_prompt": "153.inputs.text",
                    "width": "23.inputs.width",
                    "height": "23.inputs.height",
                    "seed": "202.inputs.seed",
                },
                "optional_inputs": {
                    "steps": ["3.inputs.steps", "17.inputs.steps"],
                    "cfg": ["3.inputs.cfg", "17.inputs.cfg"],
                },
                "output_nodes": ["212"],
            }
        },
    )

    request = ComfyUIRenderAdapter().build_request(
        _bundle(),
        artist=artist,
        width=832,
        height=1216,
        seed=123,
        params={"steps": 28},
    )

    self.assertEqual(request.backend, "comfyui")
    self.assertEqual(request.params["workflow"], "cunyfunky")
    self.assertEqual(request.params["output_nodes"], ["212"])
    self.assertEqual(request.params["node_overrides"]["218.inputs.wildcard_text"], request.prompt)
    self.assertEqual(request.params["node_overrides"]["153.inputs.text"], request.negative_prompt)
    self.assertEqual(request.params["node_overrides"]["23.inputs.width"], 832)
    self.assertEqual(request.params["node_overrides"]["23.inputs.height"], 1216)
    self.assertEqual(request.params["node_overrides"]["202.inputs.seed"], 123)
    self.assertEqual(request.params["node_overrides"]["3.inputs.steps"], 28)
    self.assertEqual(request.params["node_overrides"]["17.inputs.steps"], 28)
    self.assertNotIn("3.inputs.cfg", request.params["node_overrides"])
    self.assertIn("workflow_hash", request.params)
    self.assertEqual(request.params["comfyui_inputs"]["seed"], ["202.inputs.seed"])
```

- [ ] **Step 2: Run test to verify failure**

Run:

```powershell
uv run python -m unittest tests.test_multi_backend_renderers.ComfyUIRendererTest.test_comfyui_adapter_applies_artist_input_bindings
```

Expected: test fails because `inputs` and `optional_inputs` are not applied yet.

- [ ] **Step 3: Update imports in `renderers/comfyui.py`**

Add imports:

```python
from tags_machine_core.renderers.comfyui_workflow import (
    build_bound_overrides,
    optional_input_paths,
    output_node_ids,
    required_input_paths,
    validate_api_workflow,
    workflow_hash,
)
```

- [ ] **Step 4: Preserve explicit renderer params**

In `ComfyUIRenderAdapter.build_request`, keep a copy of raw params before merging artist params:

```python
raw_params = dict(params or {})
artist_params = copy.deepcopy(artist_payload.get("params", {}) or {})
final_params = self._build_parameters(
    bundle=bundle,
    seed=seed,
    width=width,
    height=height,
    model=model,
    artist=artist,
    artist_payload=artist_payload,
    params={**artist_params, **raw_params},
    explicit_params=raw_params,
)
```

Update `_build_parameters` signature to include:

```python
explicit_params: dict[str, Any],
```

- [ ] **Step 5: Build bound node overrides**

Inside `_build_parameters`, after loading `workflow_json` and before resolving templates, add this logic:

```python
workflow_source = str(params.get("workflow_path") or artist_payload.get("workflow_path") or workflow)
if workflow_json is not None:
    validate_api_workflow(workflow_json, source=workflow_source)

node_overrides = copy.deepcopy(
    params.get("node_overrides", artist_payload.get("node_overrides", {})) or {}
)

required_inputs = {}
optional_inputs = {}
bound_overrides: dict[str, Any] = {}
comfyui_inputs: dict[str, list[str]] = {}
if artist_payload.get("inputs") is not None:
    required_inputs = required_input_paths(artist_payload)
    optional_inputs = optional_input_paths(artist_payload)
    required_values = {
        "positive_prompt": bundle.prompt.positive,
        "negative_prompt": bundle.prompt.negative,
        "width": width,
        "height": height,
        "seed": seed if seed is not None else params.get("seed", 0),
    }
    bound_overrides.update(
        build_bound_overrides(
            inputs=required_inputs,
            values=required_values,
            source="renderers.comfyui.inputs",
        )
    )
    optional_values = {
        key: explicit_params[key]
        for key in optional_inputs
        if key in explicit_params
    }
    bound_overrides.update(
        build_bound_overrides(
            inputs=optional_inputs,
            values=optional_values,
            source="renderers.comfyui.optional_inputs",
        )
    )
    for key, value in {**required_inputs, **optional_inputs}.items():
        comfyui_inputs[key] = normalize_binding_paths(
            value,
            source=f"renderers.comfyui.{key}",
        )

node_overrides.update(bound_overrides)
```

Also import `normalize_binding_paths` if this exact snippet is used.

- [ ] **Step 6: Store output node and workflow metadata**

Set these fields in `final_params`:

```python
"node_overrides": node_overrides,
"output_nodes": output_node_ids(artist_payload),
"workflow_hash": workflow_hash(workflow_json) if workflow_json is not None else None,
"comfyui_inputs": comfyui_inputs,
```

Then remove `None` values from `final_params` before returning:

```python
return {key: value for key, value in final_params.items() if value is not None}
```

- [ ] **Step 7: Run renderer tests**

Run:

```powershell
uv run python -m unittest tests.test_multi_backend_renderers
```

Expected: all renderer tests pass. Existing `node_overrides` tests must continue passing.

- [ ] **Step 8: Commit**

```powershell
git add src/tags_machine_core/renderers/comfyui.py tests/test_multi_backend_renderers.py
git commit -m "feat: apply comfyui artist input bindings"
```

---

### Task 4: Filter ComfyUI Output Nodes and Improve Client Errors

**Files:**
- Modify: `F:/my_project/new/tags_machine/refactor/src/tags_machine_core/clients/comfyui.py`
- Test: `F:/my_project/new/tags_machine/refactor/tests/test_multi_backend_clients.py`

- [ ] **Step 1: Add output node filtering test**

Append to `tests/test_multi_backend_clients.py`:

```python
def test_comfyui_client_filters_history_images_by_output_nodes(self):
    history = {
        "abc123": {
            "outputs": {
                "77": {
                    "images": [
                        {"filename": "upscale.png", "subfolder": "", "type": "output"}
                    ]
                },
                "212": {
                    "images": [
                        {"filename": "face.png", "subfolder": "", "type": "output"}
                    ]
                },
            },
            "status": {"completed": True},
        }
    }
    session = FakeComfyUISession(
        get_json={
            "http://comfy.local/history/abc123": history,
        },
        get_bytes={
            "http://comfy.local/view?filename=face.png&subfolder=&type=output": b"PNG"
        },
        post_json={
            "http://comfy.local/prompt": {"prompt_id": "abc123"}
        },
    )
    client = ComfyUIClient(base_url="http://comfy.local", timeout=30, http_client=session)
    request = RenderRequest(
        backend="comfyui",
        prompt="akemi homura",
        params={
            "workflow_json": {"1": {"class_type": "SaveImage", "inputs": {}}},
            "output_nodes": ["212"],
        },
    )

    result = client.generate_images(request)

    self.assertEqual(len(result.images), 1)
    self.assertEqual(result.images[0].filename, "face.png")
    self.assertEqual(result.images[0].node_id, "212")
```

- [ ] **Step 2: Run test to verify failure**

Run:

```powershell
uv run python -m unittest tests.test_multi_backend_clients.ComfyUIClientTest.test_comfyui_client_filters_history_images_by_output_nodes
```

Expected: test fails because the client downloads all output nodes.

- [ ] **Step 3: Add output node parameter**

Change `download_history_images` signature:

```python
def download_history_images(
    self,
    history: dict[str, Any],
    *,
    prompt_id: str | None = None,
    output_nodes: list[str] | None = None,
) -> list[ComfyUIImage]:
```

Add filter:

```python
allowed_nodes = {str(item) for item in output_nodes or [] if str(item)}
for node_id, output in outputs.items():
    if allowed_nodes and str(node_id) not in allowed_nodes:
        continue
    if not isinstance(output, dict):
        continue
```

- [ ] **Step 4: Pass output nodes from request**

In `generate_images`, change the final call to:

```python
images=self.download_history_images(
    history,
    prompt_id=queued.prompt_id,
    output_nodes=[str(item) for item in request.params.get("output_nodes") or []],
),
```

- [ ] **Step 5: Add node error detail to HTTP 400 failures**

In `queue_prompt`, when `response.status_code >= 400`, keep the existing `ComfyUIClientError`, but set `response_text` to include `node_errors` if the response is JSON:

```python
response_text = response.text
try:
    error_data = response.json()
except ValueError:
    error_data = None
if isinstance(error_data, dict) and error_data.get("node_errors"):
    response_text = json.dumps(error_data, ensure_ascii=False)
```

Add `import json`.

- [ ] **Step 6: Run client tests**

Run:

```powershell
uv run python -m unittest tests.test_multi_backend_clients
```

Expected: all ComfyUI client tests pass.

- [ ] **Step 7: Commit**

```powershell
git add src/tags_machine_core/clients/comfyui.py tests/test_multi_backend_clients.py
git commit -m "feat: filter comfyui output nodes"
```

---

### Task 5: Add ComfyUI Config and Sample Splitting

**Files:**
- Modify: `F:/my_project/new/tags_machine/refactor/src/tags_machine_core/config.py`
- Modify: `F:/my_project/new/tags_machine/refactor/src/tags_machine_core/execution.py`
- Test: `F:/my_project/new/tags_machine/refactor/tests/test_execution.py`

- [ ] **Step 1: Add config fields**

In `ComfyUIConfig`, add:

```python
retry: int = 3
retry_interval: float = 2.0
poll_interval: float = 1.0
max_wait_seconds: float | None = None
```

- [ ] **Step 2: Add split generation test**

Append to `tests/test_execution.py`:

```python
def test_split_comfyui_samples_offsets_seed_and_node_override(self):
    request = RenderRequest(
        backend="comfyui",
        prompt="akemi homura",
        seed=100,
        params={
            "n_samples": 3,
            "workflow_json": {"1": {"class_type": "KSampler", "inputs": {}}},
            "node_overrides": {"202.inputs.seed": 100},
            "comfyui_inputs": {"seed": ["202.inputs.seed"]},
        },
    )

    split = split_comfyui_samples(request)

    self.assertEqual([item.seed for item in split], [100, 101, 102])
    self.assertEqual([item.params["n_samples"] for item in split], [1, 1, 1])
    self.assertEqual(
        [item.params["node_overrides"]["202.inputs.seed"] for item in split],
        [100, 101, 102],
    )
```

- [ ] **Step 3: Run test to verify failure**

Run:

```powershell
uv run python -m unittest tests.test_execution.ExecutionTest.test_split_comfyui_samples_offsets_seed_and_node_override
```

Expected: test fails because `split_comfyui_samples` does not exist.

- [ ] **Step 4: Implement ComfyUI sample splitting**

In `execution.py`, add:

```python
def split_comfyui_samples(request: RenderRequest) -> list[RenderRequest]:
    count = _request_n_samples(request)
    if count <= 1:
        return [request]

    logger.info("split ComfyUI n_samples into repeated prompts count=%s", count)
    return [_single_comfyui_sample_request(request, index, count) for index in range(count)]


def _single_comfyui_sample_request(
    request: RenderRequest,
    index: int,
    count: int,
) -> RenderRequest:
    params = dict(request.params)
    seed = _offset_novelai_seed(params.get("seed", request.seed), index)
    params["n_samples"] = 1
    if seed is not None:
        params["seed"] = seed
    node_overrides = dict(params.get("node_overrides") or {})
    comfyui_inputs = params.get("comfyui_inputs") or {}
    seed_paths = comfyui_inputs.get("seed") if isinstance(comfyui_inputs, dict) else []
    if seed is not None:
        for path in seed_paths or []:
            node_overrides[str(path)] = seed
    params["node_overrides"] = node_overrides

    meta = dict(request.meta)
    meta["split_batch"] = {
        "index": index,
        "count": count,
        "reason": "repeat_comfyui_prompt",
    }
    return request.model_copy(
        deep=True,
        update={
            "seed": seed if seed is not None else request.seed,
            "params": params,
            "meta": meta,
        },
    )
```

Reuse `_request_n_samples` and `_offset_novelai_seed` to preserve current seed validation semantics.

- [ ] **Step 5: Use split requests in `execute_comfyui_generation`**

At the start of `execute_comfyui_generation`, add:

```python
requests = split_comfyui_samples(request)
output_path = Path(output_dir or config.runtime.output_dir)
```

If `len(requests) == 1`, keep the current behavior. If more than one, mirror the NovelAI split result shape:

```python
images: list[GeneratedImage] = []
png_records: list[dict[str, Any]] = []
request_bodies: list[dict[str, Any]] = []
comfyui_records: list[dict[str, Any]] = []
for index, split_request in enumerate(requests):
    generated = execute_comfyui_generation(
        config,
        split_request,
        output_dir=output_path,
        image_format=image_format,
        client_id=client_id,
        no_wait=no_wait,
        poll_interval=poll_interval,
        max_wait_seconds=max_wait_seconds,
    )
    images.extend(
        image.model_copy(
            update={"meta": {**image.meta, "split_request_index": index}}
        )
        for image in generated.images
    )
    request_bodies.append(generated.request_body)
    comfyui_records.append(generated.png_info.get("comfyui", {}))
    for record in generated.png_info.get("images", []):
        if isinstance(record, dict):
            record["split_request_index"] = index
            png_records.append(record)

return GenerationResult(
    backend="comfyui",
    images=images,
    request_body={
        "split_batch": True,
        "reason": "repeat_comfyui_prompt",
        "requests": request_bodies,
    },
    png_info={"images": png_records, "comfyui": {"split_batch": comfyui_records}},
    cache_hit=False,
)
```

Guard this recursive call so the split branch only triggers when `len(requests) > 1`.

- [ ] **Step 6: Use config polling defaults**

In `execute_render_request`, when calling `execute_comfyui_generation`, pass:

```python
poll_interval=comfyui_poll_interval or config.comfyui.poll_interval,
max_wait_seconds=(
    comfyui_max_wait_seconds
    if comfyui_max_wait_seconds is not None
    else config.comfyui.max_wait_seconds
),
```

Keep CLI arguments as explicit overrides.

- [ ] **Step 7: Run execution tests**

Run:

```powershell
uv run python -m unittest tests.test_execution
```

Expected: tests pass.

- [ ] **Step 8: Commit**

```powershell
git add src/tags_machine_core/config.py src/tags_machine_core/execution.py tests/test_execution.py
git commit -m "feat: split comfyui samples into repeated prompts"
```

---

### Task 6: Promote ComfyUI to Opt-In Executable Backend

**Files:**
- Modify: `F:/my_project/new/tags_machine/refactor/src/tags_machine_core/backends.py`
- Test: `F:/my_project/new/tags_machine/refactor/tests/test_backend_support.py`

- [ ] **Step 1: Update backend support expectations**

In `tests/test_backend_support.py`, update ComfyUI assertions:

```python
self.assertEqual(items["comfyui"]["stage"], "stable")
self.assertTrue(items["comfyui"]["execution_supported"])
self.assertTrue(items["comfyui"]["executes_by_default"])
self.assertFalse(items["comfyui"]["requires_experimental_execution"])
```

Update the experimental list expectation to keep only SD:

```python
self.assertEqual(report["experimental_execution_backends"], ["sd"])
```

- [ ] **Step 2: Run backend tests to verify failure**

Run:

```powershell
uv run python -m unittest tests.test_backend_support
```

Expected: tests fail with old ComfyUI experimental expectations.

- [ ] **Step 3: Update ComfyUI support record**

In `backends.py`, set:

```python
"comfyui": BackendSupport(
    backend="comfyui",
    display_name="ComfyUI",
    stage="stable",
    render_plan_supported=True,
    execution_supported=True,
    executes_by_default=True,
    requires_experimental_execution=False,
    note="正式 opt-in 执行后端；默认项目后端仍由 config.defaults.backend 控制。",
),
```

SD remains experimental.

- [ ] **Step 4: Run backend tests**

Run:

```powershell
uv run python -m unittest tests.test_backend_support
```

Expected: tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/tags_machine_core/backends.py tests/test_backend_support.py
git commit -m "feat: promote comfyui backend execution"
```

---

### Task 7: Add Backend-Aware `run-prompt` and `run-action`

**Files:**
- Modify: `F:/my_project/new/tags_machine/refactor/src/tags_machine_core/cli.py`
- Test: `F:/my_project/new/tags_machine/refactor/tests/test_cli_nodes.py`

- [ ] **Step 1: Add CLI test for ComfyUI run-prompt dry-run**

Append to `tests/test_cli_nodes.py`:

```python
def test_run_prompt_supports_comfyui_backend_dry_run(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        artist = root / "artist"
        workflow_dir = artist / "workflows"
        workflow_dir.mkdir(parents=True)
        (workflow_dir / "api.json").write_text(
            json.dumps(
                {
                    "3": {"class_type": "KSampler", "inputs": {"seed": 1}},
                    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}},
                    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}},
                    "23": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512}},
                }
            ),
            encoding="utf-8",
        )
        (artist / "node.yaml").write_text(
            """
schema: tags-machine-core.node/v1
kind: artist
id: comfy_test
renderers:
  comfyui:
    workflow: test
    workflow_path: workflows/api.json
    inputs:
      positive_prompt: "6.inputs.text"
      negative_prompt: "7.inputs.text"
      width: "23.inputs.width"
      height: "23.inputs.height"
      seed: "3.inputs.seed"
""",
            encoding="utf-8",
        )

        output = run_cli(
            [
                "run-prompt",
                "--backend",
                "comfyui",
                "--prompt",
                "akemi homura",
                "--negative",
                "bad hands",
                "--artist-node",
                str(artist),
                "--width",
                "832",
                "--height",
                "1216",
                "--seed",
                "123",
                "--nt",
                "1",
                "--dry-run",
                "--full",
            ]
        )

    data = json.loads(output)
    request = data["render_request"]
    self.assertEqual(request["backend"], "comfyui")
    self.assertEqual(request["params"]["node_overrides"]["6.inputs.text"], "akemi homura")
    self.assertEqual(request["params"]["node_overrides"]["7.inputs.text"], "bad hands")
    self.assertEqual(request["params"]["node_overrides"]["23.inputs.width"], 832)
    self.assertEqual(request["params"]["node_overrides"]["23.inputs.height"], 1216)
    self.assertEqual(request["params"]["node_overrides"]["3.inputs.seed"], 123)
```

- [ ] **Step 2: Run test to verify failure**

Run:

```powershell
uv run python -m unittest tests.test_cli_nodes.CliNodeTest.test_run_prompt_supports_comfyui_backend_dry_run
```

Expected: test fails because `run-prompt` does not expose `--backend` and still calls NovelAI-specific artifact building.

- [ ] **Step 3: Add backend argument**

In `_add_prompt_run_arguments`, add:

```python
parser.add_argument("--backend", default="novelai", choices=RENDER_BACKENDS)
```

- [ ] **Step 4: Build generic prompt artifacts**

Replace `_build_novelai_prompt_artifacts` with a backend-aware wrapper:

```python
def _build_prompt_artifacts(service: GenerationService, args):
    if args.backend == "novelai":
        return _build_novelai_prompt_artifacts(service, args)
    prompt = _read_prompt_value(args)
    if not prompt:
        raise ValueError("run-prompt requires --prompt or --prompt-file")
    artist_ref, artist = _load_render_artist(args)
    resolved_nodes = _read_resolved_nodes(args, artist_ref=artist_ref, artist=artist)
    bundle = service.compose_full_prompt(
        prompt=prompt,
        negative=args.negative or "",
        prompt_policy=_prompt_policy_from_args(args, target="full_prompt"),
    )
    params = _load_json_arg(args.params_json)
    params["n_samples"] = args.nt
    request = service.build_render_request(
        bundle,
        backend=args.backend,
        seed=args.seed,
        artist=artist,
        resolved_nodes=resolved_nodes,
        width=args.width,
        height=args.height,
        model=args.model,
        action=_render_action(args.backend),
        params=params,
    )
    return bundle, request
```

Update `cmd_run_prompt` to call `_build_prompt_artifacts`.

- [ ] **Step 5: Add backend-aware run-action wrapper**

Replace `cmd_run_action` artifact call with:

```python
bundle, request = _build_action_artifacts(service, args)
```

Add:

```python
def _build_action_artifacts(service: GenerationService, args):
    if getattr(args, "backend", "novelai") == "novelai":
        return _build_novelai_action_artifacts(service, args)
    artist_ref, artist = _load_render_artist(args)
    resolved_nodes = _read_resolved_nodes(args, artist_ref=artist_ref, artist=artist)
    bundle = service.compose_resolved_nodes(
        resolved_nodes,
        extra_prompt=args.extra_prompt or "",
        negative=args.negative or "",
        character_scope=args.character_scope or args.body_scope,
        prompt_policy=_prompt_policy_from_args(args, target="script"),
    )
    params = _load_json_arg(args.params_json)
    params["n_samples"] = args.nt
    request = service.build_render_request(
        bundle,
        backend=args.backend,
        seed=args.seed,
        artist=artist,
        resolved_nodes=resolved_nodes,
        width=args.width,
        height=args.height,
        model=args.model,
        action=_render_action(args.backend),
        params=params,
    )
    return bundle, request
```

- [ ] **Step 6: Allow ComfyUI execution without experimental flag**

In `cmd_run_prompt` and `cmd_run_action`, keep:

```python
allow_experimental_backend=False
```

This works after Task 6 because ComfyUI no longer requires the experimental gate.

- [ ] **Step 7: Run CLI tests**

Run:

```powershell
uv run python -m unittest tests.test_cli_nodes
```

Expected: tests pass.

- [ ] **Step 8: Commit**

```powershell
git add src/tags_machine_core/cli.py tests/test_cli_nodes.py
git commit -m "feat: support comfyui run prompt entrypoint"
```

---

### Task 8: Ensure Batch Uses ComfyUI Cleanly

**Files:**
- Modify: `F:/my_project/new/tags_machine/refactor/src/tags_machine_core/batch/executor.py`
- Modify: `F:/my_project/new/tags_machine/refactor/src/tags_machine_core/batch/runner.py`
- Test: `F:/my_project/new/tags_machine/refactor/tests/test_batch_generation.py`

- [ ] **Step 1: Add batch render plan test**

Append to `tests/test_batch_generation.py`:

```python
def test_batch_executor_builds_comfyui_request(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        artist = root / "artist"
        workflow_dir = artist / "workflows"
        workflow_dir.mkdir(parents=True)
        (workflow_dir / "api.json").write_text(
            json.dumps(
                {
                    "3": {"class_type": "KSampler", "inputs": {"seed": 1}},
                    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}},
                    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}},
                    "23": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512}},
                }
            ),
            encoding="utf-8",
        )
        (artist / "node.yaml").write_text(
            """
schema: tags-machine-core.node/v1
kind: artist
id: comfy_test
renderers:
  comfyui:
    workflow: test
    workflow_path: workflows/api.json
    inputs:
      positive_prompt: "6.inputs.text"
      negative_prompt: "7.inputs.text"
      width: "23.inputs.width"
      height: "23.inputs.height"
      seed: "3.inputs.seed"
""",
            encoding="utf-8",
        )
        config = AppConfig.model_validate(
            {
                "legacy": {"tags_machine_root": str(root), "design_root": str(root)},
                "runtime": {"output_dir": str(root / "outputs")},
            }
        )
        task = BatchTask(
            id="task1",
            composer="full",
            prompt="akemi homura",
            nodes=[],
            render={
                "backend": "comfyui",
                "artist": str(artist),
                "width": 832,
                "height": 1216,
                "seed": 123,
                "nt": 1,
                "image_format": "png",
            },
            output={"task_dir": str(root / "tasks" / "task1"), "output_dir": str(root / "out" / "task1")},
        )

        with patch("tags_machine_core.batch.executor.execute_render_request") as execute:
            execute.return_value = GenerationResult(backend="comfyui", images=[])
            result = BatchExecutor().execute(task, config=config)

    self.assertEqual(result.status, "succeeded")
    request = execute.call_args.args[1]
    self.assertEqual(request.backend, "comfyui")
    self.assertEqual(request.params["node_overrides"]["6.inputs.text"], "akemi homura")
```

- [ ] **Step 2: Run test**

Run:

```powershell
uv run python -m unittest tests.test_batch_generation.BatchGenerationTest.test_batch_executor_builds_comfyui_request
```

Expected: pass after Tasks 3, 6, and 7. If it fails because `BatchTask` shape differs, adjust only the test construction to match `batch/models.py`.

- [ ] **Step 3: Ensure output config passes through**

Confirm `BatchExecutor.execute` passes:

```python
allow_experimental_backend=False
```

No special ComfyUI gate should remain after Task 6.

- [ ] **Step 4: Ensure timeout applies to ComfyUI**

`batch/runner.py` already updates `config.comfyui.timeout` in `_config_with_timeout`. Keep that behavior and add config fields if needed:

```python
"comfyui": config.comfyui.model_copy(update={"timeout": timeout}),
```

- [ ] **Step 5: Run batch tests**

Run:

```powershell
uv run python -m unittest tests.test_batch_generation
```

Expected: tests pass.

- [ ] **Step 6: Commit**

```powershell
git add src/tags_machine_core/batch/executor.py src/tags_machine_core/batch/runner.py tests/test_batch_generation.py
git commit -m "feat: support comfyui batch execution"
```

---

### Task 9: Add Compact ComfyUI Parameter Details

**Files:**
- Modify: `F:/my_project/new/tags_machine/refactor/src/tags_machine_core/batch/parameter_image.py`
- Test: `F:/my_project/new/tags_machine/refactor/tests/test_batch_generation.py`

- [ ] **Step 1: Add parameter image test**

Append to `tests/test_batch_generation.py`:

```python
def test_parameter_details_shows_compact_comfyui_fields(self):
    from tags_machine_core.batch.parameter_image import _display_parameters

    request = {
        "backend": "comfyui",
        "params": {
            "workflow": "cunyfunky",
            "workflow_hash": "sha256:abc",
            "output_nodes": ["212"],
            "node_overrides": {
                "218.inputs.wildcard_text": "akemi homura",
                "153.inputs.text": "bad hands",
                "202.inputs.seed": 123,
            },
        },
    }
    params = {
        "workflow": "cunyfunky",
        "workflow_hash": "sha256:abc",
        "output_nodes": ["212"],
    }

    lines = _display_parameters(request=request, params=params)

    text = "\n".join(lines)
    self.assertIn("workflow: cunyfunky", text)
    self.assertIn("workflow_hash: sha256:abc", text)
    self.assertIn("output_nodes: 212", text)
    self.assertNotIn("workflow_json", text)
```

- [ ] **Step 2: Run test to verify failure**

Run:

```powershell
uv run python -m unittest tests.test_batch_generation.BatchGenerationTest.test_parameter_details_shows_compact_comfyui_fields
```

Expected: fails because ComfyUI display is not specialized.

- [ ] **Step 3: Add ComfyUI parameter display branch**

In `parameter_image.py`, when backend is `comfyui`, display only compact fields:

```python
def _comfyui_parameter_lines(params: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    workflow = params.get("workflow")
    workflow_hash = params.get("workflow_hash")
    output_nodes = params.get("output_nodes") or []
    if workflow:
        lines.append(f"workflow: {workflow}")
    if workflow_hash:
        lines.append(f"workflow_hash: {workflow_hash}")
    if output_nodes:
        lines.append("output_nodes: " + ", ".join(str(item) for item in output_nodes))
    return lines or ["workflow: -"]
```

Ensure `workflow_json` is never rendered into the parameter image.

- [ ] **Step 4: Run parameter image tests**

Run:

```powershell
uv run python -m unittest tests.test_batch_generation.BatchGenerationTest.test_parameter_details_shows_compact_comfyui_fields tests.test_batch_generation.BatchGenerationTest.test_archive_creates_parameter_details_image
```

Expected: tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/tags_machine_core/batch/parameter_image.py tests/test_batch_generation.py
git commit -m "feat: show compact comfyui parameter details"
```

---

### Task 10: Update Config and Usage Docs

**Files:**
- Modify: `F:/my_project/new/tags_machine/refactor/configs/local.example.yaml`
- Modify: `F:/my_project/new/tags_machine/refactor/docs/batch_generation_readme.md`
- Modify: `F:/my_project/new/tags_machine/refactor/docs/refactor_architecture_v2.md`

- [ ] **Step 1: Update local config example**

Add:

```yaml
comfyui:
  base_url: "http://127.0.0.1:8188"
  timeout: 300
  poll_interval: 1.0
  max_wait_seconds: 600
  retry: 3
  retry_interval: 2.0
```

- [ ] **Step 2: Add run-prompt usage**

In `docs/batch_generation_readme.md`, add:

```markdown
## ComfyUI run-prompt

```powershell
uv run python -m tags_machine_core run-prompt `
  --backend comfyui `
  --prompt "akemi_homura, 1girl, magical_girl, standing" `
  --negative "bad hands" `
  --artist-node examples\nodes\artists\comfyui_cunyfunky `
  --width 1024 `
  --height 1536 `
  --seed 123456 `
  --nt 1 `
  --config configs\local.yaml `
  --output-dir outputs\comfyui_cunyfunky_acceptance `
  --full
```

ComfyUI artist node 的 `workflow_path` 必须指向 API workflow，也就是 ComfyUI `File -> Export (API)` 导出的 JSON。
```

- [ ] **Step 3: Update architecture doc**

In `docs/refactor_architecture_v2.md`, update ComfyUI status:

```markdown
ComfyUI 是正式 opt-in 执行后端。它通过 artist node 的 `renderers.comfyui.workflow_path` 读取 API workflow，并只 patch prompt、negative、size、seed 等外部输入。checkpoint、VAE、LoRA、upscale 和 custom node 由 workflow 自身控制。
```

- [ ] **Step 4: Run documentation grep**

Run:

```powershell
rg -n "ComfyUI|comfyui_cunyfunky|Export \\(API\\)" docs configs examples
```

Expected: new docs and example config are discoverable.

- [ ] **Step 5: Commit**

```powershell
git add configs/local.example.yaml docs/batch_generation_readme.md docs/refactor_architecture_v2.md
git commit -m "docs: document comfyui aki workflow usage"
```

---

### Task 11: Real Business Validation With Aki ComfyUI

**Files:**
- Create: `F:/my_project/new/tags_machine/refactor/docs/comfyui_aki_cunyfunky_business_test_20260704.md`

- [ ] **Step 1: Start Aki ComfyUI**

From a PowerShell terminal:

```powershell
cd D:\AI\ComfyUI-aki\ComfyUI-aki-v1.6
.\python\python.exe .\ComfyUI\main.py --listen 127.0.0.1 --port 8188
```

Expected: ComfyUI reports it is listening at `http://127.0.0.1:8188`.

- [ ] **Step 2: Check API is reachable**

Run:

```powershell
Invoke-RestMethod http://127.0.0.1:8188/object_info | Select-Object -First 1
```

Expected: JSON object is returned. If this fails, do not run core generation.

- [ ] **Step 3: Run real ComfyUI generation**

Run:

```powershell
uv run python -m tags_machine_core run-prompt `
  --backend comfyui `
  --prompt "akemi_homura, 1girl, black_hair, purple_eyes, magical_girl, standing, looking_at_viewer" `
  --negative "bad hands, low quality" `
  --artist-node examples\nodes\artists\comfyui_cunyfunky `
  --width 1024 `
  --height 1536 `
  --seed 123456 `
  --nt 1 `
  --config configs\local.yaml `
  --output-dir outputs\comfyui_cunyfunky_acceptance `
  --full
```

Expected:

- Command exits with status 0.
- Output JSON contains `generation_result.backend = "comfyui"`.
- At least one image path exists under `outputs/comfyui_cunyfunky_acceptance`.
- `generation_result.png_info.comfyui.prompt_id` is present.
- `generation_result.request_body.prompt` contains patched workflow JSON.

- [ ] **Step 4: Inspect generated image paths**

Open the generated image paths returned by the command. Record:

```markdown
| image | visual_result | notes |
| --- | --- | --- |
| `<absolute image path>` | pass/fail | 主体、画风、构图是否符合 cunyfunky workflow 预期 |
```

- [ ] **Step 5: Run a tiny batch**

Create `examples/batches/comfyui_cunyfunky_smoke.yaml`:

```yaml
schema: tags-machine-core.batch/v1
id: comfyui-cunyfunky-smoke
description: ComfyUI Aki cunyfunky business validation

defaults:
  composer: full
  backend: comfyui
  artist: examples/nodes/artists/comfyui_cunyfunky

render:
  width: 1024
  height: 1536
  seed: 123456
  nt: 1
  image_format: png

output:
  output_dir: outputs/comfyui_cunyfunky_batch
  save_parameter_image: true
  task_folder: true

items:
  - id: comfyui_prompt_001
    prompt: "akemi_homura, 1girl, black_hair, purple_eyes, magical_girl, standing, looking_at_viewer"
    negative: "bad hands, low quality"
  - id: comfyui_prompt_002
    prompt: "akemi_homura, 1girl, black_hair, purple_eyes, magical_girl, sitting, indoors"
    negative: "bad hands, low quality"
  - id: comfyui_prompt_003
    prompt: "akemi_homura, 1girl, black_hair, purple_eyes, magical_girl, upper_body, portrait"
    negative: "bad hands, low quality"
```

Run:

```powershell
uv run python -m tags_machine_core run-batch examples\batches\comfyui_cunyfunky_smoke.yaml --fresh --full --config configs\local.yaml
```

Expected:

- Three tasks succeed or failures are recorded with ComfyUI node error details.
- Each successful task has image output.
- Each successful task has `zz_<task_id>_parameter_details.png`.

- [ ] **Step 6: Write business report**

Create `docs/comfyui_aki_cunyfunky_business_test_20260704.md`:

```markdown
# ComfyUI Aki Cunyfunky Business Test 2026-07-04

## Environment

- ComfyUI: D:/AI/ComfyUI-aki/ComfyUI-aki-v1.6/ComfyUI
- Base URL: http://127.0.0.1:8188
- Artist node: examples/nodes/artists/comfyui_cunyfunky
- Workflow: examples/nodes/artists/comfyui_cunyfunky/workflows/cunyfunky_api.json

## Single run-prompt

| field | value |
| --- | --- |
| status | pass/fail |
| prompt_id | `<prompt_id>` |
| image_count | `<count>` |
| output_dir | `<output_dir>` |
| visual_result | pass/fail |

## Batch run

| task_id | status | image_paths | parameter_details | visual_result | notes |
| --- | --- | --- | --- | --- | --- |
| comfyui_prompt_001 | pass/fail | `<paths>` | `<path>` | pass/fail | `<notes>` |
| comfyui_prompt_002 | pass/fail | `<paths>` | `<path>` | pass/fail | `<notes>` |
| comfyui_prompt_003 | pass/fail | `<paths>` | `<path>` | pass/fail | `<notes>` |

## Conclusion

ComfyUI Aki cunyfunky is accepted when run-prompt and batch both produce images without manual UI interaction and parameter archives identify workflow, prompt_id, seed, size, and selected output nodes.
```

- [ ] **Step 7: Commit business report and example batch**

```powershell
git add examples/batches/comfyui_cunyfunky_smoke.yaml docs/comfyui_aki_cunyfunky_business_test_20260704.md
git commit -m "test: record comfyui cunyfunky business validation"
```

---

## 6. Acceptance Criteria

The implementation is accepted only when all items below are true:

- `run-prompt --backend comfyui` can generate a real image through the Aki ComfyUI server.
- Batch can run at least three ComfyUI tasks and archive outputs.
- `PromptBundle` remains backend-neutral and contains no workflow JSON, node paths, checkpoint, LoRA, VAE, or ComfyUI parameters.
- `RenderRequest.params.workflow_json` is an API workflow, not a UI workflow.
- `renderers.comfyui.inputs` controls prompt, negative prompt, width, height, and seed patching.
- `optional_inputs` preserves workflow defaults unless explicit CLI or batch params are passed.
- `nt > 1` submits repeated prompts with seed offsets and `n_samples=1` per submitted request.
- `GenerationResult.png_info.comfyui.prompt_id` is recorded for each real run.
- Parameter details image shows compact ComfyUI fields and never renders full `workflow_json`.
- Business test document includes generated image paths and human visual result.

---

## 7. Self-Review Checklist

- Spec coverage: The plan covers artist node structure, workflow validation, renderer patching, client execution, batch execution, server deployment, parameter details, and real Aki validation.
- Placeholder scan: The plan avoids unresolved node paths; `cunyfunky` paths are concrete and based on `C:/Downloads/cunyfunky_api.json`.
- Type consistency: `inputs`, `optional_inputs`, `output_nodes`, `node_overrides`, `workflow_hash`, and `comfyui_inputs` are consistently stored under `renderers.comfyui` or `RenderRequest.params`.
- Business priority: Real ComfyUI generation is a required task, not an optional follow-up.
