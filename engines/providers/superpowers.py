"""SuperpowersProvider —— Superpowers 能力声明。

声明 Superpowers 的 brainstrom/spec/plan 能力、skill 模板、
AI 指令注入等。完全工具无关，所有工具通过 ToolAdapter 渲染。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engines.adapters.base import McpServerDef
from engines.providers.base import ProviderManifest


class SuperpowersProvider(ProviderManifest):
    """Superpowers Provider —— 方案探索 + Spec/Plan 生成。

    推荐但非必需的 spec_provider。
    在 Claude Code / Codex / Cursor 中都可使用。
    """

    @property
    def name(self) -> str:
        return "superpowers"

    @property
    def display_name(self) -> str:
        return "Superpowers"

    @property
    def type(self) -> str:
        return "spec_provider"

    @property
    def capabilities(self) -> list[str]:
        return ["spec.generate", "plan.generate", "task.breakdown", "brainstorm"]

    @property
    def required(self) -> bool:
        return False  # 推荐但非必需

    # ── 检测 ──

    def detect(self, project_root: Path) -> bool:
        return (project_root / "superpowers").is_dir() or \
               (project_root / ".superpowers").is_dir()

    # ── Skill 模板 ──

    def get_skill_templates(self) -> dict[str, str]:
        return {
            "brainstorm": """---
name: aicode-brainstorm
description: "Superpowers 方案探索 —— 脑暴、方案比较、风险识别"
---

# {cmd_prefix}aicode-brainstorm

## 触发条件
用户想要方案探索、脑暴、架构讨论时自动触发。

## 执行

### Step 1: 收集上下文
```bash
{engines_cmd} context route --stage spec --format json
```

### Step 2: 调用 Superpowers Brainstorm
调用 Superpowers brainstrom skill 进行方案探索。

### Step 3: 输出结构
- 方案选项
- 推荐方案 + 理由
- 不推荐方案 + 原因
- 业务边界
- 关键风险
- 需要澄清的问题
- 测试思路
- 是否适合进入 Spec

## 禁止行为
- 不要在 brainstorm 阶段写代码
- 不要在没有澄清关键问题前生成最终 Spec
""",

            "spec": """---
name: aicode-spec
description: "从需求生成结构化 Spec —— 通过 Superpowers 或内置 Spec Provider"
---

# {cmd_prefix}aicode-spec

## 执行

### Step 1: 构造 Spec Context Packet
```bash
{engines_cmd} context route --stage spec --format json
```
读取 JSON，收集项目上下文。

### Step 2: 判断是否需要先 Brainstorm
如果需求模糊、有多个实现方向、涉及架构选择 → 先执行 `{cmd_prefix}aicode-brainstorm`。

### Step 3: 生成 Spec
调用 Superpowers spec skill 或内置 Spec Provider 生成 Spec。

### Step 4: Spec Quality Gate
检查：
- 是否有明确目标和非目标
- 验收标准是否可测试
- 是否有异常场景
- 是否有修改边界
- 是否标出待确认问题
- 是否存在模糊词（优化/尽量/适当/快速/友好）

### Step 5: 输出并等待确认
```yaml
# Spec 输出结构
goals: []
nonGoals: []
userScenarios: []
businessRules: []
acceptanceCriteria: []
testScenarios: []
modificationBoundary: []
riskLevel: ""
openQuestions: []
```

## 禁止行为
- 不要跳过 Spec Quality Gate
- 不要在 Spec 未确认时进入 Plan
- 不要在有 openQuestions 时盲目执行
""",

            "plan": """---
name: aicode-plan
description: "从 Spec 生成执行计划 —— 拆 Task、设边界"
---

# {cmd_prefix}aicode-plan

## 执行

### Step 1: 读取 Spec
```bash
{engines_cmd} context route --stage plan --format json
```

### Step 2: 生成 Execution Contract
每个 Task 必须包含：
- taskId / title / goal
- allowedFiles / forbiddenFiles
- mustFollow（风格约束）
- acceptance（验收标准引用）
- scenarios（验证场景引用）
- doneWhen（完成条件）

### Step 3: 设置 Diff Budget
- maxFiles / maxLinesChanged / allowNewAbstractions

### Step 4: Reuse Check
搜索项目中是否已有可复用的实现。

### Step 5: Plan Quality Gate
检查是否覆盖所有验收标准、是否存在过大任务、是否存在无法验证的 Task。

## 禁止行为
- 不要在 Plan 未 approved 时写代码
- 不要私自新增 Task 或扩大范围
""",
        }

    # ── 主配置注入 ──

    def get_ai_instructions(self) -> str:
        return """
### Superpowers 集成

本项目已集成 Superpowers，适用于方案探索和 Spec/Plan 生成：

- `{cmd_prefix}aicode-brainstorm` — 方案探索（脑暴、方案比较、风险识别）
- `{cmd_prefix}aicode-spec` — 从需求生成结构化 Spec
- `{cmd_prefix}aicode-plan` — 从 Spec 拆分执行计划

Superpowers 负责生成 Spec 内容，AI Coding Loop 负责上下文控制和质量门禁。
"""

    # ── MCP 需求 ──

    def get_mcp_servers(self) -> list[McpServerDef]:
        return []  # Superpowers 不需要 MCP

    # ── Hook 需求 ──

    def get_hooks(self) -> dict[str, Any]:
        return {
            "SessionStart": [
                {
                    "command": "{engines_cmd} context project-map --format json 2>/dev/null",
                    "async": False,
                }
            ],
        }
