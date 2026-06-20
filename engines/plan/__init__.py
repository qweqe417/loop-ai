"""Plan 执行合约模块。

提供:
- PlanContract: 完整执行合约（allowedFiles / forbiddenFiles / diffBudget / links / styleContract / reuseCheck）
- PlanLock: 锁定状态管理（LOCKED / CHANGE_REQUESTED / BREACHED / UNLOCKED）
- ContractValidator: 合约合规检查
- PlanQualityGate: Plan 质量门禁（架构 §8.6.10）
- DiffBudget: 变更预算追踪
- PlanChangeRequest: Plan 变更请求
- TaskLinks / StyleContract / ReuseCheck: 合约子结构
"""

from engines.plan.models import (
    DiffBudget,
    PlanChangeRequest,
    PlanComplianceReport,
    PlanContract,
    PlanLockState,
    PlanQualityReport,
    ReuseCheck,
    StyleContract,
    TaskLinks,
)
from engines.plan.contracts import ContractValidator
from engines.plan.lock import PlanLock
from engines.plan.quality_gate import PlanQualityGate

__all__ = [
    "PlanContract",
    "PlanLock",
    "ContractValidator",
    "PlanQualityGate",
    "DiffBudget",
    "PlanChangeRequest",
    "PlanComplianceReport",
    "PlanQualityReport",
    "PlanLockState",
    "TaskLinks",
    "StyleContract",
    "ReuseCheck",
]
