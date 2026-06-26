"""场景验证引擎模块。

提供自动化场景测试能力：加载 Scenario YAML 定义，执行步骤，
断言验证，生成测试报告。
"""

# 从 models 模块导入 Scenario 相关数据模型和枚举
from .models import (
    Assertion,
    AssertionOperator,
    AssertionType,
    AuthConfig,
    CleanupConfig,
    DeviceType,
    DomAssertion,
    Fixture,
    FixtureEntry,
    GivenConfig,
    SanityCheckItem,
    Scenario,
    ScenarioScope,
    ScenarioStep,
)
# 从 runner 模块导入场景执行引擎和结果类
from .runner import ScenarioReport, ScenarioResult, ScenarioRunner
# 从 assertion 模块导入断言引擎和报告类
from .assertion import AssertionEngine, AssertionReport, AssertionResult
# 从 sanity 模块导入健康检查器和报告类
from .sanity import SanityChecker, SanityCheckResult, SanityReport
# 从 resources 模块导入资源适配器及其工厂函数
from .resources import (
    HttpAdapter,
    ResourceAdapter,
    default_adapters,
)
# 从 failure_classifier 模块导入失败分类器
from .failure_classifier import FailureCategory, classify_failure, classify_assertion_failures
# 从 report_generator 模块导入测试报告生成器
from .report_generator import ReportGenerator
# 从 service_manager 模块导入服务管理器
from .service_manager import ServiceConfig, ServiceManager
# 从 auth_provider 模块导入鉴权提供者
from .auth_provider import AuthProvider
# 从 playwright_executor 模块导入前端执行器
from .playwright_executor import PlaywrightExecutor
# 从 safe_eval 模块导入安全表达式求值函数
from .safe_eval import safe_eval, safe_exec

# 模块公开接口列表
__all__ = [
    # 数据模型
    "Scenario",
    "ScenarioStep",
    "Assertion",
    "AssertionType",
    "AssertionOperator",
    "Fixture",
    "SanityCheckItem",
    # 增强模型
    "ScenarioScope",
    "DeviceType",
    "AuthConfig",
    "FixtureEntry",
    "GivenConfig",
    "CleanupConfig",
    "DomAssertion",
    # 引擎
    "ScenarioRunner",
    "ScenarioResult",
    "ScenarioReport",
    "AssertionEngine",
    "AssertionResult",
    "AssertionReport",
    "SanityChecker",
    "SanityCheckResult",
    "SanityReport",
    "FailureCategory",
    "classify_failure",
    "classify_assertion_failures",
    "ReportGenerator",
    "ServiceManager",
    "ServiceConfig",
    "AuthProvider",
    "PlaywrightExecutor",
    # 资源适配器
    "ResourceAdapter",
    "HttpAdapter",
    "default_adapters",
    # 安全求值
    "safe_eval",
    "safe_exec",
]