---
name: aicode-init
user-invocable: true
description: "初始化 AI Coding Loop — AI 扫描项目、生成配置文件、Python 安装 .ai/ 资产"
---

# /aicode-init — 项目初始化

> **你必须严格按顺序执行以下步骤。不要跳过任何步骤。
> 步骤 2-4 由你（AI）用 Read/Write 工具完成。
> 步骤 5 才轮到 Python。Python 不写任何配置内容。**

## 触发

```
/aicode-init [--target claude_code|codex|cursor]
```

无 `--target` 时自动检测：`.codex/` 存在 → codex，`.cursor/` 存在 → cursor，否则默认 claude_code。

## 各工具文件清单

根据目标工具，确定以下 4 个文件路径：

| 文件 | Claude Code | Codex CLI | Cursor |
|------|------------|-----------|--------|
| 主配置 | `CLAUDE.md` | `.codex/instructions.md` | `.cursor/rules/aicode.md` |
| 代码风格 | `.claude/rules/code-style.md` | `.codex/rules/code-style.md` | `.cursor/rules/code-style.md` |
| 测试规则 | `.claude/rules/testing.md` | `.codex/rules/testing.md` | `.cursor/rules/testing.md` |
| 安全规则 | `.claude/rules/safety.md` | `.codex/rules/safety.md` | `.cursor/rules/safety.md` |
| 命令前缀 | `/` | `/` | `@` |

---

## 步骤 1：确定目标工具和文件路径

根据用户指定的 `--target` 或自动检测，确定目标工具。然后从上表查得 4 个文件的完整路径。

---

## 步骤 2：AI 扫描项目

> **你必须用 Read / Glob / Bash 工具亲自读项目文件。**
> 不经过 Python，不用 subprocess。

### 2.1 读依赖文件

用 Read 读一个依赖文件确认技术栈：

- 存在 `pom.xml` → 读 `pom.xml`
- 存在 `package.json` → 读 `package.json`  
- 存在 `go.mod` → 读 `go.mod`
- 存在 `pyproject.toml` → 读 `pyproject.toml`

提取：语言、框架、包管理器、构建工具、测试框架名和版本。

### 2.2 列目录结构

用 `ls` 或 Glob 列出项目顶层和关键子目录，确认源码/测试/资源/配置的实际位置。

### 2.3 读源码（整个项目）

从源码目录选代表性文件，用 Read 打开。边读边记录：

- **命名约定**：类/函数/变量/常量各自怎么命名，至少 3 个实例
- **文件组织**：每个包/模块做什么，依赖方向
- **异常处理**：搜索 raise/throw/catch，用的是什么异常类
- **日志**：搜索 log/logger，用的是什么日志库


---

## 步骤 3：生成主配置文件

> **不存在时必须生成。已存在则跳过。**

### 3.1 检查

用 Read 试着读主配置文件路径。读到内容 → 文件存在；读不到（No such file）→ 不存在。

- **存在 → 跳过**。告知用户："{路径} 已存在，跳过。"
- **不存在 → 你必须立即用 Write 工具创建它。**

### 3.2 内容要求（≤200 行）

按以下结构写：

```
# {项目名}

## 技术栈
{语言} / {框架} / {包管理器}

## 目录结构
### 比如
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


## 代码风格
### 命名约定
{从步骤 2.3 提取的真实命名模式，每种附 3+ 个实例}
### 文件组织
{目录职责和依赖方向}
### 异常处理
{项目实际异常类和传播方式}
### 日志
{项目实际日志库和调用模式}

## 测试
- 框架: {框架+版本}
- 测试文件位置: {目录}
- 运行命令: {完整可运行命令}

## 架构约束
{分层规则、模块依赖方向}

## 禁止行为
以下行为在任何代码生成、修改或建议中均被严格禁止，必须无条件遵守：

## 安全底线
- **禁止** 在代码中硬编码任何密钥、密码、令牌或敏感配置（如 API Key、数据库密码）。
- **禁止** 使用已知存在安全漏洞的依赖版本（如 log4j 2.x 老版本、包含原型污染风险的 npm 包）。
- **禁止** 在用户输入未经验证的情况下直接拼接到 SQL 语句或系统命令中（必须使用参数化查询或转义）。

## 代码质量
- **禁止** 生成超过 80 列宽的代码行（除非语言强制要求）。
- **禁止** 使用 `var`（JavaScript/TypeScript）或 `auto` 滥用（C++）——必须使用明确的类型声明。
- **禁止** 在函数或方法中嵌套超过 3 层的条件分支（if-else）或循环。
- **禁止** 提交任何包含 `console.log`、`debugger`、`print` 等调试语句的代码（除非明确要求临时调试）。
- **禁止** 复制粘贴重复代码（必须提取公共逻辑）。
- **禁止** 代码中出现魔法值。
## 设计与架构
- **禁止** 在核心业务逻辑中直接依赖外部框架的具体实现（应依赖接口/抽象）。
- **禁止** 创建超过 300 行的单个函数或方法。
- **禁止** 在未明确要求的情况下引入新的全局变量或修改全局状态。

## 依赖与环境
- **禁止** 添加任何未经用户明确许可的新依赖（包括 npm、pip、maven 等）。
- **禁止** 在代码中硬编码文件路径或网络地址，必须使用配置文件或环境变量。

## 文档与提交
- **禁止** 生成没有清晰注释的复杂算法（至少说明思路）。
- **禁止** 在提交信息中写模糊的描述（如 "update"、"fix bug"），必须遵循 Conventional Commits 格式。

---
**执行方式**：遇到以上任何规则被违反，AI 必须先指出违规点，并提供修正方案，再给出最终代码。用户明确要求忽略某条规则时除外。
```

