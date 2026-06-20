# AI Coding Loop 技术文档

> 版本: 1.0 | 日期: 2026-06-19 | 状态: 全部 32 个架构缺口已修复

---

## 目录

1. [系统定位与设计目标](#1-系统定位与设计目标)
2. [四层架构模型](#2-四层架构模型)
3. [项目目录结构](#3-项目目录结构)
4. [Loop Engineering 流程引擎](#4-loop-engineering-流程引擎)
5. [状态管理 (State)](#5-状态管理-state)
6. [运行时与阶段处理器 (Runtime)](#6-运行时与阶段处理器-runtime)
7. [上下文路由 (Context Router)](#7-上下文路由-context-router)
8. [Guard 安全门禁系统](#8-guard-安全门禁系统)
9. [Memory 记忆系统](#9-memory-记忆系统)
10. [Scenario Runner 场景验证](#10-scenario-runner-场景验证)
11. [Plan 执行合约系统](#11-plan-执行合约系统)
12. [Spec 规格生成系统](#12-spec-规格生成系统)
13. [工具适配器层 (Adapter)](#13-工具适配器层-adapter)
14. [CLI 命令行接口](#14-cli-命令行接口)
15. [Python ↔ AI 交互协议](#15-python--ai-交互协议)
16. [Init 项目初始化](#16-init-项目初始化)
17. [Provider 扩展机制](#17-provider-扩展机制)
18. [子循环系统](#18-子循环系统)
19. [安全机制全景](#19-安全机制全景)
20. [关键数据流图](#20-关键数据流图)

---

## 1. 系统定位与设计目标

### 1.1 一句话定位

**把 AI Coding 的工程闭环，以插件形式集成到 Claude Code、Codex、Cursor 等工具中。**

### 1.2 核心能力闭环

```
项目理解 → 需求 Spec 化 → Plan/Task 拆解 → AI 编码执行
→ 真实流程验证 → 根因分析 → 自动修复 → Review → 记忆沉淀 → 跨工具复用
```

### 1.3 设计原则

| 原则 | 说明 |
|------|------|
| **插件优先** | 以插件形态进入现有 AI 编程工具，用户不学新平台 |
| **Core/Adapter 分离** | 核心能力不绑定任何特定工具 |
| **Provider 模式** | Superpowers/spec-kit/OpenSDD 作为外部 Provider 接入 |
| **渐进式上下文** | Context Router 按阶段注入上下文，防止 Token 爆炸 |
| **真实流程验证** | 优先调用接口/查数据库/查 Redis 验证，而非只靠单元测试 |
| **Python 做确定性工作** | 状态流转/Guard/ContextRouter/ScenarioRunner 由 Python 执行 |
| **AI 做创造性工作** | 写 Spec/填 Plan/写代码/分析根因由 AI 完成 |

---

## 2. 四层架构模型

系统分为四层，每层有明确职责边界：

```
┌──────────────────────────────────────────────────────────────┐
│  Prompt Layer (怎么问)                                        │
│  skills/*.md — AI 的"剧本"，告诉 AI 调什么命令、怎么读 JSON、 │
│  如何决策。每个 skill 是一个 Markdown 文件，内含步骤指令。     │
├──────────────────────────────────────────────────────────────┤
│  Context Layer (让 AI 看到什么)                               │
│  ContextRouter + FileSource + CodeGraphSource + MemorySource  │
│  按阶段策略注入上下文，Token 预算裁剪，priority 分层。        │
├──────────────────────────────────────────────────────────────┤
│  Harness Layer (AI 在什么环境里工作)                          │
│  Guard 规则引擎 + PlanLock 状态机 + Diff Budget +             │
│  Code Quality Gate + Worktree 隔离 + QuickCheck + Schema      │
│  Version + Rollback Planner                                  │
├──────────────────────────────────────────────────────────────┤
│  Loop Layer (AI 做完一步后怎么办)                             │
│  LoopRunner 驱动 8 阶段流转 + 熔断器 + 检查点 +              │
│  Python↔AI 握手协议 + 子循环系统                              │
└──────────────────────────────────────────────────────────────┘
```

### 2.1 Prompt Layer 详细设计

**Skills 目录** (`skills/`) 包含工具无关的 Markdown 剧本文件：

| Skill 文件 | 对应命令 | 功能 |
|-----------|---------|------|
| `full.md` | `/aicode-full` | 完整 8 阶段流程 |
| `dev.md` | `/aicode-dev` | 开发模式（已有 Spec/Plan） |
| `test.md` | `/aicode-test` | 测试模式（仅验证+修复） |
| `direct.md` | `/aicode-direct` | 快速通道（小改动） |
| `spec.md` | `/aicode-spec` | 仅生成 Spec |
| `plan.md` | `/aicode-plan` | 仅生成 Plan |
| `verify.md` | `/aicode-verify` | 运行验证 |
| `review.md` | `/aicode-review` | 代码审查 |
| `memory.md` | `/aicode-memory` | 记忆沉淀 |
| `init.md` | `/aicode-init` | 项目初始化 |
| `calibrate.md` | `/aicode-calibrate` | 规则校准 |

每个 skill 采用固定格式：
```markdown
---
name: aicode-<name>
description: "简短描述"
---

# /aicode-<name>

## 触发条件
## 执行
### Step N: 做什么
```bash
bash ${CLAUDE_PLUGIN_ROOT}/engines/run.sh <command> --format json
```
### Step N+1: 读结果
- JSON 字段含义
- 判断逻辑
### Step N+2: 决策/行动
## 禁止行为
```

### 2.2 Context Layer 详细设计

参见 [第 7 节](#7-上下文路由-context-router)。

### 2.3 Harness Layer 详细设计

参见 [第 8 节](#8-guard-安全门禁系统) 和 [第 11 节](#11-plan-执行合约系统)。

### 2.4 Loop Layer 详细设计

参见 [第 4 节](#4-loop-engineering-流程引擎) 和 [第 15 节](#15-python--ai-交互协议)。

---

## 3. 项目目录结构

```
ai-coding-loop/
├── plugin.json                    # 工具无关的插件声明
├── AI_CODING_LOOP_ARCHITECTURE.md # 架构设计文档
├── AI_CODING_LOOP_技术文档.md     # 本文档
│
├── skills/                        # Prompt Layer: 工具无关的 Markdown 剧本
│   ├── full.md / dev.md / test.md / direct.md
│   ├── spec.md / plan.md / verify.md / review.md / memory.md
│   ├── init.md / calibrate.md
│
├── engines/                       # Python 引擎: 工具无关
│   ├── run.sh / run.bat           # 入口脚本
│   ├── cli.py                     # 统一 CLI 入口 (argparse, 输出 JSON)
│   │
│   ├── state/                     # 状态管理
│   │   ├── enums.py               # StageType / LoopAction / TaskStatus / FailureCategory 等枚举
│   │   ├── models.py              # RunState / TaskIntakeResult / FailureRecord 等 Pydantic 模型
│   │   └── serialization.py       # JSON 序列化/反序列化
│   │
│   ├── runtime/                   # Loop 引擎 + 阶段处理器
│   │   ├── loop_runner.py         # 核心循环引擎: 驱动 RunState 完成 8 阶段流转
│   │   ├── stage_handlers.py      # 9 个阶段处理器: Intake/Spec/Plan/Execute/Verify/Repair/Review/Memory/DirectExecute
│   │   ├── worktree_isolator.py   # Git worktree 隔离环境
│   │   ├── daemon.py              # Daemon 模式骨架
│   │   ├── direct_executor.py     # Direct Mode 执行器
│   │   └── git_sync.py            # 上游 Git 同步
│   │
│   ├── guard/                     # Guard 安全门禁系统
│   │   ├── engine.py              # Guard 引擎: 规则注册 + 执行
│   │   ├── rules.py               # 10 条 Guard 规则
│   │   ├── models.py              # GuardResult / Violation
│   │   ├── code_quality.py        # Code Quality Gate
│   │   ├── quick_check.py         # Per-task 快速检查 (py_compile/ruff/tsc/eslint/go vet)
│   │   ├── rollback.py            # 回滚方案自动生成
│   │   └── schema_version.py      # Schema 版本追踪
│   │
│   ├── context/                   # Context Router 上下文路由
│   │   ├── router.py              # 路由器: 策略→收集→排序→裁剪→组装
│   │   ├── sources.py             # 数据源: FileSource / CodeGraphSource / MemorySource
│   │   ├── strategies.py          # 阶段策略: 每阶段要什么数据
│   │   └── models.py              # ContextPiece / ContextBundle / ContextBudget
│   │
│   ├── memory/                    # Memory 记忆系统
│   │   ├── store.py               # MemoryStore: .ai/memory.md 读写 + CRUD + LRU 淘汰
│   │   ├── extractor.py           # MemoryExtractor: 从 RunState 提取候选记忆
│   │   ├── projection.py          # MemoryProjection: 同步到 CLAUDE.md/.codex/.cursor
│   │   └── models.py              # MemoryEntry / MemoryCategory / Confidence / SessionMemory
│   │
│   ├── scenario/                  # Scenario Runner 场景验证
│   │   ├── runner.py              # 场景执行器
│   │   ├── models.py              # Scenario / SanityCheckItem / ScenarioResult
│   │   ├── sanity.py              # SanityChecker: 环境健康检查
│   │   ├── assertion.py           # 断言引擎
│   │   └── resources.py           # 资源适配器
│   │
│   ├── plan/                      # Plan 执行合约
│   │   ├── models.py              # PlanContract / TaskContract
│   │   ├── lock.py                # PlanLock: 状态机 (unlocked/locked/change_requested/breached)
│   │   ├── quality_gate.py        # PlanQualityGate: 检查覆盖度/边界/粒度
│   │   └── contracts.py           # 合约工具
│   │
│   ├── spec/                      # Spec 规格生成
│   │   ├── models.py              # SpecEntry / SpecContextPacket / BrainstormResult / ImpactDomain
│   │   └── quality_gate.py        # SpecQualityGate: 模糊词检测/完整性/可测性
│   │
│   ├── init/                      # 项目初始化
│   │   ├── init_runner.py         # 12 步 init 流程编排
│   │   ├── scanner.py             # ProjectScanner: 语言/框架/风格/资源检测
│   │   ├── generator.py           # FileGenerator: 通过 Adapter 生成工具原生文件
│   │   └── models.py              # ProjectProfile / InitReport / ScanResult
│   │
│   ├── adapters/                  # 工具适配器
│   │   ├── base.py                # ToolAdapter 抽象基类 + McpServerDef
│   │   ├── claude.py              # ClaudeCodeAdapter: → CLAUDE.md/.claude/rules/.claude/skills
│   │   ├── codex.py               # CodexAdapter: → .codex/instructions.md/.codex/skills/
│   │   └── cursor.py              # CursorAdapter: → .cursor/rules/
│   │
│   └── providers/                 # 外部能力 Provider
│       ├── base.py                # Provider 抽象基类
│       ├── superpowers.py         # Superpowers Provider (Spec/Plan/Brainstorm)
│       ├── scenario_runner.py     # Scenario Runner Provider (内置)
│       └── mcp_registry.py        # MCP Server 自动检测
│
├── adapters/                      # 适配器安装脚本 (legacy)
│   └── claude/
│       └── install.py
│
└── hooks/
    └── session-start.py           # SessionStart Hook 逻辑
```

---

## 4. Loop Engineering 流程引擎

### 4.1 完整流程 (8 阶段)

```
INTAKE → SPEC → PLAN → EXECUTE → VERIFY → REPAIR → REVIEW → MEMORY → COMPLETED
  ↑                                                          ↑
  └──────────────── 异常终止 (ABORTED) ──────────────────────┘
```

### 4.2 流程变体 (子循环)

| 模式 | CLI 命令 | 阶段序列 | 用途 |
|------|---------|---------|------|
| **full** | `loop full` | INTAKE→SPEC→PLAN→EXECUTE→VERIFY→REPAIR→REVIEW→MEMORY | L3-L5 完整流程 |
| **dev** | `loop dev` | EXECUTE→VERIFY→REPAIR→REVIEW | 已有 Spec/Plan 的执行 |
| **test** | `loop test` | VERIFY↻REPAIR | 验证+修复循环 |
| **spec** | `loop spec` | INTAKE→SPEC | 仅生成 Spec |
| **plan** | `loop plan` | SPEC→PLAN | 仅生成 Plan |
| **direct** | `loop direct` | DIRECT_EXECUTE→VERIFY→REVIEW | L1-L2 快速通道 |
| **verify** | `loop verify` | VERIFY | 单次验证 |
| **review** | `loop review` | REVIEW | 单次审查 |
| **memory** | `loop memory` | REVIEW→MEMORY | 记忆沉淀 |

### 4.3 LoopRunner 核心循环

```python
# 伪代码
def run(state):
    for iteration in range(1, max_iterations + 1):
        # 1. 退出检查
        if is_exit(state.current_stage):
            return finalize(state)

        # 2. Guard 检查
        if guard and guard.check(state).block:
            stop_with_guard(state)

        # 3. 熔断检查 (同一失败签名重复 3 次 → 强制终止)
        if circuit_breaker_triggered(state):
            abort(state)

        # 4. 获取并执行阶段处理器
        handler = handlers[state.current_stage]
        result = handler.handle(state)
        if result is None:  # 防护: handler 返回 None → 终止
            raise RuntimeError("state corruption prevented")

        # 5. 检查是否需要暂停等待 AI 输入
        if state.needs_ai_input:
            if not state.pending_action:  # 协议校验
                abort("pending_action 为空")
            return state  # 暂停, AI 读取后通过 CLI 恢复

        # 6. 应用流转决策 (NEXT_STAGE / RETRY / BACKTRACK / STOP_*)
        state = apply_decision(state)
```

**安全参数**:
- `DEFAULT_MAX_ITERATIONS = 100` (完整流程)
- `SUB_LOOP_MAX_ITERATIONS = 30` (子循环)
- `CIRCUIT_BREAKER_THRESHOLD = 3` (熔断阈值)

### 4.4 熔断器 (Circuit Breaker)

两层签名检测防止 AI 死循环：

**层 1 — 精确签名**: `stage + category + message` (同阶段同错误重复)
**层 2 — 跨阶段签名**: `category + message` (同一根因在不同阶段表现为不同错误)

```python
def _failure_signature(failure):
    # 归一化: 数字→N, UUID→UUID, 文件路径→FILE
    normalized = re.sub(r'\d+', 'N', failure.message[:120])
    normalized = re.sub(r'[0-9a-f]{8}-...', 'UUID', normalized)
    normalized = re.sub(r'[\w/\\]+\.\w{1,4}', 'FILE', normalized)
    return f"{failure.stage}|{failure.category}|{normalized}"
```

### 4.5 流转决策 (LoopDecision)

```
NEXT_STAGE  → 按 flow table 或 handler 指定进入下一阶段
RETRY       → 重试当前阶段 (retry_count++)
BACKTRACK   → 回退到上一阶段 (从 checkpoints 恢复)
CONTINUE    → 留在当前阶段
STOP_SUCCESS → 正常终止 → COMPLETED
STOP_FAILURE → 失败终止 → ABORTED
STOP_GUARD   → Guard 拦截 → ABORTED
STOP_ABORT   → 用户中断 → ABORTED
```

---

## 5. 状态管理 (State)

### 5.1 RunState — 顶级状态载体

`RunState` 是一个 Pydantic v2 模型，贯穿整个 Loop 流程，所有阶段共享同一个实例。

```python
class RunState(BaseModel):
    # 基础标识
    task_id: str                              # 任务唯一标识
    project: str                              # 项目标识
    project_root: str                         # 项目根目录路径
    current_stage: StageType                  # 当前阶段

    # 入口分析
    task_intake: TaskIntakeResult | None      # INTAKE 阶段产出

    # ── Python ↔ AI 交互协议 ──
    pending_action: str                       # 当前等待 AI 执行的动作
    pending_prompt: dict                      # 构造给 AI 的结构化 prompt
    needs_ai_input: bool                      # Loop 是否应暂停等待 AI

    # ── Spec 阶段 ──
    spec_entry: dict | None                   # AI 生成的 SpecEntry
    spec_quality_report: dict | None          # SpecQualityGate 报告
    brainstorm_result: dict | None            # Brainstorm 输出

    # ── Plan 阶段 ──
    plan_contracts: list[dict]                # PlanContract 列表
    plan_lock_state: str                      # unlocked/locked/change_requested/breached
    plan_quality_report: dict | None          # PlanQualityGate 报告

    # ── 隔离与运行模式 ──
    use_worktree: bool                        # 是否使用 git worktree 隔离
    daemon_mode: bool                         # 是否 daemon 模式
    context_budget_max: int = 8000            # 上下文 token 预算
    context_budget_used: int = 0              # 当前已用 token

    # ── 任务执行 ──
    task_state: TaskState                     # Per-task 执行追踪
    verification: VerificationState          # 验证状态
    scenario_results: list[ScenarioResult]    # 场景验证结果

    # ── 追踪 ──
    checkpoints: list[Checkpoint]             # 检查点快照
    decision: LoopDecision | None             # 最近流转决策
    failures: list[FailureRecord]             # 失败记录
    confirmed_actions: list[UserConfirmation] # 用户确认历史
    metadata: dict                            # 扩展元数据
```

### 5.2 核心枚举

```python
class StageType(str, Enum):
    INTAKE = "intake"
    SPEC = "spec"
    PLAN = "plan"
    EXECUTE = "execute"
    VERIFY = "verify"
    REPAIR = "repair"
    REVIEW = "review"
    MEMORY = "memory"
    DIRECT_EXECUTE = "direct_execute"
    COMPLETED = "completed"
    ABORTED = "aborted"

class LoopAction(str, Enum):
    CONTINUE = "continue"
    NEXT_STAGE = "next_stage"
    RETRY = "retry"
    BACKTRACK = "backtrack"
    STOP_SUCCESS = "stop_success"
    STOP_FAILURE = "stop_failure"
    STOP_GUARD = "stop_guard"
    STOP_ABORT = "stop_abort"

class FailureCategory(str, Enum):
    ENVIRONMENT = "environment"          # 环境问题 (不可自动修复)
    TEST_DATA = "test_data"             # 测试数据问题
    CODE_LOGIC = "code_logic"           # 代码逻辑错误
    SCOPE_VIOLATION = "scope_violation" # 越界修改
    PLAN_INSUFFICIENT = "plan_insufficient" # 计划不充分
    UNKNOWN = "unknown"
```

---

## 6. 运行时与阶段处理器 (Runtime)

### 6.1 StageHandler 抽象基类

```python
class StageHandler(ABC):
    stage: StageType

    @abstractmethod
    def handle(self, state: RunState) -> RunState: ...

    # 流转辅助方法
    def _complete(self, state, reason)    # 完成当前阶段, 按 flow table 流转
    def _advance_to(self, state, target)  # 强制跳转到指定阶段
    def _retry(self, state, reason)       # 重试当前阶段
    def _stop_success(self, state, reason) # 成功终止
    def _stop_failure(self, state, reason) # 失败终止

    # 上下文预算
    def _check_context_budget(self, state, estimated_tokens) -> bool
    def _track_context_usage(self, state, tokens_used)
```

### 6.2 IntakeHandler — 任务入口

**Python 职责**: 分析任务元数据，决定分流模式。
**AI 职责**: 输入模糊时向用户提问。

流程：
1. 检查 `task_intake` 是否存在（不存在则安全拒绝，不默认 direct）
2. L4/L5 风险 → 启用 worktree 隔离 + strict guard
3. `flow_mode == "direct"` → 跳转 `DIRECT_EXECUTE`
4. 否则 → 跳转 `SPEC`

**安全默认**: 缺少 task_intake 时调用 `_stop_failure()`，**拒绝以不安全默认值执行**。

### 6.3 SpecHandler — 规格生成

**Python 职责**: 判断 Brainstorm 需求 → 构造 Context Packet → SpecQualityGate 校验 → 重试控制。
**AI 职责**: 生成 Spec / Brainstorm 内容。

完整流程 (PREPARE → VALIDATE 两阶段)：

```
PREPARE (Python):
  1. 判断是否需要 Brainstorm (风险 L4+ / 复杂度 high+ / 关键词匹配)
  2. 需要 Brainstorm → 构造 Brainstorm prompt → needs_ai_input=True → 暂停
  3. 不需要 → ContextRouter 加载上下文 → 构造 Spec Context Packet → needs_ai_input=True

AI 介入:
  4. AI 读 pending_prompt → 生成 Spec JSON 或 Brainstorm 结果
  5. AI 调 CLI: engines/run.sh loop continue --result '<JSON>'

VALIDATE (Python):
  6. Brainstorm 结果: BrainstormResult 校验 → ready_for_spec? → 是则回到 PREPARE
  7. Spec 结果: SpecEntry 构造 → SpecQualityGate.evaluate()
  8. 通过 → 清空 needs_ai_input → _complete(state)
  9. 不通过 → 返回 quality_feedback + 修正指导 → AI 重试
  10. MAX_QUALITY_RETRIES=3 次重试上限 → 超出则 _stop_failure
```

**Brainstorm 触发条件**:
- 风险等级 L4/L5 → 强制 Brainstorm
- 复杂度 unknown/high → Brainstorm
- 用户输入含"方案/设计/架构/选型/脑暴/explore"等关键词

**Spec Context Packet 结构**:
```yaml
userInput: "原始需求"
taskIntake: {inputType, taskType, complexity, riskLevel}
projectSummary: "项目简述"
relevantModules: ["order", "inventory"]
domainTerms: ["PENDING_PAYMENT", "CLOSED"]
relevantMemory: ["订单状态变更必须写 outbox event"]
existingApis: []
impactDomains: {api, database, cache, messageQueue, permission}
riskLevel: "L4"
```

**Spec Quality Gate 检查项**:
- 是否有明确目标和非目标
- 验收标准是否可测试
- 是否有异常场景
- 是否有修改边界
- 是否有待确认问题
- **模糊词检测**: 优化/尽量/适当/快速/友好/稳定/支持一下/处理一下

### 6.4 PlanHandler — 计划生成

**Python 职责**: 从 Spec 提取 → 构造 Task 框架 → PlanQualityGate → PlanLock.lock()。
**AI 职责**: 填充每个 Task 的具体内容。

流程 (PREPARE → VALIDATE)：

```
PREPARE:
  1. ContextRouter 加载 PLAN 上下文
  2. 从 SpecEntry 提取 acceptance_criteria / test_scenarios
  3. 计算默认 Diff Budget (low: 3f/100L, medium: 5f/300L, high: 8f/600L)
  4. 构造 prompt (含 Spec 摘要 + Task 框架 + Style/Ruse/Reuse 要求 + output_schema)

VALIDATE:
  5. 解析 contracts JSON → PlanContract 列表
  6. PlanQualityGate.evaluate() — 检查覆盖度/边界/粒度
  7. 通过 → PlanLock.lock() 所有 contracts → plan_lock_state="locked"
  8. 不通过 → 返回 quality_feedback → AI 重试
```

**Plan Quality Gate 检查项**:
- 是否覆盖 Spec 中所有验收标准
- 每个 Task 是否有 allowedFiles/forbiddenFiles
- 每个 Task 是否绑定 Scenario/验证方式
- 是否有过大任务 (>5 files 建议拆分)
- 是否所有 Task 都有 doneWhen
- 是否有范围膨胀/未声明的修改

### 6.5 ExecuteHandler — 代码执行

**Python 职责**: Per-task 循环 → Task Start Gate → Guard → ContextRouter → Diff Budget 验证 → Task Execution Log。
**AI 职责**: 在约束范围内写代码。

Per-task 循环 (PREPARE → VALIDATE)：

```
PREPARE (Task Start Gate):
  1. Task Start Gate — 重新确认边界 (allowedFiles/forbiddenFiles/goal)
  2. Upstream Sync — 检查上游提交 (仅在第一个 Task 前)
  3. Worktree 隔离 — L4/L5 任务创建 git worktree
  4. Guard 前置检查 — ScopeBoundary + RiskLevel + Sanity
  5. PlanLock 状态检查 — unlocked→要求锁定, change_requested→等待审批, breached→终止
  6. ContextRouter 注入 EXECUTE 上下文
  7. 构建 Implementation Checklist → needs_ai_input=True

AI 介入:
  8. AI 读 contract → 确认 Checklist → 写代码
  9. AI 调 CLI: loop continue --result '{"changed_files": [...], "lines_added": N, ...}'

VALIDATE (Per-task 验证):
  10. 检测 Plan Change Request → 按风险等级处理
  11. git diff --stat 交叉验证 AI 自报行数
  12. Diff Budget 检查 (文件数/行数/新抽象/新依赖)
  13. 违规 → 返回 budget_violation → AI 修正
  14. QuickCheck 增量验证 (compile/lint)
  15. 记录 TaskExecutionLog → current_task_index++ → 下一 Task 或 VERIFY
```

**Diff Budget 验证** (代码行 `engines/runtime/stage_handlers.py:1378-1418`):

```python
def _count_actual_diff(self, state, changed_files):
    """通过 git diff --stat 统计实际变更行数，交叉验证 AI 自报数据。"""
    result = subprocess.run(
        ["git", "diff", "--stat", "HEAD", "--"] + changed_files,
        capture_output=True, text=True, timeout=10,
    )
    # 解析 "3 files changed, 50 insertions(+), 12 deletions(-)"
    # 取 max(ai_reported, git_actual) 不给 AI 钻空子
```

**Implementation Checklist** (AI 编码前逐项确认):
```markdown
- [ ] 只修改 allowed_files: ["src/api/user.controller.ts"]
- [ ] 不触碰 forbidden_files: ["src/db/**", "src/auth/**"]
- [ ] 复用已有模式: ["existing query parsing", "existing validation"]
- [ ] 保持变更在预算内: max_files=3, max_lines=200
- [ ] 不引入新抽象层 (allow_new_abstractions=false)
- [ ] 不引入新依赖 (allow_new_dependencies=false)
- [ ] 运行验证: ["lint", "test", "scenario"]
- [ ] 保持已有测试通过，不删除/削弱已有断言
- [ ] 不进行无关格式化和重构
```

**Plan Change Request 处理**:
- L1/L2: 自动批准
- L3: 记录但继续
- L4/L5: 必须用户确认 (needs_ai_input=True, pending_action="await_plan_change_approval")

### 6.6 VerifyHandler — 验证

**Python 职责**: SanityChecker + ScenarioRunner。
**AI 职责**: 读失败报告、判断根因。

流程：
1. 加载 Sanity 检查项 (从 `.ai/loop-config.json` 或 fallback 到 localhost 默认)
2. 执行 Sanity Check (环境健康: 端口可达/HTTP 响应)
3. 加载 `.ai/scenarios/*.yaml` → 执行 Scenario
4. **Sanity 失败** → 记录 ENVIRONMENT 类别 FailureRecord → `_stop_failure` (环境问题不自动修复)
5. **Scenario 断言失败** → 记录 CODE 类别 FailureRecord → `_advance_to(REPAIR)`
6. **无场景文件** → 标记 SKIPPED (不是 PASSED)
7. **全部通过** → `_complete`

**Sanity Check 与 Scenario 的分工**:
| 层 | 检查什么 | 失败后果 |
|----|---------|---------|
| Sanity Check | 服务是否在运行、端口是否可达、环境是否正常 | 判定为环境故障 → 终止，不进入修复循环 |
| Scenario | 业务行为是否正确、数据状态是否符合预期 | 判定为代码故障 → 进入 REPAIR 修复循环 |

### 6.7 RepairHandler — 修复

**Python 职责**: ContextRouter 注入失败上下文。
**AI 职责**: 分析根因、最小修复。

流程：
1. 检查重试次数 (max_retries=3)
2. 分析最近 FailureRecord
3. **环境故障** → `_stop_failure` (不可通过代码修复)
4. ContextRouter 注入 REPAIR 阶段的失败相关上下文
5. `_advance_to(VERIFY)` — 回到验证阶段

### 6.8 ReviewHandler — 审查

**Python 职责**: 6 层检查 → 输出审查报告。

审查流程：
1. **Guard 检查**: ScopeBoundary + RiskLevel + Sanity
2. **Plan 合规检查**: 逐 Task 对比 PlanContract (allowedFiles/forbiddenFiles/diff budget)
3. **Anti-Cheating 检查**: TestIntegrity + AssertionWeakening + SkipModification
4. **Code Quality Gate**: 简洁性/复用/抽象/可读性
5. **回滚方案生成**: L4/L5 任务强制生成
6. **Schema 版本记录**: DDL/migration 变更自动追踪
7. 汇总 Task Execution Logs → 输出审查报告

### 6.9 MemoryHandler — 记忆沉淀

**Python 职责**: MemoryExtractor → MemoryStore → MemoryProjection。
**AI 职责**: 判断哪些值得沉淀。

流程：
1. `MemoryExtractor.extract(state)` — 从 failures/decisions/notes 提取候选
2. `MemoryStore.add(entry)` — 去重 + LRU 淘汰 + 写入 `.ai/memory.md`
3. `MemoryStore.promote_by_tags()` — 同 tag 多条目自动 DRAFT→CONFIRMED
4. `MemoryProjection.sync("claude")` — 同步到 CLAUDE.md 的 `<!-- AI_CODING_LOOP_MEMORY -->` 区块

### 6.10 DirectExecuteHandler — 快速通道

**Python 职责**: 轻量 Guard → 构造 prompt → 校验结果。
**AI 职责**: 直接编码。

流程 (PREPARE → VALIDATE)：
1. 风险等级检查: L4/L5 → 拒绝，转标准流程
2. 轻量 Guard (ScopeBoundary + RiskLevel)
3. 构造 prompt (修改 ≤3 文件, 不引入新依赖/抽象)
4. AI 提交结果 → 文件数检查 (>3 记录警告) → 记录 TaskExecutionLog
5. 可选跳过 Verify → 进入 Review

---

## 7. 上下文路由 (Context Router)

### 7.1 设计目标

防止 Context Explosion — 不在每次任务开始时一次性加载所有上下文。

### 7.2 三层架构

```
ContextRouter (路由层: 策略→收集→排序→裁剪→组装)
    ├── strategies.py (策略层: 每阶段定义要什么数据)
    ├── sources.py   (数据源层: 读文件/调 CodeGraph/读 Memory)
    └── models.py    (数据模型: ContextPiece / ContextBundle / ContextBudget)
```

### 7.3 数据源

| Source | 实现 | 读取模式 |
|--------|------|---------|
| **FileSource** | 直接读文件 | `read_full` (完整) / `read_summary` (前 80 行) |
| **CodeGraphSource** | 调 CodeGraph MCP/CLI | `get_project_map` / `get_context` / `get_impact` / `get_callers` / `get_callees` |
| **MemorySource** | 读 `.ai/memory.md` | `load_relevant` (关键词匹配) / `load_recent_failures` |

**CodeGraph 可用性检测**: 缓存 CLI 检测结果 (`_CODEGRAPH_CLI_AVAILABLE`)，不可用时 Router 自动 fallback 到 FileSource.scan_structure()。

### 7.4 Token 预算模型

```python
class ContextBudget(BaseModel):
    stage: StageType
    max_tokens: int               # 该阶段的 token 上限
    min_priority_keep: int = 1    # 最低优先级门槛

    @classmethod
    def defaults(cls) -> dict[StageType, ContextBudget]:
        return {
            StageType.INTAKE:   ContextBudget(stage=..., max_tokens=1500),
            StageType.SPEC:     ContextBudget(stage=..., max_tokens=3000),
            StageType.PLAN:     ContextBudget(stage=..., max_tokens=3000),
            StageType.EXECUTE:  ContextBudget(stage=..., max_tokens=5000),
            StageType.VERIFY:   ContextBudget(stage=..., max_tokens=4000),
            StageType.REPAIR:   ContextBudget(stage=..., max_tokens=4000),
            StageType.REVIEW:   ContextBudget(stage=..., max_tokens=3000),
            StageType.MEMORY:   ContextBudget(stage=..., max_tokens=2000),
        }
```

### 7.5 裁剪算法 (Priority-based Trim)

```python
def _trim(pieces, budget):
    # 按 priority 分层
    p1 = [p for p in pieces if p.priority == min_priority_keep]   # 必保
    p2 = [p for p in pieces if p.priority == min_priority_keep + 1] # 按需
    p3 = [p for p in pieces if p.priority > min_priority_keep + 1]  # 可选

    # Priority 1: 始终保留 (超预算时记录 warning)
    keep = list(p1)
    running = sum(p.token_estimate for p in p1)

    # Priority 2: 按 token 升序填充剩余预算
    for p in sorted(p2, key=lambda x: x.token_estimate):
        if running + p.token_estimate > budget.max_tokens:
            continue
        keep.append(p)
        running += p.token_estimate

    # Priority 3: 仅当还有预算时
    for p in sorted(p3, key=lambda x: x.token_estimate):
        if running + p.token_estimate > budget.max_tokens:
            continue
        keep.append(p)
        running += p.token_estimate

    return keep, len(keep) < len(pieces)
```

### 7.6 渐进式披露策略

| 阶段 | 注入内容 | Priority 1 | Priority 2 | Priority 3 |
|------|---------|-----------|-----------|-----------|
| INTAKE | 项目地图 + 核心规则 | project_map | CLAUDE.md 摘要 | 历史 intake 记录 |
| SPEC | 相关模块 + 领域术语 + 相关 Memory | Spec 上下文 | 模块源码摘要 | 无关 Memory |
| PLAN | Spec 摘要 + Style Contract | Plan 框架 | 相关文件摘要 | - |
| EXECUTE | 当前 Task + 2-3 相关文件 | Task contract | 完整源码 (要改的文件) | 源码摘要 (不改的文件) |
| VERIFY | Scenario + 失败摘要 | 验证场景 | 失败详情 | 历史 runs |
| REPAIR | 失败上下文 + 相关源码 | FailureRecord | 失败文件源码 | 相关 Memory |
| REVIEW | 全部 diff + 合规数据 | diff 摘要 | Plan contracts | - |
| MEMORY | 候选记忆 + 统计 | 新候选 | 已有条目 | - |

---

## 8. Guard 安全门禁系统

### 8.1 架构

```python
Guard
├── rules: list[GuardRule]     # 注册的规则列表
├── check(state) → GuardResult # 执行所有规则
└── 规则优先级: BLOCK > WARN > INFO
```

### 8.2 10 条 Guard 规则

| 规则 | 严重级别 | 检查内容 | 数据来源 |
|------|---------|---------|---------|
| **ScopeBoundaryRule** | BLOCK | 修改文件是否在授权范围 | task_logs + checkpoints |
| **RiskLevelRule** | BLOCK | 当前操作风险是否匹配 Guard 级别 | task_intake.risk_level |
| **SanityCheckRule** | WARN | 编译/lint 是否通过 | QuickCheck |
| **TestIntegrityRule** | BLOCK | 是否删除/弱化测试 | git diff + .removed 标记 |
| **AssertionWeakeningRule** | BLOCK | 是否弱化断言 | diff 中的 assert 变化 |
| **SkipModificationRule** | BLOCK | 是否新增 skip/ignore | diff 中的 skip 标记 |
| **FileSizeLimitRule** | WARN | 单个文件是否过大 (>200KB) | Path.stat() |
| **NetworkCallRule** | WARN | 是否引入网络调用 | import 检测 (requests/urllib/httpx/subprocess) |
| **SecretScanRule** | BLOCK | 是否包含密钥/Token | 13 个正则模式 (AKID/AWS/OpenAI/GitHub/JWT/私钥/DB密码) |
| **SchemaVersionRule** | INFO | 是否涉及 DDL 变更 | migration 文件检测 |

### 8.3 SecretScanRule 检测模式

```python
# 13 个密钥检测正则
patterns = [
    r'sk-[A-Za-z0-9]{32,}',           # OpenAI/API Key
    r'AKIA[0-9A-Z]{16}',               # AWS Access Key
    r'ghp_[A-Za-z0-9]{36}',            # GitHub Personal Token
    r'gho_[A-Za-z0-9]{36}',            # GitHub OAuth Token
    r'github_pat_[A-Za-z0-9_]{36,}',   # GitHub PAT
    r'eyJ[A-Za-z0-9\-_]+\.eyJ',        # JWT Token
    r'-----BEGIN (RSA|OPENSSH|EC) PRIVATE KEY-----', # 私钥
    r'(?i)jdbc:[^@]+@',                # DB 连接串 (含密码)
    # ...
]
```

### 8.4 Guard 故障安全原则

Guard 检查异常时**默认阻止** (default-deny)，防止安全检查被绕过：

```python
try:
    result = guard.check(state)
except Exception as exc:
    # Guard 异常 → 默认阻止
    state.decision = LoopDecision(
        action=LoopAction.STOP_GUARD,
        target_stage=StageType.ABORTED,
        reason=f"Guard 异常: {exc}",
    )
    return True  # blocked
```

### 8.5 QuickCheck — Per-task 增量验证

```python
QuickCheckRunner
├── py_compile: python -m py_compile <files>      # Python
├── ruff: ruff check --no-cache <files>           # Python lint
├── tsc --noEmit                                  # TypeScript
├── eslint <files>                                # JS/TS lint
├── go vet <files>                                # Go
└── cargo check                                   # Rust
```

### 8.6 Schema 版本追踪

```python
SchemaVersionRecorder
├── MIGRATION_PATTERNS: [SQL, Alembic, Django, Flyway, Prisma, Sequelize]
├── record(changed_files) → 写入 .ai/schema_version.md
└── 内容: 迁移 ID / 影响表 / 执行时间 / 回滚方式 / 验证场景
```

---

## 9. Memory 记忆系统

### 9.1 架构

```
RunState 完成
    ↓
MemoryExtractor.extract(state)
    ├── _extract_failures(state)    → PITFALL / FAILURE_PATTERN
    ├── _extract_decisions(state)   → PROHIBITED / RULE
    ├── _extract_notes(state)       → RULE (手动标注)
    └── _extract_session_memory()   → 已有候选
    ↓
MemoryStore
    ├── add(entry)          → 去重 + LRU 淘汰 (MAX_ENTRIES=200)
    ├── promote(entry_id)   → DRAFT → CONFIRMED
    ├── promote_by_tags()   → 同 tag 2+ 条目自动升级
    ├── save()              → 写入 .ai/memory.md
    └── find(tags=...)      → 按 tag 查找
    ↓
MemoryProjection.sync("claude")
    → 同步到 CLAUDE.md 的 <!-- AI_CODING_LOOP_MEMORY --> 区块
```

### 9.2 Memory 分类 (9 类)

```python
class MemoryCategory(str, Enum):
    CODE_STYLE = "code_style"           # 代码风格规则
    PITFALL = "pitfall"                # 历史坑
    MODULE_BOUNDARY = "module_boundary" # 模块边界
    TESTING = "testing"                 # 测试经验
    ARCHITECTURE = "architecture"       # 架构决策
    PROHIBITED = "prohibited"           # 禁止事项
    VERIFICATION = "verification"       # 验证模式
    FAILURE_PATTERN = "failure_pattern" # 失败模式
    RULE = "rule"                       # 通用规则
```

### 9.3 置信度生命周期

```
DRAFT ────→ CONFIRMED ────→ DEPRECATED
  ↑              ↑
  │ 新提取       │ promote_by_tags()
  │              │ (同 tag 出现 2+ 次)
  └── 手动确认 ──┘
```

### 9.4 LRU 淘汰策略

```
MAX_ENTRIES = 200
MAX_FILE_SIZE_KB = 50

add(entry):
    if exists(id): return False
    while len(entries) >= MAX_ENTRIES:
        evict oldest by updated_at
    append entry
```

### 9.5 ID 生成

```python
def _next_id(category):
    prefix = CATEGORY_PREFIX[category]  # pitfall/style/boundary/...
    short_uid = uuid.uuid4().hex[:8]
    return f"{prefix}-{short_uid}"      # 如 pitfall-a1b2c3d4
```

### 9.6 Memory 提取规则

| 数据来源 | 分类 | 置信度 | 提取条件 |
|---------|------|--------|---------|
| FailureRecord (category=code_logic) | PITFALL | DRAFT | 有实质内容 |
| FailureRecord (category=environment) | FAILURE_PATTERN | DRAFT | 环境故障 |
| Decision (action=stop_guard) | PROHIBITED | CONFIRMED | Guard 拦截 |
| Decision (action=backtrack) | RULE | DRAFT | 回溯经验 |
| Notes (前缀 "memory:") | RULE | DRAFT | 手动标注 |

---

## 10. Scenario Runner 场景验证

### 10.1 架构

```
ScenarioRunner
├── sanity_check(port, base_url) → SanityCheckReport
├── run(scenario_id) → ScenarioResult
└── 场景来源: .ai/scenarios/*.yaml
```

### 10.2 Scenario 格式

```yaml
id: create-order-success
baseUrl: http://localhost:8080

given:
  mysql:
    inventory:
      - sku: A001
        stock: 10

when:
  http:
    method: POST
    path: /orders
    body:
      sku: A001
      quantity: 1

then:
  response:
    status: 200
    body:
      status: CREATED
  mysql:
    orders:
      exists:
        sku: A001
        status: CREATED
    inventory:
      equals:
        sku: A001
        stock: 9
```

### 10.3 Sanity Check 默认项

```json
[
  {"name": "http-local", "resource": "http", "target": "http://localhost:8080"},
  {"name": "port-3306", "resource": "port", "target": "localhost:3306"},
  {"name": "port-6379", "resource": "port", "target": "localhost:6379"}
]
```

可通过 `.ai/loop-config.json` 的 `sanity_checks` 字段自定义。

---

## 11. Plan 执行合约系统

### 11.1 Plan as Execution Contract

Plan 不是 TODO 列表，而是有法律效力的执行合约：

```yaml
taskId: T1
title: Add status filter to user list API
goal: Accept optional status filter without changing pagination
allowedFiles:
  - src/api/user.controller.ts
  - src/service/user.service.ts
forbiddenFiles:
  - src/db/migrations/**
  - src/auth/**
links:
  spec: [REQ-USER-STATUS-FILTER]
  acceptance: [AC-001, AC-002]
  scenarios: [user-list-filter-by-status]
styleContract:
  must: [Follow existing ApiResponse, Keep controller thin]
  forbidden: [No new response wrapper, No new abstraction]
reuseCheck:
  searchFor: [existing query parsing, existing validation]
implementation:
  - Add optional status parameter
  - Pass status to service only when present
verification: [lint, test, scenario]
doneWhen:
  - Only allowed files changed
  - Existing pagination still works
  - Scenario passes
budget:
  maxFiles: 3
  maxLinesChanged: 120
  allowNewAbstractions: false
  allowNewDependencies: false
```

### 11.2 PlanLock 状态机

```
unlocked ──→ locked ──→ change_requested ──→ locked (approved)
                │                │
                │                └──→ breached (rejected)
                └──→ breached (violation detected)

AI 只能执行 locked 状态的 Plan。
PlanLock=breached → 必须人工介入。
PlanLock=change_requested → 等待审批 (L4/L5 强制用户确认)。
```

### 11.3 Diff Budget

```
low:    max_files=3,  max_lines=100
medium: max_files=5,  max_lines=300
high:   max_files=8,  max_lines=600
```

**验证方式**: 用 `git diff --stat` 独立统计，取 `max(AI 自报, git 实际)`。

---

## 12. Spec 规格生成系统

### 12.1 SpecEntry 结构

```yaml
goal: "给订单增加超时自动关闭"
non_goals:
  - "不改变手动取消订单逻辑"
  - "不改变支付回调逻辑"
acceptance_criteria:
  - "超过 30 分钟未支付的订单自动标记为 CLOSED"
  - "关闭时释放库存"
business_rules:
  - "超时时间由配置项 order.timeout_minutes 控制"
test_scenarios:
  - "订单超时自动关闭"
  - "订单超时但已支付不关闭"
risk_level: L4
open_questions:
  - "超时时间是否需要区分订单类型？"
按需字段:
  data_changes: ["新增 order_timeout_config 表"]
  message_changes: ["发送 OrderClosed 事件到 MQ"]
  permission_rules: ["仅系统后台可查看超时记录"]
```

### 12.2 SpecQualityGate 评分

满分 100，通过阈值 70：
- 完整性 (40 分): goal/non_goals/acceptance_criteria/test_scenarios
- 可测性 (20 分): 验收标准是否可测试/可验证
- 边界清晰 (15 分): 修改边界/影响域
- 无模糊词 (15 分): 检测并标记模糊词
- 结构完整 (10 分): 按需字段是否合理

### 12.3 模糊词检测

```
检测列表: 优化, 尽量, 适当, 快速, 友好, 稳定, 支持一下, 处理一下,
         可能, 应该, 也许, 差不多, 基本上, 酌情, 相关
处理:
  - 能明确 → 自动改写为明确标准
  - 不能明确 → 加入 openQuestions
  - 影响核心行为 → 阻止进入 Plan
```

---

## 13. 工具适配器层 (Adapter)

### 13.1 ToolAdapter 抽象基类

定义了一组抽象属性和方法，每个 AI 工具的子类实现：

| 抽象属性 | Claude Code | Codex CLI | Cursor |
|---------|------------|-----------|--------|
| `tool_id` | `claude_code` | `codex` | `cursor` |
| `main_config_path` | `CLAUDE.md` | `.codex/instructions.md` | `.cursor/rules/aicode.md` |
| `rules_dir` | `.claude/rules` | `.codex/rules` | `.cursor/rules` |
| `aicode_dir` | `.claude/aicode` | `.codex/aicode` | `.cursor/aicode` |
| `commands_dir` | `.claude/commands` | None | None |
| `command_prefix` | `/` | `/` | `@` |
| `supports_hooks` | True | False | False |
| `skill_format` | `single_md` | `dir_with_skill_md` | `rule_md` |
| `mcp_config_path` | `.claude/mcp.json` | `.codex/mcp.json` | `.cursor/mcp.json` |

### 13.2 共享渲染方法 (基类提供)

```
_render_code_style_rule(p) → 代码风格规则
_render_testing_rule(p)    → 测试规范
_render_safety_rule()      → 安全约束
_render_project_map(p)     → 项目地图
_render_style_summary(p)   → 代码风格摘要
_append_language_rules()   → 语言特定规则
render_skill(template)     → 渲染模板变量
```

### 13.3 安装产物对比

| 产物 | Claude Code | Codex CLI | Cursor |
|------|------------|-----------|--------|
| 主配置 | `CLAUDE.md` | `.codex/instructions.md` | `.cursor/rules/aicode.md` |
| Rules | `.claude/rules/*.md` | `.codex/rules/*.md` | `.cursor/rules/aicode-*.md` |
| Skills | `.claude/skills/*.md` | `.codex/skills/aicode-*/SKILL.md` | `.cursor/rules/aicode-*.md` |
| Hooks | `hooks/hooks.json` | — | — |
| MCP | `.claude/mcp.json` | `.codex/mcp.json` | `.cursor/mcp.json` |
| Loop Config | `.ai/loop-config.json` | `.ai/loop-config.json` | `.ai/loop-config.json` |

### 13.4 模板变量系统

```
{plugin_root}    → ${CLAUDE_PLUGIN_ROOT} / ${CODEX_PLUGIN_ROOT} / 绝对路径
{engines_cmd}    → bash ${CLAUDE_PLUGIN_ROOT}/engines/run.sh / ...
{cmd_prefix}     → / (Claude/Codex) / @ (Cursor)
{context_var}    → ${CLAUDE_PLUGIN_ROOT} / ${CODEX_PLUGIN_ROOT} / 绝对路径
{aicode_dir}     → .claude/aicode / .codex/aicode / .cursor/aicode
```

---

## 14. CLI 命令行接口

### 14.1 命令一览

```bash
# 初始化
bash engines/run.sh init --scan-only --format json
bash engines/run.sh init --generate --auto-confirm --format json
bash engines/run.sh init --target codex --format json

# Loop 全流程
bash engines/run.sh loop full --task "需求描述"
bash engines/run.sh loop dev --task "开发任务"
bash engines/run.sh loop test --scenario <id>
bash engines/run.sh loop direct --task "小改动"
bash engines/run.sh loop spec --task "只生成 Spec"
bash engines/run.sh loop plan
bash engines/run.sh loop verify
bash engines/run.sh loop review
bash engines/run.sh loop memory

# 继续暂停的 loop (AI 提交结果)
bash engines/run.sh loop continue --state-file run.json --result '<JSON>'

# 单步命令
bash engines/run.sh verify --scenario <id> --format json
bash engines/run.sh guard check --diff HEAD --format json
bash engines/run.sh memory update
bash engines/run.sh memory search --keyword "订单超时" --format json
bash engines/run.sh context route --stage execute --state-file run.json --format json
bash engines/run.sh context project-map --format json
bash engines/run.sh status
```

### 14.2 输出格式

所有命令输出 JSON 到 stdout，日志/进度输出到 stderr。

```json
{
  "success": true,
  "final_stage": "completed",
  "task_status": "passed",
  "failures": 0,
  "checkpoints": 5,
  "duration_ms": 45230.5
}
```

暂停等待 AI 时的输出：
```json
{
  "success": true,
  "needs_ai_input": true,
  "pending_action": "generate_spec",
  "pending_prompt": { "instruction": "...", "context_packet": {...}, "output_schema": {...} },
  "hint": "AI: 读取 pending_prompt，完成 generate_spec，然后运行: engines/run.sh loop continue --state-file run.json --result '<JSON>'"
}
```

### 14.3 多工具兼容

CLI 自动检测目标工具：
1. 读 `.ai/loop-config.json` → `target_tool`
2. 探测文件 `.codex/` / `.cursor/`
3. 默认 `claude_code`

---

## 15. Python ↔ AI 交互协议

### 15.1 协议设计

```
Python 做确定性工作 (状态/校验/上下文)
    ↓
Python 设置 needs_ai_input=True + pending_prompt
    ↓
LoopRunner 检测到 needs_ai_input → 暂停 → 返回 JSON 给 AI
    ↓
AI 读取 pending_prompt → 完成创造性工作 (Spec/Plan/Code/分析)
    ↓
AI 调 CLI: engines/run.sh loop continue --result '<JSON>'
    ↓
Python 注入 result 到 state.metadata → Quality Gate 校验
    ↓
校验通过 → 继续流转
校验不通过 → 返回 feedback → AI 修正 (最多 N 次重试)
```

### 15.2 pending_action 枚举

| pending_action | 阶段 | AI 产出 | 注入到 |
|---------------|------|---------|--------|
| `brainstorm` | SPEC | Brainstorm 方案 | `metadata["spec_result"]` |
| `generate_spec` | SPEC | SpecEntry JSON | `metadata["spec_result"]` |
| `generate_plan` | PLAN | Plan Contracts JSON | `metadata["plan_result"]` |
| `execute_task` | EXECUTE | 变更文件 + 行数 | `metadata["execute_result"]` |
| `direct_execute` | DIRECT_EXECUTE | 变更文件 + 摘要 | `metadata["direct_execute_result"]` |
| `repair` | REPAIR | 修复方案 | `metadata["repair_result"]` |
| `await_user_clarification` | SPEC | — | 等待用户确认 |
| `await_plan_change_approval` | EXECUTE | — | 等待用户审批 |
| `resolve_upstream_conflicts` | EXECUTE | — | 等待人工解决冲突 |

### 15.3 协议安全检查

```python
# 必须条件: needs_ai_input=True 必须伴随有效的 pending_action
if state.needs_ai_input and not state.pending_action:
    logger.error("needs_ai_input=True but pending_action is empty — aborting")
    state.current_stage = StageType.ABORTED
    return self._finalize(state)
```

---

## 16. Init 项目初始化

### 16.1 12 步流程

```
1. 读取当前项目环境 (Git/已有配置)
2. 检测 AI 编程工具 (Claude/Codex/Cursor)
3. 检测必需插件和能力 (Superpowers/ScenarioRunner/MCP)
4. 处理缺失插件 (pip install)
5. 扫描项目结构 (语言/框架/目录/入口文件)
6. 识别代码规范 (命名/异常/日志/测试风格)
7. 识别测试和验证方式
8. 识别外部资源与 MCP 能力 (MySQL/Redis/MQ/ES)
9. 接入 Superpowers
10. 通过 Adapter 生成工具原生文件
11. 初始化 .ai 跨工具资产 (memory.md/scenarios/)
12. 输出初始化报告
```

### 16.2 插件安装

```python
KNOWN_PLUGIN_MAP = {
    "codegraph": "codegraph",
    "superpowers": "claude-code-superpowers",
    "scenario-runner": "aicode-scenario-runner",
}

def _install_plugin(name):
    package = KNOWN_PLUGIN_MAP.get(name, name)
    subprocess.run([sys.executable, "-m", "pip", "install", package], timeout=120)
```

---

## 17. Provider 扩展机制

### 17.1 Provider 架构

```python
class Provider(ABC):
    name: str
    display_name: str
    capabilities: list[str]  # ["spec.generate", "plan.generate", ...]

    def detect(self, project_root) → bool
    def get_skill_templates() → dict[str, str]   # {模板名: 内容}
    def get_ai_instructions() → str               # 写入 CLAUDE.md 的集成说明
    def get_hooks() → dict                        # 事件 → handler 列表
    def get_mcp_servers() → list[McpServerDef]
```

### 17.2 已实现的 Provider

| Provider | 能力 | 检测条件 | 描述 |
|----------|------|---------|------|
| **SuperpowersProvider** | spec.generate, plan.generate, brainstorm | `.superpowers/` 目录存在 | Spec/Plan/Brainstorm 生成 |
| **ScenarioRunnerProvider** | scenario.http, scenario.mysql, scenario.redis | 始终可用 (内置) | 真实流程验证 |
| **MCP Providers** | 动态检测 | MCP 配置 / 环境变量 | MySQL/Redis/日志等 MCP server |

---

## 18. 子循环系统

### 18.1 子循环工厂

```python
# 预设注册
SUB_LOOP_PRESETS = {
    "full":   {handlers: all,   entry: INTAKE, flow: DEFAULT_FLOW},
    "dev":    {handlers: {EXECUTE,VERIFY,REPAIR,REVIEW}, entry: EXECUTE},
    "test":   {handlers: {VERIFY,REPAIR},               entry: VERIFY},
    "spec":   {handlers: {INTAKE,SPEC},                 entry: INTAKE},
    "plan":   {handlers: {SPEC,PLAN},                   entry: SPEC},
    "verify": {handlers: {VERIFY},                      entry: VERIFY},
    "review": {handlers: {REVIEW},                      entry: REVIEW},
    "memory": {handlers: {REVIEW,MEMORY},               entry: REVIEW},
    "direct": {handlers: {DIRECT_EXECUTE,VERIFY,REVIEW}, entry: DIRECT_EXECUTE},
}

def create_sub_loop(name, **overrides) → LoopRunner:
    preset = SUB_LOOP_PRESETS[name]
    return LoopRunner(
        handlers=preset["handlers"],
        entry_stage=preset["entry_stage"],
        flow=preset["flow"],
        max_iterations=preset.get("max_iterations", 30),
        **overrides,
    )
```

### 18.2 自定义子循环

```python
# 应用项目可通过注入自定义 handler 覆盖默认实现
runner = LoopRunner(
    handlers={
        StageType.EXECUTE: MyCustomExecuteHandler(),
        StageType.VERIFY: VerifyHandler(),
        StageType.REVIEW: ReviewHandler(),
    },
    entry_stage=StageType.EXECUTE,
    exit_on_stages={StageType.COMPLETED, StageType.ABORTED},
)
```

---

## 19. 安全机制全景

### 19.1 多层防护体系

```
Layer 1 — Prompt 层:
  CLAUDE.md + .claude/rules/safety.md 中的禁止事项

Layer 2 — Plan 层:
  PlanLock 状态机 → AI 只能执行 locked plan
  Diff Budget → 文件数/行数/新抽象/新依赖限制
  Style Contract → 风格约束绑定

Layer 3 — 执行层:
  Task Start Gate → 每 Task 重新确认边界
  Guard 前置检查 → ScopeBoundary + RiskLevel + Sanity
  Worktree 隔离 → L4/L5 任务独立分支

Layer 4 — 验证层:
  QuickCheck → Per-task compile/lint
  Sanity Check → 环境健康检查
  Scenario Runner → 真实流程验证

Layer 5 — 审查层:
  6 层 Review 检查 → Guard + Plan 合规 + Anti-Cheating + Code Quality + Rollback + Schema

Layer 6 — 熔断层:
  Circuit Breaker → 同模式重复失败 3 次强制终止
  Max Iterations → 100 次硬上限
  Handle None Guard → 处理器返回 None 终止
  Guard Exception → Default-deny 阻止

Layer 7 — 记忆层:
  Memory → 失败模式沉淀 → 后续任务提前预警
```

### 19.2 Anti-Cheating 规则

| 规则 | 检测方式 | 严重级别 |
|------|---------|---------|
| TestIntegrityRule | git diff --name-status 检测删除的测试文件 | BLOCK |
| AssertionWeakeningRule | diff 中 assert→if 的语义变化 | BLOCK |
| SkipModificationRule | diff 中新增 skip/ignore/only 标记 | BLOCK |

### 19.3 风险等级 → 安全措施映射

| 风险 | Spec | Plan | Guard | Worktree | Diff Budget | 用户确认 |
|------|------|------|-------|----------|-------------|---------|
| L1 | 可选 | 可选 | 基础 | — | 3f/100L | 不需要 |
| L2 | 可选 | 推荐 | 基础 | — | 3f/100L | 不需要 |
| L3 | 需要 | 需要 | 标准 | 可选 | 5f/300L | 建议 |
| L4 | 必须 | 必须 | 严格 | **强制** | 8f/600L | **必须** |
| L5 | 必须 | 必须 | 最严 | **强制** | 按需 | **仅生成方案** |

---

## 20. 关键数据流图

### 20.1 完整 Loop 数据流

```
用户输入
  │
  ▼
┌──────────────────────────────────────────────────────────────┐
│ INTAKE: TaskIntakeResult {inputType, complexity, riskLevel, │
│         flowMode, needsSpec, needsPlan}                      │
└─────────────────────────────┬────────────────────────────────┘
                              │
               direct ◄───────┼───────► spec_from_prompt
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
  DIRECT_EXECUTE           SPEC                  SPEC
         │                    │                    │
         ▼                    ▼                    ▼
       VERIFY          SpecEntry              Brainstorm
         │           QualityGate               Result
         ▼               │                      │
       REVIEW      ┌──────┴──────┐              │
         │         ▼             ▼              ▼
         ▼      PASSED        FAILED      ready_for_spec?
    COMPLETED      │          retry/           │
                   ▼          abort       ┌────┴────┐
                 PLAN                     ▼         ▼
                   │                   YES        NO → 暂停
        ┌──────────┴──────────┐
        ▼                     ▼
    PlanContract[]      QualityGate
        │                     │
   PlanLock.lock()     ┌──────┴──────┐
        │               ▼             ▼
        ▼            PASSED        FAILED
     EXECUTE            │          retry/abort
        │               ▼
  Per-task:           ┌──────────────────────┐
  Start Gate →        │ VERIFY               │
  Guard →             │  Sanity Check        │
  ContextRouter →     │  Scenario Runner     │
  AI 编码 →           │  ┌────────┐          │
  Diff Validation →   │  │ PASSED │──────────┼──→ REVIEW
  QuickCheck →        │  └────────┘          │       │
  Task Log            │  ┌────────┐          │       ▼
        │              │  │ FAILED │→ REPAIR ─┘   MEMORY
        ▼              │  └────────┘    │            │
  所有 Task 完成        │  ┌──────────┐  │            ▼
        │              │  │ SANITY   │  │       COMPLETED
        ▼              │  │ FAILED   │──┼──→ ABORTED
     VERIFY ←──────────┘  └──────────┘  │
                                         │
                                  环境故障终止
```

### 20.2 Python ↔ AI 数据流

```
┌─────────────┐                    ┌─────────────┐
│   Python    │                    │     AI      │
│  (引擎)     │                    │  (Claude)   │
└──────┬──────┘                    └──────┬──────┘
       │                                  │
       │ 1. 执行到需要 AI 的点             │
       │    needs_ai_input = True         │
       │    pending_action = "generate_spec"│
       │    pending_prompt = {...}        │
       │                                  │
       │ 2. 返回 JSON (stdout)            │
       │─────────────────────────────────>│
       │                                  │
       │                           3. AI 读 pending_prompt
       │                           4. AI 做创造性工作
       │                           5. AI 调 CLI:
       │                              loop continue
       │                              --result '<JSON>'
       │                                  │
       │ 6. Python 读 CLI 参数            │
       │    <─────────────────────────────│
       │                                  │
       │ 7. Quality Gate 校验             │
       │    ┌─ PASSED → 继续流转          │
       │    └─ FAILED → 返回 feedback     │
       │                                  │
       │ 8. 继续流转 或 返回修正           │
       │─────────────────────────────────>│
       │                                  │
```

---

## 附录 A: 核心指标

系统目标指标 (非单一准确率):

| 指标 | 说明 | 目标 |
|------|------|------|
| 任务闭环成功率 | 从 INTAKE 到 COMPLETED 的比例 | > 85% |
| Scenario 验证通过率 | 场景断言通过比例 | > 90% |
| Loop 内修复成功率 | REPAIR 一次修复成功的比例 | > 70% |
| Diff Budget 违规率 | 超过 Plan 预算的 Task 比例 | < 10% |
| 风格违规率 | Style Contract 违反的 Task 比例 | < 5% |
| 越界修改率 | 修改 allowedFiles 之外文件的 Task 比例 | < 3% |
| 熔断触发率 | 同一失败循环 3 次触发熔断的比例 | < 5% |
| 平均上下文 Token | 每个阶段的平均 Token 消耗 | < 3000 |

## 附录 B: 实现进度

| 模块 | 文件 | 状态 |
|------|------|------|
| State (状态管理) | enums.py, models.py, serialization.py | ✅ 完成 |
| LoopRunner (核心引擎) | loop_runner.py | ✅ 完成 (含熔断器) |
| StageHandlers (9 个处理器) | stage_handlers.py | ✅ 完成 |
| Guard (10 条规则) | engine.py, rules.py, code_quality.py, quick_check.py, rollback.py, schema_version.py | ✅ 完成 |
| Context Router | router.py, sources.py, strategies.py, models.py | ✅ 完成 |
| Memory | store.py, extractor.py, projection.py, models.py | ✅ 完成 |
| Scenario Runner | runner.py, sanity.py, assertion.py, resources.py, models.py | ✅ 完成 |
| Plan | models.py, lock.py, quality_gate.py, contracts.py | ✅ 完成 |
| Spec | models.py, quality_gate.py | ✅ 完成 |
| Init | init_runner.py, scanner.py, generator.py, models.py | ✅ 完成 |
| CLI | cli.py | ✅ 完成 (多工具兼容) |
| Adapters (3 个) | base.py, claude.py, codex.py, cursor.py | ✅ 完成 |
| Providers (3 个) | superpowers.py, scenario_runner.py, mcp_registry.py | ✅ 完成 |
| Worktree Isolator | worktree_isolator.py | ✅ 完成 |
| Daemon Mode | daemon.py | ✅ 骨架完成 |
| Git Sync | git_sync.py | ✅ 完成 |

---

> 本文档基于 AI Coding Loop v1.0 代码库生成，覆盖全部 32 个已修复的架构缺口。
