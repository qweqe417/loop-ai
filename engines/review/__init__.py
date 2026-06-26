"""Review 模块 —— 代码审查门禁。

两层审查架构：
- Layer 1 (Python): 确定性检测 — SecretScan / TestIntegrity / ScopeBoundary /
  SkipDetection / AssertionDeletion / DiffBudget / LintIntegration
- Layer 2 (AI): 语义审查 — 读 git diff 做深度代码审查

ReviewEngine 编排 Layer1 + Layer2，下游项目可通过 extra_rules 扩展。
"""

# 导入审查结果和严重级别模型
from .models import ReviewResult, ReviewSeverity
# 导入所有内置审查规则
from .rules import (
    AssertionDeletionRule,   # 断言删除检测规则
    DiffBudgetRule,          # 变更预算检查规则
    LintIntegrationRule,     # Lint 集成规则
    ReviewRule,              # 审查规则基类
    ScopeBoundaryRule,       # 越界修改检测规则
    SecretScanRule,          # 硬编码凭证扫描规则
    SkipDetectionRule,       # 跳过标记检测规则
    TestIntegrityRule,       # 测试完整性检查规则
)
# 导入审查引擎和便捷工厂函数
from .engine import ReviewEngine, create_review_engine
# 导入 Schema 版本记录器及相关工具函数
from .schema_version import SchemaVersionRecorder, detect_migration_files, is_migration_file

# 公开的 API 列表
__all__ = [
    # 引擎
    "ReviewEngine",
    "create_review_engine",
    # 模型
    "ReviewResult",
    "ReviewSeverity",
    # 规则
    "ReviewRule",
    "AssertionDeletionRule",
    "DiffBudgetRule",
    "LintIntegrationRule",
    "SecretScanRule",
    "TestIntegrityRule",
    "ScopeBoundaryRule",
    "SkipDetectionRule",
    # Schema 版本
    "SchemaVersionRecorder",
    "detect_migration_files",
    "is_migration_file",
]