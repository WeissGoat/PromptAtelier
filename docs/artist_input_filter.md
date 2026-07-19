# Artist 输入过滤器

## 定位

`ArtistInputFilter` 位于 Artist 原始读取和生成链路之间：

```text
NovelAIArtistRepository / NodeReader
  -> 原始 Artist
  -> ArtistInputFilter
  -> 运行时 Artist 副本
  -> Composer / Renderer
```

过滤器不会修改 Artist 文件。`inspect-artist` 和 Web 编辑器仍可读取原始内容；
Batch、CLI run-prompt 和旧项目的 `prompt_preset_service.py run-prompt` 使用过滤后的
运行时副本。

## 默认配置

```yaml
artist_input_filter:
  negative_prompt:
    enabled: true
    blocked_tokens:
      - nsfw
    fields:
      - negative_prompt
      - after_negative_prompt
```

默认同时处理 `negative_prompt` 和 `after_negative_prompt`，避免 token 从后置负面
提示词重新进入最终请求。

Batch 项目可以在 require 基础配置中声明同一结构：

```yaml
defaults:
  artist_input_filter:
    negative_prompt:
      enabled: true
      blocked_tokens:
        - nsfw
      fields:
        - negative_prompt
        - after_negative_prompt
```

Batch 的 `defaults.artist_input_filter` 优先于 AppConfig；有效配置会写入每个
`BatchTask`，保证恢复任务时行为可回放。

## 关闭过滤

```yaml
artist_input_filter:
  negative_prompt:
    enabled: false
```

## 替换过滤列表

`blocked_tokens` 使用替换语义：

```yaml
artist_input_filter:
  negative_prompt:
    blocked_tokens:
      - censored
      - mosaic
```

此时只过滤 `censored` 和 `mosaic`，不再默认过滤 `nsfw`。

## 匹配规则

过滤器进行大小写无关的完整 token 匹配，并忽略常见权重外壳：

```text
nsfw             -> 删除
NSFW             -> 删除
{{nsfw}}         -> 删除
1.5::nsfw::      -> 删除
nsfw_only        -> 保留
```

过滤后会整理逗号，但保留未删除 token 的原始文本和权重。

## 支持的输入

- 旧 `NovelAIArtist.negative_prompt`
- 旧 `NovelAIArtist.after_negative_prompt`
- Artist `NodeDocument.negative_prompt`
- Artist `prompt.negative`
- `renderers.<backend>.negative_prompt`
- `renderers.<backend>.after_negative_prompt`

结构化 Artist 的运行时副本会在 `composition.input_filter` 中记录删除 token 和受影响
字段。过滤发生时还会写入 Info 日志。

## 范围限制

该功能只过滤 Artist 输入。Character、Action 或调用方直接提供的 negative prompt
不会被处理。
