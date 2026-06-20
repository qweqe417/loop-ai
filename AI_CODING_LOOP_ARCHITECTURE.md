# AI Coding Loop 系统架构设计

## 1. 定位

本系统是一套参考 Superpowers 插件形态设计的 AI Coding 能力包。它不是替代 Claude Code、Codex 或 Cursor，而是把一整套基于 Loop Engineering 的开发闭环，以插件方式集成到这些 AI 编程工具中。

当前优先级：

```text
第一阶段：先基于 Claude Code + Superpowers 跑通完整流程。
后续阶段：保留 Codex、Cursor、spec-kit、OpenSDD 等扩展点。
```

核心目标：

```text
项目理解
-> 需求 Spec 化
-> Plan / Task 拆解
-> AI 编码执行
-> 真实流程验证
-> 根因分析
-> 自动修复
-> Review
-> 记忆沉淀
-> 跨工具复用
```

一句话：

```text
把 AI Coding 的工程闭环，以插件形式集成到 Claude Code、Codex、Cursor 等工具中。
```

## 2. 设计目标

### 2.1 用户侧目标

- 用户可以像使用 Superpowers 一样安装能力包。
- 用户可以优先在 Claude Code 中使用完整 AI Coding 流程。
- 后续可以无缝扩展到 Codex、Cursor 等工具。
- 小需求可以直接 Prompt 执行。
- 中大型需求可以从 Prompt 或文档生成 Spec 和 Plan。
- AI 编码必须遵循项目风格和修改边界。
- 复杂功能必须通过真实流程验证。
- 历史问题和项目规则必须能沉淀。

### 2.2 工程侧目标

- AI 生成代码风格更贴近项目。
- AI 不容易遗漏复杂功能中的细节。
- AI 不依赖人工测试完成最终验证。
- AI 修复问题时先复现、再根因分析、再最小修复。
- AI 不能为了通过测试删除断言、跳过测试或越界修改。
- 项目经验可以被后续任务复用。

## 3. 核心原则

### 3.1 插件优先

系统优先以插件形态进入现有 AI 编程工具：

```text
Claude Code Plugin
Codex Skill Pack
Cursor Rule Pack
CLI Helper
```

用户不应该先学习一个庞大的新平台，而应该在已有工具里获得能力增强。

### 3.2 Claude Code + Superpowers 先行

第一阶段不追求所有工具同时打通。

优先实现：

```text
Claude Code Adapter
Superpowers Provider
Scenario Runner
Memory
Guard
Context Router
```

Codex、Cursor、spec-kit、OpenSDD 先设计接口，后续适配。

### 3.3 Core 与 Adapter 分离

核心能力不能绑定 Claude Code。

```text
Core:
Loop、Spec、Plan、Scenario、Memory、Guard、Context Router。

Adapter:
把 Core 能力映射到 Claude Code、Codex、Cursor。
```

### 3.4 外部规范体系作为 Provider 接入

Superpowers、spec-kit、OpenSDD 等不应该被吞掉或复制，而应该作为 Provider。

```text
SuperpowersSpecProvider
SpecKitProvider
OpenSDDProvider
BuiltinSpecProvider
```

第一阶段只深度兼容 Superpowers，其余保留接口。

### 3.5 Spec 动态化

不同项目不一定有 MySQL、Redis、MQ、权限、缓存、微服务。

Spec 必须根据项目能力和任务影响域动态生成。

### 3.6 渐进式上下文披露

系统不能一次性把所有上下文塞给 AI。

必须使用 Context Router 做渐进式披露：

```text
先给项目地图
再给相关 Spec
再给相关 Memory
再给相关源码
最后按需给日志和验证报告
```

### 3.7 真实流程验证优先

复杂业务不应该只靠 AI 读代码后判断正确。

验证应优先使用：

```text
启动服务或连接已启动服务
调用接口
验证响应
验证数据库 / Redis / MQ / 日志 / 文件状态
生成报告
```

原生测试框架用于长期回归沉淀，而不是第一步就强迫所有验证进入 JUnit、pytest、Jest。

## 4. 总体架构

```text
AI Coding Loop System

1. Plugin Distribution Layer
   以插件或能力包形式安装到 Claude Code、Codex、Cursor。

2. AI Tool Adapter Layer
   生成工具原生规则、命令、Skills、Memory 投影。

3. Loop Engine
   驱动 Direct Prompt、Spec From Prompt、Spec From Document 三种模式。

4. Spec / Plan Provider Layer
   接入 Superpowers、spec-kit、OpenSDD 或内置 Spec/Plan 能力。

5. Project Understanding Layer
   扫描项目结构、语言、框架、代码风格、测试方式、资源依赖。

6. Context Router Layer
   按任务阶段渐进式注入上下文，避免 Context Explosion。

7. Skill Orchestration Layer
   根据任务类型调度语言、框架、测试、调试、Review、安全等 Skills。

8. Scenario Verification Layer
   调用接口，验证响应和数据状态，输出验证报告。

9. Resource Access Layer
   通过 MCP、CLI、驱动或 SDK 访问 MySQL、Redis、MQ、日志、CI 等资源。

10. Guard Layer
    控制修改边界、风险等级、防投机行为、安全权限、可回滚性。

11. Memory Layer
    管理项目记忆、工具记忆投影、任务运行记录和历史经验复用。

12. Execution Mode Layer
    区分本地交互模式和 CI/Daemon 模式。
```

## 5. 插件形态设计

### 5.1 安装方式

第一阶段：

```bash
aicode install claude
aicode install superpowers
aicode init
```

后续扩展：

```bash
aicode install codex
aicode install cursor
aicode install spec-kit
aicode install opensdd
```

### 5.2 Claude Code 生成内容

安装后 `.claude/skills/` 由 install.py 写入，init 生成项目文件：

```text
CLAUDE.md
.claude/skills/init.md          ← install.py 写入
.claude/skills/calibrate.md
.claude/skills/spec.md
.claude/skills/plan.md
.claude/skills/verify.md
.claude/skills/review.md
.claude/skills/memory.md
.claude/skills/full.md
.claude/skills/dev.md
.claude/skills/test.md
.claude/skills/direct.md
.claude/rules/code-style.md     ← init 生成
.claude/rules/testing.md
.claude/rules/safety.md
.claude/aicode/project-map.md
.claude/aicode/style.md
.claude/aicode/workflow.md
.claude/aicode/plugin-root.txt  ← install.py 写入（引擎路径回退）
hooks/hooks.json                ← install.py 写入
```

### 5.3 未来 Codex 生成内容

```text
.codex/instructions.md
.codex/skills/aicode-spec/
.codex/skills/aicode-debug/
.codex/skills/aicode-review/
.codex/aicode/project-map.md
.codex/aicode/style.md
.codex/aicode/workflow.md
.codex/aicode/memory.md
```

### 5.4 插件能力声明

插件内部声明能力，用户不手写 Provider / Adapter 配置。

```yaml
name: superpowers-provider
capabilities:
  - spec.generate
  - plan.generate
  - task.breakdown
```

```yaml
name: claude-adapter
capabilities:
  - tool.instructions.generate
  - command.install
  - memory.project
```

```yaml
name: scenario-runner
capabilities:
  - scenario.http
  - assertion.mysql
  - assertion.redis
  - report.generate
```

## 6. 项目初始化设计

### 6.1 init 的职责

`aicode init` 负责把当前项目接入 AI Coding Loop。

它应该做：

```text
1. 检测项目语言和框架。
2. 识别目录结构和主要模块。
3. 抽样识别代码风格。
4. 识别测试风格和常见验证方式。
5. 识别是否有 MySQL、Redis、MQ、ES、对象存储等资源。
6. 检测 Claude Code 和 Superpowers。
7. 生成 Claude Code 原生规则文件。
8. 初始化 .ai 跨工具资产目录。
9. 建立 Superpowers Spec 索引。
```

第一阶段基于 Claude Code 时，初始化的重点不是生成大量中间配置，而是生成 Claude Code 能直接消费的原生文件：

```text
CLAUDE.md
.claude/rules/*
.claude/commands/*
.claude/aicode/*
```

### 6.1.1 init 主流程

完整初始化流程：

```text
1. 读取当前项目环境。
2. 检测 AI 编程工具。
3. 检测必需插件和能力。
4. 处理缺失插件。
5. 扫描项目结构。
6. 识别代码规范。
7. 识别测试和验证方式。
8. 识别外部资源与 MCP 能力。
9. 接入 Superpowers。
10. 生成 Claude Code 文件。
11. 初始化 .ai 跨工具资产。
12. 输出初始化报告。
```

默认 profile：

```text
claude-superpowers
```

等价于：

```bash
aicode init --profile claude-superpowers
```

可选参数：

```bash
aicode init --install-missing
aicode init --no-install
aicode init --mode interactive
aicode init --mode daemon
```

### 6.1.2 Step 1: 读取当前项目环境

识别：

```text
项目根目录
Git 状态
是否已有 CLAUDE.md
是否已有 .claude/
是否已有 .ai/
是否已有 Superpowers 目录
是否已有其他 AI 工具配置
```

重点检查：

```text
是否在 Git 仓库内
当前工作区是否干净
是否已有用户自定义 CLAUDE.md
是否存在冲突文件
```

如果已有 `CLAUDE.md`，不能直接覆盖。

策略：

```text
生成合并建议
展示 diff
等待用户确认
保留用户已有内容
```

### 6.1.3 Step 2: 检测 AI 编程工具

第一阶段默认检测：

```text
Claude Code
```

后续扩展：

```text
Codex
Cursor
```

检测结果：

```text
installed
missing
version-mismatch
unsupported-version
```

如果 Claude Code 缺失：

```text
interactive mode:
提示安装。

daemon mode:
失败并输出安装报告。
```

### 6.1.4 Step 3: 检测必需插件和能力

默认 profile：

```text
claude-superpowers
```

必需能力：

```text
Claude Code 可用
aicode Claude Adapter 可用
Superpowers Provider 可用
```

推荐能力：

