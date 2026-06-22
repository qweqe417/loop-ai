# AI Coding Loop — 完整系统架构文档

**版本:** 1.0
**生成时间:** 2026-06-22
**系统定位:** 生产级 AI 编程助手核心引擎，支持多 AI 工具（Claude Code / Codex / Cursor），提供从需求到代码到验证到记忆沉淀的全链路自动化。

---

## 一、概述

### 1.1 系统目标

AI Coding Loop 是一套让 AI 从"聊天助手"进化为"编程协作者"的工程化框架。

它的核心使命是：

> "让 AI 能在无人值守的情况下，完成从需求理解 → 规格生成 → 方案设计 → 代码实现 → 场景验证 → 自动修复 → 经验沉淀的全流程，并支持人工在任意环节介入。"

### 1.2 核心能力矩阵

| 能力 | 描述 |
| --- | --- |
| 项目初始化 | 自动扫描项目结构、识别技术栈、生成配置文件，零手工配置 |
| 需求理解 | 从 PRD/Spec/文字描述中提取业务规则、验收标准、边界条件 |
| 规格生成 | 生成结构化的 Spec 文档（Goals / Non-goals / Acceptance Criteria） |
| 方案设计 | 拆解任务，定义文件边界、Diff Budget、Style Contract |
| 代码实现 | 逐 Task 执行，受 PlanLock + Guard + ContextBudget 约束 |
| 场景验证 | 执行 HTTP/DB/Redis/DOM 断言，区分环境故障 vs 代码故障 |
| 自动修复 | 分析根因，最小修复，最多 3 次重试 |
| 代码审查 | Guard 边界检查 + Anti-Cheating + Code Quality Gate |
| 经验沉淀 | 从失败/决策中提取规则、坑、禁止事项，持久化到记忆库 |
| 多工具适配 | 同一套能力在 Claude Code / Codex / Cursor 上无缝运行 |

---

## 二、系统架构

### 2.1 整体架构图

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                         用户 / AI 工具 交互层                              │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │  Claude Code  │  Codex CLI  │  Cursor  │  CLI (engines/run.sh)   │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                              │                                             │
│                              ▼                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │                      Skill 层 (aicode-*.md)                         │  │
│  │  init │ calibrate │ spec │ plan │ test-design │ full │ dev │ test  │  │
│  │  direct │ verify │ review │ memory │ using-ai-coding-loop          │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                              │                                             │
│                              ▼                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │                    engines/cli.py (统一入口)                         │  │
│  │         init │ loop │ verify │ guard │ memory │ context            │  │
│  │         test-design │ status                                        │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        引擎核心层 (engines/)                               │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐                  │
│  │    Runtime    │  │     State     │  │    Context    │                  │
│  │ LoopRunner    │  │   RunState    │  │ ContextRouter │                  │
│  │ StageHandlers │  │   Models      │  │  Sources      │                  │
│  │ Daemon/       │  │   Enums       │  │  Strategies   │                  │
│  │ Worktree      │  │   Serializer  │  │              │                  │
│  └───────────────┘  └───────────────┘  └───────────────┘                  │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐                  │
│  │     Guard     │  │    Memory     │  │   Scenario    │                  │
│  │  Engine       │  │  Extractor    │  │  Runner       │                  │
│  │  Rules        │  │  Store        │  │  Assertion    │                  │
│  │  CodeQuality  │  │  Projection   │  │  Sanity       │                  │
│  │  Rollback     │  │  Governance   │  │  Resources    │                  │
│  └───────────────┘  └───────────────┘  └───────────────┘                  │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐                  │
│  │  Providers    │  │   Adapters    │  │     Init      │                  │
│  │  Scenario     │  │  ClaudeCode   │  │  Scanner      │                  │
│  │  MCP-MySQL    │  │  Codex        │  │  Generator    │                  │
│  │  MCP-Redis    │  │  Cursor       │  │  Runner       │                  │
│  └───────────────┘  └───────────────┘  └───────────────┘                  │
│  ┌───────────────────────────────────────────────────────────────┐       │
│  │                    Test Design 模块                           │       │
│  │  models │ quality_gate │ scenario_mapper │ xlsx_writer       │       │
│  └───────────────────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         项目资产层 (.ai/)                                  │
│  config.yaml │ memory.md │ memory/entries/ │ scenarios/ │ spec-index.yaml  │
│  loop-config.json │ reports/ │ fixtures/ │ worktrees/                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 模块依赖关系

```text
                    ┌─────────────┐
                    │  cli.py     │ (入口)
                    └──────┬──────┘
                           │
    ┌──────────────────────┼──────────────────────┐
    │                      ▼                      │
    │              ┌───────────────┐              │
    │              │   Runtime     │──▶ State     │
    │              │ (LoopRunner)  │──▶ Context   │
    │              │ (Handlers)    │──▶ Guard     │
    │              └───────────────┘              │
    │                      │                      │
    │         ┌────────────┼────────────┐        │
    │         ▼            ▼            ▼        │
    │   ┌──────────┐ ┌──────────┐ ┌──────────┐  │
    │   │ Scenario │ │  Memory  │ │  Guard   │  │
    │   └──────────┘ └──────────┘ └──────────┘  │
    │         │            │            │        │
    │         └────────────┼────────────┘        │
    │                      ▼                     │
    │              ┌───────────────┐              │
    │              │  Providers    │              │
    │              │  ────────     │              │
    │              │  Adapters     │              │
    │              │  ────────     │              │
    │              │  Init         │              │
    │              └───────────────┘              │
    └──────────────────────────────────────────────┘
```

