---
name: aicode-direct
description: "Fast track for small changes — skip Spec/Plan, code directly with Guard checks"
---

# /aicode-direct — Direct Mode

Fast path for low-complexity, low-risk changes. Skips Spec and Plan generation — goes straight to coding.

## Trigger

```
/aicode-direct <小改动描述>
/aicode-direct --task "给 User 模型加一个 nickname 字段"
```

## Execution

### Step 1: Start direct mode

```bash
python ${CODEX_PLUGIN_ROOT}/engines/run.sh loop direct --task "<任务>" --format json
```

### Step 2: The direct flow

```
DIRECT_EXECUTE → VERIFY (可选) → REVIEW → COMPLETED
```

### Step 3: Read results

Parse JSON:
- `task_intake.flow_mode` — should be "direct"
- `task_intake.risk_level` — L1 or L2 only
- `verification_required` — true/false

### Step 4: When to use

Suitable for:
- Adding a field to a model
- Fixing a simple bug
- Updating configuration
- Small refactoring within one file

NOT suitable for:
- New API endpoints
- Database schema changes
- Multi-file architectural changes
- Risk level L3+

## Guardrails

- Only for L1-L2 risk level changes
- Must respect project code style
- Guard checks still run on review
- If change grows beyond 3 files → stop, suggest `/aicode-full`
- Present results in Chinese
