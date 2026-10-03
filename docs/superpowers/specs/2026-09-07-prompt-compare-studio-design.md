# Prompt Compare Studio (提示词对比工坊) 设计规范

- **创建日期**: 2026-09-07
- **状态**: 待确认 / 草案已就绪
- **分类**: 架构设计 (Architectural)

---

## 1. 目标与背景

在 AI 生图（以 NovelAI / Stable Diffusion 为代表）的调优过程中，用户通常需要精准观测提示词（Prompt）中增删单个或多个 Tag 对画面构图、质感与细节造成的实际影响。
目前 PromptAtelier 具备单次生成、批量跑图与节点组装能力，但缺少针对“单提示词细微调整、多分支控制变量对照、跨轮次迭代演化与深度视觉对比”的闭环工具。

本设计旨在 PromptAtelier Web 控制台中构建全新的顶级模块 **Compare Studio（提示词对比工坊）**，完整支持：
1. **读入图片参数**：本地拖拽上传、剪贴板粘贴或从现有图库导入 PNG 图片，自动解析并提取提示词、种子、尺寸、步数、CFG Scale 等生成参数；
2. **生成基础模板**：锁定理智控制变量（Seed、分辨率、采样步数、Scale、负向等），排除参数干扰；
3. **多批次变体演化**：支持横向复制新增变体卡片（Variant A/B/C...），支持「往下新增新的一批对比」及「以选定变体为起点向下派生新批次」；
4. **实时 Tag Diff**：毫秒级实时计算并高亮显示变体相比底模的新增词（绿色）与删除词（红色删除线）；
5. **真实生图与进度监控**：调用已有的 NovelAI 生成链路进行真实跑图，实时监控任务状态与产物；
6. **深度视觉对比**：提供并排画廊展示，以及全屏双图「左右卷帘滑动（Split Slider）」与「键盘快速切帧闪烁（Flicker Mode）」视窗。

---

## 2. 总体架构与数据流

```
+-----------------------------------------------------------------------------------------+
|                                    前端 (React / Vite)                                   |
|                                                                                         |
|  [输入源: 本地PNG / 剪贴板 / 图库]                                                        |
|         │                                                                               |
|         ▼ (multipart/form-data 或 server path)                                          |
|  POST /api/image-meta/inspect                                                           |
|         │                                                                               |
|         ▼ (返回标准化元数据)                                                             |
|  [BaseTemplate 建立: 锁定 Seed、尺寸、步数、负向]                                         |
|         │                                                                               |
|         ├────────────── 变体横向扩展与实时 Tag Diff 计算                                  |
|         ▼                                                                               |
|  [CompareRound 1]: 变体 1-A (基准)  |  变体 1-B (+胶片颗粒)  |  [+] 新增变体卡片             |
|         │                                                                               |
|         ├────────────── 点击「以此卡片往下派生」或「往下新增新的一批对比」                  |
|         ▼                                                                               |
|  [CompareRound 2]: 变体 2-A (继承1-B) | 变体 2-B (仰视角度)  |  [+] 新增变体卡片             |
|         │                                                                               |
|         ▼ (点击「运行本批」/「单张生成」)                                                |
|  POST /api/generate ───► JobManager (异步执行)                                           |
|         │                                                                               |
|         ▼ (轮询任务状态，渲染图片与耗时)                                                 |
|  [主屏并排缩略图] ──► [勾选 2 张图唤起 DeepCompareModal]                                 |
|                         ├─ Split Slider (卷帘左右划动)                                  |
|                         ├─ Flicker Mode (按键瞬切两图)                                   |
|                         └─ Sync Zoom & Pan (同步放大平移)                               |
+-----------------------------------------------------------------------------------------+
```

---

## 3. 数据模型规范 (Data Contracts)