```text
Scenario Runner 可用
```

可选能力：

```text
Claude MCP MySQL Server
Claude MCP Redis Server
Claude MCP Log Server
```

检测内容：

```text
插件是否安装
版本是否满足
能力是否可用
是否能被 CLI 调用
MCP server 是否已配置
```

示例报告：

```text
Claude Code: installed
aicode Claude Adapter: installed
Superpowers Provider: missing
Scenario Runner: installed
Claude MySQL MCP: missing
Claude Redis MCP: installed
```

### 6.1.5 Step 4: 处理缺失插件

交互模式：

```text
Missing required plugins:
- superpowers-provider

Install now? [Y/n]
```

自动安装模式：

```bash
aicode init --install-missing
```

只检测模式：

```bash
aicode init --no-install
```

处理规则：

```text
必需插件失败 -> 停止 init。
推荐能力失败 -> 询问是否继续。
可选能力失败 -> 继续，并在报告中标记不可用。
```

init 可以检测和引导安装插件，但不应在用户无感知的情况下静默修改环境。

### 6.1.6 Step 5: 扫描项目结构

扫描：

```text
语言
框架
包管理器
主要目录
入口文件
模块边界
测试目录
配置目录
数据库 migration 目录
API / controller 路径
service / domain 路径
repository / dao 路径
```

输出：

```text
.claude/aicode/project-map.md
```

不生成 `project.yaml`。

### 6.1.7 Step 6: 识别代码规范

抽样分析：

```text
Controller 写法
Service 写法
Repository 写法
DTO / VO 命名
异常处理方式
日志方式
返回值包装
测试命名方式
Mock 使用习惯
格式化风格
```

生成：

```text
.claude/aicode/style.md
.claude/rules/code-style.md
```

初始标记：

```text
Status: inferred
Confidence: medium
```

如果项目样本不足：

```text
Status: inferred
Confidence: low
Needs calibration: true
```

后续通过：

```bash
aicode calibrate
```

让用户确认规则。

### 6.1.8 Step 7: 识别测试和验证方式

识别：

```text
是否有单元测试
是否有集成测试
是否有 E2E
是否有测试目录
是否有 package scripts / Maven goals / pytest 配置
是否有 Docker Compose
是否有测试数据库配置
```

生成：

```text
.claude/rules/testing.md
.claude/commands/aicode-verify.md
```

第一阶段不强制托管启动命令。

默认策略：

```text
用户手动启动项目。
Scenario Runner 调用已启动服务。
```

### 6.1.9 Step 8: 识别外部资源与 MCP 能力

扫描可能存在的资源：

```text
MySQL
Redis
MQ
ES
对象存储
第三方 API
日志系统
```

来源：

```text
配置文件
环境变量示例
docker-compose.yml
application.yml
.env.example
package scripts
README
```

如果发现 MySQL / Redis，不优先提示安装自定义 assertion 插件。

优先策略：

```text
检测 Claude Code / Codex 是否已有对应 MCP Server。
如果已配置，则 Scenario Runner 通过 MCP 读取资源。
如果未配置，则提示用户配置 MCP。
```

示例：

```text
Detected MySQL.

Available options:
1. Use existing Claude Code MySQL MCP server.
2. Configure a MySQL MCP server.
3. Skip MySQL assertions for now.
```

```text
Detected Redis.

Available options:
1. Use existing Claude Code Redis MCP server.
2. Configure a Redis MCP server.
3. Skip Redis assertions for now.
```

生成：

```text
.claude/rules/database.md
.ai/scenarios/README.md
```

资源接入架构：

```text
Scenario Runner
-> Assertion Engine
-> Resource Adapter
-> Claude / Codex MCP
-> MySQL / Redis / Logs / CI
```

职责边界：

```text
MCP Server:
负责连接和访问资源。

AICode Assertion Engine:
负责把 scenario 断言翻译为资源查询，并判断通过或失败。
```

安全默认值：

```text
默认只连接测试环境。
默认只读。
禁止生产库。
禁止执行 DDL。
禁止 dump 大量数据。
查询结果需要脱敏。
连接串需要用户确认。
```

可用命令：

```bash
aicode mcp doctor
aicode mcp setup mysql
aicode mcp setup redis
```

### 6.1.10 Step 9: 接入 Superpowers

检测：

```text
Superpowers 是否安装
Superpowers 目录是否存在
可用命令有哪些
是否支持 spec / plan
```

建立索引：

```text
.ai/spec-index.yaml
```

如果项目还没有 Superpowers spec：

```text
只建立 Provider 连接。
不强制生成 spec。
```

如果已有 spec：

```text
索引已有 spec。
映射到 aicode workflow。
```

重点：

```text
不复制 Superpowers 目录。
不接管 Superpowers 文件结构。
通过 Glue Mapping 映射到 AICode Loop 状态。
```

### 6.1.11 Step 10: 生成 Claude Code 文件

生成或更新：

```text
CLAUDE.md

.claude/rules/code-style.md
.claude/rules/testing.md
.claude/rules/api.md
.claude/rules/database.md
.claude/rules/safety.md

.claude/commands/aicode-spec.md
.claude/commands/aicode-plan.md
.claude/commands/aicode-verify.md
.claude/commands/aicode-review.md
.claude/commands/aicode-memory.md

.claude/aicode/project-map.md
.claude/aicode/style.md
.claude/aicode/workflow.md
.claude/aicode/memory.md
```

原则：

```text
CLAUDE.md 保持短。
详细规则放 .claude/rules/*。
扫描结果放 .claude/aicode/*。
工作流入口放 .claude/commands/*。
```

### 6.1.12 Step 11: 初始化 .ai 跨工具资产

生成：

```text
.ai/
  memory.md
  scenarios/
  fixtures/
  runs/
  spec-index.yaml
```

可选：

```text
.ai/schema_version.md
```

触发条件：

```text
发现 migration / schema / Flyway / Liquibase。
```

`.ai/memory.md` 初始内容：

```text
项目规则
历史坑
测试经验
禁止事项
```

初始化时可以为空模板。

如果项目有明显 API，可以生成示例 scenario 草案，但不能假装已验证通过。

### 6.1.13 Step 12: 输出初始化报告

报告包含：

```text
安装了哪些插件
缺失哪些可选能力
生成了哪些文件
识别出的项目技术栈
识别出的代码规范
识别出的测试方式
识别出的外部资源
MCP 配置状态
需要用户确认的规则
下一步建议
```

示例：

```text
Init completed.

Profile:
- claude-superpowers

Tools:
- Claude Code: installed
- Superpowers: installed

Generated:
- CLAUDE.md
- .claude/rules/*
- .claude/commands/*
- .claude/aicode/*
- .ai/memory.md
- .ai/scenarios/

Detected:
- Framework: Spring Boot
- Database: MySQL
- Cache: Redis
- Test: JUnit

MCP:
- Claude MySQL MCP: missing
- Claude Redis MCP: installed

Needs calibration:
- code style confidence: medium
- test style confidence: low

Next:
1. Review CLAUDE.md.
2. Run aicode calibrate.
3. Configure MySQL MCP if scenario needs database assertions.
4. Start your app manually.
5. Add or run first scenario.
```

### 6.2 init 不应该做

第一阶段不做：

```text
自动启动项目
连接生产数据库
强制生成大量 YAML
要求用户维护 Provider 配置
要求用户维护 Adapter 配置
强制将 Spec 放进 .ai
强制把所有测试写成 JUnit / pytest / Jest
```

### 6.3 代码规范推断

代码规范直接生成到工具原生文件中：

```text
.claude/aicode/style.md
```

初始状态必须标明：

```text
Status: inferred
Confidence: medium
```

通过人工确认或更多样本校准后：

```text
Status: confirmed
Confidence: high
```

### 6.4 Claude Code 初始化产物

```text
CLAUDE.md

.claude/
  skills/              ← install.py 写入（插件安装时）
    init.md
    calibrate.md
    spec.md
    plan.md
    verify.md
    review.md
    memory.md
    full.md
    dev.md
    test.md
    direct.md

  rules/               ← init 生成
    code-style.md
    testing.md
    safety.md

  aicode/              ← init + install.py 生成
    project-map.md
    style.md
    workflow.md
    plugin-root.txt    ← install.py 写入（引擎路径回退）
```

职责划分：

```text
CLAUDE.md:
每次会话都需要加载的最小核心共识。

.claude/rules/*:
模块化规则，按主题或路径范围拆分。

.claude/commands/*:
AI Coding Loop 的工作流入口。

.claude/aicode/*:
init 扫描生成的项目地图、风格摘要、工作流说明和 memory 投影。
```

### 6.5 CLAUDE.md 设计原则

CLAUDE.md 是 Claude Code 的核心项目记忆文件，会在会话开始时加载，并在上下文压缩后重新进入会话上下文。

但它不是强制执行层，而是高优先级上下文指令。它适合放长期稳定、每次会话都必须知道的信息。

CLAUDE.md 应该控制在较短长度，建议：

```text
目标：60-100 行
上限：200 行以内
```

过长的 CLAUDE.md 会带来：

```text
上下文占用过高
关键指令被稀释
规则遵循质量下降
Lost-in-the-Middle 风险上升
```

CLAUDE.md 应包含：

```text
项目一句话说明
技术栈
关键目录职责
必须遵守的硬规则
禁止行为
核心工作流入口
关键验证方式
细规则文件索引
```

CLAUDE.md 不应包含：

```text
完整目录树
大量代码风格细节
完整测试策略
长篇架构说明
历史问题全集
复杂流程文档
所有命令列表
```

### 6.6 三问框架

写入 CLAUDE.md 或 rules 时，使用三问框架筛选内容：

```text
WHY:
为什么这样做。记录架构决策背后的原因，帮助 AI 举一反三。

WHAT:
做什么、不做什么。记录不可越过的边界和禁止事项。

HOW:
如何一步步做。记录标准操作流程和验证方式。
```

示例：

