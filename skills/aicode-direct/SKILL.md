---
name: aicode-direct
user-invocable: true
description: "Fast track for small changes and bug fixes — 状态机全程驱动 TDD → Review → Gate → Verify → Memory"
---

# /aicode-direct — Direct Mode

轻量通道。小改动、小 bug 修复。**状态机一次性启动，整个流程不打断。**

```
/aicode-direct <小改动或bug>
/aicode-direct --no-verify "改个日志级别"        # 跳过场景验证
```

- 默认：TDD → Review → Gate → Verify → Repair → Memory，全自动
- `--no-verify`：跳过 Verify，到 Memory 结束

## direct vs dev — 一句话

| `/aicode-direct` | `/aicode-dev` |
|------------------|---------------|
| Bug 修复、小改动，你清楚要改什么 | 需求复杂，需要 AI 先帮你理清思路再写 |

**不做预判。** 如果你选错了，状态机会在 REVIEW/VERIFY 阶段发现问题，该修的修，修不了的升级给你。流程本身兜底，不用靠前置检查挡人。

## Execution — 状态机全程驱动

启动一次，循环响应 `pending_action`，直到 `final_stage: "completed"`。

### Pre-flight：检查场景覆盖

启动状态机前，**先检查有没有覆盖此改动的场景**：

1. 扫一眼 `.ai/scenarios/` 下有没有匹配此功能的 YAML（含子目录）
2. **没有 → 立即调用 `/aicode-test-design`**，为当前改动生成 1~2 个最小场景 YAML
3. 有（或生成完成）→ 启动状态机

### 首次启动

```bash
{engines_cmd} loop direct --state-file .ai/run.json --task "<用户任务描述>"
```

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

### pending_action 对照表

| pending_action | AI 做什么 | 结果 JSON |
|---|---|---|
| `direct_execute` | TDD 写代码（先写测试→失败→最小实现→通过） | `{"changed_files": [...], "summary": "...", "lines_added": N, "lines_removed": N}` |
| `review` | 调用 `/aicode-review` 执行 6 维深度审查 | `{"passed": true/false, "violations": [...], "critical_count": N, "important_count": N, "minor_count": N, "summary": "..."}` |
| `review_fix` | 修复审查违规 | `{"fixed": true/false, "changes": [{"file": "...", "description": "..."}], "summary": "..."}` |
| `repair` | 分析失败根因，最小修复 | `{"changed_files": [...], "summary": "...", "root_cause": "..."}` |
| `memory` | 调用 `/memory` 沉淀经验 | `{"files": [".claude/rules/loop-memory-xxx.md", ...]}` 或 `{"skipped": true, "reason": "无值得沉淀的经验"}` |

### 状态机流转

```
DIRECT_EXECUTE → REVIEW → VERIFY ⇄ REPAIR → MEMORY → COMPLETED
     ↑              ↑        ↑       ↑         ↑
  AI做TDD       AI审查   0 token   AI修复   AI记忆
```

- REVIEW 不通过 → review_fix → 重审（最多3轮）
- VERIFY 失败 → 自动分类，REAL_BUG 进 REPAIR（最多3轮）
- --no-verify → 跳过 VERIFY，直接 MEMORY

## Guardrails

- 改动超过 3 个文件 → 停止，建议用 `/aicode-dev`
- 涉及 DB schema / 权限 → 停止，建议用 `/aicode-dev`
- 结果用中文呈现
