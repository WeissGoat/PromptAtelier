# Publishing Workspace 自动打码接入设计

## 1. 文档状态

状态：设计已确认，等待实现计划。

本设计接入 `anr_plugin_auto_mosaics`，使 Publishing Workspace 的 `mosaic` Operation 可以执行真实的 YOLO 或 YOLO+SAM 自动打码。

## 2. 已确认决策

- 插件源码迁入 `tools/publishing_workspace`，运行时不依赖 `F:\ThreeState`。
- 迁移旧目录中当前本地修改后的核心实现，不直接使用未修改的上游版本。
- 删除插件的 Gradio UI、当前工作目录假设和全局可变 `config.json`。
- 模型存放在 Publishing Workspace 项目目录下，但不进入 Git。
- 模型默认从配置 URL 下载；当前迁移允许通过 `--source` 从旧模型目录复制。
- 重依赖使用可选 `mosaic` extra，不影响普通 `uv sync`。
- task 使用稳定英文枚举，不暴露旧插件内部中文标签。
- 模型缺失、依赖缺失、校验失败或处理失败时阻止正式 build。
- 继续使用现有原子 build、处理缓存和 Operation Registry。

## 3. 非目标

- 不接入 Gradio UI。
- 不修改 `F:\ThreeState`。
- 不在本阶段支持视频打码。
- 不自动提交大模型文件到 Git。
- 不实现在线模型训练或模型切换市场。
- 不改变 `strip_metadata` 的默认开启行为。

## 4. 许可证边界

上游项目：

```text
https://github.com/zhulinyv/anr_plugin_auto_mosaics
```

上游许可证为 GPLv3。迁移后必须保留：

```text
tools/publishing_workspace/third_party/anr_plugin_auto_mosaics/LICENSE
tools/publishing_workspace/third_party/anr_plugin_auto_mosaics/NOTICE.md
```

`NOTICE.md` 记录上游地址、迁移日期、迁移来源和本地修改说明。迁移后的源码文件保留 GPLv3 来源声明。发布包含该实现的项目时需要遵守 GPLv3。

## 5. 目录结构

```text
tools/publishing_workspace/
  models/
    anr_plugin_auto_mosaics/
      yolo/
        censor.pt
      sams/
        sam_vit_b_01ec64.pth
  assets/
    anr_plugin_auto_mosaics/
      emoji/
  third_party/
    anr_plugin_auto_mosaics/
      LICENSE
      NOTICE.md
  src/publishing_workspace/
    integrations/
      anr_mosaic/
        __init__.py
        adapter.py
        constants.py
        detector.py
        model_manager.py
        mosaics.py
        sam_detector.py
        settings.py
```

模型目录加入 `.gitignore`。仓库只提交目录说明或 `.gitkeep`，不提交 `.pt` 和 `.pth`。

## 6. 可选依赖

`pyproject.toml` 增加：

```toml
[project.optional-dependencies]
mosaic = [
  "numpy",
  "opencv-python",
  "requests",
  "scipy",
  "segment-anything",
  "torch",
  "ultralytics",
]
```

安装方式：

```powershell
uv sync --extra mosaic
```

如果用户需要特定 CUDA 版本的 PyTorch，可以在安装 extra 前按 PyTorch 官方方式安装对应 wheel。Adapter 不绑定 CUDA 版本，运行时使用 PyTorch 当前可用设备。

普通 `uv sync` 不安装这些依赖，公共 Catalog、Reader、Exporter 和未启用 mosaic 的任务仍可正常工作。

迁移代码统一使用 Publishing Workspace 已有日志接口，不继续依赖旧插件的 `loguru` 封装。

## 7. Workspace 配置

`workspace.yaml` 增加可选配置：

```yaml
integrations:
  mosaic:
    provider: anr_plugin_auto_mosaics
    model_root: null
    models:
      yolo:
        filename: yolo/censor.pt
        url: https://github.com/zhulinyv/anr_plugin_auto_mosaics/raw/main/models/yolo/censor.pt
        sha256: 62b18176b005ec5b8918d3fdd99323193ba2dd99c06e150de808087d37ebe009
      sam:
        filename: sams/sam_vit_b_01ec64.pth
        url: https://huggingface.co/datasets/Xytpz/SAM_Models/resolve/main/sam_vit_b_01ec64.pth?download=true
        sha256: ec2df62732614e57411cdcf32a23ffdf28910380d03139ee0f4fcbe91eb8c912
```