```text
WHY:
项目选择 Fastify 而非 Express，因为 schema-based validation 与类型安全目标一致。

WHAT:
必须使用 pnpm，禁止使用 npm 或 yarn。

HOW:
数据库迁移必须执行 pnpm db:migrate，并在完成后运行相关 scenario。
```

### 6.7 .claude/rules 设计

当规则超过 CLAUDE.md 承载范围时，必须拆分到 `.claude/rules/`。

建议按主题拆分：

```text
.claude/rules/code-style.md
.claude/rules/testing.md
.claude/rules/api.md
.claude/rules/database.md
.claude/rules/safety.md
```

规则文件应该：

```text
短小
主题单一
可路径限定
尽量包含正例和反例
避免重复 CLAUDE.md 的内容
```

路径范围规则用于降低上下文负担。

示例：

```markdown
---
paths:
  - "src/api/**/*.ts"
  - "src/controllers/**/*.ts"
---

# API Rules

- API handler must validate input before calling service.
- API response must use the project standard response envelope.
- Do not access database directly from controller.
```

路径规则建议：

```text
API 规则只作用于 controller / route 文件。
数据库规则只作用于 repository / migration 文件。
测试规则只作用于 test / spec 文件。
前端规则只作用于 component / page 文件。
```

### 6.8 .claude/commands 设计

`.claude/commands/` 是 AI Coding Loop 的操作入口。

建议第一阶段生成：

```text
.claude/commands/aicode-spec.md
.claude/commands/aicode-plan.md
.claude/commands/aicode-verify.md
.claude/commands/aicode-review.md
.claude/commands/aicode-memory.md
```

命令职责：

```text
aicode-spec:
从 Prompt 或文档生成 Spec，并识别歧义。

aicode-plan:
基于 Spec 拆分 Plan / Task，声明修改边界和验证方式。

aicode-verify:
调用 Scenario Runner，执行真实流程验证。

aicode-review:
检查 diff 是否满足 Spec、是否越界、是否弱化质量。

aicode-memory:
把已验证的经验沉淀到 .ai/memory.md，并同步到工具记忆投影。
```

### 6.9 指令层与强制层分离

CLAUDE.md 和 `.claude/rules/*` 只能引导 Claude Code，不应该被当成强制执行机制。

系统必须分三层：

```text
Guidance Layer:
CLAUDE.md + .claude/rules，引导 AI 怎么做。

Workflow Layer:
.claude/commands/aicode-*.md，规定任务如何进入 Loop。

Enforcement Layer:
hooks / guard check / lint / format / scenario verify，真正检查是否违规。
```

例如：

```text
禁止删除测试:
写入 CLAUDE.md 和 safety rule，但最终必须由 aicode guard check 检查 diff。

必须符合代码风格:
写入 code-style rule，但最终必须由 format / lint / review / scenario verify 验证。

业务行为正确:
写入 Spec 和 Scenario，但最终必须由 Scenario Runner 的断言报告判定。
```

结论：

```text
短 CLAUDE.md
+ path-scoped rules
+ workflow commands
+ 自动校验闭环
= 更稳定的项目规范遵循能力
```

## 7. 跨工具资产目录

`.ai/` 不作为大而全配置中心，但需要保存跨工具资产。

建议：

```text
.ai/
  memory.md
  scenarios/
  fixtures/
  runs/
  spec-index.yaml
  schema_version.md
```

说明：

- `memory.md`：项目权威记忆。
- `scenarios/`：真实流程验证场景。
- `fixtures/`：场景测试数据，可选。
- `runs/`：每次 Loop 的运行记录，可选。
- `spec-index.yaml`：外部 Spec 索引，可选。
- `schema_version.md`：数据库结构变更记录，可选，涉及 DDL 时启用。

不建议第一阶段暴露：

```text
project.yaml
style.yaml
commands.yaml
providers.yaml
adapters.yaml
boundaries.yaml
```

这些属于内部能力或工具原生文件，不应让用户维护。

## 8. 开发入口设计

### 8.0 Calibration Workflow

`aicode init` 之后的第一步应该是 `aicode calibrate`。

初始化阶段生成的项目规范来自代码扫描和样本推断，不能直接视为最终规则。否则 AI 可能会稳定地遵守错误规范。

目标：

```text
把 init 阶段生成的 inferred 规则，确认或修正为 confirmed 规则。
```

命令：

```bash
aicode calibrate
```

输入：

```text
.claude/aicode/style.md
.claude/rules/*
CLAUDE.md 中的规则摘要
项目代码样本
测试代码样本
```

流程：

```text
1. 展示 init 推断出的代码风格。
2. 展示低置信度规则。
3. 展示推断依据和样本文件。
4. 让用户确认、修改或删除规则。
5. 标记规则状态为 confirmed / rejected / needs-review。
6. 更新 .claude/aicode/style.md。
7. 更新 .claude/rules/*。
8. 更新 CLAUDE.md 中的核心规则摘要。
9. 同步长期有效规则到 .ai/memory.md。
```

输出：

```text
.claude/aicode/style.md
.claude/rules/code-style.md
.claude/rules/testing.md
CLAUDE.md
.ai/memory.md
```

规则状态：

```text
inferred:
由 init 自动推断，尚未确认。

confirmed:
用户确认或高置信度校准后的稳定规则。

rejected:
用户明确否定的错误推断。

needs-review:
样本不足或存在冲突，需要后续确认。
```

示例：

```text
Rule:
Controller must return ApiResponse.

Status:
inferred

Evidence:
- src/main/java/**/UserController.java
- src/main/java/**/OrderController.java

Action:
[confirm] [edit] [reject]
```

`calibrate` 不应该做：

```text
不修改业务代码。
不生成 Spec。
不启动服务。
不执行复杂验证。
不覆盖用户已有规则。
```

完成后，项目状态从：

```text
Initialized
```

变成：

```text
Calibrated
```

之后才建议进入正式 AI Coding Loop。

### 8.1 Task Intake Workflow

`calibrate` 之后，进入每一次 AI Coding 任务前，必须先经过 Task Intake。

Task Intake 是路由器，不是执行器。

目标：

```text
识别用户输入形式
判断任务类型
判断复杂度和风险等级
决定走哪条 workflow
判断是否需要 Spec / Scenario / Human Review
```

Task Intake 不做：

```text
不写代码
不修改文件
不生成详细实现计划
不跑复杂验证
不读取全量项目
```

#### 8.1.1 Input Classification

用户输入可能是多种形式，必须先识别输入类型。

```text
plain_prompt:
几句话需求。

code_snippet:
用户贴了一段代码，希望修改、解释、补全或参考。

doc_path:
用户给了需求文档、PRD、Issue、设计文档路径。

doc_content:
用户直接贴了一段需求文档内容。

bug_report:
用户描述 bug、贴日志、贴异常表现。

test_failure:
用户贴测试失败结果或 CI 失败日志。

brainstorm_request:
用户想让 Superpowers 先做脑暴或方案探索。

direct_instruction:
用户明确说直接改、不要 spec、不要测试。

non_coding:
用户只是问概念、架构建议、代码解释，不要求修改。
```

#### 8.1.2 输入形式到 Workflow 的初步路由

```text
plain_prompt:
根据复杂度走 direct 或 spec_from_prompt。

code_snippet:
先判断代码片段是目标代码、参考代码还是错误代码。
如果能映射到项目文件，进入 direct 或 spec。
如果不能映射，先执行 file mapping。

doc_path:
读取文档，进入 spec_from_document。

doc_content:
当作需求文档，进入 spec_from_document。

bug_report:
进入 reproduce / RCA loop。

test_failure:
进入 test_failure RCA loop。

brainstorm_request:
进入 Superpowers brainstorm，不写代码。

direct_instruction:
执行风险门控后决定是否允许 direct。

non_coding:
不进入 AI Coding Loop，走 explanation / architecture-review / no-code。
```

#### 8.1.3 Task Classification

任务类型：

```text
feature:
新增功能或扩展能力。

bugfix:
修复错误行为。

refactor:
重构、抽取、结构优化。

test:
补测试、改测试、提升覆盖率。

doc:
文档、README、注释。

style:
格式、命名、文案、样式。

config:
配置、环境变量、CI。

migration:
数据库表结构、DDL、migration。

exploration:
脑暴、方案比较、架构讨论。
```

判断线索：

```text
新增、支持、实现 -> feature
报错、失败、不对、修复、bug -> bugfix
重构、优化结构、抽取、改造 -> refactor
补测试、覆盖率、测试用例 -> test
文档、README、注释 -> doc
格式、样式、命名、文案 -> style
配置、环境变量、CI -> config
表结构、字段、migration、DDL -> migration
脑暴、方案、设计、比较 -> exploration
```

#### 8.1.4 复杂度判断

复杂度分为：

```text
low
medium
high
```

low：

```text
单文件或少量文件
不涉及业务流程
不涉及数据库 / 缓存 / 消息
不涉及权限
不涉及公共接口契约
不需要复杂测试
```

medium：

```text
涉及多个文件
涉及接口参数或返回
涉及业务规则
需要新增 scenario 或测试
影响一个模块
```

high：

```text
涉及数据库 schema
涉及权限 / 支付 / 事务 / 并发
涉及多个模块
涉及公共 API 兼容性
涉及缓存一致性或消息队列
涉及线上 bug 或历史数据
```

#### 8.1.5 风险等级判断

风险等级：

```text
L1:
文档、注释、简单样式、非行为变更。

L2:
小 bug、小函数、小范围实现。

L3:
业务逻辑变更、接口行为变更、需要 scenario。

L4:
数据库、权限、支付、事务、并发、缓存一致性、消息队列。

L5:
架构迁移、生产配置、安全策略、不可逆数据变更。
```

高风险关键词：

```text
删除数据
修改生产配置
连接生产库
绕过权限
处理支付
修改认证授权
执行 DDL
改 CI/CD
批量重构
```

这些任务必须标记为 L4 或 L5。

#### 8.1.6 是否需要 Spec

规则：