依赖方向: cli → Runtime → {Scenario, Memory, Guard} → {Providers, Adapters, Init}
          └─ State/Context 被所有模块依赖

---

## 三、模块详解

### 3.1 engines.state — 状态管理（中枢神经系统）

**定位:** 整个 Loop 的"生命体征监测仪"和"病历本"。

#### 核心职责

- 定义所有阶段枚举（StageType）和流转动作（LoopAction）
- 定义 RunState 作为贯穿全流程的单一数据载体
- 提供序列化/反序列化（断点续传）

#### 核心数据结构

| 模型 | 用途 | 关键字段 |
| --- | --- | --- |
| RunState | 顶级载体 | task_id, current_stage, task_intake, spec_entry, plan_contracts, test_design_bundle, task_state, verification, failures, checkpoints |
| TaskIntakeResult | 入口分析 | risk_level (L1~L5), flow_mode (direct/spec_from_prompt), verification_required |
| TaskState | 任务执行 | status, retry_count, task_logs, plan_compliance |
| FailureRecord | 失败记录 | category (ENVIRONMENT/CODE_LOGIC/...), message, attempt_count |
| Checkpoint | 快照 | stage, files_changed, diff, timestamp |
| LoopDecision | 流转决策 | action (NEXT_STAGE/RETRY/BACKTRACK/STOP_*), target_stage |

#### 与其他模块交互

- 被所有模块读写：每个 Handler 读取 RunState 中的对应字段（如 ExecuteHandler 读 plan_contracts）
- 序列化层：run_state_to_json() / run_state_from_json() 支持断点续传

---

### 3.2 engines.runtime — 循环引擎（心脏起搏器）

**定位:** Loop 的"心跳"——驱动 RunState 在阶段间流转。

#### 核心组件

| 组件 | 职责 |
| --- | --- |
| LoopRunner | 主循环引擎：迭代驱动、熔断器、暂停/恢复、流转决策应用 |
| StageHandler (抽象基类) | 每个阶段的处理器模板，提供 _advance_to / _complete / _retry 工具方法 |
| 具体 Handlers | IntakeHandler, SpecHandler, TestDesignStageHandler, PlanHandler, ExecuteHandler, VerifyHandler, RepairHandler, ReviewHandler, MemoryHandler, DirectExecuteHandler |
| GitSyncer | 上游同步检查（EXECUTE 前） |
| WorktreeIsolator | L4/L5 高风险任务隔离执行 |
| DirectExecutor | 极简版执行器（--only 模式） |
| LoopDaemon | 后台守护进程（骨架） |

#### ExecuteHandler 内部两阶段协议

```text
┌─────────────────────────────────────────────────────────────────┐
│                     Phase PREPARE                               │
│  1. Task Start Gate (边界确认)                                  │
│  2. Worktree 隔离 (L4/L5)                                      │
│  3. Guard 前置检查                                             │
│  4. PlanLock 检查 (需锁定 → 暂停)                              │
│  5. ContextRouter 注入 EXECUTE 上下文                          │
│  6. 构造 pending_prompt → needs_ai_input=True → 暂停          │
└─────────────────────────────────────────────────────────────────┘
                              ▼ (AI 写代码 → loop continue)
┌─────────────────────────────────────────────────────────────────┐
│                     Phase VALIDATE                              │
│  1. Plan Change Request 处理 (上限 3 次)                       │
│  2. Diff Budget 校验 (文件数/行数/抽象/依赖)                   │
│  3. Style Contract 校验 (命名规范)                             │
│  4. Reuse Check (导入检测)                                     │
│  5. QuickCheck (py_compile/ruff/tsc)                           │
│  6. 记录 TaskExecutionLog                                      │
│  7. current_task_index += 1 → 下一 Task / VERIFY              │
└─────────────────────────────────────────────────────────────────┘
```

#### 熔断器 (Circuit Breaker)

- **精确层:** 最近 3 次 stage + category + 规范化消息 完全一致 → 强制终止
- **模糊层:** 最近 3 次仅 category 相同（跨阶段同类失败）→ 强制终止
- **目的:** 防止 AI 在同一问题上无限重试，耗尽 Token

#### 与其他模块交互

- 调用 ContextRouter.route() (context) 加载上下文
- 调用 Guard.check() (guard) 做前置检查
- 调用 ScenarioRunner.run_all() (scenario) 做验证
- 调用 MemoryStore (memory) 沉淀记忆
- 调用 GitSyncer / WorktreeIsolator (runtime 内部)

---

### 3.3 engines.context — 上下文路由器（弹药补给系统）

**定位:** 每个阶段精确加载所需上下文，防止 Token 爆炸。

#### 核心设计

```text
┌─────────────────────────────────────────────────────────────────┐
│                    ContextRouter.route(stage)                   │
│  1. 查策略表 (STAGE_STRATEGIES) → 获取策略函数                 │
│  2. 策略函数调用 Sources (File/CodeGraph/Memory) 收集 Pieces   │
│  3. 按 priority 排序 (1=必须, 2=重要, 3=补充)                  │
│  4. 按预算裁剪 (从 priority=3 开始丢弃)                        │
│  5. 返回 ContextBundle (含渲染后的文本)                        │
└─────────────────────────────────────────────────────────────────┘
```

