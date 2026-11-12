---
name: compose-contract-review
description: >-
  复核 PromptAtelier「Agent 拼接契约」的出图结果：找出缺图、失败、只有旧提示词的帧，看联系表检查人物是否换人、
  服装和道具是否回退、相邻帧是否雷同，读 PNG 元数据核对参数和负面词，然后给出逐帧修改建议或直接改契约。
  在契约出过图之后、用户要求「看看结果 / 复核 / 挑图 / 哪些帧要重出」时使用；写契约本身用 compose-contract-author。
---

正文在 `.agents/skills/compose-contract-review/SKILL.md`（各 agent 共用一份），先完整读它再动手。
