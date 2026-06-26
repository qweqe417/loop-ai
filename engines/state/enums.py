"""Loop Engineering 核心枚举定义。

定义整个循环流程中的阶段类型、流转动作、任务状态、
验证状态和失败分类。
"""

# 导入 Python 标准库的 Enum 基类，用于定义枚举类型
from enum import Enum


# 循环阶段类型枚举：标记 RunState 当前处于哪个阶段
class StageType(str, Enum):
    """循环阶段类型 —— 标记 RunState 当前处于哪个阶段。"""

    INTAKE = "intake"                # 任务入口：分析复杂度 / 风险 / 分流模式
    SPEC = "spec"                    # 规格生成：由 Provider 产出 spec 文档
    TEST_DESIGN = "test_design"      # 测试设计：生成测试用例与 Scenario 草案
    PLAN = "plan"                    # 计划生成：由 Provider 产出实施计划
    EXECUTE = "execute"              # 执行：实际写代码
    VERIFY = "verify"                # 验证：跑测试 / 场景回放
    REPAIR = "repair"                # 修复：失败后自动修复
    GATE = "gate"                    # 机械门禁：Layer1 规则检查（不调 AI）
    REVIEW = "review"                # 审查：Guard 检查 / 合规校验
    MEMORY = "memory"                # 记忆：沉淀经验到 .ai/memory
    DIRECT_EXECUTE = "direct_execute"  # 直接模式：小改动跳过 Spec/Plan
    COMPLETED = "completed"          # 正常终止
    ABORTED = "aborted"              # 异常终止（Guard 拦截 / 用户中断）


# 循环流转动作枚举：每个阶段结束后决定下一步做什么
class LoopAction(str, Enum):
    """循环流转动作 —— 每个阶段结束后决定下一步做什么。"""

    CONTINUE = "continue"             # 继续当前阶段
    NEXT_STAGE = "next_stage"         # 进入下一阶段
    RETRY = "retry"                   # 重试当前阶段
    BACKTRACK = "backtrack"           # 回退到上一阶段
    STOP_SUCCESS = "stop_success"     # 成功终止
    STOP_FAILURE = "stop_failure"     # 失败终止
    STOP_GUARD = "stop_guard"         # Guard 拦截终止
    STOP_ABORT = "stop_abort"         # 用户中断 / 异常终止


# 任务执行状态枚举：跟踪单次任务的执行生命周期
class TaskStatus(str, Enum):
    """任务执行状态 —— 跟踪单次任务的执行生命周期。"""

    PENDING = "pending"               # 排队等待
    IN_PROGRESS = "in_progress"       # 执行中
    VERIFYING = "verifying"           # 验证中
    PASSED = "passed"                 # 通过
    FAILED = "failed"                 # 失败
    REPAIRING = "repairing"           # 修复中
    SKIPPED = "skipped"               # 已跳过


# 验证状态枚举：场景验证 / 测试套件的结果
class VerificationStatus(str, Enum):
    """验证状态 —— 场景验证 / 测试套件的结果。"""

    UNVERIFIED = "unverified"         # 尚未验证
    PASSED = "passed"                 # 全部通过
    FAILED = "failed"                 # 存在失败
    PARTIAL = "partial"               # 部分通过（部分跳过）
    SKIPPED = "skipped"               # 验证被跳过


# 失败分类枚举：用于 Repair 阶段策略选择和 Memory 沉淀
class FailureCategory(str, Enum):
    """失败分类 —— 用于 Repai 阶段策略选择和 Memory 沉淀。"""

    ENVIRONMENT = "environment"       # 环境问题（依赖缺失 / 网络 / 权限）
    TEST_DATA = "test_data"           # 测试数据问题（fixture 过期 / DB 状态不匹配）
    CODE_LOGIC = "code_logic"         # 代码逻辑错误
    SCOPE_VIOLATION = "scope_violation"  # 修改超出授权范围
    PLAN_INSUFFICIENT = "plan_insufficient"  # 计划不充分 / 方案不可行
    UNKNOWN = "unknown"               # 未分类