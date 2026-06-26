---
name: aicode-dev
user-invocable: true
description: "迭代开发 — 状态机全程驱动"
---

# /aicode-dev — 迭代开发

已有 Spec/Plan/Scenarios 的开发模式。**状态机一次性启动，整个流程不打断。**

```
/aicode-dev "根据 docs/plan/abc.md 生成代码" --plan-file docs/plan/abc.md
/aicode-dev "需求描述" --spec-file docs/spec/xxx.md
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
{engines_cmd} loop full --state-file .ai/run.json --task "<用户任务描述>" --plan-file <plan路径>
```

如果用户指定了 Spec 文件路径，同样提取并传入 `--spec-file`。

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

**循环内绝对禁止：** 汇报进度、展示 diff、追问用户、输出无关内容。唯一合法行为：读 JSON → 做 pending_action → loop continue。

### loop continue 命令

每个 pending_action 完成后，执行以下命令进入下一阶段：

```bash
{engines_cmd} loop continue --state-file .ai/run.json --format json
```

读返回的 JSON，根据新的 `needs_ai_input` 和 `pending_action` 继续循环。

### pending_action 对照表

| pending_action | AI 做什么 | 结果 JSON |
|---|---|---|
| `generate_spec` | 调用 `/aicode-spec` 生成需求规格 | `{"spec_file": "...", "summary": "..."}` |
| `generate_plan` | 读 Plan 文件提取 Task Contracts：每个 Contract 包含 `task_id`、`goal`、`allowed_files`、`budget` | `{"contracts": [{"task_id": "...", "goal": "...", "allowed_files": [...], "budget": {...}}]}` |
| `execute_contracts` | 逐 Contract 实现代码：每个 Contract 先输出 checklist → 最小修改 → 编译验证 → 记录结果 | `{"completed": N, "total": N, "changed_files": [...], "summary": "...", "compile_passed": true/false}` |
| `review` | 调用 `/aicode-review` 执行 6 维深度审查 | `{"passed": true/false, "violations": [...], "critical_count": N, "important_count": N, "minor_count": N, "summary": "..."}` |
| `review_fix` | 修复审查发现的违规 | `{"fixed": true/false, "changes": [{"file": "...", "description": "..."}], "summary": "..."}` |
| `verify` | 调用 `/aicode-verify --auto-fix` 执行场景验证 | 读 `.ai/reports/test-report-*.json` 最新一份，根据断言结果决定后续 |
| `repair` | 分析验证失败根因，最小修复代码（不删断言、不改场景） | `{"changed_files": [...], "summary": "...", "root_cause": "..."}` |
| `memory` | 调用 `/aicode-memory` 沉淀经验 | `{"files": [".claude/rules/loop-memory-xxx.md", ...]}` 或 `{"skipped": true, "reason": "无值得沉淀的经验"}` |

### 状态机流转

```
SPEC → PLAN → EXECUTE ⇄ REPAIR → REVIEW → VERIFY ⇄ REPAIR → MEMORY → COMPLETED
  ↑       ↑        ↑       ↑        ↑         ↑       ↑         ↑
  AI     AI   逐Contract  AI修复   AI审查   Python   AI修复   AI记忆
 生成    提取   实现代码            6维审查   跑场景
```

- 已有 Spec → 跳过 SPEC 阶段
- 已有 Plan Contracts → 跳过 PLAN 阶段
- EXECUTE 失败（编译/逻辑错误）→ 进 REPAIR（最多 3 轮）
- REVIEW 不通过（有 Critical/Important）→ review_fix → 重审（最多 3 轮）
- VERIFY 失败 → 自动分类，REAL_BUG 进 REPAIR（最多 3 轮），ENVIRONMENT 暂停提示用户
- `--no-verify` → 跳过 VERIFY，直接 MEMORY

## EXECUTE 阶段规则

每个 Contract 执行前必须输出 checklist：

```
Executing Contract: tc-1
Goal: <goal>
Allowed Files: <list>
I will:
- <具体改动 1>
- <具体改动 2>
Run: mvn compile
```

一个 Contract 完成后立即编译验证，通过后才进入下一个 Contract。

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
