---
name: aicode-review
description: "Review code changes — check diff, guard violations, plan compliance"
---

# /aicode-review — Code Review

Run a comprehensive review of the current changes against the plan and guard rules.

## Trigger

```
/aicode-review
```

## Execution

### Step 1: Run guard check

```bash
python ${CODEX_PLUGIN_ROOT}/engines/run.sh guard check --format json
```

### Step 2: Load review context

Read `.claude/rules/code-style.md` and `.claude/rules/safety.md`.

### Step 3: Review checklist

Check each item:
- **Plan compliance** — Did we change only allowed files?
- **Diff budget** — Did we exceed maxFiles / maxLinesChanged?
- **Style contract** — Does the code follow project conventions?
- **Safety rules** — No test weakening, no permission bypass, no hardcoded secrets
- **Anti-cheating** — No deleted assertions, no skipped tests, no mocked core logic
- **Reuse** — Did we reuse existing patterns instead of creating new ones?
- **Scope creep** — Any unrelated formatting or refactoring?

### Step 4: Output review report

Report in Chinese:
- Pass/Fail per category
- Specific violations with file paths
- Whether changes are ready to proceed

### Step 5: On failure

If violations found:
- For minor style issues -- suggest fixes
- For scope violations -- enter REPAIR to revert
- For plan changes needed -- initiate Plan Change Request

## Guardrails

- Review against the PLAN, not against what looks "better"
- Flag unrelated changes even if they look good
- Present findings in Chinese
