---
name: aicode-init
user-invocable: true
description: "初始化 AI Coding Loop — AI 扫描项目、生成配置文件、Python 安装 .ai/ 资产"
---

# /aicode-init

> ⚠️ **已知陷阱（必读）：**
> 你可能会在上级目录（`../`）看到 `CLAUDE.md`、`.claude/rules/` 等文件。
> **那些是其他项目的配置，不是当前项目的。忽略它们！**
> 你只操作 `$PROJECT_ROOT`（=`pwd`）下的文件。
> **之前出过 bug：AI 看到上级目录有文件就跳过了当前项目的生成。这次不能重蹈覆辙。**

## 第零步：确定项目根目录（最高优先级）

**第一步：执行 `pwd`。输出就是项目根目录。记到 `$PROJECT_ROOT`。**

**第二步：用 Bash 列出当前目录内容：**
```bash
echo "=== pwd 输出: $(pwd) ===" && ls -la
```

**第三步（强制！不可跳过！）：用 AskUserQuestion 工具问用户确认：**

> 问题: "项目根目录是 `$(pwd)`，确认在这里初始化吗？"
> 选项 1: "是的，就在这里初始化"（推荐）
> 选项 2: "不对，项目根在上级目录"
> 选项 3: "不对，项目根在其他目录（我手动输入）"

**用户选选项 2 → 用上级目录重来。选选项 3 → 等用户提供路径。**
**只有选选项 1 才能继续。** 不要让 AI 自己猜项目根！

**铁律：**
- 你看到的上级目录结构、`../CLAUDE.md`、`../.git`——都不能帮你决定项目根。只有用户说了算。
- 所有文件操作都在用户确认的目录下。绝对路径，不相对路径。

---

## 项目类型判断：新项目 vs 老项目

在开始扫描前，先判断项目类型。**只用 Bash，不用 Glob（Glob 可能搜到上级目录）：**

```bash
# 统计 $PROJECT_ROOT 下的源码文件数（不递归到上级）
find "$PROJECT_ROOT" -maxdepth 5 -name "*.java" -o -name "*.py" -o -name "*.ts" -o -name "*.tsx" -o -name "*.go" -o -name "*.rs" -o -name "*.js" 2>/dev/null | wc -l
# 检查 $PROJECT_ROOT 下是否有依赖文件
ls "$PROJECT_ROOT"/pom.xml "$PROJECT_ROOT"/package.json "$PROJECT_ROOT"/go.mod "$PROJECT_ROOT"/pyproject.toml "$PROJECT_ROOT"/Cargo.toml 2>/dev/null
```

源码文件总数 ≤ 5 且没有依赖文件 → **新项目**
否则 → **老项目**

**新项目策略（规定型）：**
- 如果没有依赖文件，根据项目目录名、用户意图、或直接询问用户确定技术栈
- 所有命名约定、代码风格按阿里巴巴规范 + 语言官方最佳实践**预设**，不推断
- 生成的规则文件更厚、更严格，作为后续开发的"宪法"
- 如果用户已选定技术栈但还没写代码，按该技术栈的阿里巴巴规范填充

**老项目策略（推断型）：**
- 从实际代码中提取模式，但必须以阿里巴巴规范为底线
- 如果现有代码违反了阿里巴巴规范，在规则文件中指出正确做法
- 阿里巴巴规范要求 > 项目现有习惯

---

## 你要创建的 5 个文件

根据目标工具（用户指定 `--target` 或自动检测：`.codex/`→codex，`.cursor/`→cursor，否则 claude_code）：

| # | Claude Code | Codex | Cursor |
|---|------------|-------|--------|
| 1 | `CLAUDE.md` | `.codex/instructions.md` | `.cursor/rules/aicode.md` |
| 2 | `.claude/rules/code-style.md` | `.codex/rules/code-style.md` | `.cursor/rules/code-style.md` |
| 3 | `.claude/rules/testing.md` | `.codex/rules/testing.md` | `.cursor/rules/testing.md` |
| 4 | `.claude/rules/safety.md` | `.codex/rules/safety.md` | `.cursor/rules/safety.md` |
| 5 | `.claude/rules/karpathy.md` | `.codex/rules/karpathy.md` | `.cursor/rules/karpathy.md` |