#### Sources

| Source | 职责 | 优先级 |
| --- | --- | --- |
| FileSource | 读文件（read_full / read_smart / read_summary） | 1~3 |
| CodeGraphSource | 调用 CodeGraph 获取项目地图/上下文/影响分析 | 1~2 |
| MemorySource | 从 .ai/memory.md 召回相关经验 | 2~3 |

#### 阶段策略表（部分示例）

| 阶段 | 加载内容 | 预算 |
| --- | --- | --- |
| INTAKE | 项目地图 + CLAUDE.md 前80行 | 1500 |
| SPEC | 项目地图 + CodeGraph 相关模块 + Memory 相关 | 2500 |
| PLAN | 代码风格规则 + 相关文件签名 + 测试规则 | 3000 |
| EXECUTE | 要改的文件全文(前3个) + 调用链 + 禁止文件清单 | 4000 |
| VERIFY | 场景定义 + 被改文件列表 + 验证命令 | 2500 |
| REPAIR | 失败上下文 + 出错文件全文 + 调用链 + 失败记忆 | 3500 |

#### 与其他模块交互

- State 中的 context_budget_max/used 联动
- MemoryStore.recall() (memory) 召回经验
- CodeGraphSource (providers) 调用 CodeGraph CLI

---

### 3.4 engines.guard — 安全守卫（免疫系统）

**定位:** 代码变更的"安全网"，防止 AI 胡作非为。

#### 核心规则

| 规则 | 严重级别 | 检查逻辑 |
| --- | --- | --- |
| ScopeBoundaryRule | BLOCK | 检查变更文件是否在 allowed_paths 白名单内 |
| RiskLevelRule | BLOCK | L4/L5 风险必须配 strict Guard |
| SanityCheckRule | BLOCK | task_id 不为空、retry_count ≤ 5 |
| TestIntegrityRule | BLOCK | 检测测试文件是否被删除（git diff --name-status + task_logs） |
| SecretScanRule | BLOCK | 扫描硬编码 API Key / 密码 / Token |
| AssertionWeakeningRule | WARN | 对比断言数量是否下降 |
| SkipModificationRule | WARN | 检测新增 skip/ignore 标记 |
| FileSizeLimitRule | WARN | 新增文件不超过 200KB |
| NetworkCallRule | WARN | 检测新增网络库导入 |

#### 子模块

| 子模块 | 职责 |
| --- | --- |
| QuickCheckRunner | Per-task 增量验证（py_compile / ruff / tsc / eslint / go vet / cargo check） |
| CodeQualityGate | 10 维度代码质量自评（简洁性、模式复用、分层合规等），阈值 70% |
| RollbackPlanner | 从 Checkpoints + Git 历史生成回滚方案（.ai/reports/rollback.md） |
| SchemaVersionRecorder | 检测 DDL/Migration 变更，记录到 .ai/schema_version.md |

#### 与其他模块交互

- 被 Runtime 各 Handler 调用（前置检查 / 验证后检查）
- 被 CLI 直接调用（guard check）
- 读取 RunState 中的 task_state、failures、plan_contracts

---

### 3.5 engines.memory — 记忆系统（大脑皮层）

**定位:** 项目经验的长期存储与自动召回。

#### 三层架构

```text
┌─────────────────────────────────────────────────────────────────┐
│                    Layer 3: Tool Projection                     │
│  .ai/memory/projections/*.md + CLAUDE.md 标记段 + rules/*.md   │
│  (只投影 CONFIRMED 条目)                                        │
└─────────────────────────────────────────────────────────────────┘
                              ▲
┌─────────────────────────────────────────────────────────────────┐
│                    Layer 2: Canonical Memory                    │
│  .ai/memory.md (索引) + .ai/memory/entries/{id}.md (正文)     │
│  (权威源, 人机可编辑)                                          │
└─────────────────────────────────────────────────────────────────┘
                              ▲
┌─────────────────────────────────────────────────────────────────┐
│                    Layer 1: Session Memory                      │
│  .ai/memory/sessions/{task_id}.json (单次任务原料)             │
└─────────────────────────────────────────────────────────────────┘
```

#### 核心组件

| 组件 | 职责 |
| --- | --- |
| MemoryExtractor | 从 RunState 提取候选记忆（Failures → PITFALL, Decisions → PROHIBITED/RULE, Notes → RULE） |
| MemoryStore | 读写 memory.md 索引 + entries/ 正文，提供 add/remove/promote/recall |
| MemoryProjection | 同步 CONFIRMED 条目到工具文件（CLAUDE.md / safety.md / testing.md） |

#### 召回算法 (recall)

- 关键词匹配 (+3 分)
- 阶段优先级匹配 (+5~1 分)
- CONFIDENCE 加分 (CONFIRMED +2)
- 近期命中加分 (7 天内 +1)
- 排序 → 取前 N 条
- 记录命中 (hit_count++, last_hit_at)

#### 分类体系