```text
low + L1/L2:
通常不需要 Spec。

medium 或 L3:
需要轻量 Spec。

high 或 L4/L5:
必须 Spec。

输入是 PRD / issue / doc:
走 spec_from_document。

brainstorm_request:
先 brainstorm，不直接生成最终 Spec。
```

#### 8.1.7 是否需要 Scenario

规则：

```text
只改文档 / 样式:
不需要 Scenario。

只改内部纯函数:
Scenario 可选。

涉及接口行为:
需要 Scenario。

涉及数据库状态:
必须 Scenario。

涉及 Redis / MQ / 权限 / 事务:
必须 Scenario。

bugfix:
必须有 reproduction scenario 或失败用例。
```

#### 8.1.8 是否需要人工确认

规则：

```text
L1 / L2:
通常不需要。

L3:
Spec 后建议确认。

L4:
必须确认。

L5:
默认不自动执行，只生成方案。
```

#### 8.1.9 支持不完整输入

用户输入经常不完整，例如：

```text
把订单这个地方优化一下
这个接口有问题
照着这个代码改一下
需求在文档里
```

Task Intake 不能强行猜。

如果缺失关键信息，输出：

```text
Need Clarification: yes
```

最多提出 1-3 个问题：

```text
具体是哪个接口？
期望行为是什么？
当前错误表现是什么？
```

#### 8.1.10 用户意图优先级

Task Intake 必须识别用户明确意图：

```text
先别写代码
先帮我分析
先 brainstorm
直接改
只生成 spec
只看风险
```

用户意图优先于默认流程，但不能越过风险边界。

例如：

```text
用户说“直接改，不要测试”
但任务涉及订单、数据库或权限
则必须标记 Policy Conflict，并要求 Scenario 或人工确认。
```

#### 8.1.11 用户覆盖规则

用户可以覆盖系统建议，但必须受风险等级限制：

```text
L1 / L2:
允许用户覆盖为 direct。

L3:
用户确认后可以覆盖，但必须保留验证要求。

L4:
不能直接覆盖为 direct，必须至少经过 Spec / Plan / Scenario。

L5:
禁止自动执行，只能生成方案或等待人工审批。
```

#### 8.1.12 标准输出结构

Task Intake 输出必须短、结构化、可解释。

示例：

```yaml
inputType: doc_path
taskType: feature
complexity: high
riskLevel: L4
recommendedFlow: spec_from_document
needSpec: true
needScenario: true
needHumanReview: true
needClarification: true
questions:
  - 超时时间是多少？
  - 是否需要释放库存？
source:
  type: file_path
  value: docs/order-timeout.md
reason:
  - 输入是需求文档路径
  - 涉及订单状态和库存数据
  - 涉及数据库一致性
```

小改动示例：

```yaml
inputType: plain_prompt
taskType: style
complexity: low
riskLevel: L1
recommendedFlow: direct
needSpec: false
needScenario: false
needHumanReview: false
reason:
  - 仅修改按钮文案
  - 不涉及业务逻辑
```

脑暴示例：

```yaml
inputType: brainstorm_request
taskType: exploration
complexity: unknown
riskLevel: unknown
recommendedFlow: superpowers_brainstorm
needSpec: false
needScenario: false
needHumanReview: true
reason:
  - 用户请求方案探索
  - 当前阶段不应写代码
  - Brainstorm 后再决定是否进入 Spec
```

代码片段示例：

```yaml
inputType: code_snippet
taskType: feature
complexity: medium
riskLevel: L3
recommendedFlow: resolve_file_mapping_then_spec
needFileMapping: true
needSpec: true
needScenario: maybe
reason:
  - 用户提供代码片段，但未说明对应项目文件
  - 涉及行为变化
```

#### 8.1.13 性能要求

Task Intake 必须轻量。

建议：

```text
正常 5-10 秒内完成。
不读全量项目。
不做深度代码分析。
只读取项目地图、CLAUDE.md 摘要、相关输入内容。
```

如果需要深度分析，应交给后续 Plan 阶段。

### 8.2 Direct Prompt Mode

适合：

- 小改动
- 简单 bug
- 文案修改
- 样式调整
- 局部测试补充

流程：

```text
用户直接输入 Prompt
-> AI 读取 Claude Code 原生规则
-> Context Router 注入最小上下文
-> 快速影响范围判断
-> 最小修改
-> 轻量验证
-> 必要时更新 memory
```

### 8.3 Spec From Prompt Mode

适合：

- 中复杂功能
- 多文件修改
- 涉及数据状态或业务流程
- 需要明确验收标准

流程：

```text
用户输入需求
-> Superpowers 生成 Spec
-> Superpowers 或内置 Plan 生成计划
-> Context Router 注入相关上下文
-> AI 按 Plan 执行代码修改
-> Scenario Runner 验证真实流程
-> 失败进入 Debug / Repair Loop
-> Review
-> Memory Update
```

### 8.4 Spec From Document Mode

适合：

- PRD
- 接口文档
- 设计文档
- Issue
- 缺陷报告
- 会议纪要

流程：

```text
导入文档
-> 提取需求
-> 识别歧义
-> 生成 Spec Draft
-> 生成验收标准
-> 生成 Scenario 草案
-> 用户确认或进入实现
```

### 8.5 Spec Generation Workflow

当 Task Intake 输出以下结果时，进入 Spec Generation Workflow：

```text
recommendedFlow: spec_from_prompt
recommendedFlow: spec_from_document
```

这一步的目标不是写代码，而是让 Superpowers 根据用户输入、需求文档和项目上下文生成高质量 Spec。

核心流程：

```text
Input from Task Intake
-> 判断是否需要 Brainstorm
-> 可选 Superpowers Brainstorm
-> 构造 Spec Context Packet
-> Superpowers 生成 Spec
-> Spec Quality Gate
-> 用户确认 / 修改
-> 进入 Plan
```

#### 8.5.1 什么时候直接生成 Spec

以下情况可以直接生成 Spec：

```text
需求明确
已有需求文档
已有 issue / PRD
用户已经给出验收标准
改动范围比较清楚
风险等级 L2 / L3
```

流程：

```text
用户输入 / 文档
-> Superpowers Spec
-> AICode Spec Quality Gate
-> 用户确认
```

#### 8.5.2 什么时候先 Brainstorm

以下情况建议先让 Superpowers Brainstorm：

```text
用户只是一个想法
需求很模糊
有多个实现方向
涉及架构选择
涉及业务流程设计
涉及数据库 / 缓存 / 消息等多组件
风险等级 L4+
用户明确说“先想想方案”
```

Brainstorm 流程：

```text
用户输入
-> Superpowers Brainstorm
-> 输出方案、边界、风险、问题
-> 用户选择方向
-> Superpowers Spec
```

Brainstorm 的目标：

```text
暴露业务边界
比较实现方案
识别风险点
识别缺失信息
提出测试思路
明确不做范围
判断是否适合进入 Spec
```

Brainstorm 不应该输出长篇自由文本，建议固定结构：

```text
方案选项
推荐方案
不推荐方案
业务边界
关键风险
需要澄清的问题
测试思路
是否适合进入 Spec
```

如果 Brainstorm 后仍有关键问题未解决：

```text
不要生成最终 Spec。
先询问用户。
```

#### 8.5.3 Spec Context Packet

不要直接把用户输入丢给 Superpowers。

在调用 Superpowers 前，必须构造 Spec Context Packet，提供足够但不过量的上下文。

Context Packet 应包含：

```text
用户原始需求
Task Intake Result
项目一句话说明
相关模块摘要
相关业务术语
相关历史 Memory
现有接口或功能摘要
影响域判断
风险等级
Spec 输出格式要求
```

不应该包含：

```text
全量代码
完整历史 runs
无关 Memory
大量日志
完整目录树
```

示例：

```yaml
userInput: "给订单增加超时自动关闭"
taskIntake:
  taskType: feature
  complexity: high
  riskLevel: L4
  recommendedFlow: spec_from_prompt
projectContext:
  summary: "电商订单服务"
  relevantModules:
    - order
    - inventory
    - payment
domainTerms:
  - PENDING_PAYMENT
  - CLOSED
  - inventory release
memory:
  - "订单状态变更必须写 outbox event"
  - "库存回滚必须通过真实 DB scenario 验证"
impactDomains:
  api: false
  database: true
  cache: false
  messageQueue: true
  permission: false
specRequirements:
  mustInclude:
    - goals
    - nonGoals
    - businessRules
    - acceptanceCriteria
    - testScenarios
    - risks
    - openQuestions
```

#### 8.5.4 高质量 Spec 标准

Spec 不固定大而全，但必须满足动态质量标准。

必填：

```text
目标
非目标
用户场景
业务规则
验收标准
测试场景
修改边界
风险等级
待确认问题
```

按需：

```text
接口变化
数据变化
缓存变化
消息变化
权限规则
配置变化
迁移变化
兼容性
性能影响
安全影响
外部服务影响
```

如果项目没有 Redis，不生成缓存章节。

如果项目没有 MQ，不生成消息章节。

如果任务不涉及权限，不生成权限章节。

#### 8.5.5 Spec Quality Gate

Superpowers 生成 Spec 后，必须经过 AICode Spec Quality Gate。

检查项：

```text
是否有明确目标。
是否有非目标，防止范围膨胀。
是否有验收标准。
验收标准是否可测试。
是否有异常场景。
是否有修改边界。
是否标出待确认问题。
是否识别影响域。
是否能生成 Scenario。
是否存在模糊词。
```

模糊词包括：

```text
优化
尽量
适当
快速
友好
稳定
支持一下
处理一下
```

处理规则：

```text
能转成明确标准 -> 自动改写。
不能明确 -> 加入 openQuestions。
影响核心行为 -> 阻止进入 Plan，要求用户确认。
```

#### 8.5.6 用户确认机制

Spec 生成后提供操作：

```text
Approve
Edit
Ask Clarification
Regenerate
Cancel
```

确认规则：

```text
L1 / L2:
可以跳过确认。

L3:
建议确认。

L4:
必须确认。

L5:
只生成方案，不自动执行。
```

只有通过 Spec Quality Gate 并满足确认规则后，才能进入 Plan。