### 3.1 基础模板 (`BaseTemplate`)
```ts
export type BaseTemplate = {
  // 核心控制变量
  prompt: string;           // 原始正向提示词
  negative: string;         // 原始负向提示词
  seed: number;             // 基准随机种子（严格锁定）
  width: number;            // 宽
  height: number;           // 高
  steps: number;            // 采样步数 (默认 28)
  scale: number;            // CFG Scale (默认 5.0)
  sampler?: string;         // 采样器 (如 k_euler)
  model?: string;           // 模型标识
  
  // 图片来源元数据
  sourceImage?: {
    previewUrl?: string;    // 本地 blob 预览或 static url
    filename?: string;      // 原始文件名
    sourcePath?: string;    // 服务器相对路径
  };
};
```

### 3.2 变体模型 (`PromptVariant`)
```ts
export type TagDiffItem = {
  text: string;
  type: "added" | "removed" | "unchanged";
};

export type PromptVariant = {
  id: string;               // 唯一标识 (如 "var-1718293-1")
  name: string;             // 变体名称 (如 "变体 A: 增加胶片质感")
  prompt: string;           // 独立正向提示词
  
  // 差异计算结果
  diff: {
    added: string[];        // 新增 Tag 列表
    removed: string[];      // 删去 Tag 列表
    tokens: TagDiffItem[];  // 完整分词高亮序列
  };

  // 参数覆盖 (默认 null 即继承模板)
  seedOverride: number | null;

  // 运行状态
  status: "idle" | "queued" | "running" | "succeeded" | "failed";
  jobId: string | null;
  resultImage?: {
    path: string;
    url: string;
    seed: number;
    durationMs?: number;
  };
  error?: string;
};
```

### 3.3 轮次模型 (`CompareRound`)
支持用户「往下新增新的一批对比」：
```ts
export type CompareRound = {
  id: string;               // 轮次 ID (如 "round-1")
  name: string;             // 轮次名称 (如 "第 1 批: 质感调优")
  basePrompt: string;       // 本批次基准提示词
  variants: PromptVariant[]; // 本批次横向排布的变体卡片
  status: "idle" | "running" | "completed";
};
```

### 3.4 核心工作区状态 (`CompareWorkspaceState`)
```ts
export type CompareWorkspaceState = {
  template: BaseTemplate;
  rounds: CompareRound[];
  
  // 深度对比视窗状态
  deepCompare: {
    isOpen: boolean;
    leftVariantId: string | null;
    rightVariantId: string | null;
    mode: "split" | "flicker";
  };

  isBatchRunning: boolean;
};
```

---

## 4. 关键算法：Tag Diff 归一化对比算法

提示词的 Tag 切分及比对规则：
1. **分词**：以英文逗号 `,`、中文逗号 `，` 及换行符切分，去除首尾空白；
2. **规范化**：不区分大小写、下划线与空格等价；保留括号加权标记（如 `{tag}`、`[tag]`、`(tag:1.2)`）；
3. **差异集合**：
   - `added`: 存在于变体中、但不存在于本轮基准中的 Tag；
   - `removed`: 存在于本轮基准中、但在变体中被删去的 Tag；
   - `unchanged`: 两者均保留的 Tag。

---

## 5. 前端交互与组件实现细节

