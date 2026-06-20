"""ScenarioRunnerProvider —— 场景验证 Provider。

声明 Scenario Runner 的验证能力：HTTP 调用、数据库断言、Redis 断言、
报告生成、环境健康检查。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engines.adapters.base import McpServerDef
from engines.providers.base import ProviderManifest


class ScenarioRunnerProvider(ProviderManifest):
    """Scenario Runner Provider —— 真实流程验证。

    必需插件。负责 HTTP 调用、断言验证、环境 health check、生成验证报告。
    """

    @property
    def name(self) -> str:
        return "scenario-runner"

    @property
    def display_name(self) -> str:
        return "Scenario Runner"

    @property
    def type(self) -> str:
        return "verification"

    @property
    def capabilities(self) -> list[str]:
        return [
            "scenario.http",
            "assertion.mysql",
            "assertion.redis",
            "assertion.response",
            "assertion.log",
            "report.generate",
            "sanity.check",
        ]

    @property
    def required(self) -> bool:
        return True  # 核心验证引擎，必需

    # ── 检测 ──

    def detect(self, project_root: Path) -> bool:
        try:
            from engines.scenario import ScenarioRunner
            return True
        except ImportError:
            return False

    # ── Skill 模板 ──

    def get_skill_templates(self) -> dict[str, str]:
        return {
            "verify": """---
name: aicode-verify
description: "场景验证 —— 执行 scenario，断言，生成验证报告"
---

# {cmd_prefix}aicode-verify

## 执行

### Step 1: Sanity Check
```bash
{engines_cmd} verify --scenario sanity --format json
```
- 检查服务是否可达
- 检查 MySQL/Redis/MQ 连接
- 环境故障 → 暂停，提示人工处理（**不进入代码修复**）

### Step 2: 执行 Scenario
```bash
{engines_cmd} verify --scenario <scenario-id> --format json
```

### Step 3: 读验证报告
- `success`: bool — 所有断言是否通过
- `assertions`: list — 每个断言的结果
- `failures`: list — 失败的断言详情

### Step 4: 决策
- 全部通过 → 进入 Review
- 失败 → 先区分故障类型：
  - 环境故障 → 停止，人工修复
  - 测试数据故障 → 检查 fixture
  - 代码逻辑故障 → 进入 Repair Loop

## 禁止行为
- 不要跳过 Sanity Check
- 不要在环境故障时修复代码
- 不要修改 scenario 让失败的代码通过
- 不要删除断言
""",
            "test": """---
name: aicode-test
description: "测试模式 —— 验证 + 修复循环"
---

# {cmd_prefix}aicode-test

## 触发条件
当需要只执行验证+修复而不走完整 Spec/Plan 流程时。

## 执行

### Step 1: 执行验证
```bash
{engines_cmd} verify --scenario <scenario-id> --format json
```

### Step 2: 分析失败
- 区分环境/数据/代码故障
- 定位根因

### Step 3: 最小修复
只修根因，不扩大范围。

### Step 4: 回归验证
```bash
{engines_cmd} verify --scenario <scenario-id> --format json
```

## 循环终止条件
- 全部通过 → 完成
- 连续 3 次失败 → 人工介入
- 环境故障 → 暂停

## 禁止行为
- 不要为了通过而删除/弱化断言
- 不要跳过测试
- 不要在修复时做无关重构
""",
            "direct": """---
name: aicode-direct
description: "快速通道 —— 小改动直接执行"
---

# {cmd_prefix}aicode-direct

## 触发条件
L1/L2 小改动：单文件、不涉及数据库、不涉及权限、不需要复杂测试。

## 执行

### Step 1: 影响范围快速判断
```bash
{engines_cmd} guard check --diff HEAD --format json
```

### Step 2: 执行修改
只修改必要文件，遵循项目规范。

### Step 3: 轻量验证
- 编译检查
- 相关接口 smoke test

### Step 4: Review
检查越界修改、风格合规。

## 禁止行为
- 不要在 L3+ 任务中使用 Direct
- 不要涉及数据库/缓存/权限修改
- 不要新增依赖
""",
        }

    # ── 主配置注入 ──

    def get_ai_instructions(self) -> str:
        return """
### Scenario Runner 验证

本项目已集成 Scenario Runner，用于真实流程验证：

- `{cmd_prefix}aicode-verify` — 执行场景验证
- `{cmd_prefix}aicode-test` — 验证+修复循环
- `{cmd_prefix}aicode-direct` — L1/L2 快速通道

验证方式（按优先级）:
1. 启动/连接服务
2. HTTP 调用接口
3. 断言响应
4. 断言 MySQL/Redis/MQ 状态
5. 生成验证报告

**禁止**：环境故障时修复代码、修改 scenario 迎合错误实现。
"""

    # ── MCP 需求 ──

    def get_mcp_servers(self) -> list[McpServerDef]:
        # Scenario Runner 本身不需要 MCP（它通过 MCP Provider 访问资源）
        return []

    # ── Hook 需求 ──

    def get_hooks(self) -> dict[str, Any]:
        return {
            "PostToolUse": [
                {
                    "matcher": "Edit|Write",
                    "command": "{engines_cmd} guard check --diff HEAD --format json 2>/dev/null",
                }
            ],
        }