#### 8.5.7 关键结论

高质量 Spec 不是靠 Superpowers 单独完成的，而是靠：

```text
Task Intake
+ Spec Context Packet
+ 可选 Brainstorm
+ Spec Quality Gate
+ 用户确认
```

所以本系统不是简单调用 Superpowers 生成 Spec，而是在 Superpowers 前后增加上下文控制和质量门禁。

### 8.6 Plan Generation Workflow

当 Spec 通过 Spec Quality Gate 并完成必要确认后，进入 Plan Generation Workflow。

这一步的目标不是写代码，而是把 Spec 转换成 AI 可以稳定执行的执行合约。

核心问题：

```text
普通 Plan 只是 TODO 列表，AI 很容易不按计划走。
本系统中的 Plan 必须是 Execution Contract。
```

核心流程：

```text
Confirmed Spec
-> Superpowers 或内置 Plan Provider 生成 Draft Plan
-> AICode Plan Quality Gate
-> 用户确认或修改
-> Plan Lock
-> 进入 Implementation Loop
```

#### 8.6.1 Plan as Execution Contract

Plan 不应该只是：

```text
1. 修改接口
2. 修改 service
3. 添加测试
```

Plan 必须包含：

```text
Task ID
目标
允许修改文件
禁止修改文件
输入上下文
具体改动
验收标准
验证方式
完成条件
不允许行为
```

示例：

```yaml
taskId: T1
title: Add status filter to user list API
goal: Accept optional status filter without changing pagination behavior
allowedFiles:
  - src/api/user.controller.ts
  - src/service/user.service.ts
forbiddenFiles:
  - src/db/migrations/**
  - src/auth/**
mustFollow:
  - Use existing ApiResponse wrapper
  - Do not introduce new DTO style
  - Keep existing pagination behavior unchanged
acceptance:
  - status query parameter filters users
  - missing status keeps existing behavior
verification:
  - scenario: user-list-filter-by-status
doneWhen:
  - code changed only in allowed files
  - scenario passes
  - no unrelated formatting changes
```

#### 8.6.2 绑定 Spec、Acceptance 和 Scenario

每个 Task 必须绑定：

```text
Spec Requirement ID
Acceptance Criteria ID
Scenario ID
```

示例：

```yaml
links:
  spec:
    - REQ-USER-STATUS-FILTER
  acceptance:
    - AC-001
    - AC-002
  scenarios:
    - user-list-filter-by-status
```

目的：

```text
防止 AI 忘记为什么修改。
让 Review 可以检查每个 Task 是否满足验收标准。
让 Verify 可以知道应该跑哪些 Scenario。
```

#### 8.6.3 控制 Task 粒度

任务太大，AI 容易自由发挥。

建议每个 Task 控制在：

```text
1-3 个文件
1 个明确目标
1 个验证方式
10-20 分钟内可完成
```

如果任务涉及：

```text
接口 + DB + Redis + 权限 + 测试
```

必须拆分。

错误示例：

```text
实现订单超时关闭功能
```

正确拆分：

```text
T1: 增加订单超时查询逻辑
T2: 增加状态变更业务逻辑
T3: 增加库存释放逻辑
T4: 增加 outbox 事件
T5: 增加 scenario 验证
```

#### 8.6.4 Plan Lock

Plan 必须有状态：

```text
draft
approved
executing
completed
```

执行规则：

```text
AI 只能执行 approved plan。
AI 不能私自新增任务。
AI 不能私自扩大任务范围。
AI 不能私自修改验收标准。
```

如果执行中发现 Plan 不足，必须进入 Plan Change Request。

#### 8.6.5 Plan Change Request

执行过程中如果 AI 发现计划不完整，不允许直接改。

必须输出：

```text
Plan Change Request
```

内容：

```text
发现的问题
为什么原 Plan 不够
需要新增或修改哪个 Task
是否影响 Spec
是否影响 Scenario
是否需要用户确认
```

规则：

```text
L1 / L2:
可自动接受小范围 Plan Change。

L3:
需要记录并建议确认。

L4 / L5:
必须用户确认。
```

#### 8.6.6 Style Contract

Plan 阶段必须把项目风格约束带入每个 Task。

每个 Task 应引用：

```text
.claude/aicode/style.md
.claude/rules/code-style.md
相关 good examples
forbidden patterns
```

示例：

```yaml
styleContract:
  source:
    - .claude/aicode/style.md
    - .claude/rules/code-style.md
  must:
    - Follow existing service method naming
    - Use existing error handling pattern
    - Keep controller thin
  forbidden:
    - Do not introduce new response wrapper
    - Do not create generic util unless reused twice
    - Do not add broad abstraction
```

重点防止：

```text
过度设计
新建不必要抽象
引入项目中不存在的代码风格
写出与现有项目不一致的结构
```

#### 8.6.7 Diff Budget

为了防止 AI 写得过多、过散、过度重构，Plan 必须设置 diff budget。

示例：

```yaml
diffBudget:
  maxFiles: 3
  maxLinesChanged: 120
  allowNewAbstractions: false
```

规则：

```text
默认最小改动。
禁止无关格式化。
禁止大范围重构。
禁止新建通用框架。
禁止重复造轮子。
超过 diff budget 必须解释原因。
```

#### 8.6.8 Reuse / Duplication Check

为减少重复代码，Plan 阶段必须要求执行前查找已有实现。

示例：

```yaml
reuseCheck:
  required: true
  searchFor:
    - existing validators
    - existing response wrappers
    - existing repository methods
    - existing error handling
```

执行前必须回答：

```text
项目里是否已有类似实现？
是否可以复用已有函数？
是否已有相同校验逻辑？
是否已有相同错误处理模式？
```

如果已有可复用实现，不允许重新造一套。

#### 8.6.9 Implementation Checklist

每个 Task 执行前，AI 必须输出简短 checklist。

示例：

```text
I will:
- Modify only user.controller.ts and user.service.ts.
- Reuse existing ApiResponse.
- Preserve pagination behavior.
- Add status filter only when provided.
- Run scenario user-list-filter-by-status.
```

目的：

```text
让 AI 在动手前自我约束。
让用户能及时发现偏差。
为后续 Plan Compliance Review 提供依据。
```

#### 8.6.10 Plan Quality Gate

Plan 生成后必须检查：

```text
是否覆盖 Spec 中所有验收标准。
是否每个 Task 都有明确目标。
是否每个 Task 都有 allowedFiles / forbiddenFiles。
是否每个 Task 都绑定 Scenario 或验证方式。
是否每个 Task 都引用 Style Contract。
是否设置 diff budget。
是否包含 reuseCheck。
是否存在过大任务。
是否存在无法验证的 Task。
是否存在范围膨胀。
```

不通过时：

```text
返回 Plan Provider 修正。
或要求用户确认风险。
```

#### 8.6.11 Plan Compliance Review

实现完成后，不能只看测试是否通过，还要检查是否遵守 Plan。

检查项：

```text
是否按 Task 执行。
是否修改了 allowedFiles 之外的文件。
是否引入未计划抽象。
是否重复已有逻辑。
是否违反 Style Contract。
是否超过 diff budget。
是否满足 acceptance。
是否 Scenario 通过。
是否存在无关格式化或重构。
```

如果不符合：

```text
进入 Correction Loop。
```

#### 8.6.12 Plan 输出结构

推荐结构：

```yaml
planId: user-status-filter
status: approved
riskLevel: L3

globalConstraints:
  style:
    - Follow .claude/aicode/style.md
    - Keep controller thin
    - Reuse existing ApiResponse
  diffBudget:
    maxFiles: 4
    maxLinesChanged: 180
    allowNewAbstractions: false
  forbidden:
    - No unrelated refactor
    - No new response wrapper
    - No broad formatting changes

tasks:
  - id: T1
    title: Add status query param to API layer
    goal: Accept optional status filter without changing pagination behavior
    allowedFiles:
      - src/api/user.controller.ts
    forbiddenFiles:
      - src/db/**
      - src/auth/**
    reuseCheck:
      required: true
      searchFor:
        - existing query parameter parsing
        - existing validation pattern
    implementation:
      - Add optional status parameter using existing validation style
      - Pass status to service only when present
    acceptance:
      - AC-001
    scenarios:
      - user-list-filter-by-status
    doneWhen:
      - Only allowed files changed
      - Existing pagination still works
      - Scenario passes
```

#### 8.6.13 关键结论

Plan 这一步要从：

```text
计划文档
```

升级为：

```text
执行合约
+ 风格约束
+ diff 预算
+ 验收绑定
+ 复用检查
+ 变更控制
+ 合规 Review
```

这样才能减少：

```text
AI 不按计划走
代码飘
代码不精简
风格不一致
重复代码
错误实现
无关修改
```

### 8.7 Implementation Workflow

当 Plan 进入 `approved` 状态后，才允许进入 Implementation Workflow。

这一步是具体代码执行阶段，但不是让 AI 自由写代码，而是在 approved plan、style contract、diff budget、reuse check、guard 和 incremental verification 的约束下逐 Task 执行。

核心目标：

```text
严格按照 Plan 执行。
严格按照 init / calibrate 确认过的项目规范执行。
生成简洁、优雅、低重复、低错误的代码。
禁止越界修改和投机式修复。
```

#### 8.7.1 Implementation 执行原则

硬规则：

```text
No task without approved plan.
No code change outside allowed files.
No new abstraction without explicit plan.
No dependency without approval.
No test weakening.
No scenario weakening.
No full-context loading.
No plan change without request.
No final success without verification.
```

一次只执行一个 Task。

每个 Task 状态：

```text
pending
in_progress
implemented
verified
blocked
requires_plan_change
```

#### 8.7.2 Task Start Gate

每个 Task 开始前，AI 必须重新确认执行边界。

必须确认：

```text
当前 Task ID
对应 Spec / Acceptance
允许修改文件
禁止修改文件
Style Contract
Diff Budget
Reuse Check
验证方式
```

示例：

