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

# 启用 Python 3.10+ 的延迟注解求值特性
from __future__ import annotations

# 导入日志模块，用于记录循环执行过程
import logging
# 导入日期时间模块，用于更新时间戳
from datetime import datetime
# 导入 TYPE_CHECKING 常量，用于类型注解的条件导入
from typing import TYPE_CHECKING

# 导入状态枚举类型：LoopAction（循环动作）、StageType（阶段类型）
from engines.state.enums import LoopAction, StageType
# 导入 FailureRecord 模型，用于记录失败信息
from engines.state.models import FailureRecord
# 从 stage_handlers 模块导入阶段流转相关工具
from engines.runtime.stage_handlers import (
    DEFAULT_FLOW,
    StageHandler,
    default_handlers,
    is_terminal,
    next_stage,
)

# 仅在类型检查时导入 RunState，避免循环导入
if TYPE_CHECKING:
    from engines.state.models import RunState

# 获取当前模块的日志记录器
logger = logging.getLogger(__name__)

# 安全上限：默认最大迭代次数，防止无限循环
DEFAULT_MAX_ITERATIONS = 30
# 子循环上限（更短），子循环通常范围更小
SUB_LOOP_MAX_ITERATIONS = 30
# 熔断阈值：同一失败签名重复 N 次后强制终止，防止 AI 在同一个问题上无限循环
CIRCUIT_BREAKER_THRESHOLD = 3

# ── 默认终端阶段 ────────────────────────────────────────────────

# 默认退出阶段集合：到达 COMPLETED 或 ABORTED 时退出循环
DEFAULT_EXIT_STAGES: set[StageType] = {StageType.COMPLETED, StageType.ABORTED}


