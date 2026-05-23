# Tags Machine Core

`tags_machine_core` 是 Tags Machine 的新一代旁路核心。

旧 `tags_machine` 仓库继续保持稳定，只作为数据源和兼容性参考。这个项目负责新的架构：

- 节点读取
- 提示词生成
- 提示词和结果缓存
- 生图后端适配
- 后续前端 UI 面向的服务 API

当前闭环：

```text
完整主体提示词 + style_ref
-> PromptBundle
-> RenderRequest
-> NovelAI generate-image
```

默认不 import 旧项目里的运行时代码。

## CLI

- `compose`：生成 `PromptBundle`
- `compose-nodes`：从结构化角色/动作/背景节点生成 `PromptBundle`
- `render-plan`：生成 NovelAI `RenderRequest`，不联网
- `render-plan-nodes`：从结构化节点生成 NovelAI `RenderRequest`，不联网
- `generate`：调用 NovelAI 并保存图片
- `inspect-node`：读取节点文件或目录
- `inspect-style`：读取旧画风节点
- `config`：查看配置解析结果

默认输出会截断图片/base64 字段，避免调试输出过大。需要完整 JSON 时使用 `--full`。

NovelAI 默认使用：

- 环境变量：`NAI_ACCESS_TOKEN`
- 接口：`https://image.novelai.net/ai/generate-image`

结构化节点示例：

```powershell
uv run python -m tags_machine_core compose-nodes `
  --character examples\nodes\characters\homura `
  --action examples\nodes\actions\foot_closeup
```

这个示例会使用动作节点里的 `body_scope: foot_detail` 过滤角色节点，保留身份和脚部相关词，跳过眼睛、头发和服装等不适合脚底特写的字段。

详细文档：

- [整体设计与开发方案](docs/development_plan_v1.md)
- [Node YAML 规范](docs/node_yaml_spec_v1.md)
- [Character YAML 规范](docs/character_yaml_spec_v1.md)
