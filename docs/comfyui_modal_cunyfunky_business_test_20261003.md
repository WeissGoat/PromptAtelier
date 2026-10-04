# ComfyUI Modal Cunyfunky Business Test 2026-10-03

## Environment

- Runtime: `deploy/comfyui/`（`manifest.yaml` + `models.yaml` + `Dockerfile`），Modal 适配层 `deploy/comfyui/providers/modal_app.py`
- Modal app: `tm-comfyui`，函数 `api`（`web_server`，proxy auth，`max_containers=1`，`scaledown_window=120`）
- GPU: L40S
- ComfyUI: v0.3.59（`72212fef`），5 个插件钉在与本地 aki 一致的 commit，Impact Pack 带 DifferentialDiffusion 兼容补丁
- Models: Modal Volume `tm-comfyui-models`，10 个文件（约 7.6 GB），云端逐个 sha256 校验通过
- Target: `configs/local.yaml` 的 `comfyui.targets.modal`（`path_style: posix`，`cold_start_wait_seconds: 300`，`allow_no_wait: false`）
- Artist node: `examples/nodes/artists/comfyui_cunyfunky`（提交前裁剪到 `output_nodes: [212]`，64 → 24 个节点）

## Live preflight

```powershell
uv run python -m tags_machine_core comfyui-check --artist-node examples/nodes/artists/comfyui_cunyfunky --manifest deploy/comfyui/manifest.yaml --config configs/local.yaml --comfyui-target modal --live
```

| field | value |
| --- | --- |
| ok | true |
| missing class types | none |
| missing values | none |
| elapsed (including cold start) | 26 s |

## Batch run

```powershell
uv run python -m tags_machine_core run-batch examples/batches/comfyui_cunyfunky_smoke.yaml --comfyui-target modal --work-root outputs/modal_smoke/work --output-dir outputs/modal_smoke/images --log-level info
```

| task_id | status | executed outputs | ComfyUI execution | correlation vs local 2026-07-04 |
| --- | --- | --- | --- | --- |
| `comfyui_prompt_001` | pass | `212` | 70.2 s（容器内首次加载模型） | 0.998 |
| `comfyui_prompt_002` | pass | `212` | 21.4 s | 0.997 |
| `comfyui_prompt_003` | pass | `212` | 23.5 s | 1.000 |

- Batch wall time: 148 s for 3 images.
- Images: 1128 x 1688 PNG, about 2 MB each.
- Correlation: 128 x 192 grayscale Pearson correlation against the local aki images with the same prompt and seed.
- Local baseline (RTX 3060 Ti 8GB, 2026-07-04): 108-119 s per image warm.

## Cost

`modal billing summary` after the whole setup session (image builds, model download/verify, live preflight, smoke batch):
metered $0.28, covered by Starter credits, billed $0.00.

## Checks

- Requests without a proxy token get HTTP 401 from Modal's edge in about 1.6 s and do not start a container.
- `png_info.comfyui.target` records `modal`; `workflow_preparation` records 24 nodes and the 4 normalized LoRA paths.
- Only output node `212` executed; the preview branches and the `Always pause` Preview Chooser branch were pruned.

## Conclusion

The Modal target produces the same images as local aki for the cunyfunky workflow, about 5x faster per warm image.
Switching between local and cloud is a config choice (`--comfyui-target`, `TAGS_MACHINE_CORE_COMFYUI_TARGET`, or `comfyui.default_target`).
