"""核心状态模块 —— 结构化状态模型。

提供 Loop Engineering 流程中的所有核心数据模型和枚举，
包括循环流转决策、任务状态、验证结果、失败记录和检查点。

顶层入口是 RunState，它是贯穿整个循环流程的单一数据载体。
"""

from .enums import (
    FailureCategory,
    LoopAction,
    StageType,
    TaskStatus,
    VerificationStatus,
)
from .models import (
    Checkpoint,
    FailureRecord,
    LoopDecision,
    RunState,
    ScenarioResult,
    TaskExecutionLog,
    TaskIntakeResult,
    TaskState,
    VerificationState,
)
from .serialization import (
    checkpoint_from_json,
    checkpoint_to_json,
    run_state_from_json,
    run_state_to_json,
)

__all__ = [
    # 枚举
    "StageType",
    "LoopAction",
    "TaskStatus",
    "VerificationStatus",
    "FailureCategory",
    # 模型
    "RunState",
    "TaskIntakeResult",
    "TaskState",
    "VerificationState",
    "ScenarioResult",
    "FailureRecord",
    "TaskExecutionLog",
    "Checkpoint",
    "LoopDecision",
    # 序列化
    "run_state_to_json",
    "run_state_from_json",
    "checkpoint_to_json",
    "checkpoint_from_json",
]
