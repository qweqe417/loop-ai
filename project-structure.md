# AI Coding Loop — 项目目录结构、架构评估与 Loop Engineering 分析

## 一、项目定位

本项目要做的是一个**AI Coding 能力插件包**——应用项目下载安装后，可以无缝执行 Loop Engineering 流程完成「需求理解 → Spec 生成 → Plan 拆分 → AI 编码 → 真实验证 → 失败修复 → Review → 记忆沉淀」的完整开发闭环。

它不是替代 Claude Code / Codex / Cursor，而是以一个**插件**形态把 AI Coding 闭环能力集成到这些工具里。

---

## 二、完整目录结构（中文职责标注）

```
loop/                                   # 项目根目录
│
├── .ai/                                # ★ 跨工具资产与运行时状态目录（与具体 AI 工具解耦）
│   ├── memory.md                       # 项目权威记忆：代码规则、历史坑点、架构决策、禁止事项
│   ├── spec-index.yaml                 # 外部 Spec 索引（记录 Superpowers/spec-kit 已有 Spec 指针）
│   ├── schema_version.md               # 数据库结构变更记录（DDL/migration 时启用）
│   ├── scenarios/                      # 真实流程验证场景（.yaml），定义 "given-when-then" 断言
│   ├── fixtures/                       # 场景测试初始数据（如 MySQL 预置数据）
│   ├── runs/                           # 每次 Loop 运行记录（可选）
│   ├── plans/                          # 计划产物：任务拆解结果、执行合约
│   ├── reports/                        # 验证报告、Review 结果、失败分析
│   └── checkpoints/                    # 阶段快照与恢复点（人工审批前暂停、daemon 模式断点）
│
├── .idea/                              # JetBrains IDE 配置（PyCharm 自动生成，非项目代码）
├── .venv/                              # Python 虚拟环境（依赖隔离，非项目代码）
│
├── docs/                               # 项目文档
│   ├── AI_CODING_LOOP_ARCHITECTURE.md  # ★ 系统架构设计文档（权威参考）
│   ├── architecture/                   # 架构相关文档
│   │   └── project-structure.md        # 目录结构说明
│   ├── workflows/                      # 工作流说明文档
│   └── decisions/                      # 架构决策记录（ADR）
│
├── src/                                # ★ 源代码根目录
│   │
│   ├── cli/                            # CLI 命令行入口
│   │                                   # 命令：init / calibrate / install / spec / plan / verify / guard / memory / report
│   │
│   ├── core/                           # ★★★ 核心引擎层（工具无关，是整个系统的闭环主线）
│   │   │
│   │   ├── runtime/                    # 【Loop 主流程编排器】
│   │   │                               # 职责：Discover → Plan → Execute → Verify → Repair → Review → Memory
│   │   │                               # 阶段切换、停止条件判断、失败后回环入口、Loop 决策
│   │   │
│   │   ├── state/                      # 【闭环状态模型】
│   │   │                               # 定义：RunState / TaskState / StageType / VerificationState
│   │   │                               # FailureReason / Checkpoint / LoopDecision / NextAction
│   │   │                               # 没有这一层，系统只是"连续调用函数"而非"真正做 Loop"
│   │   │
│   │   ├── loop/                       # Loop 引擎核心
│   │   │                               # 驱动三种模式：Direct / SpecFromPrompt / SpecFromDocument
│   │   │
│   │   ├── spec/                       # Spec 管理器
│   │   │                               # Spec 生成、Spec Quality Gate（模糊词检测、完整性检查）、动态字段生成
│   │   │
│   │   ├── plan/                       # Plan 管理器
│   │   │                               # 任务拆分、执行合约（allowedFiles / forbiddenFiles / diffBudget）
│   │   │                               # Plan Lock、Plan Change Request、Plan Compliance Review
│   │   │
│   │   ├── context/                    # Context Router 上下文路由器
│   │   │                               # 渐进式披露：先项目地图 → 再相关 Spec → 再相关 Memory → 再相关源码
│   │   │                               # 防止 Token 爆炸、防止 Lost-in-the-Middle
│   │   │
│   │   ├── scenario/                   # Scenario Runner 场景验证器
│   │   │                               # HTTP 调用、响应验证、数据断言（MySQL/Redis/MQ/日志）、报告生成
│   │   │
│   │   ├── guard/                      # Guard 守卫系统
│   │   │                               # 修改边界控制、风险分级（L1-L5）、Anti-Cheating 防作弊、
│   │   │                               # 回滚方案生成（Reversibility Check）
│   │   │
│   │   ├── memory/                     # Memory 记忆系统
│   │   │                               # .ai/memory.md 读写、Memory 候选筛选（三问框架过滤）、工具投影同步
│   │   │
│   │   ├── project/                    # 项目理解层（Project Understanding）
│   │   │                               # 扫描项目结构、语言/框架/包管理器识别、代码风格抽样
│   │   │
│   │   └── resources/                  # 资源访问层
│   │                                   # 通过 MCP/CLI/驱动/SDK 访问 MySQL、Redis、MQ、ES、日志、CI
│   │                                   # 安全默认值：只连测试环境、默认只读、禁止生产库、禁止 DDL
│   │
│   ├── providers/                      # ★ 外部规范体系 Provider 层（不复制、不吞并，只做胶水映射）
│   │   ├── builtin/                    # 内置 Spec/Plan Provider（不依赖外部工具的降级兜底）
│   │   ├── superpowers/                # Superpowers Provider（第一阶段重点）
│   │   │                               # Glue Mapping：外部命令/Skill ↔ Loop State ↔ 输入/输出/失败/确认点
│   │   ├── opensdd/                    # OpenSDD Provider（预留接口）
│   │   └── spec_kit/                   # spec-kit Provider（预留接口）
│   │
│   ├── plugins/                        # ★ 工具插件层（Adapter 模式：将 Core 能力映射到具体 AI 工具）
│   │   │
│   │   ├── _shared/                    # 插件共享资源
│   │   │   ├── prompts/               # 共享 Prompt 模板
│   │   │   ├── rules/                 # 共享规则片段
│   │   │   ├── templates/             # 共享文件模板
│   │   │   └── assets/                # 共享静态资产
│   │   │
│   │   ├── claude_code/                # ★ Claude Code 插件（第一阶段主实现目标）
│   │   │   ├── plugin/                # 插件核心：能力声明、生命周期
│   │   │   ├── installer/             # 安装逻辑 aicode install claude
│   │   │   ├── commands/              # /aicode-spec、/aicode-plan、/aicode-verify、/aicode-review、/aicode-memory
│   │   │   ├── rules/                 # .claude/rules/* 生成器（code-style/testing/api/database/safety）
│   │   │   ├── aicode/                # .claude/aicode/* 生成器（project-map/style/workflow/memory）
│   │   │   └── templates/             # CLAUDE.md 等原生文件模板
│   │   │
│   │   ├── codex/                      # Codex 插件（后续阶段扩展）
│   │   │   ├── plugin/                # 插件核心
│   │   │   ├── installer/             # 安装逻辑
│   │   │   ├── skills/                # .codex/skills/aicode-* Skill 包
│   │   │   ├── aicode/                # .codex/aicode/* 资产投影
│   │   │   └── templates/             # .codex/instructions.md 模板
│   │   │
│   │   └── cursor/                     # Cursor 插件（后续阶段扩展）
│   │       ├── plugin/                # 插件核心
│   │       ├── installer/             # 安装逻辑
│   │       ├── rules/                 # .cursor/rules/aicode-* 规则
│   │       └── templates/             # Cursor 原生文件模板
│   │
│   ├── platform/                       # 插件平台基础设施
│   │   └── plugin_sdk/                 # 插件开发 SDK
│   │       ├── base/                  # 基础类型与接口（PluginBase、Capability、Adapter）
│   │       ├── manifest/              # 插件清单解析（capabilities.yaml → 能力注册）
│   │       ├── renderer/              # 原生文件生成器（内部模型 → 工具原生格式渲染）
│   │       ├── installer/             # 通用安装器（安装/卸载/更新/版本检测）
│   │       ├── projection/            # 工具记忆投影（.ai/memory.md → CLAUDE.md / .codex / .cursor）
│   │       └── registry/              # 插件注册中心（发现、依赖检查、版本管理）
│   │
│   └── shared/                         # 共享底层工具库（纯技术，无业务语义）
│       ├── utils/                     # 通用工具函数
│       ├── io/                        # 文件 IO 封装
│       ├── markdown/                  # Markdown 解析与生成
│       ├── yaml/                      # YAML 解析与生成
│       ├── errors/                    # 统一错误类型定义
│       └── logging/                   # 日志系统
│
├── tests/                              # 测试目录
│   ├── unit/                          # 单元测试（每个 core 模块的独立测试）
│   ├── integration/                   # 集成测试（多模块协作、Provider 接入测试）
│   └── e2e/                           # 端到端测试（完整 CLI 命令 + 真实项目模拟）
│
└── README.md                           # 项目说明
```

