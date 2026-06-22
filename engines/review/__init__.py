"""Review 模块 —— 代码审查门禁。

两层审查架构：
- Layer 1 (Python): 确定性检测 — SecretScan / TestIntegrity / ScopeBoundary / SkipDetection
- Layer 2 (AI): 语义审查 — 读 git diff 做深度代码审查

ReviewEngine 编排 Layer1 + Layer2，下游项目可通过 extra_rules 扩展。
"""

from .models import ReviewResult, ReviewSeverity
from .rules import (
    ReviewRule,
    ScopeBoundaryRule,
    SecretScanRule,
    SkipDetectionRule,
    TestIntegrityRule,
)
from .engine import ReviewEngine, create_review_engine
from .schema_version import SchemaVersionRecorder, detect_migration_files, is_migration_file

__all__ = [
    # 引擎
    "ReviewEngine",
    "create_review_engine",
    # 模型
    "ReviewResult",
    "ReviewSeverity",
    # 规则
    "ReviewRule",
    "SecretScanRule",
    "TestIntegrityRule",
    "ScopeBoundaryRule",
    "SkipDetectionRule",
    # Schema 版本
    "SchemaVersionRecorder",
    "detect_migration_files",
    "is_migration_file",
]
