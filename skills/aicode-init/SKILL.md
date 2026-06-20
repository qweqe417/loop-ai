---
name: aicode-init
user-invocable: true
description: "初始化 AI Coding Loop — AI 扫描项目、生成配置文件、Python 安装 .ai/ 资产"
---

# /aicode-init

> **你现在必须用 Write 工具创建以下 4 个文件。不要跳过任何一个。**
>
> **如果文件已存在就跳过，不存在就必须生成。每个文件先 Read 检查。**
>
> **禁止生成这 4 个文件以外的任何文件（禁止 skills/commands/aicode/hooks）。**

## 你要创建的 4 个文件

根据目标工具（用户指定 `--target` 或自动检测：`.codex/`→codex，`.cursor/`→cursor，否则 claude_code）：

| # | Claude Code | Codex | Cursor |
|---|------------|-------|--------|
| 1 | `CLAUDE.md` | `.codex/instructions.md` | `.cursor/rules/aicode.md` |
| 2 | `.claude/rules/code-style.md` | `.codex/rules/code-style.md` | `.cursor/rules/code-style.md` |
| 3 | `.claude/rules/testing.md` | `.codex/rules/testing.md` | `.cursor/rules/testing.md` |
| 4 | `.claude/rules/safety.md` | `.codex/rules/safety.md` | `.cursor/rules/safety.md` |

记下你的 4 个路径。然后开始。

---

## 第一步：扫描项目，收集数据

**按顺序做以下 4 件事。把结果记下来，步骤二写文件时会用到。**

### A. 找依赖文件

用 Glob 按顺序找第一个存在的：`pom.xml` → `build.gradle*` → `package.json` → `go.mod` → `pyproject.toml` → `requirements.txt` → `Cargo.toml` → `*.csproj`。Read 它，提取：语言、框架、测试框架、构建工具、包管理器。

| 要提取的信息 | 在文件中怎么找 |
|-------------|---------------|
| **语言** | 由文件名决定（`pom.xml`→Java，`package.json`→Node.js，`go.mod`→Go） |
| **语言版本** | pom.xml 看 `<maven.compiler.source>`；package.json 看 `engines.node`；go.mod 第一行 `go 1.x` |
| **框架** | 查依赖列表：Spring(`spring-boot`)、React(`react`)、Vue(`vue`)、FastAPI(`fastapi`)、Django(`django`)、Express(`express`) 等。表中没列出的框架（quarkus、svelte 等）也必须记录 |
| **测试框架** | 查依赖：`junit`、`mockito`、`jest`、`vitest`、`pytest`、`mocha` 等 |
| **包管理器** | 文件名决定（`pom.xml`→Maven，`package.json`→npm/yarn/pnpm，`go.mod`→Go modules） |
| **构建工具** | 文件名决定（`pom.xml`→Maven，`build.gradle`→Gradle，`package.json`→Vite/Webpack/npm scripts） |

### B. 读源码采样命名

Read 至少 3 个源码文件（优先 Controller/Service/Repository），提取以下信息。每个类别至少 3 个实例，不能编造：

| 类别 | 模式 | 实例（≥3个） |
|------|------|-------------|
| 类名 | PascalCase | {例1}, {例2}, {例3} |
| 方法名 | camelCase | {例1}, {例2}, {例3}, {例4}, {例5}, {例6} |
| 常量 | UPPER_SNAKE | {例1}, {例2}, {例3} |
| 变量/参数 | camelCase | {例1}, {例2}, {例3} |

同时从源码中摘录：
- 异常类名和处理方式（1 段真实代码）
- 日志调用（1 条真实语句）
- 依赖注入方式（1 条真实语句）
- 返回值包装模式（1 条真实语句）
- 常用注解（列出所有见到的）

### C. 看目录结构

`tree -L 3 -d` 或 `ls -R`，记录：
- 源码目录、测试目录、资源目录
- 各模块名和职责

### D. 找命令

从 package.json scripts / pom.xml / Makefile 找完整可运行命令：
- 构建命令
- 测试命令
- Lint 命令

---

## 第二步：立即用 Write 创建 4 个文件

**每个文件：先 Read 检查是否存在。存在→跳过。不存在→用下面模板 Write。
所有 `{...}` 替换为上一步采集的实际值。不能留空。项目没有的写"本项目未使用"。**

---

### 文件 1: `<主配置路径>`（≥100 行）

{步骤 A 中的项目名称}