class LoopRunner:
    """核心循环引擎 —— 支持完整循环和子循环。

    关键参数:
        handlers: 阶段处理器映射（子循环只注入需要的 handler）
        entry_stage: 强制入口阶段（None 则沿用 state.current_stage）
        exit_on_stages: 到达这些阶段时退出（默认 COMPLETED / ABORTED）
        flow: 自定义流转表（None 则用 DEFAULT_FLOW）
        review: ReviewEngine 实例（可选，每轮迭代前运行 Layer1 检查）
    """

    def __init__(
        self,
        handlers: dict[StageType, StageHandler] | None = None,
        *,
        entry_stage: StageType | None = None,
        exit_on_stages: set[StageType] | None = None,
        flow: dict[StageType, StageType | None] | None = None,
        review: object | None = None,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
    ):
        # 阶段处理器映射，默认使用内置处理器
        self.handlers = handlers or default_handlers()
        # 强制入口阶段，覆盖 state 的当前阶段
        self.entry_stage = entry_stage
        # 退出阶段集合，默认使用 DEFAULT_EXIT_STAGES
        self.exit_on_stages = exit_on_stages or DEFAULT_EXIT_STAGES
        # 自定义流转表，默认使用 DEFAULT_FLOW
        self._flow = flow or DEFAULT_FLOW
        # Review 审查引擎实例（可选）
        self.review = review
        # 最大迭代次数
        self.max_iterations = max_iterations

    # ── 流转表 ────────────────────────────────────────────────

    @property
    def flow(self) -> dict[StageType, StageType | None]:
        """当前使用的流转表。"""
        return self._flow

    def next_stage(self, current: StageType) -> StageType | None:
        """查询当前阶段默认的下一阶段。

        Args:
            current: 当前阶段类型

        Returns:
            StageType | None: 下一阶段，None 表示流程结束
        """
        return self._flow.get(current)

    def is_exit(self, stage: StageType) -> bool:
        """判断阶段是否为退出点。

        Args:
            stage: 要检查的阶段类型

        Returns:
            bool: 是否为退出阶段
        """
        return stage in self.exit_on_stages

    # ── 主循环 ────────────────────────────────────────────────

    def run(self, state: RunState) -> RunState:
        """驱动循环直到退出条件满足。

        Args:
            state: 当前运行状态对象

        Returns:
            RunState: 最终的运行状态
        """
        # 入口阶段覆盖：仅首次启动时应用，resume 沿用 state 已有阶段
        if self.entry_stage is not None and not state.metadata.get("_entry_stage_applied"):
            state.current_stage = self.entry_stage
            state.metadata["_entry_stage_applied"] = True

        # 构建阶段名称列表用于日志
        stage_names = ",".join(s.value for s in self.handlers)
        logger.info(
            "LoopRunner started: task_id=%s entry=%s handlers=[%s]",
            state.task_id,
            state.current_stage.value,
            stage_names,
        )

        # 主迭代循环：从 1 到 max_iterations
        for iteration in range(1, self.max_iterations + 1):
            logger.debug("Iteration %d: stage=%s", iteration, state.current_stage.value)

            # 1. 退出检查：如果当前阶段是退出阶段，结束循环
            if self.is_exit(state.current_stage):
                return self._finalize(state)

            # 2. Review 检查（可选，每轮迭代前运行 Layer1 审查）
            if self.review is not None:
                blocked = self._run_review_check(state)
                if blocked:
                    # 被审查阻止，直接返回当前状态
                    return state

            # 2.5 熔断检查：同一失败模式重复多次 → 强制终止
            breaker_msg = self._check_circuit_breaker(state)
            if breaker_msg:
                # 熔断器触发，记录错误并中止
                logger.error("Circuit breaker active, aborting loop")
                state.current_stage = StageType.ABORTED
                state.task_state.notes.append(breaker_msg)
                return self._finalize(state)

            # 3. 获取当前阶段的处理器
            handler = self.handlers.get(state.current_stage)
            if handler is None:
                # 没有 handler → 检查是否在退出集合中
                if self.is_exit(state.current_stage):
                    return self._finalize(state)
                # 不在退出集合但无 handler → 尝试使用默认流转表
                target = self.next_stage(state.current_stage)
                if target is None:
                    # 流转表到头了 → 视为正常完成
                    logger.debug("Flow ended at %s, completing", state.current_stage.value)
                    state.current_stage = StageType.COMPLETED
                    return self._finalize(state)
                # 自动推进到下一阶段
                logger.debug(
                    "No handler for %s, auto-advancing to %s",
                    state.current_stage.value, target.value,
                )
                state.current_stage = target
                continue

            # 4. 执行阶段处理器
            try:
                result = handler.handle(state)
                if result is None:
                    # 处理器返回 None 是严重错误，阻止状态损坏
                    raise RuntimeError(
                        f"Handler {handler.stage.value} returned None — state corruption prevented"
                    )
                state = result
            except Exception as exc:
                # 处理器抛出异常，记录并处理
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

            # 5. 应用流转决策：根据 state.decision 决定下一阶段
            state = self._apply_decision(state)

            # 6. 更新时间戳
            state.updated_at = datetime.now()

            # 7. 退出检查（决策可能导向退出阶段）
            if self.is_exit(state.current_stage):
                return self._finalize(state)

        # 超过最大迭代次数，强制终止
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

        双层检测:
        - 层1 (精确): stage + category + 规范化消息 — 完全相同错误
        - 层2 (模糊): 仅 category — 同类失败跨阶段的累积效应

        Args:
            state: 当前运行状态

        Returns:
            str | None: 触发熔断时返回错误消息，否则返回 None
        """
        failures = state.failures
        if len(failures) < CIRCUIT_BREAKER_THRESHOLD:
            # 失败记录不足阈值，不触发熔断
            return None

        # 取最近 N 条失败记录
        recent = failures[-CIRCUIT_BREAKER_THRESHOLD:]

        # 层1: 精确签名检测 (stage + category + 规范化消息)
        exact_sigs = [self._failure_signature(f) for f in recent]
        if len(set(exact_sigs)) == 1:
            # 所有签名相同，触发精确熔断
            return self._build_breaker_message(recent, "精确", exact_sigs[0])

        # 层2: 类别签名检测 (仅 category) — 同一类别错误在不同阶段累积出现
        # 用于捕获 "同根因导致不同类型错误" 的模式（如：逻辑错误在
        # EXECUTE→VALIDATION_FAILURE, VERIFY→TEST_FAILURE, REPAIR→LOGIC_ERROR）
        category_sigs = [f.category.value for f in recent]
        if len(set(category_sigs)) == 1:
            # 所有失败属于同一类别，触发模糊熔断
            return self._build_breaker_message(
                recent, "同类", f"category={category_sigs[0]}"
            )

        return None

    def _build_breaker_message(
        self, recent: list, scope: str, sig: str,
    ) -> str:
        """构造熔断消息。

        Args:
            recent: 最近 N 条失败记录列表
            scope: 检测范围（"精确" 或 "同类"）
            sig: 失败签名

        Returns:
            str: 格式化的熔断消息
        """
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

        Args:
            failure: FailureRecord 对象

        Returns:
            str: 生成的失败签名
        """
        import re

        msg = failure.message[:120]
        # 去掉数字、UUID、时间戳、路径等易变部分，使签名更稳定
        normalized = re.sub(r'\d+', 'N', msg)
        normalized = re.sub(
            r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
            'UUID', normalized,
        )
        normalized = re.sub(r'[\w/\\]+\.\w{1,4}', 'FILE', normalized)
        # 组合 stage、category 和规范化消息
        return f"{failure.stage.value}|{failure.category.value}|{normalized}"

    # ── 决策应用 ──────────────────────────────────────────────

    def _apply_decision(self, state: RunState) -> RunState:
        """根据 state.decision 更新 current_stage。

        Args:
            state: 当前运行状态

        Returns:
            RunState: 更新后的运行状态
        """
        decision = state.decision
        if decision is None:
            # 无决策 → 使用 flow table 的默认流转
            target = self.next_stage(state.current_stage)
            if target is None:
                # 流转表结束 → 视为正常完成
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
            # 进入指定阶段
            state.current_stage = decision.target_stage

        elif action == LoopAction.RETRY:
            if decision.target_stage:
                # 重试，进入指定阶段
                state.current_stage = decision.target_stage

        elif action == LoopAction.BACKTRACK and decision.target_stage:
            # 回溯，回到之前的阶段
            state.current_stage = decision.target_stage

        elif action == LoopAction.CONTINUE:
            pass  # 留在当前阶段，不做任何修改

        elif action in (
            LoopAction.STOP_SUCCESS,
            LoopAction.STOP_FAILURE,
            LoopAction.STOP_GUARD,
            LoopAction.STOP_ABORT,
        ):
            # 各种停止动作：根据动作类型决定目标状态
            target = (
                StageType.COMPLETED
                if action == LoopAction.STOP_SUCCESS
                else StageType.ABORTED
            )
            state.current_stage = decision.target_stage or target

        return state

    # ── Review 检查 ────────────────────────────────────────────

    def _run_review_check(self, state: RunState) -> bool:
        """执行 Review Layer1 检查，返回 True 表示被阻止。

        Args:
            state: 当前运行状态

        Returns:
            bool: True 表示被审查阻止，False 表示通过
        """
        try:
            result = self.review.check(state)  # type: ignore[union-attr]
            if getattr(result, "block", False):
                # 审查阻止，设置决策为 STOP_GUARD
                logger.warning("Review blocked: %s", getattr(result, "reason", ""))
                from engines.state.models import LoopDecision

                state.decision = LoopDecision(
                    action=LoopAction.STOP_GUARD,
                    target_stage=StageType.ABORTED,
                    reason=getattr(result, "reason", "Review 拦截"),
                )
                state.current_stage = StageType.ABORTED
                return True
        except AttributeError:
            # review 对象没有 check 方法，跳过
            logger.debug("Review object has no check() method, skipping")
        except Exception as exc:
            # Review 异常时默认阻止，防止安全检查被绕过
            logger.exception("Review check raised exception, blocking to be safe: %s", exc)
            from engines.state.models import LoopDecision

            state.decision = LoopDecision(
                action=LoopAction.STOP_GUARD,
                target_stage=StageType.ABORTED,
                reason=f"Review 异常: {exc}",
            )
            state.current_stage = StageType.ABORTED
            return True
        return False

    # ── 异常处理 ──────────────────────────────────────────────

    def _handle_exception(
        self, state: RunState, stage: StageType, exc: Exception
    ) -> RunState:
        """处理器异常 → 记录 FailureRecord，中止执行。

        Args:
            state: 当前运行状态
            stage: 发生异常时所在的阶段
            exc: 捕获的异常对象

        Returns:
            RunState: 更新后的运行状态
        """
        from engines.state.enums import FailureCategory

        # 记录环境类失败记录
        state.failures.append(
            FailureRecord(
                category=FailureCategory.ENVIRONMENT,
                message=f"{type(exc).__name__}: {exc}",
                stage=stage,
                attempt_count=state.task_state.retry_count + 1,
            )
        )
        # 设置当前阶段为中止
        state.current_stage = StageType.ABORTED
        state.task_state.notes.append(f"异常终止于 {stage.value}: {exc}")
        return state

    # ── 清理 ──────────────────────────────────────────────────

    def _finalize(self, state: RunState) -> RunState:
        """循环结束清理。

        如果 needs_ai_input=True，标记为 PAUSED 而非终端状态，等待 AI 提交结果后恢复。

        Args:
            state: 当前运行状态

        Returns:
            RunState: 最终的运行状态
        """
        state.updated_at = datetime.now()
        if state.needs_ai_input:
            # 等待 AI 输入，状态为暂停
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