| 分类 | 用途 | 示例 |
| --- | --- | --- |
| RULE | 通用开发规则 | "所有 API 必须加权限校验" |
| PITFALL | 历史坑 | "取消订单不释放库存导致超卖" |
| PROHIBITED | 禁止事项 | "禁止在 Controller 中写业务逻辑" |
| FAILURE_PATTERN | 失败模式 | "环境变量缺失导致启动失败" |
| TESTING | 测试经验 | "使用 @DataJpaTest 做 Repository 测试" |

#### 与其他模块交互

- ContextRouter 调用 MemoryStore.recall() 注入上下文
- MemoryHandler 调用 MemoryExtractor + MemoryStore + MemoryProjection
- Guard 的 SecretScanRule 与 PROHIBITED 联动

---

### 3.6 engines.scenario — 场景验证（眼睛和裁判）

**定位:** 从测试用例 YAML 到可执行验证的"自动驾驶测试仪"。

#### 核心流程

```text
ScenarioRunner.run(scenario)
    1. Sanity Check (环境: HTTP/MySQL/Redis 是否可达)
    2. Apply Fixtures (插入前置数据)
    3. Execute Steps (HTTP 调用 / Wait / Script)
    4. Evaluate Assertions (HTTP状态 / DB查询 / Redis值 / MQ消息 / 日志 / 自定义脚本)
    5. Teardown (清理数据)
    6. 返回 ScenarioResult (passed / assertions_total / errors)
```

#### 断言类型

| 类型 | 说明 |
| --- | --- |
| HTTP_STATUS | 校验 HTTP 状态码 |
| HTTP_BODY | 校验响应体包含 |
| JSON_PATH | 校验 JSON 路径值 |
| DB_QUERY / DB_COUNT | SQL 查询结果 / 行数 |
| REDIS_KEY / REDIS_VALUE | Redis Key 存在 / Value 匹配 |
| MQ_MESSAGE | 消息队列消息 |
| LOG_CONTAINS | 日志包含 |
| SCRIPT | 自定义 Python 脚本断言（最强武器） |

#### Resource Adapter（万能转换头）

| 适配器 | 当前实现 | 可替换为 |
| --- | --- | --- |
| HttpAdapter | urllib (真实 HTTP) | 不变 |
| DatabaseAdapter | 内存 SQLite | MCP MySQL (真实) |
| RedisAdapter | 内存字典 | MCP Redis (真实) |
| MessageQueueAdapter | 内存队列 | Kafka / RabbitMQ MCP |
| LogAdapter | 文件 I/O | 不变 |

#### 与其他模块交互

- 被 VerifyHandler 调用
- 被 CLI verify 直接调用
- 读取 .ai/scenarios/\*.yaml
- 输出 ScenarioResult 写入 RunState.scenario_results

---

### 3.7 engines.providers — 能力声明（万能插座）

**定位:** 外部能力的声明式接入，与具体 AI 工具解耦。

#### 核心抽象: ProviderManifest

| 方法 | 职责 |
| --- | --- |
| detect() | 自动检测是否可用（扫描配置文件） |
| get_skill_templates() | 返回 Skill 模板（含 {engines_cmd} 占位符） |
| get_ai_instructions() | 注入到主配置的说明段落 |
| get_mcp_servers() | 声明的 MCP Server 定义 |
| get_hooks() | 声明的 Hook 定义 |

#### 内置 Provider

| Provider | 类型 | 说明 |
| --- | --- | --- |
| ScenarioRunnerProvider | verification | 必需，提供验证能力 |
| McpMysqlProvider | resource_access | 检测到 mysql 关键字时自动启用 |
| McpRedisProvider | resource_access | 检测到 redis 关键字时自动启用 |
| McpKafkaProvider | resource_access | 检测到 kafka 关键字时自动启用 |
| McpElasticsearchProvider | resource_access | 检测到 elasticsearch 关键字时自动启用 |

#### 与其他模块交互

- Init 调用 detect_mcp_providers() 自动发现
- ToolAdapter 读取 get_skill_templates() + get_mcp_servers() + get_hooks()

---

### 3.8 engines.adapters — 工具适配器（万能转换头）

**定位:** 把 Provider 声明的能力翻译成具体 AI 工具的原生格式。

#### 核心抽象: ToolAdapter

| 属性/方法 | 职责 |
| --- | --- |
| tool_id / display_name | 工具标识 |
| main_config_path / rules_dir / skills_dir / mcp_config_path | 路径映射 |
| command_prefix | / (Claude/Codex) 或 @ (Cursor) |
| supports_hooks | 是否支持 Hook |
| skill_format | single_md / dir_with_skill_md / rule_md |
| render_skill() | 替换 {engines_cmd} 等占位符 |
| render_main_config() | 生成自举引导 Prompt（AI 自己写 CLAUDE.md） |
| generate_mcp_config() | 翻译 McpServerDef → 工具原生 JSON |
| generate_hooks() | 翻译 Hook 声明 → 工具原生配置 |
| install() | 安装 MCP 配置 / loop-config.json / karpathy.md |

#### 三个具体适配器对比

| 特性 | ClaudeCodeAdapter | CodexAdapter | CursorAdapter |
| --- | --- | --- | --- |
| 主配置 | CLAUDE.md | .codex/instructions.md | .cursor/rules/aicode.md |
| 规则目录 | .claude/rules/ | .codex/rules/ | .cursor/rules/ |
| Skill 格式 | single_md | dir_with_skill_md | rule_md |
| 命令前缀 | / | / | @ |
| 支持 Hooks | ✅ | ✅ | ❌ |
| 变量机制 | ${CLAUDE_PLUGIN_ROOT} | ${CODEX_PLUGIN_ROOT} | 无（用绝对路径） |
| MCP 配置 | .claude/mcp.json | .codex/mcp.json | .cursor/mcp.json |

