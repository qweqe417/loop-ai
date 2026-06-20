---
name: aicode-full
description: "Run the full 8-stage Loop Engineering cycle — Intake→Spec→Plan→Execute→Verify→Repair→Review→Memory"
---

# /aicode-full — Full Loop Cycle

Run a complete AI Coding Loop from requirement intake to memory persistence.

## Trigger

```
/aicode-full <需求描述>
/aicode-full --task "实现订单超时自动关闭功能"
```

## Execution

### Step 1: Start the full loop

```bash
python ${CLAUDE_PLUGIN_ROOT}/engines/run.sh loop full --task "<需求>" --format json
```

Or on Windows:
```bat
python ${CLAUDE_PLUGIN_ROOT}\engines\run.sh loop full --task "<需求>" --format json
```

### Step 2: Monitor each stage

The loop runs through 8 stages automatically:

| Stage | Python does | AI does |
|-------|------------|---------|
| INTAKE | 分析输入类型、复杂度、风险等级 | 输入模糊时向用户提问 |
| SPEC | ContextRouter 注入上下文 | 生成 Spec 内容 |
| PLAN | 拆 Task 框架、设定 diff budget | 填每个 Task 具体内容 |
| EXECUTE | Guard 前置检查、ContextRouter 注入 | 写代码 |
| VERIFY | ScenarioRunner 跑场景、SanityChecker 检查环境 | 读失败报告、判断根因 |
| REPAIR | ContextRouter 注入失败上下文 | 分析根因、最小修复 |
| REVIEW | Guard 检查越界/diff/合规 | 判断是否需要 Plan Change |
| MEMORY | MemoryExtractor 提取候选、MemoryProjection 同步 | 判断哪些值得沉淀 |

### Step 3: Read results

Parse JSON output at each stage:
- `current_stage` — which stage the loop is at
- `task_state.status` — current task status
- `failures` — list of failure records (env vs code)
- `decision` — loop decision (next stage / retry / stop)

### Step 4: Handle failures

If `VERIFY` fails:
- Check `failure.category`: ENVIRONMENT → tell user to fix environment; CODE → enter REPAIR
- REPAIR auto-analyzes and attempts fix, then returns to VERIFY
- After 3 failed repair attempts → escalate to user

### Step 5: Review and persist

After REVIEW passes:
- Check changes comply with plan boundaries
- Run `/aicode-memory` to persist learnings

## Guardrails

- NEVER skip stages without user confirmation
- NEVER modify plan boundaries during execution
- Stop and ask user if risk level is L4-L5
- Present stage progress in Chinese
- Max 100 loop iterations before forced stop
- REPAIR loop: max 3 attempts before escalation
