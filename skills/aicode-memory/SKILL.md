---
name: aicode-memory
user-invocable: true
description: "Extract and persist experiences — update .ai/memory.md index + entries/"
---

# /aicode-memory — Memory Update

Extract reusable knowledge from the current session and persist to the three-layer memory system.

## Memory Architecture

```
.ai/memory.md              — 权威索引（只放摘要，不放长文）
.ai/memory/entries/        — 详细条目正文 ({id}.md)
.ai/memory/sessions/       — 单次任务候选原料
.ai/memory/archive/        — 废弃/低频归档
.ai/memory/projections/    — 工具投影缓存（非权威源）
.ai/memory/stats.json      — 运营面板数据
```

## Trigger

```
/aicode-memory
```

## Execution

### Step 1: Load current memory state

```bash
{engines_cmd} memory stats --format json
```

Read `.ai/memory.md` index to understand existing entries. Only load detailed entries when suspicious of duplicates.

### Step 2: Extract candidates from session

Review the session:
- Failures and their root causes
- Key decisions made
- Patterns observed (good and bad)
- New rules or boundaries discovered

### Step 3: Classify candidates

Assign each candidate a category:
- `rule` — 通用开发规则
- `pitfall` — 历史坑和易错点
- `verification` — 验证方式、场景、回归检查
- `testing` — 测试经验
- `module_boundary` — 模块职责边界
- `architecture` — 架构决策和原则
- `failure_pattern` — 常见失败模式及修复路径
- `prohibited` — 明确禁止事项
- `code_style` — 稳定的风格规范

### Step 4: Filter

Keep only:
- **可复用**: 以后还会遇到
- **已验证**: 不是猜测
- **对决策有帮助**: 能影响后续行动
- **不是重复噪音**: 不与已有记忆重复

Discard:
- One-off implementation details
- Unverified guesses
- Verbose logs
- Expired workarounds
- Sensitive information (passwords, tokens, internal URLs)

### Step 5: Write to memory

Write each entry using standard format:

```
{engines_cmd} memory add --id {id} --category {category} --title "{title}" --content "{1-3句结论}" --tags "{tags}" --confidence {draft|confirmed}
```

This will:
1. Create `.ai/memory/entries/{id}.md` (full detail)
2. Append summary line to `.ai/memory.md` index

### Step 6: Governance

Check if compression or archival is needed:

```bash
{engines_cmd} memory governance --format json
```

- Same-category entries with overlapping tags >= 3 → suggest merge
- Stale drafts (>30 days no hit) → archive

### Step 7: Sync projections

```bash
{engines_cmd} memory update --format json
```

This regenerates `.ai/memory/projections/` cache files. Only `confirmed` entries are projected.

## Guardrails

- Only persist verified, reusable experiences
- Do NOT write one-time task details
- Do NOT write session logs
- Never write sensitive information
- Present all entries to user in Chinese for confirmation
- **memory.md 是索引，不是全文仓库** — 长文放 entries/
