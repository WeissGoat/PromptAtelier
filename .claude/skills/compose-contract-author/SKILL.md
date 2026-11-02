---
name: compose-contract-author
description: >-
  为 PromptAtelier 的「Agent 拼接契约」写每一帧的完整提示词：读契约请求和素材（角色、st_/stn_ 动作组、服装、背景），
  按定制要求逐帧拼接，写回契约 Markdown 文件，用 contract check 自检后标记完成。
  在收到「Agent 拼接契约」要求 prompt、或要填写 动作改2/contracts/*.md 时使用。
---

正文在 `.agents/skills/compose-contract-author/SKILL.md`（各 agent 共用一份），先完整读它再动手。
