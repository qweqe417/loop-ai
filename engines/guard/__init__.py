"""Guard 模块 —— 代码变更安全守卫。

提供可插拔的规则检查引擎，在每个循环阶段前自动执行：
- 修改范围校验（ScopeBoundaryRule）
- 风险等级匹配（RiskLevelRule）
- 冒烟检查（SanityCheckRule）
- 反作弊规则（TestIntegrityRule / AssertionWeakeningRule / SkipModificationRule）
- 回滚计划生成（RollbackPlanner）

所有规则通过 Guard 引擎统一注册和执行，返回聚合的 GuardResult。
"""

from .models import GuardResult, GuardSeverity
from .rules import (
    AssertionWeakeningRule,
    FileSizeLimitRule,
    GuardRule,
    NetworkCallRule,
    RiskLevelRule,
    SanityCheckRule,
    ScopeBoundaryRule,
    SecretScanRule,
    SkipModificationRule,
    TestIntegrityRule,
)
from .engine import Guard, create_guard
from .code_quality import CodeQualityCheck, CodeQualityGate, CodeQualityReport
from .rollback import RollbackPlan, RollbackPlanner
from .quick_check import QuickCheckReport, QuickCheckResult, QuickCheckRunner, QuickCheckStatus
from .schema_version import SchemaVersionRecorder, detect_migration_files, is_migration_file

__all__ = [
    # 引擎
    "Guard",
    "create_guard",
    # 模型
    "GuardResult",
    "GuardSeverity",
    # 规则
    "GuardRule",
    "ScopeBoundaryRule",
    "RiskLevelRule",
    "SanityCheckRule",
    "TestIntegrityRule",
    "AssertionWeakeningRule",
    "SkipModificationRule",
    "FileSizeLimitRule",
    "NetworkCallRule",
    "SecretScanRule",
    # 回滚
    "RollbackPlanner",
    "RollbackPlan",
    # 代码质量
    "CodeQualityGate",
    "CodeQualityReport",
    "CodeQualityCheck",
    # Schema 版本
    "SchemaVersionRecorder",
    "detect_migration_files",
    "is_migration_file",
    # 增量验证
    "QuickCheckRunner",
    "QuickCheckReport",
    "QuickCheckResult",
    "QuickCheckStatus",
]
