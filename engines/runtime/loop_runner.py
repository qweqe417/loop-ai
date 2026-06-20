"""Loop Runner —— 核心循环引擎。

驱动 RunState 完成从任意入口阶段到退出阶段的循环流程。
支持子循环（Sub-Loop）：通过 entry_stage + exit_on_stages + 局部 handlers，
实现 test-only / dev-only / spec-only 等独立能力。

用法:
    from engines.state import RunState
    from engines.runtime import LoopRunner, create_sub_loop

    # 完整流程
    runner = LoopRunner()
    final = runner.run(state)

    # 仅测试子循环
    runner = create_sub_loop("test")
    final = runner.run(state)

    # 自定义子循环
    runner = LoopRunner(
        handlers={StageType.VERIFY: VerifyHandler(), StageType.REPAIR: RepairHandler()},
        entry_stage=StageType.VERIFY,
        exit_on_stages={StageType.COMPLETED, StageType.ABORTED},
    )
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from engines.state.enums import LoopAction, StageType
from engines.state.models import FailureRecord
from engines.runtime.stage_handlers import (
    DEFAULT_FLOW,
    StageHandler,
    default_handlers,
    is_terminal,
    next_stage,
)

if TYPE_CHECKING:
    from engines.state.models import RunState

logger = logging.getLogger(__name__)

# 安全上限
DEFAULT_MAX_ITERATIONS = 100
# 子循环上限（更短）
SUB_LOOP_MAX_ITERATIONS = 30
# 熔断阈值：同一失败签名重复 N 次后强制终止
CIRCUIT_BREAKER_THRESHOLD = 3

# ── 默认终端阶段 ────────────────────────────────────────────────

DEFAULT_EXIT_STAGES: set[StageType] = {StageType.COMPLETED, StageType.ABORTED}


class LoopRunner:
    """核心循环引擎 —— 支持完整循环和子循环。

    关键参数:
        handlers: 阶段处理器映射（子循环只注入需要的 handler）
        entry_stage: 强制入口阶段（None 则沿用 state.current_stage）
        exit_on_stages: 到达这些阶段时退出（默认 COMPLETED / ABORTED）
        flow: 自定义流转表（None 则用 DEFAULT_FLOW）
        guard: Guard 引擎实例
    """

    def __init__(
        self,
        handlers: dict[StageType, StageHandler] | None = None,
        *,
        entry_stage: StageType | None = None,
        exit_on_stages: set[StageType] | None = None,
        flow: dict[StageType, StageType | None] | None = None,
        guard: object | None = None,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
    ):
        self.handlers = handlers or default_handlers()
        self.entry_stage = entry_stage
        self.exit_on_stages = exit_on_stages or DEFAULT_EXIT_STAGES
        self._flow = flow or DEFAULT_FLOW
        self.guard = guard
        self.max_iterations = max_iterations

    # ── 流转表 ────────────────────────────────────────────────

    @property
    def flow(self) -> dict[StageType, StageType | None]:
        """当前使用的流转表。"""
        return self._flow

    def next_stage(self, current: StageType) -> StageType | None:
        """查询当前阶段默认的下一阶段。"""
        return self._flow.get(current)

    def is_exit(self, stage: StageType) -> bool:
        """判断阶段是否为退出点。"""
        return stage in self.exit_on_stages

    # ── 主循环 ────────────────────────────────────────────────

    def run(self, state: RunState) -> RunState:
        """驱动循环直到退出条件满足。"""
        # 入口阶段覆盖
        if self.entry_stage is not None:
            state.current_stage = self.entry_stage

        stage_names = ",".join(s.value for s in self.handlers)
        logger.info(
            "LoopRunner started: task_id=%s entry=%s handlers=[%s]",
            state.task_id,
            state.current_stage.value,
            stage_names,
        )

        for iteration in range(1, self.max_iterations + 1):
            logger.debug("Iteration %d: stage=%s", iteration, state.current_stage.value)

            # 1. 退出检查
            if self.is_exit(state.current_stage):
                return self._finalize(state)

            # 2. Guard 检查
            if self.guard is not None:
                blocked = self._run_guard_check(state)
                if blocked:
                    return state

            # 2.5 熔断检查：同一失败模式重复多次 → 强制终止
            breaker_msg = self._check_circuit_breaker(state)
            if breaker_msg:
                logger.error("Circuit breaker active, aborting loop")
                state.current_stage = StageType.ABORTED
                state.task_state.notes.append(breaker_msg)
                return self._finalize(state)

            # 3. 获取处理器
            handler = self.handlers.get(state.current_stage)
            if handler is None:
                # 没有 handler → 检查是否在退出集合中
                if self.is_exit(state.current_stage):
                    return self._finalize(state)
                # 不在退出集合但无 handler → 尝试默认流转
                target = self.next_stage(state.current_stage)
                if target is None:
                    # flow table 到头了 → 视为正常完成
                    logger.debug("Flow ended at %s, completing", state.current_stage.value)
                    state.current_stage = StageType.COMPLETED
                    return self._finalize(state)
                logger.debug(
                    "No handler for %s, auto-advancing to %s",
                    state.current_stage.value, target.value,
                )
                state.current_stage = target
                continue

            # 4. 执行阶段
            try:
                result = handler.handle(state)
                if result is None:
                    raise RuntimeError(
                        f"Handler {handler.stage.value} returned None — state corruption prevented"
                    )
                state = result
            except Exception as exc:
                logger.exception("Handler %s raised exception", handler.stage.value)
                state = self._handle_exception(state, handler.stage, exc)
                if self.is_exit(state.current_stage):
                    return self._finalize(state)
                continue

            # 4.5 检查是否需要暂停等待 AI 输入
            if state.needs_ai_input:
                # 验证: needs_ai_input 必须伴随有效的 pending_action
                if not state.pending_action:
                    logger.error(
                        "needs_ai_input=True but pending_action is empty — aborting"
                    )
                    state.current_stage = StageType.ABORTED
                    state.task_state.notes.append(
                        "[LOOP] 协议错误: needs_ai_input=True 但 pending_action 为空"
                    )
                    return self._finalize(state)
                logger.info(
                    "Pausing for AI input: stage=%s action=%s",
                    state.current_stage.value, state.pending_action,
                )
                return self._finalize(state)  # 返回当前状态，AI 读取后通过 CLI 恢复

            # 5. 应用流转决策
            state = self._apply_decision(state)

            # 6. 更新时间戳
            state.updated_at = datetime.now()

            # 7. 退出检查（决策可能导向退出阶段）
            if self.is_exit(state.current_stage):
                return self._finalize(state)

        # 超过最大迭代次数
        logger.error(
            "LoopRunner exceeded max iterations (%d): task=%s",
            self.max_iterations, state.task_id,
        )
        state.current_stage = StageType.ABORTED
        state.task_state.notes.append(f"超过最大迭代次数 {self.max_iterations}，强制终止")
        return self._finalize(state)

    # ── 熔断器 ──────────────────────────────────────────────

    def _check_circuit_breaker(self, state: RunState) -> str | None:
        """检测同模式重复失败，触发熔断时返回错误消息。

        如果最近 N 个 failure（N=THRESHOLD）具有相同签名，则触发熔断，
        防止 AI 在同一个问题上无限循环浪费 Token。
        """
        failures = state.failures
        if len(failures) < CIRCUIT_BREAKER_THRESHOLD:
            return None

        recent = failures[-CIRCUIT_BREAKER_THRESHOLD:]

        # 层1: 精确签名 (stage + category + message)
        exact_sigs = [self._failure_signature(f) for f in recent]
        if len(set(exact_sigs)) == 1:
            return self._build_breaker_message(recent, "精确", exact_sigs[0])

        # 层2: 跨阶段消息签名 (category + message, 忽略 stage)
        # 同一根因在不同阶段表现为不同错误时也能被检测
        message_sigs = [self._failure_message_signature(f) for f in recent]
        if len(set(message_sigs)) == 1:
            return self._build_breaker_message(recent, "跨阶段", message_sigs[0])

        return None

    def _build_breaker_message(
        self, recent: list, scope: str, sig: str,
    ) -> str:
        """构造熔断消息。"""
        logger.warning(
            "Circuit breaker triggered (%s): %d failures, sig=%s",
            scope, len(recent), sig,
        )
        return (
            f"熔断触发 ({scope}): 同一失败模式重复 {len(recent)} 次 "
            f"(stage={recent[-1].stage.value} category={recent[-1].category.value})。\n"
            f"最后错误: {recent[-1].message[:200]}\n"
            "建议: 分析根因后再重新开始，而非继续自动重试。"
        )

    @staticmethod
    def _failure_signature(failure) -> str:
        """为失败记录生成签名，用于检测重复模式。

        签名 = stage + category + 规范化消息（去掉数字/时间戳/ID）。
        """
        import re

        msg = failure.message[:120]
        # 去掉数字、UUID、时间戳、路径等易变部分
        normalized = re.sub(r'\d+', 'N', msg)
        normalized = re.sub(
            r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
            'UUID', normalized,
        )
        normalized = re.sub(r'[\w/\\]+\.\w{1,4}', 'FILE', normalized)
        return f"{failure.stage.value}|{failure.category.value}|{normalized}"

    @staticmethod
    def _failure_message_signature(failure) -> str:
        """跨阶段签名: category + 规范化消息（忽略 stage 差异）。"""
        import re

        msg = failure.message[:120]
        normalized = re.sub(r'\d+', 'N', msg)
        normalized = re.sub(
            r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
            'UUID', normalized,
        )
        normalized = re.sub(r'[\w/\\]+\.\w{1,4}', 'FILE', normalized)
        return f"{failure.category.value}|{normalized}"

    # ── 决策应用 ──────────────────────────────────────────────

    def _apply_decision(self, state: RunState) -> RunState:
        """根据 state.decision 更新 current_stage。"""
        decision = state.decision
        if decision is None:
            # 无决策 → 使用 flow table 的默认流转
            target = self.next_stage(state.current_stage)
            if target is None:
                # flow table 结束 → 视为正常完成
                logger.debug("Flow ended at %s, completing", state.current_stage.value)
                state.current_stage = StageType.COMPLETED
                return state
            logger.debug("Default flow: %s → %s", state.current_stage.value, target.value)
            state.current_stage = target
            return state

        action = decision.action
        logger.debug(
            "Decision: %s target=%s reason=%s",
            action.value,
            decision.target_stage.value if decision.target_stage else "-",
            decision.reason[:60],
        )

        if action == LoopAction.NEXT_STAGE and decision.target_stage:
            state.current_stage = decision.target_stage

        elif action == LoopAction.RETRY:
            if decision.target_stage:
                state.current_stage = decision.target_stage

        elif action == LoopAction.BACKTRACK and decision.target_stage:
            state.current_stage = decision.target_stage

        elif action == LoopAction.CONTINUE:
            pass  # 留在当前阶段

        elif action in (
            LoopAction.STOP_SUCCESS,
            LoopAction.STOP_FAILURE,
            LoopAction.STOP_GUARD,
            LoopAction.STOP_ABORT,
        ):
            target = (
                StageType.COMPLETED
                if action == LoopAction.STOP_SUCCESS
                else StageType.ABORTED
            )
            state.current_stage = decision.target_stage or target

        return state

    # ── Guard 检查 ────────────────────────────────────────────

    def _run_guard_check(self, state: RunState) -> bool:
        """执行 Guard 检查，返回 True 表示被阻止。"""
        try:
            result = self.guard.check(state)  # type: ignore[union-attr]
            if getattr(result, "block", False):
                logger.warning("Guard blocked: %s", getattr(result, "reason", ""))
                from engines.state.models import LoopDecision

                state.decision = LoopDecision(
                    action=LoopAction.STOP_GUARD,
                    target_stage=StageType.ABORTED,
                    reason=getattr(result, "reason", "Guard 拦截"),
                )
                state.current_stage = StageType.ABORTED
                return True
        except AttributeError:
            logger.debug("Guard object has no check() method, skipping")
        except Exception as exc:
            # Guard 异常时默认阻止，防止安全检查被绕过
            logger.exception("Guard check raised exception, blocking to be safe: %s", exc)
            from engines.state.models import LoopDecision

            state.decision = LoopDecision(
                action=LoopAction.STOP_GUARD,
                target_stage=StageType.ABORTED,
                reason=f"Guard 异常: {exc}",
            )
            state.current_stage = StageType.ABORTED
            return True
        return False

    # ── 异常处理 ──────────────────────────────────────────────

    def _handle_exception(
        self, state: RunState, stage: StageType, exc: Exception
    ) -> RunState:
        """处理器异常 → 记录 FailureRecord，中止。"""
        from engines.state.enums import FailureCategory

        state.failures.append(
            FailureRecord(
                category=FailureCategory.ENVIRONMENT,
                message=f"{type(exc).__name__}: {exc}",
                stage=stage,
                attempt_count=state.task_state.retry_count + 1,
            )
        )
        state.current_stage = StageType.ABORTED
        state.task_state.notes.append(f"异常终止于 {stage.value}: {exc}")
        return state

    # ── 清理 ──────────────────────────────────────────────────

    def _finalize(self, state: RunState) -> RunState:
        """循环结束清理。

        如果 needs_ai_input=True，标记为 PAUSED 而非终端状态，等待 AI 提交结果后恢复。
        """
        state.updated_at = datetime.now()
        if state.needs_ai_input:
            status = "PAUSED_WAITING_AI"
        elif state.current_stage == StageType.COMPLETED:
            status = "SUCCESS"
        elif state.current_stage == StageType.ABORTED:
            status = "ABORTED"
        else:
            status = "EXIT"
        logger.info(
            "LoopRunner finished: task=%s stage=%s status=%s failures=%d",
            state.task_id, state.current_stage.value, status, len(state.failures),
        )
        return state


# ══════════════════════════════════════════════════════════════════
# 子循环工厂
# ══════════════════════════════════════════════════════════════════

# 子循环预设：每个预设定义了 handler 集 + 入口阶段 + 自定义流转表
# key → CLI 命令对应: aicode <key>

from engines.runtime.stage_handlers import (
    DirectExecuteHandler,
    ExecuteHandler,
    IntakeHandler,
    MemoryHandler,
    PlanHandler,
    RepairHandler,
    ReviewHandler,
    SpecHandler,
    VerifyHandler,
)


# ── 子循环流转表 ──────────────────────────────────────────────
# 注：flow table 定义的是「成功/默认」路径。
#     异常分支（如 VERIFY 失败 → REPAIR）由 handler 通过 _advance_to() 覆盖。

# 仅测试：VERIFY 通过 → COMPLETED；失败 → handler 覆盖到 REPAIR → VERIFY
FLOW_TEST: dict[StageType, StageType | None] = {
    StageType.VERIFY: StageType.COMPLETED,
    StageType.REPAIR: StageType.VERIFY,
    StageType.COMPLETED: None,
    StageType.ABORTED: None,
}

# 开发模式：EXECUTE → VERIFY → REVIEW → COMPLETED（失败时 handler 覆盖到 REPAIR）
FLOW_DEV: dict[StageType, StageType | None] = {
    StageType.EXECUTE: StageType.VERIFY,
    StageType.VERIFY: StageType.REVIEW,
    StageType.REPAIR: StageType.VERIFY,
    StageType.REVIEW: StageType.COMPLETED,
    StageType.COMPLETED: None,
    StageType.ABORTED: None,
}

# Spec 生成：INTAKE → SPEC → COMPLETED（不写代码）
FLOW_SPEC: dict[StageType, StageType | None] = {
    StageType.INTAKE: StageType.SPEC,
    StageType.SPEC: StageType.COMPLETED,
    StageType.COMPLETED: None,
    StageType.ABORTED: None,
}

# Plan 生成：SPEC → PLAN → COMPLETED（不写代码）
FLOW_PLAN: dict[StageType, StageType | None] = {
    StageType.SPEC: StageType.PLAN,
    StageType.PLAN: StageType.COMPLETED,
    StageType.COMPLETED: None,
    StageType.ABORTED: None,
}

# Plan-only：已有 Spec，只生成 Plan（不写代码）
FLOW_PLAN_ONLY: dict[StageType, StageType | None] = {
    StageType.PLAN: StageType.COMPLETED,
    StageType.COMPLETED: None,
    StageType.ABORTED: None,
}

# Memory 沉淀：REVIEW → MEMORY → COMPLETED
FLOW_MEMORY: dict[StageType, StageType | None] = {
    StageType.REVIEW: StageType.MEMORY,
    StageType.MEMORY: StageType.COMPLETED,
    StageType.COMPLETED: None,
    StageType.ABORTED: None,
}


# ── 预设注册表 ──────────────────────────────────────────────────

SUB_LOOP_PRESETS: dict[str, dict] = {
    "full": {
        "handlers": default_handlers(),
        "entry_stage": StageType.INTAKE,
        "flow": DEFAULT_FLOW,
        "max_iterations": DEFAULT_MAX_ITERATIONS,
        "description": "完整 8 阶段流程",
    },
    "dev": {
        "handlers": {
            StageType.EXECUTE: ExecuteHandler(),
            StageType.VERIFY: VerifyHandler(),
            StageType.REPAIR: RepairHandler(),
            StageType.REVIEW: ReviewHandler(),
        },
        "entry_stage": StageType.EXECUTE,
        "flow": FLOW_DEV,
        "max_iterations": SUB_LOOP_MAX_ITERATIONS,
        "description": "开发模式：执行→验证→修复→审查（已有 Spec/Plan 时使用）",
    },
    "test": {
        "handlers": {
            StageType.VERIFY: VerifyHandler(),
            StageType.REPAIR: RepairHandler(),
        },
        "entry_stage": StageType.VERIFY,
        "flow": FLOW_TEST,
        "max_iterations": SUB_LOOP_MAX_ITERATIONS,
        "description": "测试模式：验证↻修复循环",
    },
    "spec": {
        "handlers": {
            StageType.INTAKE: IntakeHandler(),
            StageType.SPEC: SpecHandler(),
        },
        "entry_stage": StageType.INTAKE,
        "flow": FLOW_SPEC,
        "max_iterations": SUB_LOOP_MAX_ITERATIONS,
        "description": "Spec 生成：入口→规格生成→完成（不写代码）",
    },
    "plan": {
        "handlers": {
            StageType.SPEC: SpecHandler(),
            StageType.PLAN: PlanHandler(),
        },
        "entry_stage": StageType.SPEC,
        "flow": FLOW_PLAN,
        "max_iterations": SUB_LOOP_MAX_ITERATIONS,
        "description": "Spec+Plan 生成：入口→规格→计划→完成（不写代码，从需求开始）",
    },
    "plan-only": {
        "handlers": {
            StageType.PLAN: PlanHandler(),
        },
        "entry_stage": StageType.PLAN,
        "flow": FLOW_PLAN_ONLY,
        "max_iterations": SUB_LOOP_MAX_ITERATIONS,
        "description": "仅 Plan 生成：计划→完成（需要已有 Spec，通过 --state-file 传入）",
    },
    "verify": {
        "handlers": {
            StageType.VERIFY: VerifyHandler(),
        },
        "entry_stage": StageType.VERIFY,
        "flow": {
            StageType.VERIFY: StageType.COMPLETED,
            StageType.COMPLETED: None,
            StageType.ABORTED: None,
        },
        "max_iterations": SUB_LOOP_MAX_ITERATIONS,
        "description": "仅验证：单次验证→报告结果（不做修复）",
    },
    "review": {
        "handlers": {
            StageType.REVIEW: ReviewHandler(),
        },
        "entry_stage": StageType.REVIEW,
        "flow": {
            StageType.REVIEW: StageType.COMPLETED,
            StageType.COMPLETED: None,
            StageType.ABORTED: None,
        },
        "max_iterations": SUB_LOOP_MAX_ITERATIONS,
        "description": "仅审查：单次 Review→输出报告",
    },
    "memory": {
        "handlers": {
            StageType.REVIEW: ReviewHandler(),
            StageType.MEMORY: MemoryHandler(),
        },
        "entry_stage": StageType.REVIEW,
        "flow": FLOW_MEMORY,
        "max_iterations": SUB_LOOP_MAX_ITERATIONS,
        "description": "记忆沉淀：审查→记忆→完成",
    },
    "direct": {
        "handlers": {
            StageType.DIRECT_EXECUTE: DirectExecuteHandler(),
            StageType.VERIFY: VerifyHandler(),
            StageType.REVIEW: ReviewHandler(),
        },
        "entry_stage": StageType.DIRECT_EXECUTE,
        "flow": {
            StageType.DIRECT_EXECUTE: StageType.VERIFY,
            StageType.VERIFY: StageType.REVIEW,
            StageType.REVIEW: StageType.COMPLETED,
            StageType.COMPLETED: None,
            StageType.ABORTED: None,
        },
        "max_iterations": SUB_LOOP_MAX_ITERATIONS,
        "description": "Direct Mode：直接执行→验证→审查（小改动快速通道）",
    },
}


def create_sub_loop(name: str, **overrides) -> LoopRunner:
    """根据预设名创建子循环 Runner。

    Args:
        name: 预设名，可选: full / dev / test / spec / plan / verify / review / memory / direct
        **overrides: 覆盖预设参数（handlers / entry_stage / flow / guard / max_iterations）

    Returns:
        配置好的 LoopRunner 实例

    Raises:
        ValueError: 预设名不存在
    """
    preset = SUB_LOOP_PRESETS.get(name)
    if preset is None:
        available = ", ".join(SUB_LOOP_PRESETS)
        raise ValueError(f"Unknown sub-loop preset: {name!r}. Available: {available}")

    kwargs: dict = {
        "handlers": preset["handlers"],
        "entry_stage": preset["entry_stage"],
        "flow": preset["flow"],
        "max_iterations": preset["max_iterations"],
    }
    kwargs.update(overrides)
    return LoopRunner(**kwargs)


def list_sub_loops() -> dict[str, str]:
    """列出所有子循环预设及其描述。"""
    return {name: cfg["description"] for name, cfg in SUB_LOOP_PRESETS.items()}
