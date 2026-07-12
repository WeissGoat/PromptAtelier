# Web Compare Artist 一致性设计

## 背景

Web 节点接口当前统一使用 `NodeReader` 读取旧 `tags.txt`。Artist 临时修改后作为 inline `NodeDocument` 传入时，会丢失 `NovelAIArtistRepository` 解析出的 `renderers.novelai` 参数；通用读取还会把同一批画风词同时写入 `tags` 和 `prompt.positive`，导致 Renderer 重复拼接。

## 设计

### Artist 输入边界

- `/api/nodes/read` 接收节点 `role`。
- `NodeWorkspace` 在 `role=artist` 时使用 `NovelAIArtistRepository.load_node()`，其他节点继续使用 `NodeReader`。
- Web 临时修改和 Compare 镜像都直接复制完整 `NodeDocument`，不在 Renderer 根据路径回查或补参数。
- 原始 Artist 和临时 Artist 因此共享同一份 `renderers.novelai` 参数来源。

### Compare 归档

- 每次点击 Compare Generate 生成一个独立运行目录。
- 目录格式为 `outputs/compare_<timestamp>_<seed>_<short-id>`。
- 本轮所有组合向 `/api/generate` 传递相同 `output_dir`；下一轮创建新目录。

### Compare 节点创建

- 点击节点类型右侧加号时，新增槽位深拷贝该类型的 Primary 槽位内容。
- Primary 为空时，新增槽位保持为空。
- Compare 后续修改只影响自身，不与 Primary 共享对象引用。

## 验收

- 修改后的 legacy Artist 仍保留 `gen_json` 中的 sampler、steps、noise schedule 和 negative prompt。
- Artist 提示词不再因 `tags + prompt` 重复出现。
- 同一次 Compare 的所有图片位于同一独立目录。
- 新增 Compare 默认显示与 Primary 相同的节点，修改 Compare 不改变 Primary。
- 使用 `109841329_03_manga_monochrome_yabuki_rance_no_vibe_latest_stable` 完成真实 Compare 出图并读取 PNG 参数确认。
