---
name: aicode-dev
user-invocable: true
description: "迭代开发 — 状态机全程驱动"
---

# /aicode-dev — 迭代开发

已有 Spec/Plan/Scenarios 的开发模式。**状态机一次性启动，整个流程不打断。**

```
/aicode-dev "根据 docs/plan/abc.md 生成代码" --plan-file docs/plan/abc.md
```

- 已有 Spec/Plan/Scenarios 的阶段会自动跳过
- Plan 文件路径从用户消息中提取，传入 `--plan-file`
- Spec 文件路径同样提取，传入 `--spec-file`

## dev vs direct — 一句话

| `/aicode-direct` | `/aicode-dev` |
|------------------|---------------|
| Bug 修复、小改动，你清楚要改什么 | 需求复杂，需要 Plan 拆 Task，逐 Contract 执行 |

**不做预判。** 如果你选错了，状态机会在 REVIEW/VERIFY 阶段发现问题，该修的修，修不了的升级给你。流程本身兜底，不用靠前置检查挡人。

## Execution — 状态机全程驱动

启动一次，循环响应 `pending_action`，直到 `final_stage: "completed"`。

### 首次启动

```bash
{engines_cmd} loop dev --state-file .ai/run.json --task "<用户任务描述>" --plan-file <plan路径> --spec-file <spec路径>
```

dev 模式从 EXECUTE 开始（跳过 INTAKE/SPEC/PLAN），需要传入 `--plan-file` 和 `--spec-file`。

已有 Spec/Plan/Scenarios 的状态机会自动跳过对应阶段。

### 交互循环

```
┌──────────────────────────────────────────┐
│  1. 读命令输出的 JSON                      │
│  2. needs_ai_input: true → 看 pending_action │
│     完成对应任务 → loop continue             │
│  3. final_stage: "completed" → 结束         │
└──────────────────────────────────────────┘
```

**循环内绝对禁止：** 汇报进度、展示 diff、追问用户、输出无关内容。唯一合法行为：读 JSON → 做 pending_action → **立即 loop continue** → 读 JSON → 做 pending_action → **立即 loop continue** → ... → 直到 `final_stage: "completed"`。

### loop continue 命令

每个 pending_action 完成后，执行以下命令进入下一阶段：

```bash
{engines_cmd} loop continue --state-file .ai/run.json
```

读返回的 JSON，根据新的 `needs_ai_input` 和 `pending_action` 继续循环。

### pending_action 对照表

| pending_action | AI 做什么 | 结果 JSON |
|---|---|---|
| `generate_plan` | plan_contracts 为空时，从 --plan-file 读取并提取 Task Contracts | `{"contracts": [{"task_id": "...", "goal": "...", "allowed_files": [...], "budget": {...}}]}` |
| `execute_contracts` | **必须调用** `Skill: superpowers:executing-plans` 执行所有 Task，完成后 report | `{"sdd_completed": true, "tasks_executed": N, "changed_files": [...], "summary": "..."}` |
| `review` | 调用 `/aicode-review` 执行 6 维深度审查 | `{"passed": true/false, "violations": [{"severity": "Critical/Important/Minor", "file": "path:line", "description": "..."}], "critical_count": N, "important_count": N, "minor_count": N, "summary": "..."}` |
| `review_fix` | 修复审查发现的违规 | `{"fixed": true/false, "changes": [{"file": "...", "description": "..."}], "summary": "..."}` |
| `verify` | 调用 `/aicode-verify --auto-fix` 执行场景验证 | 读 `.ai/reports/test-report-*.json` 最新一份，根据断言结果决定后续 |
| `repair` | 分析验证失败根因，最小修复代码（不删断言、不改场景） | `{"changed_files": [...], "summary": "...", "root_cause": "..."}` |
| `memory` | 调用 `/aicode-memory` 沉淀经验 | `{"files": [".claude/rules/loop-memory-xxx.md", ...]}` 或 `{"skipped": true, "reason": "无值得沉淀的经验"}` |

### 状态机流转

```
EXECUTE ⇄ REPAIR → REVIEW → VERIFY ⇄ REPAIR → MEMORY → COMPLETED
   ↑       ↑        ↑         ↑       ↑         ↑
 Plan执行  AI修复   AI审查   Python   AI修复   AI记忆
 subagent           6维审查   跑场景
```

> **说明：** dev 模式跳过 INTAKE/SPEC/PLAN，从 EXECUTE 开始。
> - 如果 `plan_contracts` 为空 → 自动触发 `generate_plan` 提取（从 `--plan-file` 或 `.ai/run.json` 中的 Plan 文件）
> - EXECUTE 失败（编译/逻辑错误）→ 进 REPAIR（最多 3 轮）
> - REVIEW 不通过（有 Critical/Important）→ review_fix → 重审（最多 3 轮）
> - VERIFY 失败 → 自动分类，REAL_BUG 进 REPAIR（最多 3 轮），ENVIRONMENT 暂停提示用户
> - `--no-verify` → 跳过 VERIFY，直接 MEMORY

## EXECUTE 阶段规则

**EXECUTE 阶段只有一种执行方式：必须调用 `Skill: superpowers:executing-plans`。没有其他选项。禁止自己逐 Task 写代码。**

操作步骤：
1. **立即调用** `Skill: superpowers:executing-plans`（不是参考，是调用）
2. 读取 Plan 文件完整内容，提取所有 Task 文本
3. 按 Plan 逐 Task 执行，每步验证
4. 全部 Task 完成并验证通过后，调用：
   ```
   loop continue --state-file .ai/run.json --result '{"sdd_completed": true, "tasks_executed": N, "summary": "..."}'
   ```

**禁止行为：**
- 自己逐 Contract 写代码（confirm_checklist / lock_plan / 逐个 execute 全部禁止）
- 跳过 executing-plans 直接进 REVIEW
- 在执行过程中暂停等待用户

## Guardrails

- 改动超过 Plan 声明的 `allowed_files` → 停止，发起 Plan Change Request
- 涉及 DB schema / 权限变更但 Plan 未声明 → 停止，升级给用户
- 禁止手动编辑 `.ai/run.json`，状态流转必须通过 `loop continue`
- 禁止跳过 `loop continue` 直接改代码进入下一阶段
- 结果用中文呈现
- 不删断言让测试通过
- 不改场景 YAML 让错误代码通过
- 环境故障不进 REPAIR
- 最多 3 轮修复
