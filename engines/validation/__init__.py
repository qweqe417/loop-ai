"""增量验证 —— Per-task 快速检查（compile / lint）。"""

from .quick_check import QuickCheckReport, QuickCheckResult, QuickCheckRunner, QuickCheckStatus

__all__ = [
    "QuickCheckRunner",
    "QuickCheckReport",
    "QuickCheckResult",
    "QuickCheckStatus",
]