# 从 stage_handlers 模块导入各个阶段处理器类
from engines.runtime.stage_handlers import (
    DirectExecuteHandler,
    ExecuteHandler,
    GateHandler,
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

# 仅测试流转表：VERIFY 通过 → COMPLETED；失败 → handler 覆盖到 REPAIR → VERIFY
FLOW_TEST: dict[StageType, StageType | None] = {
    StageType.VERIFY: StageType.MEMORY,
    StageType.REPAIR: StageType.VERIFY,
    StageType.MEMORY: StageType.COMPLETED,
    StageType.COMPLETED: None,
    StageType.ABORTED: None,
}

# 开发模式 (loop) 流转表: EXECUTE → REVIEW ⇄ REPAIR → VERIFY → MEMORY → COMPLETED
# REVIEW 在 VERIFY 之前：先静态审查，通过后再场景验证
# REPAIR 由 handler 通过 _advance_to 覆盖：VERIFY 失败 → REPAIR → VERIFY
FLOW_DEV: dict[StageType, StageType | None] = {
    StageType.EXECUTE: StageType.REVIEW,
    StageType.REVIEW: StageType.VERIFY,
    StageType.VERIFY: StageType.MEMORY,
    StageType.REPAIR: StageType.VERIFY,
    StageType.MEMORY: StageType.COMPLETED,
    StageType.COMPLETED: None,
    StageType.ABORTED: None,
}

# SDD 后验证流转表: GATE → VERIFY ⇄ REPAIR → MEMORY → COMPLETED
# 执行由 SDD 完成，loop 只做机械门禁 + 场景验证 + 记忆沉淀
FLOW_DEV_VERIFY: dict[StageType, StageType | None] = {
    StageType.GATE: StageType.VERIFY,
    StageType.VERIFY: StageType.MEMORY,
    StageType.REPAIR: StageType.VERIFY,
    StageType.MEMORY: StageType.COMPLETED,
    StageType.COMPLETED: None,
    StageType.ABORTED: None,
}

# Gate-only 流转表: GATE → COMPLETED（仅机械门禁，不过场景）
FLOW_GATE: dict[StageType, StageType | None] = {
    StageType.GATE: StageType.COMPLETED,
    StageType.COMPLETED: None,
    StageType.ABORTED: None,
}

# 开发模式 (standalone) 流转表: EXECUTE → COMPLETED（仅生成代码，不验证）
FLOW_DEV_ONLY: dict[StageType, StageType | None] = {
    StageType.EXECUTE: StageType.COMPLETED,
    StageType.COMPLETED: None,
    StageType.ABORTED: None,
}

# Direct 模式 (loop) 流转表: DIRECT_EXECUTE → REVIEW ⇄ REPAIR → VERIFY → COMPLETED
# REVIEW 在 VERIFY 之前：先静态审查，通过后再场景验证
FLOW_DIRECT_LOOP: dict[StageType, StageType | None] = {
    StageType.DIRECT_EXECUTE: StageType.REVIEW,
    StageType.REVIEW: StageType.VERIFY,
    StageType.VERIFY: StageType.MEMORY,
    StageType.REPAIR: StageType.VERIFY,
    StageType.MEMORY: StageType.COMPLETED,
    StageType.COMPLETED: None,
    StageType.ABORTED: None,
}

# Direct 模式 (standalone) 流转表: DIRECT_EXECUTE → COMPLETED（仅生成代码，不验证）
FLOW_DIRECT_ONLY: dict[StageType, StageType | None] = {
    StageType.DIRECT_EXECUTE: StageType.COMPLETED,
    StageType.COMPLETED: None,
    StageType.ABORTED: None,
}

# Spec 生成流转表：INTAKE → SPEC → COMPLETED（不写代码，仅生成规格）
FLOW_SPEC: dict[StageType, StageType | None] = {
    StageType.INTAKE: StageType.SPEC,
    StageType.SPEC: StageType.COMPLETED,
    StageType.COMPLETED: None,
    StageType.ABORTED: None,
}

# Plan 生成流转表：SPEC → PLAN → COMPLETED（不写代码，仅生成计划）
FLOW_PLAN: dict[StageType, StageType | None] = {
    StageType.SPEC: StageType.PLAN,
    StageType.PLAN: StageType.COMPLETED,
    StageType.COMPLETED: None,
    StageType.ABORTED: None,
}

# Plan-only 流转表：已有 Spec，只生成 Plan（不写代码）
FLOW_PLAN_ONLY: dict[StageType, StageType | None] = {
    StageType.PLAN: StageType.COMPLETED,
    StageType.COMPLETED: None,
    StageType.ABORTED: None,
}

# Memory 沉淀流转表：REVIEW → MEMORY → COMPLETED
FLOW_MEMORY: dict[StageType, StageType | None] = {
    StageType.REVIEW: StageType.MEMORY,
    StageType.MEMORY: StageType.COMPLETED,
    StageType.COMPLETED: None,
    StageType.ABORTED: None,
}

# Post-SDD 流转表: REVIEW → VERIFY ⇄ REPAIR → MEMORY → COMPLETED
# SDD 完成后的审查+验证+记忆沉淀，入口是 REVIEW（跳过 EXECUTE）
FLOW_POST_SDD: dict[StageType, StageType | None] = {
    StageType.REVIEW: StageType.VERIFY,
    StageType.VERIFY: StageType.MEMORY,
    StageType.REPAIR: StageType.VERIFY,
    StageType.MEMORY: StageType.COMPLETED,
    StageType.COMPLETED: None,
    StageType.ABORTED: None,
}

# Direct Post-TDD 流转表: REVIEW → GATE → MEMORY → COMPLETED
# TDD 完成后的审查+机械门禁+记忆沉淀，入口是 REVIEW（小改动，不需要场景验证）
FLOW_DIRECT_POST_TDD: dict[StageType, StageType | None] = {
    StageType.REVIEW: StageType.GATE,
    StageType.GATE: StageType.MEMORY,
    StageType.MEMORY: StageType.COMPLETED,
    StageType.COMPLETED: None,
    StageType.ABORTED: None,
}


# ── 预设注册表 ──────────────────────────────────────────────────

# 子循环预设字典：key 为预设名称，value 为配置字典
SUB_LOOP_PRESETS: dict[str, dict] = {
    "full": {
        "handlers": default_handlers(),
        "entry_stage": StageType.INTAKE,
        "flow": DEFAULT_FLOW,
        "max_iterations": DEFAULT_MAX_ITERATIONS,
        "description": "完整 8 阶段流程",
    },
    # ── Dev-Verify: SDD 执行后验证 ──
    "dev-verify": {
        "handlers": {
            StageType.GATE: GateHandler(),
            StageType.VERIFY: VerifyHandler(),
            StageType.REPAIR: RepairHandler(),
            StageType.MEMORY: MemoryHandler(),
        },
        "entry_stage": StageType.GATE,
        "flow": FLOW_DEV_VERIFY,
        "max_iterations": SUB_LOOP_MAX_ITERATIONS,
        "description": "SDD 后验证：Gate 门禁 → 场景验证↻修复 → 记忆沉淀",
    },
    "gate": {
        "handlers": {
            StageType.GATE: GateHandler(),
        },
        "entry_stage": StageType.GATE,
        "flow": FLOW_GATE,
        "max_iterations": SUB_LOOP_MAX_ITERATIONS,
        "description": "仅机械门禁：Layer1 规则检查 → 完成",
    },
    # ── Dev: loop + standalone ──
    "dev": {
        "handlers": {
            StageType.EXECUTE: ExecuteHandler(),
            StageType.VERIFY: VerifyHandler(),
            StageType.REPAIR: RepairHandler(),
            StageType.REVIEW: ReviewHandler(),
            StageType.MEMORY: MemoryHandler(),
        },
        "entry_stage": StageType.EXECUTE,
        "flow": FLOW_DEV,
        "max_iterations": SUB_LOOP_MAX_ITERATIONS,
        "description": "Dev 完整 loop：执行→验证↻修复→审查→记忆沉淀",
    },
    "dev-only": {
        "handlers": {
            StageType.EXECUTE: ExecuteHandler(),
        },
        "entry_stage": StageType.EXECUTE,
        "flow": FLOW_DEV_ONLY,
        "max_iterations": 10,
        "description": "Dev standalone：仅生成代码，不验证/审查",
    },
    # ── Direct: loop + standalone ──
    "direct": {
        "handlers": {
            StageType.DIRECT_EXECUTE: DirectExecuteHandler(),
            StageType.VERIFY: VerifyHandler(),
            StageType.REPAIR: RepairHandler(),
            StageType.REVIEW: ReviewHandler(),
            StageType.MEMORY: MemoryHandler(),
        },
        "entry_stage": StageType.DIRECT_EXECUTE,
        "flow": FLOW_DIRECT_LOOP,
        "max_iterations": SUB_LOOP_MAX_ITERATIONS,
        "description": "Direct 完整 loop：直接执行→验证↻修复→审查→记忆沉淀",
    },
    "direct-only": {
        "handlers": {
            StageType.DIRECT_EXECUTE: DirectExecuteHandler(),
        },
        "entry_stage": StageType.DIRECT_EXECUTE,
        "flow": FLOW_DIRECT_ONLY,
        "max_iterations": 10,
        "description": "Direct standalone：仅生成代码，不验证/审查",
    },
    "verify-loop": {
        "handlers": {
            StageType.VERIFY: VerifyHandler(),
            StageType.REPAIR: RepairHandler(),
            StageType.MEMORY: MemoryHandler(),
        },
        "entry_stage": StageType.VERIFY,
        "flow": FLOW_TEST,
        "max_iterations": SUB_LOOP_MAX_ITERATIONS,
        "description": "验证+修复循环：跑场景→失败→修复→复测→记忆沉淀（/aicode-verify --auto-fix）",
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
    "post-sdd": {
        "handlers": {
            StageType.REVIEW: ReviewHandler(),
            StageType.VERIFY: VerifyHandler(),
            StageType.REPAIR: RepairHandler(),
            StageType.MEMORY: MemoryHandler(),
        },
        "entry_stage": StageType.REVIEW,
        "flow": FLOW_POST_SDD,
        "max_iterations": SUB_LOOP_MAX_ITERATIONS,
        "description": "SDD 后审查验证：审查→场景验证↻修复→记忆沉淀（跳过 EXECUTE，假设代码已由 SDD 生成）",
    },
    "direct-post-tdd": {
        "handlers": {
            StageType.REVIEW: ReviewHandler(),
            StageType.GATE: GateHandler(),
            StageType.MEMORY: MemoryHandler(),
        },
        "entry_stage": StageType.REVIEW,
        "flow": FLOW_DIRECT_POST_TDD,
        "max_iterations": SUB_LOOP_MAX_ITERATIONS,
        "description": "TDD 后审查+门禁+记忆沉淀：审查→机械门禁→记忆沉淀→完成（小改动专用，跳过场景验证）",
    },
}


def create_sub_loop(name: str, **overrides) -> LoopRunner:
    """根据预设名创建子循环 Runner。

    Args:
        name: 预设名，可选: full / dev / dev-verify / dev-only / direct / direct-only / spec / plan / plan-only / verify / verify-loop / review / memory / post-sdd / direct-post-tdd / gate
        **overrides: 覆盖预设参数（handlers / entry_stage / flow / guard / max_iterations）

    Returns:
        配置好的 LoopRunner 实例

    Raises:
        ValueError: 预设名不存在时抛出
    """
    preset = SUB_LOOP_PRESETS.get(name)
    if preset is None:
        # 预设名不存在，列出所有可用预设
        available = ", ".join(SUB_LOOP_PRESETS)
        raise ValueError(f"Unknown sub-loop preset: {name!r}. Available: {available}")

    # 构建参数字典，从预设中提取配置
    kwargs: dict = {
        "handlers": preset["handlers"],
        "entry_stage": preset["entry_stage"],
        "flow": preset["flow"],
        "max_iterations": preset["max_iterations"],
    }
    # 用传入的覆盖参数更新
    kwargs.update(overrides)
    return LoopRunner(**kwargs)


def list_sub_loops() -> dict[str, str]:
    """列出所有子循环预设及其描述。

    Returns:
        dict[str, str]: 预设名到描述的映射字典
    """
    return {name: cfg["description"] for name, cfg in SUB_LOOP_PRESETS.items()}