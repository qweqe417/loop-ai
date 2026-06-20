---
name: aicode-memory
description: "Extract and persist experiences — update .ai/memory.md from session learnings"
---

# /aicode-memory — Memory Update

Extract reusable knowledge from the current session and persist to `.ai/memory.md`.

## Trigger

```
/aicode-memory
```

## Execution

### Step 1: Load current memory state

```bash
python ${CODEX_PLUGIN_ROOT}/engines/run.sh memory stats --format json
```

Read `.ai/memory.md` to understand existing entries.

### Step 2: Extract candidates from session

Review the session:
- Failures and their root causes
- Key decisions made
- Patterns observed (good and bad)
- New rules or boundaries discovered

### Step 3: Classify candidates

Assign each candidate a category:
- `code_style` — code formatting / naming conventions
- `pitfall` — historical pitfalls / bugs
- `module_boundary` — module responsibility boundaries
- `testing` — testing patterns / verification approaches
- `architecture` — architectural decisions
- `prohibited` — things that should never be done
- `failure_pattern` — recognized failure modes + fixes

### Step 4: Filter

Keep only:
- Reusable across future sessions
- Based on verified experience (not guesses)
- Not one-time task details
- Not sensitive information

Discard:
- One-off implementation details
- Unverified guesses
- Verbose logs
- Expired workarounds

### Step 5: Write to memory

Append new entries to `.ai/memory.md` in the standard format:
```markdown
- [id] Title: Brief summary
```

### Step 6: Sync projections

```bash
python ${CODEX_PLUGIN_ROOT}/engines/run.sh memory update --format json
```

## Guardrails

- Only persist verified, reusable experiences
- Do NOT write one-time task details
- Do NOT write session logs
- Never write sensitive information (passwords, tokens, internal URLs)
- Present all entries to user in Chinese for confirmation