---

## 三、架构层 → 源码目录映射表

将架构文档（AI_CODING_LOOP_ARCHITECTURE.md 第 4 节）定义的 12 个架构层与实际目录对应：

| 架构层 | 对应目录 | 职责 |
|---|---|---|
| 1. Plugin Distribution Layer | `src/platform/plugin_sdk/` | 插件分发、安装、清单、注册 |
| 2. AI Tool Adapter Layer | `src/plugins/claude_code/` `codex/` `cursor/` | 生成工具原生规则/命令/Skills |
| 3. Loop Engine | `src/core/runtime/` + `src/core/loop/` | 阶段编排、模式驱动、停止条件 |
| 4. Spec / Plan Provider Layer | `src/providers/` | 外部 Spec/Plan 能力接入 |
| 5. Project Understanding Layer | `src/core/project/` | 项目扫描、语言/框架识别 |
| 6. Context Router Layer | `src/core/context/` | 渐进式上下文披露 |
| 7. Skill Orchestration Layer | `src/core/runtime/` + `src/plugins/_shared/` | 按任务类型调度 Skills |
| 8. Scenario Verification Layer | `src/core/scenario/` | 真实流程验证 + 断言引擎 |
| 9. Resource Access Layer | `src/core/resources/` | MySQL/Redis/MQ/日志 访问适配 |
| 10. Guard Layer | `src/core/guard/` | 修改边界/风险/防作弊/回滚 |
| 11. Memory Layer | `src/core/memory/` + `.ai/` | 项目记忆 + 工具投影 |
| 12. Execution Mode Layer | `src/cli/` + `src/core/runtime/` | 交互模式/Daemon 模式 |

