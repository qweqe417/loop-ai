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

## 步骤 2：AI 扫描项目（必须产出以下数据）
> **在进入步骤 3 之前，你必须完整填写下方"项目画像"。任何字段不得留空，不得写"待确认"或"通用"。如果项目中没有对应内容，写"无"。**

### 2.0 技术栈快速识别树（按顺序检查，命中即停）

> **不要根据记忆或常识判断。必须用 Read 工具实际读取依赖文件，从文件中提取真实信息。**

#### 第一步：寻找依赖文件

按顺序检查项目根目录是否存在以下文件（用 `Glob` 或 `ls` 检查），**命中第一个存在的文件后，用 Read 读取其内容**：

| 优先级 | 依赖文件 | 对应的语言/生态 |
|--------|----------|-----------------|
| 1 | `pom.xml` | Java (Maven) |
| 2 | `build.gradle` 或 `build.gradle.kts` | Java/Kotlin (Gradle) |
| 3 | `package.json` | Node.js / JavaScript / TypeScript |
| 4 | `go.mod` | Go |
| 5 | `pyproject.toml` | Python |
| 6 | `requirements.txt` | Python |
| 7 | `Cargo.toml` | Rust |
| 8 | `*.csproj` | C# |

#### 第二步：从依赖文件中提取信息

**读取依赖文件后，从中提取以下信息：**

| 要提取的信息 | 在文件中怎么找 |
|-------------|---------------|
| **语言** | 由文件名决定（如 `pom.xml` → Java，`package.json` → Node.js） |
| **语言版本** | 检查 `properties` → `<maven.compiler.source>` (pom.xml)；`engines.node` (package.json)；`go.mod` 第一行的 `go 1.x` |
| **框架** | 检查依赖列表中的常见框架名：Spring (`spring-boot`)、React (`react`)、Vue (`vue`)、FastAPI (`fastapi`)、Django (`django`)、Express (`express`) 等 |
| **测试框架** | 检查依赖列表中的 `junit`、`mockito`、`jest`、`vitest`、`pytest`、`mocha` 等 |
| **包管理器** | 由文件名决定（`pom.xml` → Maven，`package.json` → npm/yarn/pnpm，`go.mod` → Go modules） |
| **构建工具** | 由文件名决定（`pom.xml` → Maven，`build.gradle` → Gradle，`package.json` → npm scripts / Vite / Webpack） |

> **关于"常见框架名"的说明**：上表中的框架名只是示例，**AI 必须实际读文件寻找依赖**。如果依赖列表中出现表中没有列出的框架（如 `quarkus`、`micronaut`、`svelte` 等），也必须如实记录。不要因为不在示例列表中就忽略。

#### 第三步：输出填表

将提取到的信息填入步骤 2.1 的"项目画像"表格中。如果某个信息在文件中找不到（比如没有明确指定语言版本），写"未指定"而不是编造。

### 2.1 项目画像（必填）

| 字段 | 值 |
|------|-----|
| **项目名称** | 从 `package.json`/`pom.xml`/`go.mod`/`pyproject.toml` 提取 |
| **语言** | 如 Java 17 / TypeScript 5.0 / Python 3.11 |
| **框架** | 如 Spring Boot 3.2 / React 18 / FastAPI |
| **包管理器** | 如 Maven / npm / poetry |
| **构建工具** | 如 Maven / Gradle / Vite / Go build |
| **测试框架** | 如 JUnit 5 + Mockito / Jest / pytest |
| **测试目录** | 如 `src/test/java` / `__tests__` / `tests/` |
| **测试文件命名** | 如 `*Test.java` / `*.spec.ts` / `test_*.py` |
| **运行测试命令** | 完整可复制命令，如 `mvn test` / `npm test` / `pytest` |
| **日志库** | 如 SLF4J + Logback / Winston / loguru |
| **日志调用示例** | 从源码复制 1 条真实调用语句 |
| **异常基类** | 如 `RuntimeException` / `PowerJobException` / `AppError` |
| **异常处理模式** | 如 `try-catch` / `throws` / `except`，附 1 个实例 |
| **依赖注入方式** | 如 `@Resource` / `@Autowired` / `constructor` |
| **源码目录** | 如 `src/main/java` / `src/` / `app/` |
| **资源配置目录** | 如 `src/main/resources` / `config/` |