> **无条件创建以上 5 个文件。不要检查它们是否已存在。不要跳过。**
>
> **为什么不能检查：你之前用 Glob/Read 检查，结果搜到了上级目录的同名文件，错误地跳过了。这次不检查，直接 Write。**
>
> **Write 的文件路径（每个前面拼上 `$PROJECT_ROOT`）：**
> - `$PROJECT_ROOT/CLAUDE.md`
> - `$PROJECT_ROOT/.claude/rules/code-style.md`
> - `$PROJECT_ROOT/.claude/rules/testing.md`
> - `$PROJECT_ROOT/.claude/rules/safety.md`
> - `$PROJECT_ROOT/.claude/rules/karpathy.md`
>
> **如果 Write 提示文件已存在（在 $PROJECT_ROOT 下）→ 跳过该文件。其他任何情况 → 必须生成。**
>
> **禁止生成以上 5 个文件以外的任何文件。**

记下你的 5 个路径。然后开始。

---

## 第一步：扫描项目，收集数据

**在 $PROJECT_ROOT 下做以下 4 件事。把结果记下来，步骤二写文件时会用到。**

### A. 找依赖文件

**只在 `$PROJECT_ROOT` 下找，不要用 `**` 递归到上级：**
```bash
ls "$PROJECT_ROOT"/pom.xml "$PROJECT_ROOT"/build.gradle* "$PROJECT_ROOT"/package.json "$PROJECT_ROOT"/go.mod "$PROJECT_ROOT"/pyproject.toml "$PROJECT_ROOT"/requirements.txt "$PROJECT_ROOT"/Cargo.toml "$PROJECT_ROOT"/*.csproj 2>/dev/null
```
找到后 Read 它，提取：语言、框架、测试框架、构建工具、包管理器。

| 要提取的信息 | 在文件中怎么找 |
|-------------|---------------|
| **语言** | 由文件名决定（`pom.xml`→Java，`package.json`→Node.js，`go.mod`→Go） |
| **语言版本** | pom.xml 看 `<maven.compiler.source>`；package.json 看 `engines.node`；go.mod 第一行 `go 1.x` |
| **框架** | 查依赖列表：Spring(`spring-boot`)、React(`react`)、Vue(`vue`)、FastAPI(`fastapi`)、Django(`django`)、Express(`express`) 等。表中没列出的框架（quarkus、svelte 等）也必须记录 |
| **测试框架** | 查依赖：`junit`、`mockito`、`jest`、`vitest`、`pytest`、`mocha` 等 |
| **包管理器** | 文件名决定（`pom.xml`→Maven，`package.json`→npm/yarn/pnpm，`go.mod`→Go modules） |
| **构建工具** | 文件名决定（`pom.xml`→Maven，`build.gradle`→Gradle，`package.json`→Vite/Webpack/npm scripts） |

**新项目特殊处理：**
- 如果找不到任何依赖文件 → 不要留空！根据以下规则预设：
  - 如果目录名含 `java`/`spring` → 预设 Java 8+/Spring Boot/Maven
  - 如果目录名含 `vue`/`react`/`frontend` → 预设 Node.js 18+/TypeScript
  - 如果目录名含 `py`/`fastapi`/`django` → 预设 Python 3.11+
  - 否则 → 问用户：`这个项目计划用什么技术栈？`
- 如果找到依赖文件（如 pom.xml），正常提取

### B. 读源码采样命名

**老项目：** Read 至少 3 个源码文件（优先 Controller/Service/Repository），提取以下信息。每个类别至少 3 个实例，不能编造。

**新项目（源码文件 ≤ 5）：** 跳过采样。直接使用阿里巴巴规范预设值（见下方各语言默认值）。

| 类别 | 模式 | 实例（≥3个） |
|------|------|-------------|
| 类名 | PascalCase | {例1}, {例2}, {例3} |
| 方法名 | camelCase | {例1}, {例2}, {例3}, {例4}, {例5}, {例6} |
| 常量 | UPPER_SNAKE | {例1}, {例2}, {例3} |
| 变量/参数 | camelCase | {例1}, {例2}, {例3} |

