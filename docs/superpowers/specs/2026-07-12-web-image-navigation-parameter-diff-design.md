# Web 图片详情导航与参数 Diff 设计

## 图片序列

- 图片详情接收有序 `paths` 和当前 `index`，不再只接收单个 path。
- 普通 Generate 使用当前 Job 的 `images[]` 顺序。
- Compare Generate 使用本轮结果矩阵顺序，将所有成功 Job 的图片展平。
- 左右按钮和键盘 `ArrowLeft` / `ArrowRight` 切换；第一张和最后一张在边界停住并禁用对应按钮。
- 标题区显示 `当前位置 / 总数`。

## 参数 Diff

- 新增 `GET /api/results/image-parameter-diff?previous_path=...&current_path=...`。
- 两个路径都通过 `ResultIndex.resolve_image()` 校验，并从实际 PNG 读取参数。
- 后端复用 `normalize_render_parameters()` 与 `compare_render_parameters()`，避免前端复制 NovelAI 参数归一化规则。
- reference image 等大字段沿用现有 hash 摘要，不返回原始 base64 Diff。

## 展示

- Diff 位于右侧基础参数之后、Prompt 之前。
- 摘要显示变化数量，并分为 `变更`、`新增`、`移除`。
- 每行显示易读参数路径、上一张值和当前值。
- Prompt 与 Negative 使用更宽的文本差异行。
- 无变化显示“生成参数一致”；第一张显示“这是序列中的第一张”。
- 原始 Diff JSON 放入默认折叠区。

## 验收

- 普通 Generate 与 Compare 都能左右切图。
- 导航到边界时按钮禁用且不会循环。
- Diff 始终比较当前图与序列上一张。
- Diff 数据来自实际 PNG，并正确摘要 reference image。
- 切换图片后大图、元数据、Diff 和打开文件夹目标同步更新。
