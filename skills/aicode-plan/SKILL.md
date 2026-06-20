---
name: aicode-plan
user-invocable: true
description: "Generate an Execution Plan — break requirements into tasks with boundaries, budget, and contracts"
---

# /aicode-plan — 生成执行计划

> **核心原则：确定需求来源 → 评估是否需要 Spec → 加载上下文 → superpowers 实现分析 → 生成 Plan → 质量门禁 → 用户确认。**
>
> **Plan 阶段不写代码，不加载 Memory，不修改任何配置文件。**

---

## 完整流程

### 步骤 0：理解用户输入模式

用户可能进入 Plan 的 5 种模式：

| # | 模式 | 说明 |
|---|------|------|
| 1 | **Spec 自然过渡** | 刚从 /aicode-spec 确认了 spec，直接进 plan |
| 2 | `--from <spec-name>` | 显式指定 `docs/spec/<name>.md` |
| 3 | `/aicode-plan <文字描述>` | 用户直接用文字描述需求 |
| 4 | `/aicode-plan --from-prd <目录>` | 用户指定 PRD 目录 |
| 5 | `/aicode-plan` | 无任何附加内容 |

记下当前是哪种模式。

---

### 步骤 1：强检 superpowers（阻断）

尝试调用 `Skill: superpowers:planning`。

- **成功** → 继续步骤 2。
- **失败**（skill not found）→ 告诉用户："superpowers 是 plan 生成的必需依赖，正在自动安装..."

  执行安装（根据当前工具选择命令）：
  - Claude Code: `claude plugins install superpowers`
  - Codex: `codex plugin install superpowers`

  安装完成后继续步骤 2。

---

### 步骤 2：提醒 CodeGraph（非阻断，区分场景）

- **从 Spec 过渡而来**（模式 1）→ 跳过。spec 阶段已提醒过。
- **直接进入 /aicode-plan**（模式 2/3/4/5）→ 尝试 `codegraph_status`：
  - 已初始化 → 继续。
  - 未初始化 → 告诉用户："建议安装 CodeGraph 以便理解项目结构（`codegraph init -i`），跳过不影响 plan 生成。"

不阻断，继续下一步。

---

### 步骤 3：确定需求来源（按优先级）

| 优先 | 来源 | 处理方式 |
|------|------|---------|
| 1 | Spec 过渡（模式 1） | 直接用刚生成的 `docs/spec/<name>.md` |
| 2 | `--from <name>`（模式 2） | Read `docs/spec/<name>.md` |
| 3 | `docs/spec/` 自动发现 | Glob `docs/spec/*.md`，单个直接用，多个 AskUserQuestion 让用户选 |
| 4 | `.ai/prd/` 下有文件 | Glob `.ai/prd/*.{md,txt}`，单个直接用，多个让用户选 |
| 5 | 用户输入文字（模式 3） | 用文字作为需求 |
| 6 | 什么都没有（模式 5） | 询问用户"你有什么需求？或把文档放到 .ai/prd/ 下" |

---

### 步骤 4：评估是否需要先生成 Spec

- **来源是 1/2/3（已有 Spec）→ 跳过评估。** Spec 已充分。
- **来源是 4/5/6（PRD / 用户文字 / 无输入）**：
  - **内容明确**（如"给 OrderService 加分页查询接口"）→ 不需要 Spec，直接 Plan。
  - **需求模糊**（范围不清、目标不明确）→ 用 AskUserQuestion 询问：
    > "需求范围不太明确，建议先 `/aicode-spec` 明确需求和边界。你也可以坚持直接生成 Plan。"
    - 用户接受 → 跳转 `/aicode-spec`
    - 用户坚持 → 继续 Plan，但在 Plan 文件开头标注 `> ⚠️ 无 Spec，可能遗漏边界`

---

### 步骤 5：加载项目上下文

- `codegraph_context` 了解模块结构和依赖关系（**必须**）
- 有 Spec → Read `docs/spec/<name>.md`
- 有 PRD → Read `.ai/prd/<name>.md`

**不读** CLAUDE.md、rules（系统 prompt 已自动加载）
**不读** Memory（Execute/Repair 阶段才需要）

---

### 步骤 6：superpowers 做实现方案分析

调用 `Skill: superpowers:planning`，输入：

| 输入 | 内容 |
|------|------|
| 需求 | Spec / PRD / 用户文字描述 |
| 项目上下文 | codegraph 返回的模块结构、依赖关系 |

superpowers planning 会产出：Task 拆解、文件边界、依赖顺序、可复用代码、潜在风险。

---

### 步骤 7：生成 Plan → Write `docs/plan/<name>.md`

基于 superpowers planning 的输出，生成 Plan 文件。

文件内容：

```markdown
# Plan: <特性名称>

> 关联 Spec: docs/spec/<name>.md（有则写，无则标注"⚠️ 无 Spec"）

## Task 列表

### T1: <标题>
- **Goal**: 这个 Task 达成什么
- **Allowed Files**: file1.py, file2.py
- **Forbidden Files**: file3.py, migrations/
- **绑定**: AC-1, AC-2 / Scenario: xxx
- **Style Contract**: must: 遵循现有命名 / forbidden: 引入新依赖
- **Reuse Check**: 搜索已有: validator, base_service
- **Implementation**: 1. xxx  2. xxx  3. xxx
- **Verification**: lint + 测试命令 + 场景断言
- **Done When**: curl 返回 200，响应包含分页字段
- **Budget**: maxFiles=2, maxLines=80

### T2: ...
### T3: ...

## Budget 汇总

| Task | 文件数 | 预计行数 |
|------|--------|---------|
| T1   | 2      | 80      |
| T2   | 3      | 150     |
| T3   | 1      | 40      |

## 风险点
- T2 涉及缓存层改造，需确认 Redis key 命名规范
- ...
```

---

### 步骤 8：Plan 质量门禁

自查以下项：

- [ ] 如果有 Spec，每个 Acceptance Criteria 都绑定到至少一个 Task？
- [ ] 每个 Task 都有 allowedFiles / forbiddenFiles？
- [ ] 每个 Task 都有 doneWhen（且可验证，不是"做好了"）？
- [ ] 每个 Task 都有 verification？
- [ ] 没有 Task 超过 5 个文件？（超过则需拆分）
- [ ] 禁止范围膨胀：没有无关重构/格式化/新抽象？
- [ ] 无 Spec 时 Plan 文件开头标注了风险？

不通过 → 补写。通过 → 进入步骤 9。

---

### 步骤 9：呈现给用户确认

```
✅ Plan 生成完成

文件: docs/plan/<name>.md
Task 数: 3  |  总预算: 6 files / ~270 lines

T1: <标题>  (2 files, 80 lines)
T2: <标题>  (3 files, 150 lines)
T3: <标题>  (1 file, 40 lines)

确认后执行 /aicode-dev 开始开发。
```

等待用户确认。

---

## Guardrails

- **不写代码** — Plan 阶段只写计划文档
- **不加载 Memory** — 方案设计不受历史经验限制
- **codegraph 获取结构** — 不手动 grep 项目文件
- **每个 Task 有边界** — allowedFiles / forbiddenFiles 必填
- **每个 Task 可验证** — doneWhen 必须具体可验证，不能用模糊词
- **禁止范围膨胀** — 不允许在同一个 Task 中混入无关重构、格式化或新抽象
