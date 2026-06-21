"""Test Design 模块 —— 从需求文档生成测试用例。

双入口设计：
  视图A（默认）：AI → Skill: xlsx → 测试用例.xlsx，给人看
  视图B（--mode full）：AI 生成 YAML → Python 管道校验/门禁/映射 → 3+1 个文件

Action Pipeline:
  steps 是结构化动作序列，每步可独立执行和断言。
  不再有独立的 trigger —— 触发动作是 steps 的一环。
"""

from .models import (
    AutomationCandidate,
    CleanupConfig,
    CoverageEntry,
    DataAssertion,
    DOMAssertion,
    ExpectedResult,
    OpenQuestion,
    QualityReport,
    RequirementItem,
    RiskLevel,
    Scope,
    Step,
    StepAction,
    StepAssertion,
    TestCase,
    TestDesignBundle,
    TestLevel,
    TestType,
)
from .serialization import (
    read_test_cases_yaml,
    write_quality_report_md,
    write_scenario_drafts_yaml,
    write_test_cases_yaml,
)
from .quality_gate import QualityGate
from .scenario_mapper import ScenarioMapper
from .xlsx_writer import write_xlsx

__all__ = [
    # 模型
    "Scope",
    "StepAction",
    "Step",
    "StepAssertion",
    "TestCase",
    "RequirementItem",
    "ExpectedResult",
    "DataAssertion",
    "DOMAssertion",
    "CleanupConfig",
    "AutomationCandidate",
    "CoverageEntry",
    "OpenQuestion",
    "TestDesignBundle",
    "QualityReport",
    "TestLevel",
    "TestType",
    "RiskLevel",
    # 序列化
    "write_test_cases_yaml",
    "read_test_cases_yaml",
    "write_scenario_drafts_yaml",
    "write_quality_report_md",
    # 质量门禁
    "QualityGate",
    # Scenario 映射
    "ScenarioMapper",
    # xlsx 导出
    "write_xlsx",
]