```text
Executing Task: T2
Goal: Add status filter in service layer

Allowed Files:
- src/service/user.service.ts

Forbidden:
- src/db/**
- src/auth/**

I will:
- Reuse existing repository filter pattern.
- Preserve pagination behavior.
- Avoid new abstraction.
- Run scenario user-list-filter-by-status.
```

没有通过 Task Start Gate，不允许修改代码。

#### 8.7.3 逐 Task 执行

AI 不能一次性执行多个任务。

流程：

```text
1. 进入 Task Start Gate。
2. 读取当前 Task 必需上下文。
3. 执行最小修改。
4. 执行 Task 级检查。
5. 记录 Task Execution Log。
6. 进入下一个 Task。
```

规则：

```text
一个 Task 完成后必须检查。
检查通过后才进入下一个 Task。
失败时进入 Correction Loop 或 Plan Change Request。
```

#### 8.7.4 Implementation Context Routing

Implementation 阶段必须使用 Context Router，避免上下文爆炸。

每个 Task 只加载：

```text
当前 Task
相关 Spec 片段
相关 Style Rule
2-3 个相关文件
相关 Memory
相关 Scenario
```

只有真正要修改的文件才读取完整内容。

禁止：

```text
加载完整 Spec 全文
加载完整项目
加载所有 Memory
加载所有历史 runs
加载无关日志
```

#### 8.7.5 Reuse Check

执行前必须查找已有实现，防止重复代码。

必须检查：

```text
是否已有类似 service 方法
是否已有相同 validator
是否已有 response wrapper
是否已有错误处理模式
是否已有 repository 查询方法
是否已有测试 helper
```

规则：

```text
已有可复用实现 -> 优先复用。
不复用 -> 必须说明原因。
不允许重新造一套项目已有模式。
```

#### 8.7.6 Style Contract Enforcement

Implementation 阶段必须遵守 init / calibrate 后确认的规则。

规则来源：

```text
CLAUDE.md
.claude/rules/code-style.md
.claude/rules/testing.md
.claude/aicode/style.md
.ai/memory.md
```

但不能全部塞进上下文，必须由 Context Router 召回相关部分。

检查点：

```text
命名是否符合项目习惯
异常处理是否一致
日志风格是否一致
返回结构是否一致
Controller 是否保持 thin
Service 是否承载业务逻辑
Repository 是否只做数据访问
测试命名是否一致
```

#### 8.7.7 Diff Budget Enforcement

AI 必须遵守 Plan 中的 diff budget。

检查：

```text
maxFiles
maxLinesChanged
allowNewAbstractions
allowNewDependencies
```

默认规则：

```text
小任务不允许新增依赖。
不允许新建通用工具类。
不允许大规模重构。
不允许格式化无关文件。
```

超过 diff budget 时：

```text
暂停执行。
说明原因。
发起 Plan Change Request。
```

#### 8.7.8 Incremental Verification

不要等所有 Task 写完才验证。

每个 Task 后做轻量检查：

```text
类型检查
编译
lint
局部 scenario
相关接口 smoke
```

推荐：

```text
Task 级:
quick check

Feature 级:
scenario verify

最终:
review + guard
```

#### 8.7.9 Plan Change Request

执行中发现以下情况，不能私自继续：

```text
Plan 少了文件
Spec 不完整
需要改数据库
需要改权限
需要新增接口
需要新增依赖
需要扩大修改范围
```

必须进入 Plan Change Request。

内容：

```text
发现什么问题
为什么原计划不够
建议改什么
风险是否提升
是否影响 Spec
是否影响 Scenario
是否需要用户确认
```

#### 8.7.10 Anti-Cheating During Implementation

Implementation 阶段必须禁止：

```text
删除测试
弱化断言
跳过测试
吞异常
硬编码结果
mock 掉核心逻辑
绕过权限
改 CI 门禁
改 scenario 让错误代码通过
```

如果 AI 修改了测试或 scenario：

```text
必须解释为什么。
必须证明不是为了迎合错误实现。
必须通过 Review 和 Guard。
```

#### 8.7.11 Code Quality Gate

代码写完后，不只看能不能跑，还要检查代码质量。

检查项：

```text
是否简洁
是否复用已有模式
是否没有重复逻辑
是否没有无用抽象
是否没有未使用代码
是否没有过度封装
是否没有引入新依赖
是否符合项目分层
是否保持可读性
```

可设计为：

```text
Elegance Review
```

检查原则：

```text
少即是多。
贴合项目风格。
没有过度设计。
没有重复。
命名清晰。
边界清楚。
错误处理一致。
```

#### 8.7.12 Task Execution Log

每个 Task 完成后必须记录：

```text
Task ID
改了哪些文件
为什么改
是否超出 Plan
跑了什么检查
结果如何
是否有 Plan Change
```

可以写入：

```text
.ai/runs/{run-id}.md
```

或作为本地临时 run record。

#### 8.7.13 Task 输出结构

每个 Task 完成后输出：

```yaml
taskId: T2
status: implemented
changedFiles:
  - src/service/user.service.ts
planCompliance:
  allowedFilesOnly: true
  diffBudgetExceeded: false
  styleContractFollowed: true
  reusedExistingPatterns: true
verification:
  quickCheck: passed
  scenario: pending
issues:
  - none
next:
  - proceed_to_T3
```

#### 8.7.14 关于准确率目标

不建议承诺“一次生成代码准确率 98%”。

更合理的目标是：

```text
在 Spec 已确认、Plan 已锁定、Context 已路由、Scenario 可验证、Guard 生效的条件下，提高最终任务闭环成功率。
```

推荐指标：

```text
Task plan compliance rate
Scenario pass rate
Correction loop count
Manual review change rate
Style violation count
Out-of-scope diff rate
Duplicate code finding rate
```

#### 8.7.15 关键结论

Implementation 不是：

```text
AI 根据计划自由写代码
```

而是：

```text
AI 在 approved plan、style contract、diff budget、reuse check、guard、incremental verification 的约束下逐 Task 执行。
```

这样才能减少：

```text
不按计划
代码飘
重复代码
过度设计
风格不一致
错误实现
越界修改
测试被弱化
```

## 9. Loop Engineering 设计

### 9.1 Requirement Loop

目标：把模糊需求变成可执行、可验证的 Spec。

步骤：

```text
1. 提取目标和非目标。
2. 提取业务规则。
3. 提取异常场景。
4. 判断影响域。
5. 生成验收标准。
6. 生成 Scenario 草案。
7. 标记歧义和待确认问题。
```

### 9.2 Planning Loop

目标：让 AI 编码前知道改什么、不改什么、怎么验证。

步骤：

```text
1. 读取 Spec 摘要。
2. Context Router 召回相关模块和 Memory。
3. 分析影响模块。
4. 映射相关文件和接口。
5. 声明修改边界。
6. 拆分任务。
7. 把任务绑定到验收标准。
8. 选择验证场景。
```

### 9.3 Implementation Loop

目标：按计划最小范围修改代码。

规则：

```text
只修改计划内文件。
避免无关重构。
避免大规模格式化。
遵循项目风格。
每个阶段保持 diff 可解释。
每次迭代前或提交前检查上游变化。
```

### 9.4 Verification Loop

目标：通过真实流程验证代码行为。

步骤：

```text
1. 执行环境健康检查 Sanity Check。
2. 确认服务已启动或启动测试环境。
3. 准备 fixture。
4. 调用接口或执行业务入口。
5. 验证响应。
6. 验证 MySQL / Redis / MQ / 日志状态。
7. 输出验证报告。
```

Sanity Check 必须先于业务验证执行。

```text
如果 Redis 未启动、数据库连接失败、端口不可用、Node/JDK/Maven 环境异常，则判定为环境故障。
环境故障不能进入代码修复 Loop，必须暂停并提示人工处理。
```

### 9.5 Debug / Repair Loop

目标：失败时先复现和根因分析，再最小修复。

步骤：

```text
1. 复现失败。
2. 收集请求、响应、日志、数据库、Redis、消息状态。
3. 先区分环境故障、测试数据故障、代码逻辑故障。
4. 定位失败点。
5. 分析根因。
6. 设计最小修复。
7. 执行修复。
8. 回归验证。
```

### 9.6 Review Loop

目标：防止遗漏、越界、质量下降。

检查：

```text
是否满足 Spec。
是否覆盖验收标准。
是否存在越界修改。
是否破坏项目风格。
是否新增安全风险。
是否弱化测试或验证。
是否需要更新 Memory。
是否生成必要 rollback plan。
```

### 9.7 Memory Loop

目标：将可复用经验沉淀。

写入：

```text
项目规则
历史坑
模块边界
测试经验
失败根因
禁止事项
```

不写入：

```text
一次性任务细节
未验证猜测
大量日志
敏感信息
过期方案
```

## 10. Context Router

Context Explosion 是系统最大的隐形风险之一。

不能在每次任务开始时一次性加载：

```text
CLAUDE.md
.ai/memory.md
完整 Spec
完整 Plan
大量源码
完整 Scenario 报告
历史 runs
```

否则会造成：

```text
Token 成本过高
Lost-in-the-Middle
AI 忘记关键约束
响应变慢
错误引用旧上下文
```

### 10.1 渐进式披露

系统必须使用 Progressive Disclosure：

```text
启动阶段:
只注入项目地图、模块职责、核心规则、当前任务入口。

Planning 阶段:
加载相关 Spec 摘要、影响模块、相关 Memory。

Implementation 阶段:
只读取需要修改的文件完整内容。

Verification 阶段:
加载 Scenario、失败摘要、关键日志。

Debug 阶段:
按根因假设动态拉取更多代码、日志、数据。
```

### 10.2 上下文路由规则

Context Router 负责：

```text
选择当前任务相关的 Memory。
选择相关源码文件。
选择相关 Spec 片段。
选择相关 Scenario。
压缩历史运行记录。
避免重复注入大文件。
```

推荐策略：

```text
默认只注入项目地图。
召回 2-3 个最相关模块。
完整代码只在需要修改时读取。
历史 Memory 只召回与当前模块相关的条目。
Scenario 报告只注入失败摘要和关键断言。
```