### 2.2 命名约定采样（必须从源码中提取）

> **每个类别至少列出 3 个真实类名/方法名/变量名/常量名，不能凭空编造。**

| 类别 | 模式 | 源码实例（至少 3 个） |
|------|------|----------------------|
| 类名 | PascalCase | `InstanceManager`, `ResultDTO`, `CommonUtils` |
| 方法名 | camelCase | `updateStatus`, `processFinishedInstance`, `getInStringCondition` |
| 常量 | UPPER_SNAKE | `MAXIMUM_CAPACITY`, `COMMA_SPLITTER`, `MONITOR_JOINER` |
| 变量/参数 | camelCase | `instanceId`, `jobInfo`, `workerClusterQueryService` |

### 2.3 目录结构采样（必须用 `tree` 或 `ls -R` 实际列出）

执行 `tree -L 3 -d` 或 `ls -R`，把输出结果**原样粘贴**到下方，然后标注核心模块职责：
{粘贴实际目录树}

模块职责：

{模块名}: {职责描述}

{模块名}: {职责描述}

### 2.4 关键代码采样（必须 Read 至少 3 个代表性文件）

读取文件路径：
1. `{路径}` → 记录了 {关键特征}
2. `{路径}` → 记录了 {关键特征}
3. `{路径}` → 记录了 {关键特征}

从这些文件中提取：
- **异常处理实例**：粘贴 1 段真实代码
- **日志调用实例**：粘贴 1 条真实语句
- **依赖注入实例**：粘贴 1 个真实字段

---
---

## 步骤 3：生成主配置文件

> **不存在时必须生成。已存在则跳过。**
> **禁止编造：下文所有 `{...}` 占位符必须替换为步骤 2 项目画像中的实际值。如果某个值在步骤 2 中未采集到，回到步骤 2 补采，不能留空。**

### 3.1 检查

用 Read 试着读主配置文件路径。读到内容 → 文件存在；读不到（No such file）→ 不存在。

- **存在 → 跳过**。告知用户："{路径} 已存在，跳过。"
- **不存在 → 你必须立即用 Write 工具创建它。**

### 3.2 内容要求（≤200 行）

按以下结构写：

```
{步骤 2.1 中的项目名称}
技术栈
{步骤 2.1：语言} / {步骤 2.1：框架} / {步骤 2.1：包管理器}

目录结构
{从步骤 2.3 中提炼的模块职责，精简到 1 段}

代码风格
命名约定
类名: {步骤 2.2 中的模式} — 示例: {步骤 2.2 中的类名实例列表}

方法名: {步骤 2.2 中的模式} — 示例: {步骤 2.2 中的方法名实例列表}

常量: {步骤 2.2 中的模式} — 示例: {步骤 2.2 中的常量实例列表}

变量: {步骤 2.2 中的模式} — 示例: {步骤 2.2 中的变量实例列表}

文件组织
{从步骤 2.3 提炼的 3-5 条核心原则}

依赖注入
{步骤 2.1 中的方式}，示例: {从 2.4 中摘 1 条}

异常处理
{步骤 2.1 中的异常基类}，示例: {从 2.4 中摘 1 段}

日志
{步骤 2.1 中的日志库}，示例: {从 2.4 中摘 1 条}

测试
框架: {步骤 2.1 中的测试框架}

目录: {步骤 2.1 中的测试目录}

文件命名: {步骤 2.1 中的测试文件命名}

运行命令: {步骤 2.1 中的运行测试命令}

架构约束
{从步骤 2.3 的模块职责提炼 3-5 条依赖方向规则}

禁止行为
以下行为在任何代码生成、修改或建议中均被严格禁止，必须无条件遵守：

安全底线
禁止 在代码中硬编码任何密钥、密码、令牌或敏感配置（如 API Key、数据库密码）。

禁止 使用已知存在安全漏洞的依赖版本（如 log4j 2.x 老版本、包含原型污染风险的 npm 包）。

禁止 在用户输入未经验证的情况下直接拼接到 SQL 语句或系统命令中（必须使用参数化查询或转义）。

代码质量
禁止 生成超过 80 列宽的代码行（除非语言强制要求）。

禁止 使用 var（JavaScript/TypeScript）或 auto 滥用（C++）——必须使用明确的类型声明。

禁止 在函数或方法中嵌套超过 3 层的条件分支（if-else）或循环。

禁止 提交任何包含 console.log、debugger、print 等调试语句的代码（除非明确要求临时调试）。

禁止 复制粘贴重复代码（必须提取公共逻辑）。

禁止 代码中出现魔法值。

设计与架构
禁止 在核心业务逻辑中直接依赖外部框架的具体实现（应依赖接口/抽象）。

禁止 创建超过 300 行的单个函数或方法。

禁止 在未明确要求的情况下引入新的全局变量或修改全局状态。

依赖与环境
禁止 添加任何未经用户明确许可的新依赖（包括 npm、pip、maven 等）。

禁止 在代码中硬编码文件路径或网络地址，必须使用配置文件或环境变量。

文档与提交
禁止 生成没有清晰注释的复杂算法（至少说明思路）。

禁止 在提交信息中写模糊的描述（如 "update"、"fix bug"），必须遵循 Conventional Commits 格式。

执行方式：遇到以上任何规则被违反，AI 必须先指出违规点，并提供修正方案，再给出最终代码。用户明确要求忽略某条规则时除外。。
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

> **每个文件独立检查：不存在则必须生成，存在则跳过。生成时必须使用步骤 2 的实际数据，不得编造。**

### 4.1 {rules_dir}/code-style.md

Read 检查是否存在。不存在则 Write 创建：

```
# 代码风格

