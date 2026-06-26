---
name: aicode-full
user-invocable: true
description: "全新需求 — 状态机全程驱动"
---

```bash
{engines_cmd} loop full --state-file .ai/run.json --task "<用户需求>"
```

然后循环：读 JSON → `needs_ai_input` → 做 `pending_action` → `loop continue` → 直到 `final_stage: "completed"`
