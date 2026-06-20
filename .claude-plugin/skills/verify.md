---
name: aicode-verify
description: "Run scenario verification — execute scenarios, check assertions, output report"
---

# /aicode-verify — Scenario Verification

Run scenario verification against the current project. Executes scenarios,
checks assertions, and outputs a structured report for the AI to analyze.

## Trigger

```
/aicode-verify
/aicode-verify <scenario-id>
```

## Execution

### Step 1: Run verification

```bash
python ${CLAUDE_PLUGIN_ROOT}/engines/run.sh verify --scenario <scenario-id> --format json
```

### Step 2: Analyze results

Parse JSON:
- `passed: true` → All assertions passed, verification complete
- `passed: false` with `sanity.failed` → Environment issue (port down, DB unreachable)
- `passed: false` with sanity all OK → Code logic issue, enter REPAIR

### Step 3: On failure — Environment vs Code

**If environment fault (port unavailable, MySQL/Redis down):**
- Report to user: which service is unreachable
- Suggest: "Please start {service} and retry"
- Do NOT attempt to fix code

**If code logic fault (assertion mismatch, wrong data):**
- Analyze the failed assertions
- Use Context Router to load the failed file:
  ```bash
  python ${CLAUDE_PLUGIN_ROOT}/engines/run.sh context route --stage repair --format json
  ```
- Find root cause
- Apply minimal fix
- Re-run verification

### Step 4: Report results

Show in Chinese:
- Scenario name and result
- Assertions passed / total
- If failed: which assertions failed and why
- Next action

## Guardrails

- NEVER delete assertions to make tests pass
- NEVER mock core business logic to pass
- NEVER modify the scenario definition to match incorrect code
- If recovery fails after 3 attempts, escalate to user
- Present all results in Chinese
