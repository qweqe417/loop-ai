"""Scenario 验证模块 —— 真实流程验证。

提供场景定义、执行引擎、断言引擎和环境健康检查：
- Scenario / ScenarioStep / Assertion / Fixture: 声明式场景定义
- ScenarioRunner: 加载场景 → Sanity Check → 执行步骤 → 执行断言 → 输出报告
- AssertionEngine: 对 HTTP / DB / Redis / MQ / 日志 断言进行判断
- SanityChecker: 环境健康检查（端口 / HTTP / MySQL / Redis / MQ）

与 Loop 集成：
    VerifyHandler 调用 ScenarioRunner.run_all()，
    结果写入 RunState.scenario_results 和 RunState.verification。
"""

from .models import (
    Assertion,
    AssertionOperator,
    AssertionType,
    Fixture,
    SanityCheckItem,
    SanityCheckResult,
    SanityReport,
    Scenario,
    ScenarioStep,
)
from .assertion import AssertionEngine, AssertionReport, AssertionResult
from .resources import (
    DatabaseAdapter,
    HttpAdapter,
    LogAdapter,
    MessageQueueAdapter,
    RedisAdapter,
    ResourceAdapter,
    default_adapters,
)
from .sanity import SanityChecker
from .runner import ScenarioReport, ScenarioResult, ScenarioRunner

__all__ = [
    # 场景模型
    "Scenario",
    "ScenarioStep",
    "Assertion",
    "AssertionType",
    "AssertionOperator",
    "Fixture",
    # 环境检查
    "SanityCheckItem",
    "SanityCheckResult",
    "SanityReport",
    "SanityChecker",
    # 断言引擎
    "AssertionEngine",
    "AssertionReport",
    "AssertionResult",
    # 执行引擎
    "ScenarioRunner",
    "ScenarioReport",
    "ScenarioResult",
    # 资源适配器
    "ResourceAdapter",
    "HttpAdapter",
    "DatabaseAdapter",
    "RedisAdapter",
    "MessageQueueAdapter",
    "LogAdapter",
    "default_adapters",
]