#### 与其他模块交互

- Init 调用 adapter.install() 安装文件
- CLI 的 _get_tool_config() 读取 loop-config.json 决定 engines_cmd

---

### 3.9 engines.init — 项目初始化（安装师傅）

**定位:** 第一次进入项目时，自动扫描、适配、生成所有配置文件。

#### 12 步流程

| 步骤 | 动作 | 输出 |
| --- | --- | --- |
| 1 | 读取项目环境（Git 状态、已有工具文件） | ProjectProfile.existing_tool_files |
| 2 | 检测 AI 工具（通过已有文件推断） | detected_tools |
| 3 | 检测外部插件（Superpowers / Karpathy / CodeGraph） | detected_plugins, missing_recommended |
| 4 | 检测内部模块（ScenarioRunner / Guard / Memory） | internal_modules |
| 5 | 扫描项目结构（语言/框架/目录） | language, framework, source_dirs |
| 6 | 识别代码规范（命名/异常/日志） | code_style (含 confidence) |
| 7 | 识别测试方式（框架/运行命令） | test_framework, test_runner_command |
| 8 | 识别外部资源（MySQL/Redis/Kafka） | resources |
| 9 | 检测 Provider | ScenarioRunnerProvider, MCP Providers |
| 10 | 通过 ToolAdapter 生成工具原生文件 | CLAUDE.md + rules/\*.md (由 AI 写) |
| 11 | 初始化 .ai/ 资产（config / memory / scenarios） | .ai/config.yaml, .ai/memory.md, .ai/scenarios/example.yaml |
| 12 | 输出报告 | InitReport |

#### 核心组件

| 组件 | 职责 |
| --- | --- |
| ProjectScanner | 执行扫描步骤 1-8 |
| FileGenerator | 生成 .ai/ 资产（不生成主配置文件，由 AI 写） |
| InitRunner | 编排完整 12 步流程，支持 --scan-only, --assets-only |

#### 自举（Bootstrapping）哲学

- Python 不生成 CLAUDE.md 内容，只生成一个"引导 Prompt"
- AI 读取引导 Prompt 后，扫描项目源码，自己提取真实信息，重写 CLAUDE.md
- 生成的配置文件是"从代码中生长出来的"，每条规则都有真实代码作为依据

#### 与其他模块交互

- 调用 ProjectProfile (models)
- 调用 ToolAdapter.install() (adapters)
- 调用 detect_mcp_providers() (providers)
- 调用 CLI 的 --target 参数决定适配器

---

### 3.10 engines.test_design — 测试设计（测试工厂）

**定位:** 从需求文档到生产级测试用例和可执行 Scenario。

#### 双视图设计

```text
┌─────────────────────────────────────────────────────────────────┐
│                      输入: PRD / Spec / Plan                    │
└──────────────────────────┬──────────────────────────────────────┘
                           │
         ┌─────────────────┴─────────────────┐
         ▼                                   ▼
┌─────────────────────┐             ┌─────────────────────┐
│     视图A (默认)     │             │    视图B (full)      │
│  输出: Excel         │             │  输出: YAML +         │
│  目标: 人读评审      │             │  Scenario + Excel     │
│  输入: 只需需求文档  │             │  输入: 需求文档 + Plan│
│  语言: 业务语言      │             │  语言: 技术 + 业务    │
└─────────────────────┘             └─────────────────────┘
```

#### 核心数据结构

| 模型 | 用途 | 关键字段 |
| --- | --- | --- |
| Step | Action Pipeline 原子单元 | seq, action (ui_click/api_call/db_query), description (人读), config (机读), assertions |
| TestCase | 单条测试用例 | id, scope, steps, expected (response/data_assertions/dom_assertions), cleanup |
| TestDesignBundle | 完整产物包 | requirements, test_cases, coverage, open_questions |
| QualityReport | 门禁报告 | errors (硬阻断), warnings (软警告) |

#### 质量门禁（硬阻断 vs 软警告）

| 硬阻断 | 软警告 |
| --- | --- |
| P0/P1 需求覆盖率为 0 | 负向/边界用例 < 正向的 30% |
| 数据变更用例缺少 data_assertions | e2e 占比 > 80% |
| open_questions 未解决 | 用例缺少前置条件 |
| 自动化候选用例缺少 dependencies | 用例缺少预期结果 |

#### Scenario 映射器

```text
TestCase.steps (Action Pipeline)
    ↓ (映射)
Scenario.steps (ScenarioRunner 可执行)
    ↓
engines.scenario 消费
```

#### 与其他模块交互

- 被 aicode-test-design Skill 调用
- 通过 CLI test-design process / export-xlsx 暴露 API
- 输出 scenario-drafts.yaml 给 ScenarioRunner
- TestCase.cleanup 与 scenario 的 Teardown 联动

---

### 3.11 engines.cli — 统一入口（驾驶舱）

**定位:** 所有命令的统一入口，JSON 输出，日志走 stderr。

#### 子命令一览