## 命名约定

### 类与接口
- 类名: {PascalCase} — 示例: {3 个实例}
- 抽象类: {如 AbstractXxx 或 XxxBase} — 示例: {1-2 个实例}
- 异常类: {如 XxxException} — 示例: {1-2 个实例}
- 枚举: {如 XxxEnum 或直接 Xxx} — 示例: {1-2 个实例}
- DTO/VO: {如 XxxDTO / XxxVO / XxxRequest / XxxResponse} — 示例: {1-2 个实例}
- 接口: {I 前缀或后缀} — 示例: {1-2 个实例}
- 测试类: {如 XxxTest / XxxIntegrationTest} — 示例: {1-2 个实例}

### 方法
- 查询方法: {如 get* / find* / query* / list*} — 示例: {至少 2 个}
- 更新方法: {如 update* / set* / save*} — 示例: {至少 2 个}
- 删除方法: {如 delete* / remove*} — 示例: {至少 2 个}
- 判断方法: {如 is* / has* / can*} — 示例: {至少 2 个}
- 工厂方法: {如 of* / from* / builder()} — 示例: {至少 1 个}

### 常量与变量
- 常量: {UPPER_SNAKE_CASE} — 示例: {至少 3 个}
- 变量/参数: {camelCase} — 示例: {至少 3 个}
- 静态字段: {如 private static final 类型 名称} — 示例: {1 个}
- 成员字段: {如 private 类型 名称} — 示例: {1 个}
- 局部变量: {如 camelCase} — 示例: {1 个}

### 包/模块命名
- 基础包名: {如 com.company.project}
- 分层包名: {如 controller / service / repository / dto / entity / util}
- 模块划分: {从步骤 2.3 提炼，≤5 条}

## 文件组织
{从步骤 2.3 提炼核心原则，≤5 条}

## 返回值和参数规范
- 单对象返回: {如 Optional<T> / 直接 T / 可能 null?}
- 列表返回: {如 List<T> / Page<T> / 直接数组?}
- 分页返回: {如 PageResult<T> / Page<T>}
- 参数传递: {如 直接传参 vs DTO vs 多个参数}
- 校验注解: {如 @Valid / @NotNull / @NotBlank 等}
- 参数数量限制: {如 不超过 3 个参数，超过则用 DTO}