## 技术栈
{语言版本} / {框架} / {构建工具}

## 关键目录
- 源码: {目录}
- 测试: {目录}
- 资源: {目录}

## 常用命令
- 构建: {命令}
- 测试: {命令}
- Lint: {命令}

## 代码风格
### 命名约定
- 类名: {模式}，例: {B 中的类名实例}
- 方法名: {模式}，例: {B 中的方法名实例}
- 常量: {模式}，例: {B 中的常量实例}
- 变量/参数: {模式}，例: {B 中的变量实例}

### 文件组织
{从 C 提炼 3-5 条核心原则}

### 依赖注入
{方式}，例: {B 中摘录的语句}

### 返回值规范
{模式}，例: {B 中摘录的语句}

### 异常处理
{异常类名}，例: {B 中摘录的代码段}

### 日志
{日志库}，例: {B 中摘录的语句}

### 注解使用
{B 中提取的注解，≥3 条}

## 测试
- 框架: {A 中的测试框架}
- 目录: {C 中的测试目录}
- 命名: {模式}
- 命令: `{D 中的测试命令}`

## 架构约束
{从 C 的模块职责提炼 3-5 条}

## 禁止行为
- 禁止硬编码密钥、密码、令牌或敏感配置
- 禁止在代码中硬编码文件路径或网络地址，使用配置文件或环境变量
- 禁止使用已知安全漏洞的依赖版本
- 禁止直接将用户输入拼接到 SQL 或系统命令中（必须参数化查询或转义）
- 禁止使用 var（JS/TS）或 auto 滥用（C++）——使用明确类型声明
- 禁止嵌套超过 3 层的条件分支或循环
- 禁止提交包含 console.log / debugger / print 的调试代码
- 禁止复制粘贴重复代码（提取公共逻辑）
- 禁止代码中出现魔法值
- 禁止在核心业务逻辑中直接依赖外部框架具体实现（依赖接口/抽象）
- 禁止创建超过 300 行的单个函数或方法
- 禁止未经用户许可添加新依赖
- 禁止无清晰注释的复杂算法
- 禁止模糊的提交信息，遵循 Conventional Commits

违反时：先指出违规点 → 提供修正方案 → 再给出最终代码。

**写作铁律：**
- 只写项目特有的，不写"遵循最佳实践"
- 每条命令可直接复制运行
- 每条命名约定有 3+ 实例支撑
- 正面引导："使用 X"而非"不要用 Y"
- 不抄 linter 已有的规则
- 每条规则：做什么 + 不这样会怎样 + 为什么

---

### 文件 2: `<rules_dir>/code-style.md`（≥150 行）

# 代码风格

## 命名约定

### 类与接口
- 类名: {PascalCase}，例: {≥3个}
- 抽象类: {AbstractXxx / XxxBase}，例: {1-2个}
- 异常类: {XxxException}，例: {1-2个}
- 枚举: {XxxEnum}，例: {1-2个}
- DTO/VO: {XxxDTO / XxxVO / XxxRequest / XxxResponse}，例: {1-2个}
- 接口: {I前缀 / 后缀}，例: {1-2个}
- 测试类: {XxxTest / XxxIntegrationTest}，例: {1-2个}

### 方法
- 查询: {get* / find* / query* / list*}，例: {≥2个}
- 更新: {update* / set* / save*}，例: {≥2个}
- 删除: {delete* / remove*}，例: {≥2个}
- 判断: {is* / has* / can*}，例: {≥2个}
- 工厂: {of* / from* / builder()}，例: {≥1个}

### 常量与变量
- 常量: {UPPER_SNAKE}，例: {≥3个}
- 变量/参数: {camelCase}，例: {≥3个}
- 静态字段: {private static final}，例: {1个}
- 成员字段: {private}，例: {1个}
- 局部变量: {camelCase}，例: {1个}

### 包/模块命名
- 基础包: {com.company.project}
- 分层: {controller / service / repository / dto / entity / util}
- 模块划分（≤5条）

## 文件组织
{从 C 提炼，≤5条}

## 返回值和参数规范
- 单对象返回: {Optional<T> / 直接T / null}
- 列表返回: {List<T> / Page<T> / 数组}
- 分页返回: {PageResult<T> / Page<T>}
- 参数传递: {直接传参 / DTO / 多参数}
- 校验注解: {@Valid / @NotNull / @NotBlank}
- 参数数量限制: {规则}