| 子命令 | 调用模块 | 主要功能 |
| --- | --- | --- |
| init | engines.init | 项目初始化 |
| loop | engines.runtime | 运行 Loop（支持 continue 恢复） |
| verify | engines.scenario | 执行场景验证 |
| guard | engines.guard | 运行 Guard 检查 |
| memory | engines.memory | 记忆管理（search/stats/update） |
| context | engines.context | 上下文路由（route/project-map） |
| test-design | engines.test_design | 测试设计（process/export-xlsx） |
| status | 内部检测 | 引擎状态检查 |

#### 核心机制: continue 模式（暂停-恢复）

```text
1. Loop 运行到需要 AI 创造性的阶段
2. CLI 返回 JSON: { "needs_ai_input": true, "pending_prompt": {...}, "hint": "..." }
3. AI 读取 pending_prompt，生成内容
4. AI 调用: engines/run.sh loop continue --state-file run.json --result '<JSON>'
5. CLI 注入结果到 RunState，继续执行
```

#### 工具自适应

- 读取 .ai/loop-config.json 获取 target_tool 和 engines_cmd
- 无文件时自动检测（.codex/ → codex, .cursor/ → cursor）

---

## 四、核心流程与交互

### 4.1 8 阶段完整流程（/aicode-full）

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                              INTAKE (入口分析)                              │
│  Python: 分析输入类型 / 复杂度 / 风险等级 / 分流模式                       │
│  输出: TaskIntakeResult (flow_mode, risk_level, verification_required)    │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
          ┌─────────────────┐             ┌─────────────────┐
          │  flow_mode =    │             │  flow_mode =    │
          │  spec_from_*    │             │  direct         │
          └────────┬────────┘             └────────┬────────┘
                   │                               │
                   ▼                               ▼
┌─────────────────────────────────────┐ ┌─────────────────────────────────────┐
│              SPEC (规格生成)          │ │        DIRECT_EXECUTE (直接执行)    │
│  AI: /aicode-spec 生成 Spec         │ │  跳过 Spec/Plan，直接改码          │
│  输出: spec_entry (JSON)            │ │  仅允许 L1/L2 风险                 │
└─────────────────────────────────────┘ └─────────────────────────────────────┘
                   │                               │
                   ▼                               │
┌─────────────────────────────────────┐           │
│          TEST_DESIGN (测试设计)      │           │
│  AI: /aicode-test-design 生成用例   │           │
│  输出: test_design_bundle           │           │
└─────────────────────────────────────┘           │
                   │                               │
                   ▼                               │
┌─────────────────────────────────────┐           │
│              PLAN (方案设计)          │           │
│  AI: /aicode-plan 生成执行计划      │           │
│  输出: plan_contracts (Task列表)    │           │
└─────────────────────────────────────┘           │
                   │                               │
                   └───────────────┬───────────────┘
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         EXECUTE (执行)                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │  逐 Task 执行 (PREPARE → VALIDATE 两阶段)                          │  │
│  │  PREPARE: Task Start Gate → Guard → ContextRouter → 构造 Prompt   │  │
│  │  VALIDATE: Diff Budget → Style Contract → Reuse → QuickCheck      │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│  输出: task_logs (每个 Task 的记录)                                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         VERIFY (验证)                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │  1. Sanity Check (环境健康: HTTP/MySQL/Redis)                      │  │
│  │  2. Scenario Runner (执行场景断言)                                  │  │
│  │  3. 失败分类: ENVIRONMENT → STOP_FAILURE | CODE → REPAIR          │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│  输出: verification, scenario_results, failures                          │
└─────────────────────────────────────────────────────────────────────────────┘
                          │                    │
                    ┌─────┴─────┐              │
                    ▼           ▼              │
              ┌──────────┐ ┌──────────┐        │
              │ PASSED   │ │ FAILED   │        │
              └────┬─────┘ └────┬─────┘        │
                   │            │              │
                   │            ▼              │
                   │  ┌─────────────────────┐  │
                   │  │     REPAIR (修复)    │  │
                   │  │  1. 分析根因         │  │
                   │  │  2. 最小修复         │  │
                   │  │  3. 回到 VERIFY      │  │
                   │  │  4. 最多 3 次        │  │
                   │  └─────────────────────┘  │
                   │            │              │
                   └────────────┴──────────────┘
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         REVIEW (审查)                                      │
│  1. Guard 检查 (边界/风险/反作弊)                                         │
│  2. Plan 合规检查 (allowedFiles / diff budget)                           │
│  3. Code Quality Gate (10 维度自评)                                      │
│  4. Anti-Cheating (测试完整性/断言弱化/Skip检测)                          │
│  5. 回滚计划生成 (L4/L5)                                                 │
│  6. Schema 版本记录 (DDL 变更)                                           │
│  输出: review_report, rollback.md, schema_version.md                     │
└─────────────────────────────────────────────────────────────────────────────┘
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         MEMORY (记忆沉淀)                                  │
│  1. MemoryExtractor 提取候选 (Failures → PITFALL, Decisions → RULE)     │
│  2. MemoryStore 写入 entries/ + 更新索引                                 │
│  3. MemoryProjection 同步到工具文件 (CLAUDE.md / safety.md)              │
│  输出: .ai/memory/entries/{id}.md, projections/                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              COMPLETED                                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Execute 阶段时序图（核心）

