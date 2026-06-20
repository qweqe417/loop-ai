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

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from engines.state.enums import LoopAction, StageType, TaskStatus
from engines.state.models import LoopDecision

if TYPE_CHECKING:
    from engines.state.models import RunState

logger = logging.getLogger(__name__)


class DirectExecutor:
    """Direct Mode 快速执行器 —— 轻量、快速、适合小改动。

    Direct Mode 的简化流程:
        INTAKE → DIRECT_EXECUTE → VERIFY → REVIEW → MEMORY → COMPLETED
                       ↓ (verification_required=False 时跳过 VERIFY)
    """

    def __init__(
        self,
        guard: object | None = None,
        max_iterations: int = 20,
    ):
        self.guard = guard
        self.max_iterations = max_iterations

    def run(self, state: RunState) -> RunState:
        """快速执行入口。"""
        logger.info("DirectExecutor started: task_id=%s", state.task_id)

        # 确保走 Direct Mode
        if state.current_stage not in (
            StageType.INTAKE,
            StageType.DIRECT_EXECUTE,
        ):
            state.current_stage = StageType.INTAKE

        # 1. INTAKE → DIRECT_EXECUTE
        if state.current_stage == StageType.INTAKE:
            state.current_stage = StageType.DIRECT_EXECUTE
            state.decision = LoopDecision(
                action=LoopAction.NEXT_STAGE,
                target_stage=StageType.DIRECT_EXECUTE,
                reason="Direct Mode: 跳过 Spec/Plan",
            )

        # 2. DIRECT_EXECUTE
        logger.info("Direct Execute: running code changes...")
        state.task_state.status = TaskStatus.IN_PROGRESS
        state.task_state.stage = StageType.DIRECT_EXECUTE

        # 3. 决定是否需要验证
        intake = state.task_intake
        skip_verify = intake and not intake.verification_required

        if skip_verify:
            state.current_stage = StageType.REVIEW
            state.decision = LoopDecision(
                action=LoopAction.NEXT_STAGE,
                target_stage=StageType.REVIEW,
                reason="Direct Mode: 跳过验证",
            )
        else:
            state.current_stage = StageType.VERIFY
            state.decision = LoopDecision(
                action=LoopAction.NEXT_STAGE,
                target_stage=StageType.VERIFY,
                reason="Direct Mode: 进入验证",
            )

        # 4. VERIFY（如果需要）
        if not skip_verify:
            state.task_state.status = TaskStatus.VERIFYING
            state.task_state.stage = StageType.VERIFY
            # 验证逻辑由 ScenarioRunner 负责，此处仅流转
            state.current_stage = StageType.REVIEW

        # 5. REVIEW → MEMORY → COMPLETED
        state.current_stage = StageType.REVIEW
        state.task_state.stage = StageType.REVIEW
        # Review 逻辑由 Guard 负责

        state.current_stage = StageType.MEMORY
        state.task_state.stage = StageType.MEMORY

        state.current_stage = StageType.COMPLETED
        state.task_state.status = TaskStatus.PASSED
        state.task_state.completed_at = datetime.now()
        state.updated_at = datetime.now()

        logger.info(
            "DirectExecutor finished: task_id=%s, failures=%d",
            state.task_id,
            len(state.failures),
        )
        return state
