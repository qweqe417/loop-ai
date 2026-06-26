"""ScenarioRunnerProvider —— 场景验证 Provider。

声明 Scenario Runner 的验证能力：HTTP 调用、数据库断言、Redis 断言、
报告生成、环境健康检查。
"""

# 启用延迟注解求值
from __future__ import annotations

# 导入 Path 用于文件路径操作
from pathlib import Path
# 导入 Any 类型
from typing import Any

# 从 adapters.base 导入 McpServerDef 数据类
from engines.adapters.base import McpServerDef
# 从 providers.base 导入 ProviderManifest 抽象基类
from engines.providers.base import ProviderManifest


# 场景验证 Provider 类
class ScenarioRunnerProvider(ProviderManifest):
    """Scenario Runner Provider —— 真实流程验证。

    必需插件。负责 HTTP 调用、断言验证、环境 health check、生成验证报告。
    """

    # Provider 名称
    @property
    def name(self) -> str:
        return "scenario-runner"

    # 显示名
    @property
    def display_name(self) -> str:
        return "Scenario Runner"

    # Provider 类型：验证
    @property
    def type(self) -> str:
        return "verification"

    # 能力声明列表
    @property
    def capabilities(self) -> list[str]:
        return [
            "scenario.http",         # HTTP 场景验证
            "assertion.mysql",       # MySQL 断言
            "assertion.redis",       # Redis 断言
            "assertion.response",    # HTTP 响应断言
            "assertion.log",         # 日志断言
            "report.generate",       # 报告生成
            "sanity.check",          # 冒烟检查
        ]

    # 是否为必需插件：是（核心验证引擎）
    @property
    def required(self) -> bool:
        return True  # 核心验证引擎，必需

    # ── 检测 ──

    # 检测此 Provider 是否已安装/可用
    # 参数 project_root: 项目根目录
    # 返回值: True 表示可用
    def detect(self, project_root: Path) -> bool:
        try:
            # 尝试导入 ScenarioRunner 类
            from engines.scenario import ScenarioRunner
            scenarios_dir = project_root / ".ai" / "scenarios"
            # 首次 init 时 .ai/ 还不存在 → 允许通过（FileGenerator 会创建）
            if not scenarios_dir.is_dir():
                return True
            # 已初始化 → 必须有真实场景文件才认为可用
            return any(scenarios_dir.rglob("*.yaml"))
        except ImportError:
            return False

    # ── Skill 模板 ──

    # 获取 skill 模板（包含 verify、test、direct 三种模式）
    # 返回值: {逻辑名: 模板内容} 字典
    def get_skill_templates(self) -> dict[str, str]:
        return {
            # verify 模式：场景验证
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
            # test 模式：验证 + 修复循环
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
            # direct 模式：快速通道
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

    # 获取 AI 指令：在主配置文件中注入的说明段落
    # 返回值: AI 指令文本
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

    # 获取 MCP Server 定义列表
    # 返回值: 空列表（Scenario Runner 本身不需要 MCP，它通过 MCP Provider 访问资源）
    def get_mcp_servers(self) -> list[McpServerDef]:
        # Scenario Runner 本身不需要 MCP（它通过 MCP Provider 访问资源）
        return []

    # ── Hook 需求 ──

    # PostToolUse hook 默认间隔（秒），防止连续编辑时频繁触发
    _HOOK_THROTTLE_SECONDS: int = 5

    # 获取 hook 定义
    # 返回值: hook 定义字典
    def get_hooks(self) -> dict[str, Any]:
        return {
            # 在每次编辑/写入操作后触发 guard 检查
            "PostToolUse": [
                {
                    "matcher": "Edit|Write",
                    "command": "{engines_cmd} guard check --diff HEAD --format json 2>/dev/null",
                    # ToolAdapter 层实现节流：_HOOK_THROTTLE_SECONDS 秒内最多触发一次
                    "_throttle_seconds": self._HOOK_THROTTLE_SECONDS,
                }
            ],
        }