## 11. Spec 设计

### 11.1 核心字段

```text
目标
非目标
业务规则
验收标准
测试场景
修改边界
风险等级
```

### 11.2 按需字段

```text
接口变化
数据变化
缓存变化
消息变化
权限规则
配置变化
迁移变化
性能影响
安全影响
兼容性影响
外部服务影响
```

如果项目没有 Redis，不生成缓存章节。

如果项目没有 MQ，不生成消息章节。

如果任务不涉及权限，不生成权限章节。

### 11.3 外部 Spec 兼容

如果使用 Superpowers：

```text
Spec 保留在 Superpowers 原目录。
.ai/spec-index.yaml 只记录索引。
Loop Engine 通过 Superpowers Provider 读取 Spec。
Claude Code Adapter 获得必要上下文。
```

spec-kit、OpenSDD 后续按同样模型接入。

## 12. Skill System

### 12.1 Skill 分类

```text
Project Skills
项目结构、业务术语、模块边界。

Language Skills
Java、TypeScript、Python、Go 等语言实践。

Framework Skills
Spring Boot、React、FastAPI、NestJS 等框架实践。

Workflow Skills
Spec、Plan、Implement、Debug、Review、Memory。

Testing Skills
Scenario、数据断言、回归测试、覆盖率。

Safety Skills
边界控制、防投机、安全限制。

Resource Skills
MySQL、Redis、MQ、日志、CI、Issue 系统。
```

### 12.2 Skill 调度

```text
小改动:
Project + Style + Safety

复杂功能:
Project + Spec + Plan + Framework + Scenario + Review

Bug 修复:
Project + Debug + Root Cause + Regression + Safety

测试补充:
Project + Scenario + Data Assertion + Coverage

重构:
Project + Architecture + Safe Refactor + Verification
```

### 12.3 Provider Glue Mapping

外部 Provider 通常不是为本系统的 Loop Engine 设计的，会存在阻抗失配。

例如：

```text
Superpowers 的 Skill 多是 Markdown Prompt。
Loop Engine 需要的是结构化状态、任务、输入、输出和退出条件。
```

所以外部 Provider 接入必须提供 Glue Mapping：

```text
外部命令 / Skill
-> 映射到本系统的 Loop State
-> 映射输入字段
-> 映射输出字段
-> 映射失败状态
-> 映射人工确认点
```

第一阶段策略：

```text
深度兼容 Superpowers。
spec-kit、OpenSDD 只保留 Provider 接口和实验性接入。
```

## 13. Scenario Runner

### 13.1 目标

Scenario Runner 用于替代人工流程测试：

```text
手动调用接口
手动查数据库
手动查 Redis
手动看日志
手动判断结果
```

变成：

```text
可重复执行的 scenario
```

### 13.2 第一阶段策略

第一阶段建议：

```text
用户手动启动项目
Scenario Runner 连接已启动服务
```

后续支持：

```text
自动启动服务
Docker Compose
Testcontainers
临时测试环境
CI 环境
```

### 13.3 Scenario 示例

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

### 13.4 Data Assertion

支持：

```text
HTTP response
MySQL row exists / equals / count
Redis key exists / absent / value
MQ event exists
Outbox event exists
Log contains
File generated
External mock called
```

## 14. Resource Access 与 MCP

MCP 可以作为资源访问协议之一，但不是记忆存储，也不是最终验收裁判。

适合通过 MCP 接入：

```text
MySQL
Redis
日志系统
Issue 系统
CI 报告
文档系统
代码索引
```

用途：

```text
读取 schema
查询测试数据
辅助 fixture 准备
收集失败上下文
辅助根因分析
提供 AI 可读资源
```

边界：

```text
MCP 查询结果不能单独代表测试通过。
最终通过由 Scenario Runner 的断言报告决定。
```

### 14.1 Schema / DDL 变更

数据库结构变更具有不可逆风险，不能和普通业务代码修改混在同一个 Loop 中盲目执行。

一旦检测到：

```text
schema.sql
migration/*.sql
Flyway / Liquibase migration
ALTER TABLE
CREATE INDEX
DROP COLUMN
```

必须拆出独立的数据迁移子任务：

```text
1. 生成 migration plan。
2. 先执行 migration 验证。
3. 再执行业务代码修改。
4. Scenario Runner 验证新旧数据状态。
5. 记录 schema version。
```

记录：

```text
.ai/schema_version.md
```

内容：

```text
迁移 ID
影响表
执行时间
回滚方式
验证场景
```

## 15. Memory System

### 15.1 项目权威记忆

`.ai/memory.md` 是跨工具项目记忆。

内容：

```text
代码风格规则
历史坑
模块边界
测试经验
架构决策
禁止事项
常用验证方式
```

### 15.2 工具记忆投影

Claude Code 和 Codex 自带记忆系统可以利用，但不是唯一源。

关系：

```text
.ai/memory.md 是权威源
Claude/Codex memory 是投影和缓存
```

同步方向：

```text
.ai/memory.md
-> CLAUDE.md / .claude/aicode/memory.md
-> .codex/aicode/memory.md
-> .cursor/rules/aicode-memory.md
```

### 15.3 Session Memory

每次任务中的临时信息保存在运行记录中：

```text
用户需求
关联 Spec
修改范围
验证场景
失败原因
修复过程
最终结果
Memory 候选
```

有价值的内容再沉淀到 `.ai/memory.md`。

## 16. Guard System

### 16.1 修改边界

AI 修改前必须声明：

```text
计划修改哪些文件
不修改哪些文件
为什么需要修改
如何验证
```

### 16.2 风险分级

```text
Level 1:
文档、注释、小样式、小测试。

Level 2:
小 bug、小函数、小范围实现。

Level 3:
业务逻辑变更，需要 Spec 和 Scenario。

Level 4:
数据库、权限、支付、事务、并发，需要强验证。

Level 5:
架构迁移、生产配置、安全策略，默认禁止自动落地。
```

### 16.3 Anti-Cheating

禁止：

```text
删除测试
删除断言
新增 skip/ignore/only
降低覆盖率阈值
Mock 掉核心业务逻辑
吞异常
硬编码测试结果
绕开权限校验
修改 CI 门禁来通过
```

### 16.4 Reversibility Check

每次高风险提交前必须生成回滚方案。

输出：

```text
rollback_plan.md
```

内容：

```text
关联 commit
回滚命令
数据库回滚策略
配置回滚策略
影响范围
回滚后验证 Scenario
```

如果涉及 DDL，必须明确：

```text
是否可逆
是否需要备份
是否需要手工迁移
是否禁止自动回滚
```

## 17. Git Worktree 与上游同步

### 17.1 Worktree 隔离

每个中高风险任务建议使用独立分支或 worktree：

```text
避免污染主工作区
便于回滚和 Review
便于记录任务边界
```

### 17.2 Upstream Sync

长周期任务必须处理上游变化。

Implementation Loop 每次迭代开始前，或提交前，必须检查上游变化：

```text
git fetch origin
git merge origin/main
```

策略：

```text
无冲突:
继续执行。

简单冲突:
允许 AI 解决，并重新跑 Scenario。

复杂业务冲突:
触发 HUMAN_ASK_HELP。
```

复杂冲突包括：

```text
同一业务函数大面积变更
数据库 migration 冲突
公共接口契约冲突
权限逻辑冲突
测试断言语义冲突
```

## 18. Execution Mode

系统必须区分本地交互和自动化执行。

### 18.1 Interactive Mode

默认用于本地 Claude Code。

```bash
aicode run --mode=interactive
```

行为：

```text
遇到人工确认点时暂停。
等待用户 approve / reject / modify。
适合本地开发。
```

### 18.2 Daemon Mode

用于 CI、夜间任务、自动回归。

```bash
aicode run --mode=daemon
```

行为：

```text
不在终端永久等待人工输入。
遇到审查点时生成审查报告。
将 Loop 状态标记为 paused。
通过飞书、钉钉、邮件或 PR Comment 通知人工审批。
审批后从 checkpoint 恢复。
```

## 19. Tool Adapter 设计

### 19.1 Claude Code Adapter

生成：

```text
CLAUDE.md
.claude/commands/aicode-spec.md
.claude/commands/aicode-plan.md
.claude/commands/aicode-verify.md
.claude/commands/aicode-review.md
.claude/aicode/project-map.md
.claude/aicode/style.md
.claude/aicode/workflow.md
.claude/aicode/memory.md
```

能力：

```text
提供项目规范
提供 Loop 流程
提供 Spec / Plan 命令
提供 Memory 投影
约束修改边界
调用 Superpowers Provider
调用 Scenario Runner
```

### 19.2 Codex Adapter

后续扩展。

生成：

```text
.codex/instructions.md
.codex/skills/aicode-spec/
.codex/skills/aicode-debug/
.codex/skills/aicode-review/
.codex/aicode/project-map.md
.codex/aicode/style.md
.codex/aicode/workflow.md
.codex/aicode/memory.md
```

### 19.3 Cursor Adapter

后续扩展。

生成：

```text
.cursor/rules/aicode.md
.cursor/rules/aicode-style.md
.cursor/rules/aicode-memory.md
```

## 20. CLI 设计

第一阶段：

```bash
aicode init
aicode calibrate
aicode install claude
aicode install superpowers
aicode sync

aicode spec "需求描述"
aicode spec --from-doc docs/prd.md
aicode plan
aicode verify scenario <scenario-id>
aicode guard check
aicode memory update
aicode report
```

后续扩展：

```bash
aicode install codex
aicode install cursor
aicode env up
aicode start
aicode verify native
aicode ci generate
aicode plugin list
aicode plugin install <name>
```

## 21. MVP 与完整架构边界

### 21.1 MVP 目标

MVP 不等于最终架构缩水，而是先跑通核心闭环。

第一阶段只做：