同时从源码中摘录（新项目用预设值）：
- 异常类名和处理方式（1 段真实代码）
- 日志调用（1 条真实语句）
- 依赖注入方式（1 条真实语句）
- 返回值包装模式（1 条真实语句）
- 常用注解（列出所有见到的）

### C. 看目录结构

**只看 `$PROJECT_ROOT`，不要看上级：**
```bash
ls -R "$PROJECT_ROOT" | head -100
```
或者：
```bash
find "$PROJECT_ROOT" -maxdepth 3 -type d | sort
```
记录：源码目录、测试目录、资源目录、各模块名和职责。

### D. 找命令

从 package.json scripts / pom.xml / Makefile 找完整可运行命令：
- 构建命令
- 测试命令
- Lint 命令

**新项目：** 如果找不到命令，预设常用命令（如 Java: `mvn clean package`, `mvn test`）

---

## 阿里巴巴编码规范（强制要求）

**所有生成的文件必须融入阿里巴巴编码规范。** 这是底线，不论是新项目还是老项目。

核心规范要点（必须体现在生成的 5 个文件中）：

| 规范项 | 要求 |
|--------|------|
| **命名** | 类名 PascalCase，方法/变量 camelCase，常量 UPPER_SNAKE，严禁拼音+英文混用 |
| **分层** | Controller → Service → Mapper/Repository，严禁逆向调用 |
| **异常** | 使用项目统一异常类，禁止吞异常（空 catch），异常信息要有足够上下文 |
| **日志** | 禁止使用 System.out/console.log，使用日志框架（SLF4J/log4j/logging/loguru） |
| **集合** | 判断空用 isEmpty() 而非 size()==0；遍历用 for-each/Stream 而非裸 for-i |
| **魔法值** | 禁止魔法值——除了 0/1/-1 之外的所有数字和字符串必须定义为有意义的常量 |
| **注释** | 复杂逻辑（>10行）必须有注释说明意图；所有 public 方法有 Javadoc/Docstring |
| **代码长度** | 单方法 ≤ 80 行，单文件 ≤ 500 行 |
| **安全** | 禁止硬编码密钥/密码；SQL 必须参数化；用户输入必须校验和转义 |

**Java 项目额外规范（Alibaba Java Coding Guidelines）：**
- POJO 类必须覆写 toString()
- 禁止在循环中进行 try-catch
- 禁止使用 Apache BeanUtils 复制属性（用 Spring BeanUtils 或 MapStruct）
- BigDecimal 初始化用 new BigDecimal("0.01") 而非 new BigDecimal(0.01d)
- equals() 先判断类型再强转

**TypeScript/JavaScript 项目额外规范：**
- 优先 const，其次 let，禁用 var
- 使用 === 而非 ==
- 异步操作用 async/await，禁止回调地狱

**Python 项目额外规范（PEP8 + Alibaba Python）：**
- 遵循 PEP8，缩进 4 空格
- 类型注解必须写
- 使用 f-string 而非 % 或 .format()
- 异常捕获具体类型，禁止裸 except

---

## 第二步：立即用 Write 创建 5 个文件

**每个文件：先 Read 检查是否存在。存在→跳过。不存在→用下面模板 Write。
所有 `{...}` 替换为上一步采集的实际值。不能留空。项目没有的写"本项目未使用"。
新项目：使用阿里巴巴规范预设值填充，不要留空。**

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

### 文件 5: `<rules_dir>/karpathy.md`（≥40 行）

# AI 编码行为规范

