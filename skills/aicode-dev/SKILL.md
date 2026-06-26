---
name: aicode-dev
user-invocable: true
description: "迭代开发 — 状态机全程驱动"
---

## 启动

```bash
{engines_cmd} loop full --state-file .ai/run.json --task "<用户需求>"
```

已有 Spec/Plan/Scenarios 会自动跳过。

## 循环

读 JSON → `needs_ai_input: true` → 做 `pending_action` → `loop continue` → 直到 `final_stage: "completed"`
