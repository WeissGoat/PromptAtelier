# Web 图片详情与实际 PNG 元数据设计

## 目标

点击普通 Generate 或 Compare 结果缩略图后打开图片详情弹窗。弹窗展示大图和从磁盘图片实时读取的 PNG 元数据，并允许在 Windows 资源管理器中打开图片所在目录且选中该文件。

## 后端接口

### GET `/api/results/image-metadata`

查询参数：`path`。

处理流程：

1. 使用 `ResultIndex.resolve_image()` 将路径解析为允许结果根目录内的实际图片。
2. 对 PNG 调用 `read_image_parameters()` 和 `read_png_dimensions()`。
3. 返回文件名、绝对路径、文件大小、修改时间、尺寸、`png_text` 和 `parameters`。
4. 非 PNG 图片返回文件信息和尺寸读取错误；不得伪造 PNG 参数。

### POST `/api/results/open-image-folder`

请求体：`{"path": "outputs/example.png"}`。

处理流程：

1. 使用 `ResultIndex.resolve_image()` 完成相同安全校验。
2. Windows 调用 `explorer.exe /select, <absolute-path>`。
3. 返回 `opened: true` 和已解析路径。
4. 不支持的平台返回明确错误，不执行任意客户端传入命令。

## 前端交互

- 所有生成缩略图使用按钮语义，点击打开 `ImageDetailDialog`。
- 弹窗左侧显示保持原始比例的大图，右侧显示文件信息和常用参数。
- 常用参数包括尺寸、seed、model、sampler、steps、scale、noise schedule 和 Negative。
- Prompt 与 Negative 使用可滚动文本区域。
- 完整 `png_text` 和 `parameters` 放在折叠区。
- 元数据请求期间显示加载状态；失败时保留大图并显示错误。
- 支持关闭按钮、Escape 和点击遮罩关闭。
- “打开所在文件夹”按钮调用后端接口，成功和失败均提供界面反馈。

## 安全边界

- 图片读取和打开目录都必须经过 `ResultIndex.resolve_image()`。
- 不允许访问结果根目录外的绝对路径、目录或非图片文件。
- 前端不直接拼接 shell 命令。

## 验收

- 普通 Generate 与 Compare 图片均可打开详情。
- 元数据来自实际 PNG 文件，测试中修改 PNG 文本后接口返回新值。
- 后端拒绝越界路径。
- 打开文件夹调用资源管理器并选中图片。