基于 [Andrej Karpathy 的 LLM 编码陷阱观察](https://x.com/karpathy/status/2015883857489522876)，约束 AI 编码助手的行为。

**权衡：** 这些规范偏向谨慎而非速度。简单任务自行判断。

## 1. 先想后写

**不要猜测。不要隐藏困惑。暴露权衡。**

实现前：
- 明确说出你的假设。不确定就问。
- 如果存在多种解读，列出来——不要默默选一个。
- 如果存在更简单的方法，说出来。有理由时反驳需求。
- 有不清楚的地方，停下来。说出困惑。问。

## 2. 简洁优先

**最少代码解决问题。不要投机性代码。**

- 不写超出需求的功能。
- 不为单次使用的代码建抽象层。
- 不写没人要的"灵活性"或"可配置性"。
- 不处理不可能发生的错误场景。
- 如果你写了 200 行而 50 行能搞定，重写。

自问："一个高级工程师会说这过度复杂吗？" 如果是，简化。

## 3. 外科手术式修改

**只改必须改的。只清理你自己搞乱的东西。**

编辑已有代码时：
- 不要"改进"相邻代码、注释、格式化。
- 不要重构没有 bug 的东西。
- 匹配已有风格，即使你觉得有更好的写法。
- 发现无关的死代码，提出来——但不要删。

当你的改动留下孤儿时：
- 清理你的改动导致的未使用 import/变量/函数。
- 不要删除已有死代码，除非被要求。

检验标准：每个改动行都应直接追溯到用户需求。

## 4. 目标驱动执行

**定义成功标准。循环直到验证通过。**

将任务转化为可验证目标：
- "加校验" → "为无效输入写测试用例，再让它们通过"
- "修 bug" → "写一个能复现的测试，再修好它"
- "重构 X" → "确保重构前后测试全通过"

多步骤任务，先写简短计划：
```
1. [步骤] → 验证: [检查方法]
2. [步骤] → 验证: [检查方法]
3. [步骤] → 验证: [检查方法]
```

强成功标准让你独立循环。弱标准（"让它能跑"）需要不断澄清。

---

## 第三步：自查

5 个文件全部写完后，检查：
- [ ] 每个文件行数达标（≥100 / ≥150 / ≥30 / ≥20 / ≥40），不够说明漏了章节
- [ ] 所有 `{...}` 已替换为实际值，没有遗留占位符
- [ ] 主配置包含"返回值规范"和"注解使用"
- [ ] code-style.md 包含"调用关系与依赖方向"和阿里巴巴分层规范
- [ ] karpathy.md 包含 4 节行为规范，不可缩水
- [ ] 测试命令用 `cd 目录 && 命令` 格式
- [ ] 没有"遵循最佳实践"、"通常建议"等通用废话
- [ ] 文件内容体现了阿里巴巴编码规范的核心要点
- [ ] 没有生成这 5 个以外的任何文件

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

**只需要试一次，失败了就直接跳过，不要反复尝试！**

```bash
cd "<引擎根目录>" && py -3 engines/cli.py init --assets-only --format json --project-root "$PROJECT_ROOT" --target <target_tool> 2>&1
```

- 成功 → 继续第六步。
- 失败（exit code 非 0 或 "py: command not found"）→ **立即跳过，不要尝试其他 Python 命令。**

引擎根目录 = 本 SKILL.md 所在目录向上两级。

如果跳过，报告中写：
```
⚠️ Python 资产安装未执行（py -3 不可用）
请手动在终端运行:
cd "<引擎根目录>"
py -3 engines/cli.py init --assets-only --format json --project-root "<项目根目录>" --target <target_tool>
```

---

## 第六步：报告

```
✅ AI Coding Loop Init 完成

目标工具: {tool}
技术栈: {language} / {framework}
项目类型: {新项目/老项目}

配置文件:
  [已生成/已跳过] <路径1>  (主配置)
  [已生成/已跳过] <路径2>  (代码风格 - 阿里巴巴规范)
  [已生成/已跳过] <路径3>  (测试规则)
  [已生成/已跳过] <路径4>  (安全边界)
  [已生成/已跳过] <路径5>  (AI 编码行为规范)

资产:
  .ai/prd/ + MCP + loop-config.json

下一步:
  1. /aicode-calibrate  确认规则（建议立即执行）
  2. 建议安装插件（复制到终端执行）:
     - superpowers（必须，/aicode-spec 依赖）:
       /plugin marketplace add obra/superpowers-marketplace
       /plugin install superpowers@superpowers-marketplace
     - ponytail（建议，避免过度工程化）:
       /plugin marketplace add DietrichGebert/ponytail
       /plugin install ponytail@ponytail
     - CodeGraph（可选，代码索引）:
       codegraph init -i
     - Playwright（前端项目可选，QA 测试）:
       npm init playwright@latest
  3. /aicode-spec <需求>  开始第一个任务
```
