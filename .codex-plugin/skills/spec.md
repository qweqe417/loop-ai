---
name: aicode-spec
description: "Generate a Spec from a prompt or document — goals, acceptance criteria, test scenarios"
---

# /aicode-spec — Generate Spec

Generate a structured Specification from user requirements.

## Trigger

```
/aicode-spec <description>
/aicode-spec --from-doc docs/prd.md
```

## Execution

### Step 1: Load context

```bash
python ${CODEX_PLUGIN_ROOT}/engines/run.sh context route --stage spec --format json
```

### Step 2: Generate Spec

Based on the context and user input, generate a Spec document containing:
- **Goals** — what this feature achieves
- **Non-goals** — what is explicitly out of scope
- **Business rules** — key business logic
- **Acceptance criteria** — verifiable conditions
- **Test scenarios** — scenarios that will verify the feature
- **Risk level** — L1 to L5
- **Open questions** — anything that needs clarification

### Step 3: Spec quality gate

Self-check the Spec:
- Are goals clear and specific?
- Are non-goals declared?
- Are acceptance criteria testable?
- Are edge cases covered?
- Are there vague words ("improve", "optimize", "handle everything")?

### Step 4: Present to user for approval

Wait for user confirmation before proceeding to Plan.

## Guardrails

- Do NOT write any code during Spec generation
- Do NOT read the full codebase — only what Context Router provides
- Flag ambiguity instead of guessing
