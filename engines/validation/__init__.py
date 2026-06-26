"""增量验证 —— Per-task 快速检查（compile / lint）。"""

# 从 quick_check 模块导入快速检查相关的类和枚举
from .quick_check import QuickCheckReport, QuickCheckResult, QuickCheckRunner, QuickCheckStatus

# 显式声明模块对外暴露的公共 API 列表
__all__ = [
    "QuickCheckRunner",     # 快速检查执行器类
    "QuickCheckReport",     # 快速检查汇总报告类
    "QuickCheckResult",     # 单项快速检查结果类
    "QuickCheckStatus",     # 快速检查状态枚举
]