```text
1. Claude Code 插件安装。
2. init 扫描项目并生成 Claude Code 原生规范文件。
3. 深度接入 Superpowers 作为 Spec / Plan Provider。
4. 生成 Spec / Plan。
5. Context Router 基础版。
6. Scenario Runner 调接口并验证数据状态。
7. Verification Sanity Check。
8. .ai/memory.md 记忆沉淀。
9. Guard 基础规则。
```

Codex、Cursor 在第一阶段只保留 Adapter 接口和文档设计，不作为主实现目标。

### 21.2 暂不做

```text
复杂云平台
完整插件市场
全语言覆盖
自动连接生产资源
复杂 Agent 调度
Mutation Testing
深度 CI 平台化
```

### 21.3 完整架构保留

后续逐步扩展：

```text
更多 Provider
更多 Tool Adapter
自动环境编排
Native Test 回归沉淀
覆盖率和架构检查
CI/CD 集成
Daemon Mode
组织级 Memory
多项目迁移工具
```

## 22. 路线图

### Phase 1: Claude Code + Superpowers 骨架

```text
CLI
Claude Adapter
工具原生文件生成
.ai/memory.md
.ai/scenarios/
Superpowers Glue Mapping
```

### Phase 2: Spec / Plan + Context Router

```text
Superpowers Provider
内置 Spec Provider
动态 Spec
Plan 拆分
歧义识别
Context Router 基础版
```

### Phase 3: Scenario Runner

```text
Sanity Check
HTTP 调用
MySQL 断言
Redis 断言
Fixture
报告
失败上下文收集
```

### Phase 4: Guard / Memory / Git

```text
Diff 越界检查
Anti-Cheating
Rollback Plan
Git Upstream Sync
Schema Version 记录
Memory 更新
Claude Memory 投影
```

### Phase 5: 工程增强

```text
自动启动服务
Docker / Testcontainers
Native Tests
CI 集成
Daemon Mode
覆盖率
架构规则
Codex Adapter
Cursor Adapter
更多语言插件
```

## 23. 成功指标

不建议使用单一“代码准确率 98%”作为指标。

建议指标：

```text
任务闭环成功率
一次生成通过率
Scenario 验证通过率
Loop 内修复成功率
人工测试耗时下降
人工 Review 修改率
代码风格返工率
越界修改率
重复问题发生率
缺陷逃逸率
环境故障误修复率
上下文召回命中率
平均上下文 Token 数
```

目标：

```text
在明确 Spec、项目规范、修改边界和真实流程验证下，提高 AI Coding 的闭环成功率，并降低人工测试和人工返工成本。
```

## 24. 总结

本系统最终不是一个简单脚手架，而是一套 AI Coding 工作流能力包。

它参考 Superpowers 的插件形态，但能力更完整：

```text
Spec / Plan
AI 编码执行约束
Context Router
真实流程验证
数据断言
环境健康检查
根因分析
自动修复
Guard
Rollback
Memory
多工具适配
```

当前落地路线：

```text
先打通 Claude Code + Superpowers。
架构上保留 Codex、Cursor、spec-kit、OpenSDD 扩展点。
先跑通 AI Coding Loop 的完整闭环，再逐步补齐多工具和工程增强能力。
```

## 25. 最终实现架构

### 25.1 插件目录结构

```
ai-coding-loop/
│
├── plugin.json                      # 工具无关的插件声明
│
├── skills/                          # 工具无关 —— 通用 Markdown 剧本
│   ├── init.md                      # /aicode-init
│   ├── calibrate.md                 # /aicode-calibrate
│   ├── spec.md                      # /aicode-spec
│   ├── plan.md                      # /aicode-plan
│   ├── verify.md                    # /aicode-verify
│   ├── review.md                    # /aicode-review
│   └── memory.md                    # /aicode-memory
│
├── engines/                         # Python 引擎 —— 工具无关
│   ├── run.sh                       # Linux/Mac 入口
│   ├── run.bat                      # Windows 入口
│   ├── cli.py                       # 统一 CLI 入口
│   ├── state/                       # 状态管理
│   ├── runtime/                     # Loop 引擎 + 阶段处理器
│   ├── guard/                       # Guard 系统
│   ├── scenario/                    # Scenario Runner
│   ├── memory/                      # Memory 系统
│   ├── init/                        # Init 扫描器 + 生成器
│   └── context/                     # Context Router
│
├── adapters/                        # 各工具适配层
│   ├── claude/
│   │   ├── plugin.json              # Claude Code 识别用
│   │   ├── hooks.json               # SessionStart hook
│   │   └── install.py               # aicode install claude 时执行
│   ├── codex/                       # 后续
│   └── cursor/                      # 后续
│
└── hooks/
    └── session-start.py             # 工具无关的 SessionStart hook 逻辑
```

### 25.2 三层职责分离

```
┌─────────────────────────────────────────────────┐
│  skills/*.md     │  AI 的"剧本"                  │
│                  │  告诉 AI：调什么命令、怎么     │
│                  │  读 JSON、如何决策             │
├─────────────────────────────────────────────────┤
│  engines/        │  AI 的"工具箱"                │
│                  │  确定性工作：扫描/生成/验证    │
│                  │  状态机/校验/上下文路由        │
│                  │  输出 JSON 给 AI 读            │
├─────────────────────────────────────────────────┤
│  adapters/       │  工具适配层                   │
│                  │  把 skills/ 翻译成各工具格式   │
│                  │  Claude/Codex/Cursor           │
└─────────────────────────────────────────────────┘
```

### 25.3 执行流程

**AI 是编排者，Python 引擎是工具：**

```
用户敲 /aicode-init
  → Claude Code 加载 adapters/claude/plugin.json
  → 找到 skills/init.md → 塞入 AI 上下文
  → AI 读剧本 → 理解要做什么

  Step 1: AI 调 Bash: bash ${CLAUDE_PLUGIN_ROOT}/engines/run.sh init --scan-only --format json
  Step 2: AI 读 JSON → 判断是否能继续
  Step 3: AI 调 Bash: bash ${CLAUDE_PLUGIN_ROOT}/engines/run.sh init --generate --auto-confirm --format json
  Step 4: AI 读 JSON → 用中文向用户报告
```

**LoopRunner 驱动流程，AI 在需要时介入：**

```
/aicode-full "需求"
  → AI 调: bash ${CLAUDE_PLUGIN_ROOT}/engines/run.sh loop full --task "需求"
  → Python LoopRunner 驱动 8 阶段:

  INTAKE → SPEC → PLAN → EXECUTE → VERIFY → REPAIR → REVIEW → MEMORY → COMPLETED

  Python 做: 状态流转、Guard 校验、ContextRouter 注入、ScenarioRunner 验证
  AI 做: 生成 Spec 内容、写代码、分析失败根因、修复 bug
```

**每个阶段谁做什么：**

| 阶段 | Python (LoopRunner) | AI |
|------|---------------------|-----|
| INTAKE | 分析输入类型、复杂度、风险等级 | 输入模糊时向用户提问 |
| SPEC | ContextRouter 注入上下文 | 生成 Spec 内容 |
| PLAN | 拆 Task 框架、设定 diff budget | 填每个 Task 具体内容 |
| EXECUTE | Guard 前置检查、ContextRouter 注入 | 写代码 |
| VERIFY | ScenarioRunner 跑场景、SanityChecker 检查环境 | 读失败报告、判断根因 |
| REPAIR | ContextRouter 注入失败上下文 | 分析根因、最小修复 |
| REVIEW | Guard 检查越界/diff/合规 | 判断是否需要 Plan Change |
| MEMORY | MemoryExtractor 提取候选、MemoryProjection 同步 | 判断哪些值得沉淀 |

### 25.4 CLI 设计

```bash
# 初始化
bash engines/run.sh init --scan-only --format json
bash engines/run.sh init --generate --auto-confirm --format json

# Loop 全流程
bash engines/run.sh loop full --task "需求描述"
bash engines/run.sh loop dev --task "开发任务"
bash engines/run.sh loop test --scenario <id>

# 单步命令
bash engines/run.sh verify --scenario <id> --format json
bash engines/run.sh guard check --diff HEAD
bash engines/run.sh memory update
bash engines/run.sh memory search --keyword "订单超时" --format json
bash engines/run.sh context route --stage execute --state-file run.json --format json
```

所有命令输出 JSON，日志/进度输出到 stderr。

> **注意**: skill 文件中引用 CLI 时使用 `${CLAUDE_PLUGIN_ROOT}/engines/run.sh`，Claude Code 在插件上下文中解析该变量。engines/ 不拷贝到用户项目。

### 25.5 SKILL.md 格式

```markdown
---
name: aicode-<name>
description: "简短描述"
---

# /aicode-<name>

## 触发条件
（可选 —— 什么时候自动触发）

## 执行

### Step N: 做什么
```bash
bash ${CLAUDE_PLUGIN_ROOT}/engines/run.sh <command> --format json
```

### Step N+1: 读结果
- JSON 字段含义
- 判断逻辑

### Step N+2: 决策/行动
- 根据结果做什么

## 禁止行为
- 不做什么
```

### 25.6 适配器职责

| 适配器 | 安装后产物（项目内） | 命令格式 |
|--------|----------------------|----------|
| claude | `.claude/skills/*.md` + `hooks/hooks.json` | `/aicode-xxx` |
| codex | `.codex/skills/aicode-xxx/SKILL.md` | `/aicode-xxx` |
| cursor | `.cursor/rules/aicode-*.md` | `@aicode-xxx` |

**engines/ 和 hooks/session-start.py 等 Python 源码留在插件全局安装目录**，skill 通过 `${CLAUDE_PLUGIN_ROOT}/engines/run.sh` 引用。安装只拷贝 skill 文件和 hooks 配置，不拷贝引擎源码。

### 25.7 数据流

```
AI ←→ Bash( ${CLAUDE_PLUGIN_ROOT}/engines/run.sh ) ←→ engines/各模块
                    ↑
              插件全局安装目录

通信协议: stdout JSON
  - Python 输出 {"success": bool, "data": {...}, "errors": [...]}
  - AI 解析 JSON → 决策 → 调下一个命令或继续 Loop
```
