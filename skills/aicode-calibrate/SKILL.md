---
name: aicode-calibrate
user-invocable: true
description: "Calibrate inferred rules — confirm, edit, or reject rules that init generated"
---

# /aicode-calibrate — Rule Calibration

Review and confirm code style rules that `aicode init` inferred from code samples.
Moves rules from `Status: inferred` to `Status: confirmed`.

## Trigger

```
/aicode-calibrate
```

## Execution

### Step 1: Read current rules

Read `.claude/aicode/style.md` and `.claude/rules/code-style.md` to understand
what was inferred during init.

### Step 2: Show low-confidence rules

Present each rule with:
- The inferred rule
- Confidence level (`low` / `medium`)
- Evidence files (which files were sampled)
- Status: `inferred`

### Step 3: Let user decide

For each rule, ask the user to:
- `[confirm]` — accept the rule as-is
- `[edit]` — modify the rule
- `[reject]` — discard the rule

### Step 4: Commit confirmed rules

After user confirms:
- Update `.claude/aicode/style.md` with `Status: confirmed`
- Update `.claude/rules/code-style.md` with confirmed rules
- Update `CLAUDE.md` core rule summary if needed

### Step 5: Sync to memory

If the user confirms long-term rules, suggest running `/aicode-memory` to
persist them to `.ai/memory.md`.

## Guardrails

- NEVER modify business code
- NEVER generate Spec or Plan
- NEVER start services or run verification
- NEVER overwrite rules the user manually wrote before init
- Present everything in Chinese
