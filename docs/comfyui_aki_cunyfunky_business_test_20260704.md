# ComfyUI Aki Cunyfunky Business Test 2026-07-04

## Environment

- ComfyUI: `D:/AI/ComfyUI-aki/ComfyUI-aki-v1.6/ComfyUI`
- Base URL: `http://127.0.0.1:8188`
- ComfyUI version: `0.3.59`
- Artist node: `examples/nodes/artists/comfyui_cunyfunky`
- Workflow: `examples/nodes/artists/comfyui_cunyfunky/workflows/cunyfunky_api.json`
- Workflow hash: `sha256:460e1487dc764d94898905bbdbfdcf27a3ca4a9bfad0ba87ab8454bfb15db26d`

## Single run-prompt

Command:

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
  --config configs\local.example.yaml `
  --output-dir outputs\comfyui_cunyfunky_acceptance `
  --full `
  --log-level info
```

| field | value |
| --- | --- |
| status | pass |
| prompt_id | `fe7a8eef-39e3-4b05-aac6-00f940407316` |
| image_count | 1 |
| image_path | `F:/my_project/new/tags_machine/refactor/outputs/comfyui_cunyfunky_acceptance/42862c9f_123456_01.png` |
| output_nodes | `212` |
| visual_result | pass |

Visual note: image shows Akemi Homura-like character, black hair, purple eyes, magical girl outfit, standing portrait composition, and the expected cunyfunky workflow rendering style.

## Batch run

Command:

```powershell
uv run python -m tags_machine_core run-batch examples\batches\comfyui_cunyfunky_smoke.yaml `
  --fresh `
  --config configs\local.example.yaml `
  --log-level info
```

| task_id | status | prompt_id | image_path | parameter_details | visual_result |
| --- | --- | --- | --- | --- | --- |
| `comfyui_prompt_001` | pass | `2affc119-b431-42ff-8b79-96d78ec78376` | `F:/my_project/new/tags_machine/refactor/examples/batches/outputs/comfyui_cunyfunky_batch/comfyui_prompt_001/ada9b8b9_123456_01.png` | `F:/my_project/new/tags_machine/refactor/examples/batches/outputs/comfyui_cunyfunky_batch/comfyui_prompt_001/zz_comfyui_prompt_001_parameter_details.png` | pass |
| `comfyui_prompt_002` | pass | `cef8ccc0-37fa-47d1-8868-1972a9d6fc18` | `F:/my_project/new/tags_machine/refactor/examples/batches/outputs/comfyui_cunyfunky_batch/comfyui_prompt_002/cf0c25f5_123456_01.png` | `F:/my_project/new/tags_machine/refactor/examples/batches/outputs/comfyui_cunyfunky_batch/comfyui_prompt_002/zz_comfyui_prompt_002_parameter_details.png` | pass |
| `comfyui_prompt_003` | pass | `e1678292-24de-4a31-9210-43720db01edc` | `F:/my_project/new/tags_machine/refactor/examples/batches/outputs/comfyui_cunyfunky_batch/comfyui_prompt_003/facce0d9_123456_01.png` | `F:/my_project/new/tags_machine/refactor/examples/batches/outputs/comfyui_cunyfunky_batch/comfyui_prompt_003/zz_comfyui_prompt_003_parameter_details.png` | pass |

## Checks

- `run-prompt --backend comfyui` produced a real image through Aki ComfyUI.
- Batch produced 3 succeeded tasks with one image per task.
- Output paths use `output_dir/<task_id>/*`.
- `RenderRequest.model` is `null` for ComfyUI; checkpoint/model remains controlled by workflow.
- `GenerationResult.request_body.prompt` contains patched workflow values:
  - `218.inputs.wildcard_text`: final positive prompt.
  - `153.inputs.text`: final negative prompt.
  - `23.inputs.width`: `1024`.
  - `23.inputs.height`: `1536`.
  - `202.inputs.seed`: `123456`.
- Parameter details images show compact ComfyUI fields and do not render full `workflow_json`.

## Conclusion

ComfyUI Aki `comfyui_cunyfunky` is accepted for the first integration slice. The core pipeline can compose a backend-neutral `PromptBundle`, patch the ComfyUI API workflow through the artist node bindings, execute real generation, archive images and JSON artifacts, and run batch tasks without manual UI interaction.