### 5.1 页面入口
在 [web/src/components/Layout.tsx](file:///f:/my_project/new/tags_machine/refactor/web/src/components/Layout.tsx) 中新增导航项：
- `Compare`（图标采用 `GitCompare` 或 `Split`），对应新页面 `CompareStudio`。

### 5.2 组件结构拆解
1. **`CompareStudio`**：页面主入口，包裹 `CompareWorkspaceProvider`。
2. **`CompareTemplateBar`**：
   - 包含文件拖拽与点击上传区域；
   - 全局快捷键监听（`window.addEventListener("paste", ...)`），支持从剪贴板直接粘贴图片；
   - 展示锁定的控制变量（Seed、分辨率、步数、CFG），支持一键清空/重置。
3. **`CompareRoundSection`**：
   - 每行展示一个批次，包含批次标题、基准提示词折叠栏、`[▶ 运行本批]` 按钮、`[以此批基准往下派生]` 按钮。
   - 变体卡片横向水平滚动/排布，最右侧固定 `[+ 新增变体卡片]` 按钮。
4. **`VariantCard`**：
   - 卡片顶部：名称编辑、`[复制]`、`[删除]`、`[还原为基准]`；
   - 提示词文本框：支持多行输入与 Diff Pills 即时预览；
   - Seed 状态指示：`🔒 锁定 (继承自底模)` 或 `🔓 独立 Seed`；
   - 单卡操作：`[生成]` 按钮与耗时进度；
   - 产物预览：成功后展示缩略图、点击放大、以及 `[✓ 对比勾选]` 复选框；
   - 卡片底部按钮：**`[以此变体为新起点往下派生 ⬇]`**。
5. **页面底部**：
   - 常驻大按钮 **`[➕ 往下新增新的一批对比 (New Batch Below)]`**。
6. **`DeepCompareModal`**：
   - 全屏/大尺寸弹窗，支持横向任意两张图片的深度比对；
   - **Split Slider（左右卷帘）**：通过鼠标拖动中线分割两图；
   - **Flicker Mode（快速切帧）**：按键盘 `←` / `→` 或空格键瞬间切换两图；
   - **Sync Pan & Zoom**：同步缩放（滚轮）与平移（鼠标中键/拖拽）。

---

## 6. 后端 API 规范与扩展

### 6.1 `POST /api/image-meta/inspect`
- **实现位置**：`src/tags_machine_core/web/routes/image_meta.py`
- **支持入参**：
  1. `file: UploadFile`（表单文件上传，支持本地拖入/剪贴板粘贴）；
  2. `JSON { "path": "outputs/..." }`（服务端已有文件路径）。
- **执行逻辑**：
  - 调用 `read_png_dimensions()` 读取分辨率；
  - 调用 `read_image_parameters()` 解析内嵌参数；
  - 提取并归一化输出 `prompt`, `negative_prompt`, `seed`, `steps`, `scale`, `sampler`, `model`。
- **错误处理**：若上传的文件不是有效 PNG 或未包含元数据，优雅返回分辨率与空提示词，并附加友好提示 `metadata_warning`，不抛出 500 异常。

### 6.2 生图执行与 Job 管理
- 无缝复用现有 `POST /api/generate` 与 `JobManager`；
- 前端控制器维护并发上限（默认并发数 = 1~2），依次下发变体任务并轮询，保证 NovelAI 速率限制平稳。

---

## 7. 测试与验证策略

### 7.1 后端单元测试
- **测试文件**: `tests/test_web_image_meta.py`
  - 验证带 NovelAI `Comment` 的 PNG 上传解析；
  - 验证服务端绝对/相对路径解析；
  - 验证无元数据图片的容错处理。

### 7.2 前端单元测试
- **测试文件 1**: `web/src/compare/tagDiff.test.ts`
  - 验证提示词分词、归一化、加权括号保留；
  - 验证新增、删除、无变化 Tag 的计算准确度。
- **测试文件 2**: `web/src/compare/useCompareWorkspace.test.tsx`
  - 验证底模导入初始化；
  - 验证横向添加与复制变体；
  - 验证向下新增对比批次（New Round）；
  - 验证变体向下派生新批次的数据继承。
- **测试文件 3**: `web/src/compare/DeepCompareModal.test.tsx`
  - 验证卷帘分割比例计算；
  - 验证切帧模式按键切换逻辑。

### 7.3 真实生图全流程验收 (Live E2E Verification)
依据用户明确要求，必须包含**真实生图正常**的验证步骤：
1. 配置有效的 `NAI_ACCESS_TOKEN`，启动本地后端与前端服务；
2. 在 Compare Studio 界面拖入一张已有生成图作为底模；
3. 编辑变体 A 与变体 B，保留相同 Seed；
4. 点击「运行本批」，实际发起真实 NovelAI 生图请求；
5. 验证图片成功生成并落盘到 `outputs/`，验证 PNG 包含正确的内嵌参数；
6. 验证前端界面能正确接收并展示真实生图结果，无死锁、无静默失败；
7. 唤起 DeepCompareModal，验证真实图片在 Split Slider 与 Flicker 模式下能够流畅对比。
