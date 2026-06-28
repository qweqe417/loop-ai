---
name: aicode-full
user-invocable: true
description: "全新需求 — 状态机全程驱动 8 阶段"
---

# /aicode-full — 全新需求完整流程

从需求到代码的完整 8 阶段闭环。**状态机一次性启动，整个流程不打断。**

```
/aicode-full "实现用户登录功能，支持 JWT 认证"
/aicode-full "根据 docs/plan/abc.md 生成代码" --plan-file docs/plan/abc.md
/aicode-full "需求描述" --spec-file docs/spec/xxx.md
```

- 已有 Spec/Plan/Scenarios 的阶段会自动跳过
- Plan 文件路径从用户消息中提取，传入 `--plan-file`
- Spec 文件路径同样提取，传入 `--spec-file`

## full vs dev vs direct — 一句话

| `/aicode-direct` | `/aicode-dev` | `/aicode-full` |
|------------------|---------------|----------------|
| Bug 修复，你清楚要改什么 | 已有 Spec/Plan，逐 Contract 实现 | 全新需求，AI 帮你从零生成 Spec → Plan → 代码 |

**不做预判。** 如果你选错了，状态机会在 REVIEW/VERIFY 阶段发现问题，该修的修。

## Execution — 状态机全程驱动

启动一次，循环响应 `pending_action`，直到 `final_stage: "completed"`。

### 首次启动

```bash
{engines_cmd} loop full --state-file .ai/run.json --task "<用户任务描述>"
```

如果用户指定了 Plan 或 Spec 文件路径，提取并传入 `--plan-file` / `--spec-file`。

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

每个 pending_action 完成后，必须用正确的 state file 继续：

```bash
{engines_cmd} loop continue --state-file .ai/run.json --result '<JSON>'
```

**state file 路径必须与首次启动时一致。** 如果首次用 `.ai/run.json`，后续所有 continue 都用 `.ai/run.json`。

### pending_action 对照表

| pending_action | 阶段 | 做什么 | 提交格式 `--result '<JSON>'` |
|---|---|---|---|
| `generate_spec` | SPEC | 运行 /aicode-spec 生成 Spec，输出到 .ai/spec.md 或 docs/spec/ | `{"spec_file": ".ai/spec.md", "summary": "..."}` |
| `generate_plan` | PLAN | 运行 /aicode-plan 从 Spec 生成 Plan + 提取 Task Contracts | `{"plan_file": ".ai/plan.md", "contracts": [{"task_id": "T1", "goal": "...", "allowed_files": [...], "budget": {...}}], "summary": "..."}` |
| `generate_scenarios` | TEST_DESIGN | 运行 /aicode-test-design --mode full 生成场景 YAML | `{"scenario_dir": "<子目录名>", "scenarios": [...], "summary": "..."}` |
| `confirm_checklist` | ~~EXECUTE~~ | 已废弃，改用 executing-plans |
| `lock_plan` | ~~EXECUTE~~ | 已废弃，改用 executing-plans |
| `execute_task` | EXECUTE | **必须调用** `Skill: superpowers:executing-plans` 执行所有 Task，完成后 report | `{"sdd_completed": true, "tasks_executed": N, "changed_files": [...], "summary": "..."}` |
| `await_plan_change_approval` | ~~EXECUTE~~ | 已废弃，改用 executing-plans |
| `review` | REVIEW | 运行 /aicode-review 执行 6 维静态审查 | `{"passed": true/false, "violations": [{"severity": "Critical/Important/Minor", "file": "path:line", "description": "..."}], "critical_count": N, "important_count": N, "minor_count": N, "summary": "..."}` |
| `review_fix` | REVIEW | 修复审查发现的 Critical/Important 违规，不改 Minor | `{"fixed": true/false, "changes": [{"file": "...", "description": "..."}], "summary": "..."}` |
| `repair` | VERIFY | 分析验证失败根因，最小修复代码（不删断言、不改场景 YAML） | `{"changed_files": [...], "summary": "...", "root_cause": "..."}` |
| `memory` | MEMORY | 运行 /aicode-memory 沉淀经验到 .claude/rules/loop-memory-*.md | `{"files": [".claude/rules/loop-memory-xxx.md", ...]}` 或 `{"skipped": true, "reason": "无值得沉淀的经验"}` |

