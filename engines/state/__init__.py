"""核心状态模块 —— 结构化状态模型。

提供 Loop Engineering 流程中的所有核心数据模型和枚举，
包括循环流转决策、任务状态、验证结果、失败记录和检查点。

顶层入口是 RunState，它是贯穿整个循环流程的单一数据载体。
"""

# 从 enums 模块导入所有枚举类型
from .enums import (
    FailureCategory,       # 失败分类枚举：环境问题、测试数据、代码逻辑等
    LoopAction,            # 循环流转动作枚举：继续、下一阶段、重试、回溯、终止等
    StageType,             # 循环阶段类型枚举：INTAKE、SPEC、PLAN、EXECUTE 等
    TaskStatus,            # 任务执行状态枚举：等待中、执行中、验证中、通过、失败等
    VerificationStatus,    # 验证状态枚举：未验证、通过、失败、部分通过、跳过
)
# 从 models 模块导入所有核心数据模型
from .models import (
    Checkpoint,            # 检查点模型：关键阶段完成后保存快照，支持回溯
    FailureRecord,         # 失败记录模型：REPAIR 阶段的输入，MEMORY 阶段的素材
    LoopDecision,          # 循环流转决策模型：每个阶段结束后的产物
    RunState,              # 运行时状态模型：整个 Loop 的单一数据载体，贯穿所有阶段
    ScenarioResult,        # 场景验证结果模型：单个场景的执行记录
    TaskExecutionLog,      # 任务执行日志模型：每个 Task 完成后写入一条
    TaskIntakeResult,      # 任务入口分析结果模型：INTAKE 阶段产出
    TaskState,             # 任务执行状态模型：跟踪单次任务的生命周期
    VerificationState,     # 验证状态模型：VERIFY 阶段产出
)
# 从 serialization 模块导入序列化/反序列化工具函数
from .serialization import (
    checkpoint_from_json,  # 将 JSON 反序列化为 Checkpoint 对象
    checkpoint_to_json,    # 将 Checkpoint 对象序列化为 JSON 字符串
    run_state_from_json,   # 将 JSON 反序列化为 RunState 对象
    run_state_to_json,     # 将 RunState 对象序列化为 JSON 字符串
)

# 显式声明模块对外暴露的公共 API 列表
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