### 3.3 写作铁律

- 只写项目特有的，不写"遵循最佳实践"
- 每条命令复制粘贴到终端可直接运行
- 每条命名约定从代码中找到 3+ 个实例支撑
- 正面引导："使用 X"而非"不要用 Y"
- 不抄 linter 已有的规则
- 每条规则：做什么 + 不这样会怎样 + 为什么

---

## 步骤 4：生成 3 个规则文件

> **每个文件独立检查：不存在则必须生成，存在则跳过。**

### 4.1 {rules_dir}/code-style.md

Read 检查是否存在。不存在则 Write 创建：

```
# 代码风格

## 命名约定
{类名/函数名/变量名/常量名各附 3+ 实例}

## 文件组织
{每个包/模块的职责和依赖方向}

## 异常处理
{实际异常类、何时用哪个、如何传播}

## 日志
{实际日志库和调用模式}
```

目标 ≤60 行。

### 4.2 {rules_dir}/testing.md

Read 检查是否存在。不存在则 Write 创建：

```
# 测试规则

## 测试框架
{框架名 + 版本}

## 目录结构
{测试目录与源码的对应关系}

## 文件命名
{测试文件命名约定}

## Mock/Stub/Fixture
{从现有测试提取的实际模式}

## 运行命令
{可直接运行的完整命令}
```

目标 ≤40 行。

### 4.3 {rules_dir}/safety.md

Read 检查是否存在。不存在则 Write 创建：

```
# 安全边界

## 不可修改
{不应修改的文件/目录}

## 禁止操作
{项目特有的禁止行为}

## 修改边界
{哪些模块可以改、哪些是外部接口不能动}
```

目标 ≤30 行。

### 4.4 规则文件写作原则

- 每条规则 = 做什么 + 不这样会怎样 + 为什么
- 正面引导
- 不写长篇说明，只写 AI 需要知道的约束

---

## 步骤 5：Python 安装 .ai/ 资产和 adapter 配置

> **⚠️ 确认步骤 2-4 全部完成后再执行此步骤。**

4 个配置文件已由你写入，现在让 Python 安装 .ai/ 目录和 adapter 配置：

```bash
cd <引擎根目录> && python -m engines.cli init --assets-only --format json --project-root "<项目根目录>" --target <target_tool>
```

引擎根目录 = 当前 SKILL.md 文件所在目录向上两级。

Python 会创建 .ai/ 目录结构（memory、scenarios、config.yaml）和 MCP 配置 / loop-config.json。不生成配置文件、skills 或 hooks。

---

## 步骤 6：向用户报告

展示完整结果：

```
✅ AI Coding Loop Init 完成

目标工具: {adapter}
技术栈: {language} / {framework}

配置文件:
  [已生成] CLAUDE.md
  [已生成] .claude/rules/code-style.md
  [已生成] .claude/rules/testing.md
  [已生成] .claude/rules/safety.md

资产:
  .ai/ 目录结构（memory / scenarios / config.yaml）
  MCP 配置 / loop-config.json

下一步:
  /aicode-calibrate  确认规则
  /aicode-spec <需求>  开始第一个任务
```

如果某个文件因已存在被跳过，标注 `[已跳过]` 而不是 `[已生成]`。