## 依赖注入规范
- 注入方式: {@Resource / @Autowired / 构造器}
- 类的职责区分:
  - @Service: {service 层业务逻辑}
  - @Repository / @Mapper: {数据访问层}
  - @Component: {通用组件}
  - @Controller / @RestController: {Web 层}
- 工具类: {static 方法，不实例化}
- 配置类: {@Configuration / @Bean}
- 示例: {从步骤 2.4 摘 1 条}

## 注解使用规范
{从实际代码中提取的常用注解组合，不超过 10 条}
- @{Anno1}: 用于 {场景}
- @{Anno2}: 用于 {场景}

## 异常处理
- 异常类: {步骤 2.1 中的异常基类}
- 模式: {步骤 2.1 中的异常处理模式}
- 示例: {从步骤 2.4 中摘录的真实代码段}

## 日志
- 库: {步骤 2.1 中的日志库}
- 格式: {从步骤 2.4 中提炼}
- 示例: {从步骤 2.4 中摘录的真实调用}
- 占位符格式: {如 {} vs {} vs 字符串拼接}
- 日志级别使用: {如 error 用于什么场景，warn 用于什么场景}

## 调用关系与依赖方向

### 分层调用规则
- **Controller → Service → Repository/DAO**
- Controller 不能直接调用 Repository
- Service 不能直接调用 Controller
- Repository 之间不能相互依赖

### 模块依赖方向
{从步骤 2.3 的模块职责提炼}
- `{模块A}` → `{模块B}`：允许依赖
- `{模块B}` → `{模块A}`：禁止依赖（循环依赖）
- `{模块C}` 不依赖任何模块（基础模块）

### 跨模块调用方式
- 模块间调用方式: {如 Feign Client / Dubbo / HTTP / MQ}
- 配置位置: {如 application.yml / 服务发现配置}
- 示例: {从步骤 2.4 摘录 1 个真实调用}

### 工具类调用
- 调用方式: {如 直接 `ClassName.methodName()` 调用}
- 示例: {从步骤 2.4 摘录 1 条}
- 是否允许注入: {是/否}

### 外部服务调用
- 调用方式: {如 RestTemplate / WebClient / 自定义 HttpClient}
- 超时配置: {如 连接超时 3s，读取超时 10s}
- 错误处理: {如 捕获异常后包装为自定义异常}
- 示例: {从步骤 2.4 摘录 1 段}
```

目标 ≤200 行。

### 4.2 {rules_dir}/testing.md

Read 检查是否存在。不存在则 Write 创建：

```
# 测试规则

测试框架
{步骤 2.1 中的测试框架} v{从依赖文件提取的版本}

目录结构
{步骤 2.1 中的测试目录} ↔ 对应 {步骤 2.1 中的源码目录}

文件命名
{步骤 2.1 中的测试文件命名}

Mock/Stub/Fixture
{从实际测试代码中提取的模式，附 1 个实例}

运行命令
cd {项目根目录} && {步骤 2.1 中的运行测试命令}
```

目标 ≤200 行。

### 4.3 {rules_dir}/safety.md

Read 检查是否存在。不存在则 Write 创建：

```
# 安全边界

不可修改
{从实际代码推断的不应修改的文件/目录}

禁止操作
{从步骤 2.3 的模块职责推断的项目特有禁止行为}

修改边界
{哪些模块可以改、哪些是外部接口不能动}
```

目标 ≤200 行。

### 4.4 规则文件写作原则

- 每条规则 = 做什么 + 不这样会怎样 + 为什么
- 正面引导
- 不写长篇说明，只写 AI 需要知道的约束

###  4.5：自我验证
在进入步骤 5 之前，你必须逐条检查以下清单：

- [ ] CLAUDE.md 中每一条命名约定都来自步骤 2.2 的采样，有实例支撑
- [ ] code-style.md 中每一条规则都对应步骤 2 中的真实代码模式
- [ ] testing.md 中的测试命令已用 `cd <项目根目录> && <命令>` 格式可复制
- [ ] safety.md 中的禁止操作是项目特有的，不是通用模板抄来的
- [ ] 没有任何一处写"遵循最佳实践"或"通常建议"——所有内容都来自本项目

如果任何一项不通过，回到相应步骤补采数据。

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