### 状态机流转

```
INTAKE → SPEC → PLAN → TEST_DESIGN → EXECUTE → REVIEW → VERIFY ⇄ REPAIR → MEMORY → COMPLETED
   ↑       ↑       ↑         ↑           ↑         ↑        ↑       ↑         ↑
  自动   AI生成  AI生成   AI生成场景  Plan执行  AI审查   Python  AI修复   AI记忆
 风险评估  Spec   Plan+Contracts      subagent   6维审查   跑场景   最小修复
```

- INTAKE：Python 自动分析风险等级，无需 AI 参与
- 已有 Spec → 跳过 SPEC 阶段
- 已有 Plan Contracts → 跳过 PLAN 阶段
- 已有 Scenarios → 跳过 TEST_DESIGN 阶段
- REVIEW 不通过（有 Critical/Important）→ review_fix → 重审（最多 3 轮）
- VERIFY 失败 → 自动分类，REAL_BUG 进 REPAIR（最多 3 轮），ENVIRONMENT 暂停提示用户
- 所有 AI 阶段产物写入文件后，通过 loop continue 让 Python Gate 校验

## 各阶段详细规则

### SPEC 阶段

生成 Spec 后必须写入文件（`.ai/spec.md` 或 `docs/spec/*.md`）。Python Gate 会检查文件存在 + 大小 > 200 字节。

### PLAN 阶段

生成 Plan 后写入文件，**同时必须提取 Contracts**：

```json
{
  "contracts": [
    {
      "task_id": "T1",
      "goal": "实现 JWT Token 签发",
      "allowed_files": ["src/auth/jwt.py", "src/auth/models.py"],
      "forbidden_files": [],
      "budget": {"max_files": 3, "max_lines_changed": 200}
    }
  ]
}
```

每个 Contract 必须声明 `allowed_files` 限制修改范围。Contracts 为空会导致 EXECUTE 阶段失败。

### TEST_DESIGN 阶段

生成的场景 YAML 写入 `.ai/scenarios/<feature>/` 子目录。返回 `scenario_dir` 告诉引擎去哪里找。

### EXECUTE 阶段

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
- 自己逐 Contract 写代码（confirm_checklist / lock_plan / 逐个 execute_task 全部禁止）
- 跳过 executing-plans 直接进 REVIEW
- 在执行过程中暂停等待用户

**原有 confirm_checklist / lock_plan / await_plan_change_approval 已废弃，忽略它们。**

### REVIEW 阶段

先跑 Layer1 机械规则（Python），再跑 Layer2 语义审查（AI）。Critical/Important 违规必须修复，Minor 记录不阻断。

### VERIFY 阶段

Python 引擎自动跑场景验证。失败自动分类：
- REAL_BUG → 进 REPAIR，AI 修复后重新验证
- ENVIRONMENT → 暂停，提示用户检查环境

## 常见断点与恢复

**state file 路径不一致** — 最常见断点。初始命令用 `--state-file .ai/run.json`，后续所有 continue 也必须用同样路径。

**ABORTED 状态** — `entry=aborted` 说明上次运行已异常终止。重新运行初始启动命令启动新流程。

**plan_contracts 为空** — `generate_plan` 提交时忘了 `contracts` 字段。确保返回完整 `contracts` 数组。PlanHandler 最多重试 3 次。

**State file not found** — CWD 不对或路径不一致。确认当前目录是项目根目录。

**loop continue 的 --result JSON 格式错误** — 用单引号包裹整个 JSON，内部用双引号。

## Guardrails

- 所有 AI 产物先写文件，再通过 loop continue 让 Gate 校验
- 改动超过 Plan 声明的 `allowed_files` → 停止，发起 Plan Change Request
- 涉及 DB schema / 权限变更但 Plan 未声明 → 停止，升级给用户
- 禁止手动编辑 `.ai/run.json`，状态流转必须通过 `loop continue`
- 禁止跳过 `loop continue` 直接改代码进入下一阶段
- 不删断言让测试通过
- 不改场景 YAML 让错误代码通过
- 环境故障不进 REPAIR
- 最多 3 轮修复/审查
- 结果用中文呈现