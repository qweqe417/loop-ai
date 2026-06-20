---
name: aicode-spec
user-invocable: true
description: "Generate a Spec from user requirements — with optional brainstorming and multi-source PRD support"
---

# /aicode-spec — 生成需求规格

> **核心原则：先脑暴（可选）→ 确定需求来源 → 生成 Spec → 质量门禁 → 用户确认。**
>
> **Spec 阶段不写代码，不加载 Memory，不修改任何配置文件。**

---

## 完整流程

### 步骤 0：理解用户输入模式

用户可能：
- `/aicode-spec` — 无任何附加内容
- `/aicode-spec <文字描述>` — 直接用文字描述需求
- `/aicode-spec --from <目录>` — 指定某个目录下的需求文档

记下用户输入的内容，后面会用。

---

### 步骤 1：强检 superpowers（阻断）

尝试调用 `Skill: superpowers:brainstorming`。

- **成功** → 继续步骤 2。
- **失败**（skill not found）→ 告诉用户："superpowers 是 spec 生成的必需依赖，正在自动安装..."

  执行安装（根据当前工具选择命令）：
  - Claude Code: `claude plugins install superpowers`
  - Codex: `codex plugin install superpowers`
  
  安装完成后继续步骤 2。

---

### 步骤 2：提醒 CodeGraph（非阻断）

尝试调用 `codegraph_status`。

- 已初始化 → 继续。
- 未初始化 → 告诉用户："建议安装 CodeGraph 以便更好地理解项目结构（`codegraph init -i`），跳过不影响 spec 生成。"

不阻断，继续下一步。

---

### 步骤 3：询问是否需要脑暴

用 AskUserQuestion 询问用户：

> "是否需要先脑暴梳理需求？"
> - "需要" — 用 superpowers brainstorming 对需求进行结构化梳理，输出需求要点再生成 spec
> - "不需要" — 直接基于需求文档/描述生成 spec

**如果需要脑暴**：
1. 调用 `Skill: superpowers:brainstorming`，将当前的需求信息传入
2. 脑暴完成后，将输出作为后续 spec 生成的需求输入之一
3. 然后继续步骤 4（仍需确定需求文档来源）

**如果不需要**：直接进入步骤 4。

---

### 步骤 4：确定需求来源

按以下优先级顺序查找：

#### 4.1 检查 `.ai/prd/` 目录

用 Glob 检查 `.ai/prd/` 下的文件（`*.md`, `*.txt`）。

- **有文件**：
  - **1 个文件** → 直接 Read 它，作为需求文档
  - **多个文件** → 用 AskUserQuestion 列出文件，让用户选一个
- **无文件** → 进入 4.2

#### 4.2 检查用户指定的目录

用户是否通过 `--from <目录>` 指定了路径？
- **是** → Read 该目录下的需求文档
- **否** → 进入 4.3

#### 4.3 检查用户输入的文字

用户在 `/aicode-spec` 后是否输入了需求描述？
- **有文字** → 直接用文字作为需求
- **没有** → 进入 4.4

#### 4.4 无任何输入

用户只输入了 `/aicode-spec`，且 `.ai/prd/` 下也没有文档。

询问用户："请描述你的需求，或者将产品文档放到 `.ai/prd/` 目录下。"

等待用户输入后继续。

---

### 步骤 5：生成 Spec

基于已确定的需求内容，生成结构化 Spec 文档。

用 Write 写入 `docs/spec/<feature-name>.md`，内容包含：

| 章节 | 说明 |
|------|------|
| **标题** | 清晰的特性名称 |
| **Goals** | 这个特性要实现什么 |
| **Non-goals** | 明确不在本次范围内 |
| **Background** | 为什么做这个（从需求文档提取，没有则标注"用户未提供"） |
| **User Stories** | 用户视角的使用场景 |
| **Business Rules** | 核心业务规则 |
| **Acceptance Criteria** | 可验证的验收条件 |
| **Test Scenarios** | 验证场景（成功路径 + 异常路径 + 边界条件） |
| **Edge Cases** | 边界和异常情况 |
| **Dependencies** | 依赖的外部系统/服务/模块 |
| **Risk Level** | L1（最低）到 L5（最高） |
| **Open Questions** | 需要用户澄清的问题 |

### 步骤 6：Spec 质量门禁

自查以下项：

- [ ] Goals 是否清晰、具体？
- [ ] Non-goals 是否已声明（防止范围蔓延）？
- [ ] Acceptance Criteria 是否可验证（不是模糊的"更好""更快"）？
- [ ] Test Scenarios 是否覆盖了成功/异常/边界三种路径？
- [ ] Edge Cases 是否列了至少 2 个？
- [ ] 是否有模糊词（"优化""改进""处理所有"）→ 有则改成具体描述
- [ ] 是否有不确定的地方写到 Open Questions？

不通过 → 补写。通过 → 进入步骤 7。

### 步骤 7：呈现给用户确认

展示 Spec 文件的路径和关键内容摘要，等待用户确认。

确认后可以进入 `/aicode-plan` 阶段。

---

## Guardrails

- **不写代码** — Spec 阶段只写需求文档
- **不加载 Memory** — 需求分析不应被历史经验限制
- **不修改配置** — 不碰 CLAUDE.md、rules、hooks
- **有歧义就标注** — 不确定的写到 Open Questions，不猜测
- **范围可控** — Non-goals 必须声明，防止用户后续要求超出范围