```text
AI Assistant              LoopRunner              ExecuteHandler           ContextRouter           Guard          ScenarioRunner
     │                         │                         │                      │                 │                 │
     │  loop continue          │                         │                      │                 │                 │
     │────────────────────────▶│                         │                      │                 │                 │
     │                         │  handle(state)          │                      │                 │                 │
     │                         │────────────────────────▶│                      │                 │                 │
     │                         │                         │  1. Task Start Gate   │                 │                 │
     │                         │                         │  2. check_worktree   │                 │                 │
     │                         │                         │  3. pre_guard_check  │                 │                 │
     │                         │                         │─────────────────────────────────────────▶│                 │
     │                         │                         │  result              │                 │                 │
     │                         │                         │◀─────────────────────────────────────────│                 │
     │                         │                         │  4. context route    │                 │                 │
     │                         │                         │─────────────────────▶│                 │                 │
     │                         │                         │  bundle              │                 │                 │
     │                         │                         │◀─────────────────────│                 │                 │
     │                         │                         │  5. construct prompt │                 │                 │
     │                         │                         │  6. needs_ai_input   │                 │                 │
     │                         │◀────────────────────────│                     │                 │                 │
     │◀────────────────────────│                         │                     │                 │                 │
     │  (return JSON with      │                         │                     │                 │                 │
     │   pending_prompt)       │                         │                     │                 │                 │
     │                         │                         │                     │                 │                 │
     │  AI 写代码...           │                         │                     │                 │                 │
     │                         │                         │                     │                 │                 │
     │  loop continue --result │                         │                     │                 │                 │
     │────────────────────────▶│                         │                     │                 │                 │
     │                         │  handle(state)          │                     │                 │                 │
     │                         │────────────────────────▶│                     │                 │                 │
     │                         │                         │  VALIDATE:          │                 │                 │
     │                         │                         │  1. diff budget     │                 │                 │
     │                         │                         │  2. style contract  │                 │                 │
     │                         │                         │  3. reuse check     │                 │                 │
     │                         │                         │  4. QuickCheck      │                 │                 │
     │                         │                         │──────────────────────────────────────────────────────▶│
     │                         │                         │  report             │                 │                 │
     │                         │                         │◀──────────────────────────────────────────────────────│
     │                         │                         │  5. record log      │                 │                 │
     │                         │                         │  6. next_task       │                 │                 │
     │                         │◀────────────────────────│                     │                 │                 │
     │◀────────────────────────│                         │                     │                 │                 │
     │  (继续或 VERIFY)       │                         │                     │                 │                 │
```

### 4.3 Continue 模式时序图（AI 暂停-恢复）

```text
AI Assistant              CLI (run.sh)          LoopRunner          RunState (run.json)
     │                        │                     │                      │
     │  loop full --task      │                     │                      │
     │───────────────────────▶│                     │                      │
     │                        │  create_sub_loop    │                      │
     │                        │────────────────────▶│                      │
     │                        │                     │  run(state)          │
     │                        │                     │─────────────────────▶│
     │                        │                     │  需要 AI 创造性工作   │
     │                        │                     │  needs_ai_input=True │
     │                        │                     │  pending_prompt=...  │
     │                        │                     │◀─────────────────────│
     │                        │◀────────────────────│                      │
     │◀───────────────────────│                     │                      │
     │  JSON: {              │                     │                      │
     │    needs_ai_input: true,│                   │                      │
     │    pending_prompt: ..., │                   │                      │
     │    hint: "..."         │                     │                      │
     │  }                     │                     │                      │
     │                        │                     │                      │
     │  AI 读取 pending_prompt, 生成内容 (Spec/代码/修复)               │
     │                        │                     │                      │
     │  loop continue --result '{"spec": ...}'    │                      │
     │───────────────────────▶│                     │                      │
     │                        │  _cmd_loop_continue │                      │
     │                        │────────────────────▶│                      │
     │                        │                     │  注入 result 到      │
     │                        │                     │  spec_entry         │
     │                        │                     │─────────────────────▶│
     │                        │                     │  needs_ai_input=False│
     │                        │                     │  继续 run(state)     │
     │                        │                     │◀─────────────────────│
     │                        │◀────────────────────│                      │
     │◀───────────────────────│                     │                      │
     │  最终结果              │                     │                      │
```

### 4.4 模块交互总图

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CLI (入口)                                    │
│  run.sh loop full --task "xxx"                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Runtime                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │                         LoopRunner                                  │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                │  │
│  │  │ Intake      │  │ Spec/Plan   │  │ Execute     │                │  │
│  │  │ Handler     │  │ Handlers    │  │ Handler     │                │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘                │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                │  │
│  │  │ Verify      │  │ Repair      │  │ Review      │                │  │
│  │  │ Handler     │  │ Handler     │  │ Handler     │                │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘                │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
          │              │              │              │              │
          ▼              ▼              ▼              ▼              ▼
┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│   Context   │ │    Guard    │ │  Scenario   │ │   Memory    │ │    State    │
│  Router     │ │   Engine    │ │   Runner    │ │   Store     │ │   (Model)   │
│             │ │             │ │             │ │             │ │             │
│ ·Sources    │ │ ·Rules      │ │ ·Assertions │ │ ·Extractor  │ │ ·RunState   │
│ ·Strategies │ │ ·QuickCheck │ │ ·Sanity     │ │ ·Projection │ │ ·Enums      │
│ ·Budget     │ │ ·CodeQuality│ │ ·Resources  │ │ ·Governance │ │ ·Serializer │
└─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘
          │              │              │              │
          └──────────────┴──────────────┴──────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Providers / Adapters / Init                       │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐  │
