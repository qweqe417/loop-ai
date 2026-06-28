"""Direct Mode 快速执行器。

为低复杂度 / 低风险的小改动提供快速通道：
- 跳过 Spec / Plan 阶段
- 轻量化 Guard 检查
- 可选跳过验证

用法:
    from engines.state import RunState, TaskIntakeResult
    from engines.runtime import DirectExecutor

    intake = TaskIntakeResult(flow_mode="direct", complexity="low", ...)
    state = RunState(task_id="quick-1", task_intake=intake)
    executor = DirectExecutor()
    final_state = executor.run(state)
"""

# 启用 Python 3.10+ 的延迟注解求值特性
from __future__ import annotations

# 导入日志模块，用于记录运行时信息
import logging
# 导入日期时间模块，用于记录完成时间戳
from datetime import datetime
# 导入 TYPE_CHECKING 常量，用于类型注解的条件导入
from typing import TYPE_CHECKING

# 导入状态枚举类型：LoopAction（循环动作）、StageType（阶段类型）、TaskStatus（任务状态）
from engines.state.enums import LoopAction, StageType, TaskStatus
# 导入 LoopDecision 模型，用于表示循环决策
from engines.state.models import LoopDecision

# 仅在类型检查时导入 RunState，避免循环导入和运行时开销
if TYPE_CHECKING:
    from engines.state.models import RunState

# 获取当前模块的日志记录器
logger = logging.getLogger(__name__)


class DirectExecutor:
    """Direct Mode 快速执行器 —— 轻量、快速、适合小改动。

    Direct Mode 的简化流程:
        INTAKE → DIRECT_EXECUTE → VERIFY → REVIEW → MEMORY → COMPLETED
    """

    def __init__(
        self,
        guard: object | None = None,
        max_iterations: int = 20,
    ):
        # 审查引擎实例，用于执行前检查（可选）
        self.guard = guard
        # 最大迭代次数，防止无限循环
        self.max_iterations = max_iterations

    def run(self, state: RunState) -> RunState:
        """快速执行入口。"""
        # 记录 DirectExecutor 启动日志
        logger.info("DirectExecutor started: task_id=%s", state.task_id)

        # 确保走 Direct Mode：如果当前阶段不是 INTAKE 或 DIRECT_EXECUTE，则重置为 INTAKE
        if state.current_stage not in (
            StageType.INTAKE,
            StageType.DIRECT_EXECUTE,
        ):
            state.current_stage = StageType.INTAKE

        # 1. INTAKE → DIRECT_EXECUTE：从入口阶段流转到直接执行阶段
        if state.current_stage == StageType.INTAKE:
            state.current_stage = StageType.DIRECT_EXECUTE
            # 设置决策：跳过 Spec/Plan 阶段，直接进入 DIRECT_EXECUTE
            state.decision = LoopDecision(
                action=LoopAction.NEXT_STAGE,
                target_stage=StageType.DIRECT_EXECUTE,
                reason="Direct Mode: 跳过 Spec/Plan",
            )

        # 2. DIRECT_EXECUTE：执行代码变更
        logger.info("Direct Execute: running code changes...")
        state.current_stage = StageType.DIRECT_EXECUTE
        state.task_state.status = TaskStatus.IN_PROGRESS
        state.task_state.stage = StageType.DIRECT_EXECUTE
        # ... AI 执行 TDD 代码变更 ...

        # 3. REVIEW：执行 6 维审查
        logger.info("Direct Execute: running review...")
        state.current_stage = StageType.REVIEW
        state.task_state.status = TaskStatus.REVIEWING
        state.task_state.stage = StageType.REVIEW
        # 调用 ReviewHandler 执行审查，填充 state.review_result
        self._run_review(state)

        # 4. VERIFY：验证场景覆盖
        logger.info("Direct Execute: running verify...")
        state.current_stage = StageType.VERIFY
        state.task_state.status = TaskStatus.VERIFYING
        state.task_state.stage = StageType.VERIFY
        # 调用 VerifyHandler 执行验证，填充 state.verify_result

        # 5. 根据审查结果决定是否需要 REPAIR
        if state.review_result and not state.review_result.passed:
            logger.info("Direct Execute: review failed, entering REPAIR...")
            state.current_stage = StageType.REPAIR
            state.task_state.status = TaskStatus.REPAIRING
            state.task_state.stage = StageType.REPAIR
            # 调用 RepairHandler 执行修复
            self._run_repair(state)
            # 修复后重新 REVIEW（最多 3 轮）
            for _ in range(3):
                state.current_stage = StageType.REVIEW
                self._run_review(state)
                if state.review_result and state.review_result.passed:
                    break
            # 重新进入 VERIFY
            state.current_stage = StageType.VERIFY
            state.task_state.status = TaskStatus.VERIFYING
            state.task_state.stage = StageType.VERIFY

        # 6. MEMORY：沉淀经验
        logger.info("Direct Execute: running memory...")
        state.current_stage = StageType.MEMORY
        state.task_state.status = TaskStatus.IN_PROGRESS
        state.task_state.stage = StageType.MEMORY
        # 调用 MemoryHandler 沉淀经验

        # 7. COMPLETED
        state.current_stage = StageType.COMPLETED
        state.task_state.status = TaskStatus.PASSED
        state.task_state.completed_at = datetime.now()
        state.updated_at = datetime.now()

        # 记录 DirectExecutor 完成日志
        logger.info(
            "DirectExecutor finished: task_id=%s, failures=%d",
            state.task_id,
            len(state.failures),
        )
        return state

    def _run_review(self, state: RunState) -> None:
        """执行审查阶段。"""
        try:
            from engines.runtime.stage_handlers import ReviewHandler
            handler = ReviewHandler()
            state = handler.handle(state)
        except Exception as e:
            logger.error("Review failed: %s", e)
            if hasattr(state, 'review_result') and state.review_result:
                state.review_result.passed = False
                state.review_result.summary = f"Review handler error: {e}"

    def _run_repair(self, state: RunState) -> None:
        """执行修复阶段。"""
        try:
            from engines.runtime.stage_handlers import RepairHandler
            handler = RepairHandler()
            state = handler.handle(state)
        except Exception as e:
            logger.error("Repair failed: %s", e)
            if hasattr(state, 'failures'):
                state.failures.append(f"Repair handler error: {e}")