`model_root: null` 时使用：

```text
tools/publishing_workspace/models/anr_plugin_auto_mosaics
```

显式路径可以是绝对路径，也可以是相对 Publishing 根目录的路径。运行时不读取旧插件配置文件。

旧 workspace 配置没有 `integrations` 时继续按默认值加载，不需要手工迁移。

## 8. 模型管理

新增固定 CLI：

```powershell
publishing-workspace mosaic status <root>
publishing-workspace mosaic install <root>
publishing-workspace mosaic install <root> --source <models-directory>
```

默认下载流程：

1. 读取 `workspace.yaml` 中的模型 manifest。
2. 已存在且 SHA-256 正确的模型直接跳过。
3. 下载到同目录临时文件。
4. 计算 SHA-256。
5. 校验通过后原子替换到正式路径。
6. 校验失败或网络中断时删除临时文件，不覆盖已有正确模型。

当前迁移可以执行：

```powershell
uv run publishing-workspace mosaic install G:\ai_publish `
  --source F:\ThreeState\anr_plugin_auto_mosaics\models
```

`--source` 只用于安装阶段。复制后仍执行 SHA-256 校验和原子替换。后续 build 不保存或访问 source 路径。

`mosaic status` 输出每个模型的目标路径、是否存在、实际 SHA-256、期望 SHA-256和状态：`ready`、`missing` 或 `checksum_mismatch`。

## 9. Task 配置

```yaml
processing:
  profile: pixiv_default
  operations:
    strip_metadata:
      enabled: true
    mosaic:
      enabled: true
      version: "2"
      adapter: anr_plugin_auto_mosaics
      options:
        detector: yolo_sam
        method: pixel
        parts:
          - penis
          - pussy
        pixel_size: 15
```

支持字段：

| 字段 | 可选值 | 默认值 |
| --- | --- | --- |
| `detector` | `yolo`、`yolo_sam` | `yolo_sam` |
| `method` | `pixel`、`blur`、`line`、`solid`、`emoji` | `pixel` |
| `parts` | `penis`、`pussy`、`female_nipple`、`anus` | `penis`、`pussy` |
| `pixel_size` | 1-100 | 15 |
| `blur_radius` | 1-100 | 12 |
| `line_width_range` | 两个正整数 | `[1, 4]` |
| `line_spacing_range` | 两个正整数 | `[3, 8]` |
| `color` | 三个 0-255 整数 | `[128, 128, 128]` |
| `emoji_dir` | 图片目录 | 内置 emoji 目录 |

Adapter 把英文枚举映射到旧实现：

```text
penis         -> 欧金金 -> penis
pussy         -> 欧芒果 -> pussy
female_nipple -> 欧派派 -> nipple_f
anus          -> 欧西利
```

YOLO 和 YOLO+SAM 不支持 anus 时记录 warning 并忽略该 part，保持旧实现语义。

## 10. Adapter 设计

`AnrAutoMosaicsAdapter` 实现现有 `MosaicAdapter`：

```python
class AnrAutoMosaicsAdapter:
    name = "anr_plugin_auto_mosaics"

    def process(self, source: Path, target: Path, options: dict) -> None:
        ...