│  │  Providers  │ │  Adapters   │ │   Init      │ │   Test Design       │  │
│  │  Scenario   │ │  ClaudeCode │ │  Scanner    │ │   models             │  │
│  │  MCP-MySQL  │ │  Codex      │ │  Generator  │ │   quality_gate       │  │
│  │  MCP-Redis  │ │  Cursor     │ │  Runner     │ │   scenario_mapper    │  │
│  └─────────────┘ └─────────────┘ └─────────────┘ │   xlsx_writer        │  │
│                                                   └─────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 五、数据流与状态扭转

### 5.1 RunState 各阶段数据注入

| 阶段 | 写入字段 | 读取字段 |
| --- | --- | --- |
| INTAKE | task_intake, use_worktree | (无) |
| SPEC | spec_entry, spec_quality_report | task_intake |
| TEST_DESIGN | test_design_bundle, test_case_refs, scenario_candidate_refs | spec_entry |
| PLAN | plan_contracts, plan_lock_state, plan_quality_report | spec_entry, test_case_refs |
| EXECUTE | task_state.task_logs, checkpoints, task_state.status | plan_contracts, plan_lock_state |
| VERIFY | verification, scenario_results, failures | plan_contracts |
| REPAIR | failures (追加), task_state.retry_count | failures |
| REVIEW | metadata.review_report | task_state.task_logs, plan_contracts |
| MEMORY | metadata.memory_entries | failures, task_state.notes |

### 5.2 关键状态流转决策

```text
普通流转:
  INTAKE → SPEC (flow_mode=spec_from_prompt)
  INTAKE → DIRECT_EXECUTE (flow_mode=direct)
  SPEC → TEST_DESIGN → PLAN → EXECUTE → VERIFY
  VERIFY → (PASSED) → REVIEW → MEMORY → COMPLETED
  VERIFY → (FAILED: CODE) → REPAIR → VERIFY
  VERIFY → (FAILED: ENVIRONMENT) → STOP_FAILURE
  REPAIR → (retry < 3) → VERIFY
  REPAIR → (retry >= 3) → STOP_FAILURE
  REVIEW → (violations) → STOP_ABORT / REPAIR
  REVIEW → (passed) → MEMORY
  DIRECT_EXECUTE → VERIFY → REVIEW → COMPLETED
```

### 5.3 暂停-恢复状态

```text
【暂停点】
  1. ExecuteHandler._prepare_task() → needs_ai_input=True, pending_action="execute_task"
  2. RepairHandler._prepare_repair() → needs_ai_input=True, pending_action="repair"
  3. SpecHandler → (透传, 由 AI Skill 处理)
  4. PlanHandler → (透传, 由 AI Skill 处理)
  5. TestDesignStageHandler → (透传, 由 AI Skill 处理)

【恢复】
  AI 调用: engines/run.sh loop continue --state-file run.json --result '<JSON>'
  CLI: _cmd_loop_continue() → 注入结果到对应字段 → needs_ai_input=False → 继续
```

---

## 六、总结

### 6.1 架构设计原则

| 原则 | 体现 |
| --- | --- |
| 单一职责 | 每个模块只做一件事（State 只管数据，Runtime 只管流转，Context 只管加载） |
| 依赖倒置 | Providers 声明能力，Adapters 翻译格式，Runtime 不直接依赖具体工具 |
| 开闭原则 | 新增 AI 工具只需加 Adapter，新增 Stage 只需加 Handler |
| 适配器模式 | ToolAdapter 让核心逻辑与 AI 工具完全解耦 |
| 策略模式 | StageHandler 让每个阶段的逻辑独立可替换 |
| 状态模式 | RunState + StageType 驱动整个流转 |
| 熔断器模式 | 防止 AI 在同一问题上无限重试 |
| 模板方法模式 | StageHandler 提供 _advance_to / _complete 统一流转 |

### 6.2 与 AI 工具的交互模式

| 模式 | 说明 |
| --- | --- |
| Skill 调用 | AI 通过 Skill: ai-coding-loop:xxx 触发命令 |
| CLI 管道 | AI 执行 engines/run.sh loop xxx --format json 获取结构化结果 |
| 暂停-恢复 | Python 设置 needs_ai_input=True，AI 读取 pending_prompt，完成后 loop continue |
| Hook 注入 | SessionStart 时自动注入 using-ai-coding-loop 技能，AI 开机即知 |

### 6.3 关键数据流路径

```text
用户需求
    ↓
RunState (task_id, current_stage, task_intake)
    ↓
Spec (spec_entry) ← AI 生成
    ↓
Test Design (test_design_bundle) ← AI 生成
    ↓
Plan (plan_contracts) ← AI 生成
    ↓
Execute (task_logs, checkpoints) ← AI 写代码 + Python 校验
    ↓
Verify (scenario_results, failures) ← Python 执行
    ↓
Repair (failures 追加) ← AI 修复 + Python 校验
    ↓
Review (metadata.review_report) ← Python + AI 自评
    ↓
Memory (.ai/memory/entries/*.md) ← Python 提取 + 持久化
    ↓
COMPLETED
```