---
name: aicode-spec
user-invocable: true
description: "Generate a Spec from user requirements — delegates to superpowers for interactive brainstorming"
---

# /aicode-spec — 生成需求规格

> **核心原则：调用 superpowers 进行交互式脑暴 → 生成 Spec → 自动进入 Plan。**
>
> **Spec 阶段不写代码，不加载 Memory，不修改任何配置文件。**

---

## 完整流程

### 步骤 0：理解用户输入

用户可能：
- `/aicode-spec` — 无任何附加内容
- `/aicode-spec <文字描述>` — 直接用文字描述需求
- `/aicode-spec --from <目录>` — 指定某个目录下的需求文档

记录下来，准备传给 brainstorming。

---

### 步骤 1：收集需求上下文

按以下优先级确定需求来源：

#### 1.1 检查 `.ai/prd/` 目录

用 Glob 检查 `.ai/prd/` 下的文件（`*.md`, `*.txt`）。

- **1 个文件** → Read 它
- **多个文件** → 用 AskUserQuestion 让用户选一个
- **无文件** → 进入 1.2

#### 1.2 检查用户指定的目录

用户通过 `--from <目录>` 指定了路径？
- **是** → Read 该目录
- **否** → 进入 1.3

#### 1.3 检查用户输入的文字

用户在 `/aicode-spec` 后输入了需求描述？
- **有** → 直接用文字
- **没有** → 进入 1.4

#### 1.4 无任何输入

只输入了 `/aicode-spec`，且 `.ai/prd/` 下也没文档。

直接进入步骤 2，让 brainstorming 引导用户描述需求。

---

### 步骤 2：强检 superpowers（阻断）

尝试调用 `Skill: superpowers:brainstorming`，传入：

| 输入 | 内容 |
|------|------|
| 需求描述 | 步骤 1 收集的内容（如有） |
| 项目上下文 | codegraph_context 返回的模块结构 |

**成功** → brainstorming 会完成：
1. 探索项目结构
2. 一次问一个问题澄清需求
3. 提出 2-3 种方案（带权衡）
4. 分段展示设计方案，用户逐段确认
5. 写入 `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`
6. 用户审阅并确认
7. **自动调用 writing-plans 生成实现方案**

**失败**（skill not found）→ 告诉用户："superpowers 是 spec 生成的必需依赖，正在自动安装..."

执行安装：
- Claude Code: `claude plugins install superpowers`
- Codex: `codex plugin install superpowers`

安装完成后重试步骤 2。

---

### 步骤 3：复制 Spec 到 docs/spec/

superpowers 生成的文件默认在 `docs/superpowers/specs/`。

将其复制到 `docs/spec/<feature-name>.md`（去掉日期前缀）：

```bash
cp "docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md" "docs/spec/<topic>.md"
```

或在 AI Coding Loop 中：
1. Read `docs/superpowers/specs/<file>.md`
2. Write 到 `docs/spec/<feature-name>.md`

---

### 步骤 4：提醒 CodeGraph（非阻断）

尝试 `codegraph_status`：
- 已初始化 → 跳过
- 未初始化 → 告诉用户："建议安装 CodeGraph（`codegraph init -i`）以便更好理解项目结构"

---

### 步骤 5：呈现给用户确认

```
✅ Spec 生成完成

文件: docs/spec/<feature-name>.md
关联 Plan: docs/superpowers/plans/<plan>.md

确认后执行 /aicode-dev 开始开发。
```

等待用户确认。

---

## Guardrails

- **不写代码** — Spec 阶段只写需求文档
- **不加载 Memory** — 需求分析不应被历史经验限制
- **不修改配置** — 不碰 CLAUDE.md、rules、hooks
- **superpowers 优先** — 优先让 brainstorming 完成交互式设计
- **有歧义就标注** — 不确定的写到 Open Questions，不猜测