## 依赖注入规范
- 注入方式: {@Resource / @Autowired / 构造器}
- @Service: {职责}
- @Repository / @Mapper: {职责}
- @Component: {职责}
- @Controller / @RestController: {职责}
- 工具类: {规则}
- 配置类: {规则}
- 示例: {B 中摘录 1 条}

## 注解使用规范
{从代码提取，≤10条}

## 异常处理
- 异常类: {名称}
- 模式: {try-catch / throws / except}
- 示例: {B 中摘录 1 段真实代码}

## 日志
- 库: {名称}
- 格式: {描述}
- 示例: {B 中摘录 1 条}
- 占位符: {格式}
- 级别: {error/warn/info/debug 各自场景}

## 调用关系与依赖方向

### 分层调用规则
- Controller → Service → Repository/DAO
- Controller 不能直接调 Repository
- Service 不能调 Controller
- Repository 之间不相互依赖

### 模块依赖方向
{从 C 的模块职责提炼}
- `{模块A}` → `{模块B}`：允许
- `{模块B}` → `{模块A}`：禁止（循环依赖）
- `{模块C}` 不依赖任何模块（基础模块）

### 跨模块调用方式
- 方式: {Feign / Dubbo / HTTP / MQ}
- 配置: {位置}
- 示例: {B 中摘录 1 条}

### 工具类调用
- 方式: {ClassName.methodName()}
- 示例: {B 中摘录 1 条}
- 是否允许注入: {是/否}

### 外部服务调用
- 方式: {RestTemplate / WebClient / HttpClient}
- 超时: {连接3s，读取10s}
- 错误处理: {描述}
- 示例: {B 中摘录 1 段}

---

### 文件 3: `<rules_dir>/testing.md`（≥30 行）

# 测试规则

测试框架
{A 中的测试框架} v{版本}

目录结构
{C 中的测试目录} ↔ {C 中的源码目录}

文件命名
{模式}

Mock/Stub/Fixture
{模式}，例: {1个}

运行命令
cd {项目根目录} && {D 中的测试命令}

---

### 文件 4: `<rules_dir>/safety.md`（≥20 行）

# 安全边界

不可修改
{不应修改的文件/目录}

禁止操作
{从 C 的模块职责推断的项目特有禁止行为}

修改边界
{哪些能改，哪些不能动}

---

## 第三步：自查

4 个文件全部写完后，检查：
- [ ] 每个文件行数达标（≥100 / ≥150 / ≥30 / ≥20），不够说明漏了章节
- [ ] 所有 `{...}` 已替换为实际值，没有遗留占位符
- [ ] 主配置包含"返回值规范"和"注解使用"
- [ ] code-style.md 包含"调用关系与依赖方向"
- [ ] 测试命令用 `cd 目录 && 命令` 格式
- [ ] 没有"遵循最佳实践"、"通常建议"等通用废话
- [ ] 没有生成这 4 个以外的任何文件

不通过 → 补写。

---

## 第四步：创建 .ai/prd/ 目录

Write `.ai/prd/README.md`，内容：

```markdown
# PRD 目录

放你的需求文档、用户故事、截图、原型链接等。

执行 /aicode-spec 时会自动读取这里的文档。

## 推荐内容
- 背景：为什么要做这个功能
- 目标用户：谁会用到
- 核心流程：用户操作的 3-5 个步骤
- 验收标准：怎么判断做完了
- 约束条件：技术/时间/资源限制
```

---

## 第五步：运行 Python 安装 .ai/ 资产

```bash
cd <引擎根目录> && python -m engines.cli init --assets-only --format json --project-root "<项目根目录>" --target <target_tool>
```

引擎根目录 = 本 SKILL.md 所在目录向上两级。

---

## 第六步：报告

```
✅ AI Coding Loop Init 完成

目标工具: {tool}
技术栈: {language} / {framework}

配置文件:
  [已生成/已跳过] <路径1>
  [已生成/已跳过] <路径2>
  [已生成/已跳过] <路径3>
  [已生成/已跳过] <路径4>

资产:
  .ai/prd/ + MCP + loop-config.json

下一步:
  1. 安装 superpowers：/aicode-spec 必须依赖，如未安装请立即执行安装
  2. 建议安装 CodeGraph：codegraph init -i（可选的代码索引，加速后续流程）
  3. /aicode-calibrate  确认规则
  4. /aicode-spec <需求>  开始第一个任务
```