---

## 四、Loop Engineering 视角下的架构评估

### 4.1 什么是 Loop Engineering（社区共识）

Loop Engineering 是 2026 年 6 月由 OpenClaw 作者 Peter Steinberger 提出的概念。核心理念：

> **开发者不应再直接写 Prompt，而应设计一套能让 Agent 自主迭代的 Loop（循环）系统。**

它本质上是 **ReAct 范式的工程化延伸**：

```
Plan（计划）→ Act（行动）→ Observe（观察）→ Critique（反思）→ Loop（循环）
```

五个核心要素：

| 要素 | 说明 | 本架构对应 |
|---|---|---|
| **明确目标 (Goal)** | 可由 Agent 自行验证的结果定义 | Spec 中的 Acceptance Criteria、Scenario 中的断言 |
| **上下文管理 (Context)** | 动态更新：保留/压缩/遗忘 | `src/core/context/` Context Router 渐进式披露 |
| **可调用工具 (Tools)** | 运行测试、读写文件、搜索代码、调用 API | Scenario Runner、Resource Access、MCP |
| **产出评估 (Evaluation)** | 客观（跑测试）、主观（LLM 打分）、混合（diff 判断） | Scenario 断言 + Guard + Review |
| **停止标准 (Termination)** | 目标达成或达最大迭代次数 | `src/core/runtime/` 停止条件、`src/core/state/` LoopDecision |

### 4.2 四代工程范式演进与当前架构的对应

```
Prompt Engineering  →  "怎么问他"     →  本项目不卡在这一层
Context Engineering →  "让他看见什么"   →  src/core/context/
Harness Engineering →  "把他放在什么环境" →  src/core/guard/ + src/core/scenario/
Loop Engineering    →  "系统怎么自己转"  →  src/core/runtime/ + src/core/state/
```

**当前架构已经覆盖了 Context / Harness / Loop 三层能力**，不是只停留在 Prompt 层面。

### 4.3 当前架构的优势

**1. Loop 闭环主线完整**

架构文档定义的 7 个 Loop（Requirement → Planning → Implementation → Verification → Debug/Repair → Review → Memory）全部有源码目录对应：
- `src/core/runtime/` 承载主流程编排
- `src/core/state/` 承载结构化状态流转
- 每个 Loop 阶段都有明确的模块归属

**2. 插件化分发方案清晰**

