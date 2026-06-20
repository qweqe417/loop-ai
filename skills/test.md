---
name: aicode-test
description: "Test mode — Verify↔Repair loop for running scenarios and fixing failures"
---

# /aicode-test — Test Mode

Run verification scenarios and repair failures in a loop. No new code generation — only verify and fix.

## Trigger

```
/aicode-test
/aicode-test <scenario-id>
/aicode-test --scenario order-timeout-close
```

## Execution

### Step 1: Run verification

```bash
{engines_cmd} loop test --scenario <scenario-id> --format json
```

### Step 2: The test loop

```
VERIFY → (passed) → COMPLETED
       → (failed) → REPAIR → VERIFY
```

### Step 3: Analyze failures

Parse JSON:
- `sanity.failed` → environment issue, tell user
- `assertions[].passed: false` → code issue, enter repair
- `failure.category` → ENVIRONMENT / CODE / DATA / ASSERTION

### Step 4: Repair

If code fault:
- Load failed context via Context Router
- Find root cause
- Apply minimal fix
- Re-run verification

If 3 repair attempts fail → escalate to user.

## Guardrails

- NEVER delete assertions to make tests pass
- NEVER mock core business logic
- NEVER modify scenario definitions
- Max 3 repair attempts
- Present results in Chinese
