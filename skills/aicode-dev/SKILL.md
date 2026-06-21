---
name: aicode-dev
user-invocable: true
description: "Development mode — Execute→Verify→Repair→Review loop for when Spec/Plan already exist"
---

# /aicode-dev — Development Mode

Execute code changes, verify, and review. Assumes Spec and Plan already exist.

## Trigger

```
/aicode-dev <开发任务>
/aicode-dev --task "实现 UserService.getById"
/aicode-dev --only --task "小改动"          (仅生成代码，不验证/审查)
```

## Execution

### Step 1: Start dev loop

```bash
# 完整模式 (生成+验证+修复+审查)
{engines_cmd} loop dev --task "<任务>" --format json

# 仅生成代码
{engines_cmd} loop dev --only --task "<任务>" --format json
```

### Step 2: The dev loop

完整模式:
```
EXECUTE → VERIFY → REVIEW → MEMORY → COMPLETED
                ↓ (失败)
             REPAIR → VERIFY
```

--only 模式:
```
EXECUTE → COMPLETED
```

### Step 3: Read results

Parse JSON:
- `task_state.status` — PASSED / FAILED / REPAIRING
- `verification.passed` — all assertions passed?
- `failures[]` — failure details if any

### Step 4: On failure

- ENVIRONMENT fault → report to user, do NOT fix code
- CODE fault → analyze root cause, minimal fix, re-verify

## Guardrails

- Do NOT modify Spec or Plan during dev mode
- Respect allowedFiles / forbiddenFiles from Plan
- If fix requires Plan change → stop and suggest `/aicode-plan` update
- Present results in Chinese
