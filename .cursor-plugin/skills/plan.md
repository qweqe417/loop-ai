---
name: aicode-plan
description: "Generate an Execution Plan — break Spec into tasks with allowed/forbidden files"
---

# /aicode-plan — Generate Plan

Break a confirmed Spec into executable tasks with clear boundaries.

## Trigger

```
/aicode-plan
/aicode-plan <spec-id>
```

## Execution

### Step 1: Load context

```bash
python CURSOR_PLUGIN_ROOT_PLACEHOLDER/engines/run.sh context route --stage plan --format json
```

### Step 2: Generate Plan

For each task in the plan, define:
- **Task ID** — unique identifier
- **Goal** — what this task achieves
- **Allowed files** — files that can be modified
- **Forbidden files** — files that must NOT be touched
- **Style contract** — code style rules to follow
- **Verification** — scenario or test to run after completion
- **Done when** — completion criteria
- **Reuse check** — existing patterns to reuse

### Step 3: Set diff budget

For each task:
- `maxFiles` — maximum files changed
- `maxLinesChanged` — maximum lines changed
- `allowNewAbstractions` — whether new abstractions are allowed

### Step 4: Plan quality gate

Self-check:
- Does every Spec acceptance criteria map to a task?
- Does every task have allowedFiles / forbiddenFiles?
- Does every task have a verification method?
- Are there tasks that are too large (suggest splitting)?

### Step 5: Present to user for approval

Show the plan summary with all tasks.
Wait for user to approve before implementation begins.

## Guardrails

- Do NOT write code during planning
- Use Context Router to load only relevant context
- Each task should target 1-3 files, max 20 minutes of work
- Bind each task to a Spec requirement + scenario