```

职责：

- 校验 optional dependency。
- 校验模型状态。
- 解析和校验 task options。
- 懒加载 YOLO 或 YOLO+SAM detector。
- 在进程内缓存 detector，模型配置相同时复用。
- 在独立临时目录生成 mask 和打码结果。
- 将最终图片精确写入 Pipeline 指定的 `target`。
- 清理 mask、中间图和临时目录。
- 不恢复 PNG metadata。

Adapter 不负责 ZIP、任务扫描、selection 或缓存键生成。

## 11. 插件迁移原则

迁移以下能力：

- YOLO 检测
- YOLO+SAM 检测
- 像素、模糊、线条、纯色和表情处理
- 当前本地版本的 `process_mosaic` 行为

不迁移：

- Gradio UI
- `main()` 批处理入口
- `save_config()`
- 全局 `config.json`
- 依赖进程当前目录的 `./outputs/temp_mask.png`
- 自动恢复 PNG metadata

旧插件的 emoji 素材迁入 `assets/anr_plugin_auto_mosaics/emoji`。所有模型路径、素材路径、临时路径和输出路径均通过参数传递，不在 import 阶段加载模型。

## 12. Operation Registry 接入

`PackageBuilder` 创建默认 `ImageProcessingPipeline` 时，根据 workspace 配置建立：

```python
mosaic_adapters = {
    "anr_plugin_auto_mosaics": AnrAutoMosaicsAdapter(...),
}
```

然后调用现有 `default_operation_registry(mosaic_adapters)`。测试和外部调用仍可显式传入自定义 registry，不引入全局单例。

Operation 执行顺序继续由 `processing.operations` 的 YAML 顺序决定，默认保持 `strip_metadata -> mosaic`。

## 13. 缓存

沿用现有 ProcessingCache。缓存键继续包含：

- 输入图片 SHA-256
- processing profile
- Operation type 和 version
- adapter 名称
- detector、method、parts 和其他 options

`mosaic.version` 升级为 `2`，避免复用此前不存在真实 Adapter 时产生的缓存。

同一张图片同时存在于 all、post 和 cover 时，只执行一次真实打码，其他集合复用缓存结果。

## 14. 错误处理

以下错误阻止正式 build：

- 未安装 `mosaic` extra
- adapter 名称未知
- 模型缺失或 SHA-256 不匹配
- task options 非法
- 模型加载或 detector 执行失败
- 插件没有生成可读取图片
- 目标图片写入失败

错误信息必须包含建议动作，例如：

```text
Mosaic 依赖未安装，请执行：uv sync --extra mosaic
Mosaic 模型缺失，请执行：publishing-workspace mosaic install G:\ai_publish
```

失败时沿用现有 PackageBuilder 原子清理，不产生正式 build，不修改 selection 和原图。

## 15. 日志

`info`：模型加载、当前 detector、图片处理完成、模型下载或复制进度。

`warning`：当前 detector 不支持某个 part，或使用 CPU 导致处理较慢。

`error`：依赖、模型、下载、校验或处理失败。

模型只在首次加载时记录日志，不为每张图重复输出加载信息。

## 16. 验收标准

### 16.1 模型安装

- `mosaic status` 能报告缺失模型。
- `mosaic install --source` 能从当前旧模型目录复制两个模型。
- 复制后 SHA-256 与配置一致。
- 默认下载模式使用配置 URL，不包含 `F:\ThreeState` 路径。
- 校验失败不会留下正式模型文件。

### 16.2 Adapter

- 使用真实需要打码的图片执行 YOLO+SAM。
- 输出图片可读取，尺寸保持不变。
- 检测区域产生可见马赛克。
- 输出 PNG 不包含 prompt、seed 等内部参数。
- 不修改输入图片。
- 第二次相同构建命中 ProcessingCache。

### 16.3 PackageBuilder

- mosaic 开启时 all、post、cover 均输出处理后图片。
- 同图跨集合共享缓存。
- ZIP 包含处理后的图片，不包含内部记录或原始参数。
- 模型缺失和依赖缺失时不产生正式 build。

### 16.4 回归

- mosaic 关闭时无需安装 extra 或模型即可构建。
- 公共 Catalog、Reader、分类和 Exporter 行为不变。
- 完整 `publishing_workspace` 测试通过。

## 17. 实施顺序

1. 增加配置模型、可选依赖和模型目录忽略规则。
2. 实现 ModelManager 和 `mosaic status/install` CLI。
3. 迁移并清理 GPLv3 插件核心代码。
4. 实现 `AnrAutoMosaicsAdapter`。
5. 接入默认 Operation Registry。
6. 增加自动化测试。
7. 从旧目录复制模型并执行真实图片验收。
8. 更新 README 和验收报告。