用户说"应用项目下载插件后无缝执行"——这正是当前 `src/plugins/` 层做的事：
- `aicode init` 扫描项目 → 生成 CLAUDE.md + .claude/rules/* + .claude/commands/*
- 用户项目无需修改自身代码，AI 工具自动获得 Loop 能力
- `.ai/` 目录承载跨工具运行状态

**3. 防无限循环机制已设计**

社区讨论的核心担忧之一是"Loop 可能烧 Token"。当前架构已有：
- `src/core/state/` 中的 `LoopDecision`（停止/继续/回环/求助）
- Plan 中的 `diffBudget`（修改行数上限）
- Guard 中的风险等级（L5 默认不自动执行）
- Task 粒度控制（1-3 个文件，10-20 分钟）

**4. 验证不是"看代码猜正确"**

很多 AI Coding 工具的验证靠 LLM 读代码判断对错——这是不可靠的。当前架构的 Scenario Runner：
- 真实调接口、验 HTTP 响应
- 查 MySQL/Redis/MQ 状态
- 环境健康检查（Sanity Check）区分"环境故障"和"代码故障"
- 防止 AI 删除测试/弱化断言来"通过"验证

### 4.4 需要注意和改进的点

**1. `src/core/state/` 是当前最关键但最薄弱的模块**

Loop Engineering 的本质区别在于"带着状态循环"，而非"连续调用几个函数"。`RunState`、`TaskState`、`Checkpoint`、`LoopDecision` 这些模型的完整性直接决定系统是"真正在 Loop"还是"只是串行执行"。

建议：优先实现 state 模块的结构化模型，尤其是 `LoopDecision` 的停止条件逻辑。

**2. 停止条件需要更显式的设计**

社区讨论反复提到：停止条件设计不当是 Loop 的最大工程风险。当前架构在 runtime 中提到了停止条件，但应该更显式地定义：
- 目标达成类：Scenario 全部通过、Acceptance Criteria 全部满足
- 上限保护类：最大迭代次数、最大 Token 消耗、最大耗时
- 外部干预类：人工确认点、Plan Change Request 触发暂停

**3. Orchestrator + Worker 模式预留不足**

社区讨论指出，单纯的单 Agent Loop 存在上下文衰减和试错能力不足的问题，更推荐 Orchestrator + Worker 模式。当前架构的 `src/core/runtime/` 可以作为 Orchestrator，但子任务隔离执行的 Worker 模式在目录结构中没有明确体现。

建议：在 `src/core/runtime/` 中预留 sub-task dispatcher / worker context isolation 的概念。

**4. 插件"即装即用"体验还需要完善的 CLI**

用户说"下载插件后无缝执行"，这意味着 `aicode init` 必须是零配置或接近零配置的。当前 CLI 设计已有 init → calibrate → spec → plan → verify 的完整命令链，但需要确保：
- init 的自动检测足够准确（语言/框架/测试方式/外部资源）
- calibrate 的交互体验足够友好（规则确认不是负担）
- 缺失能力（如 MCP Server）的引导足够清晰

### 4.5 总体评估结论

| 维度 | 评分 | 说明 |
|---|---|---|
| Loop 闭环完整性 | ★★★★★ | 7 个 Loop 全部有对应模块 |
| 状态管理 | ★★★★☆ | state 目录已规划，模型待实现 |
| 上下文管理 | ★★★★★ | Context Router 渐进式披露设计完善 |
| 验证体系 | ★★★★★ | Scenario Runner + 真实流程验证 + Anti-Cheating |
| 风险控制 | ★★★★★ | 5 级风险体系 + Guard + 回滚方案 |
| 插件化分发 | ★★★★★ | Claude Code/Codex/Cursor 插件层清晰 |
| 停止条件 | ★★★☆☆ | 概念存在，需要更显式的实现 |
| 多 Agent 预备 | ★★★☆☆ | Orchestrator + Worker 预留空间不足 |

**总结论：当前架构非常适合做 AI Coding Loop 插件。** 它不是"为了像 Loop Engineering 而改造目录名"的表面工程，而是从架构文档到目录结构到开发流程都按 Loop Engineering 理念设计的。核心的 `runtime/` + `state/` 创新补充（相对于架构文档的原有 12 层）使 Loop 主线更加清晰。

当前值得投入的方向不是再调整目录结构，而是：
1. 把 `src/core/state/` 的状态模型做扎实（这是 Loop Engineering 的"灵魂"）
2. 把 `src/core/runtime/` 的主流程骨架跑通
3. 把 `src/plugins/claude_code/` 的最小可用版本做出来

---

## 五、应用项目接入流程（用户视角）

一个典型 Spring Boot / FastAPI / Next.js 项目接入本插件的体验：

```bash
# 1. 安装
aicode install claude
aicode install superpowers

# 2. 初始化（自动扫描项目，生成原生规范文件）
aicode init

# 3. 校准（确认 init 推断的代码风格和规则）
aicode calibrate

# 4. 日常使用
aicode spec "给订单增加超时自动关闭功能"    # 从需求生成 Spec
aicode plan                                    # 从 Spec 拆分为执行合约
aicode verify scenario order-timeout-close     # 真实流程验证
aicode guard check                             # 修改边界与安全检查
aicode memory update                           # 沉淀经验

# 5. 也可以在 Claude Code 中直接用 / 命令
/aicode-spec 给订单增加超时自动关闭功能
/aicode-plan
/aicode-verify order-timeout-close
/aicode-review
/aicode-memory
```

接入后，AI 编码过程从"手动指挥 AI 写代码 + 手动测试"变成：

```
需求输入 → Task Intake（复杂度/风险判断）
→ Spec 生成（含验收标准、修改边界）
→ Plan 拆分（含执行合约、Diff Budget）
→ AI 逐 Task 编码（受 Guard 约束）
→ Scenario Runner 真实验证（调接口 + 验数据库）
→ 失败自动 RCA + 最小修复
→ Review（越界/风格/安全/防作弊）
→ Memory 沉淀
```

---

## 六、与 Loop Engineering 社区讨论的关键呼应

| 社区关注点 | 当前架构的回应 |
|---|---|
| "Loop 不是 CI/CD 换皮" | 本系统的 Loop 是 AI 驱动的智能闭环，不是定时触发器——有 Context Router、Spec Quality Gate、Plan Compliance Review |
| "Token 烧钱风险" | Diff Budget、Task 粒度控制、渐进式上下文、L5 默认不自动执行 |
| "ReAct 单 Agent 瓶颈" | `runtime/` 作为 Orchestrator、允许按 Task 隔离上下文执行 |
| "停止条件是最难的" | `state/LoopDecision` 设计 + 三层停止条件（目标达成/上限保护/外部干预）|
| "Harness + Loop 关系" | `guard/` = Harness（护栏）、`runtime/` = Loop（剧本）——架构文档本身已有分离 |
| "多 Agent 协作" | `runtime/` 可扩展为 Orchestrator、`core/` 各模块可作为独立 Worker 能力单元 |

---

## 七、优先级路线图

### 当前最优先（Phase 1）

```
src/core/state/     → 结构化状态模型（RunState / LoopDecision）
src/core/runtime/   → 主流程骨架（Discover → Plan → Execute → Verify → Repair → Review → Memory）
src/core/loop/      → 三种模式路由（Direct / SpecFromPrompt / SpecFromDocument）
src/cli/            → aicode init / calibrate 命令
```

### 紧随其后（Phase 2）

```
src/core/spec/      → Spec Quality Gate
src/core/plan/      → Plan 执行合约 + Plan Change Request
src/core/context/   → 渐进式上下文路由
src/providers/superpowers/ → Superpowers Glue Mapping
```

### 工程验证（Phase 3）

```
src/core/scenario/  → Scenario Runner + 断言引擎
src/core/guard/     → 边界检查 + Anti-Cheating
src/core/memory/    → 记忆沉淀规则
src/plugins/claude_code/ → 最小可用插件
```

---

## 八、最终结论

**这套架构非常适合做"下载即用"的 AI Coding Loop 插件。**

核心原因不是目录结构看起来像 Loop Engineering，而是四个方面：

1. **Core 闭环主线清晰**：runtime → state → loop → spec → plan → context → scenario → guard → memory，每一环都有明确模块
2. **插件层纯粹**：Claude Code / Codex / Cursor 的适配逻辑隔离在 plugins 中，不污染核心能力
3. **Provider 可插拔**：Superpowers / spec-kit / OpenSDD 作为外部能力接入，系统不绑定任何单一规范体系
4. **.ai/ 跨工具资产**：状态、计划、报告、检查点独立于任何 AI 工具，保证工具切换时经验不丢失

当前不需要推翻重建，按优先级路线图推进即可。