"""阶段处理器基类与阶段流转定义。

每个 StageHandler 对应一个循环阶段，负责处理该阶段的逻辑，
并在完成后设置 RunState.decision 决定下一步流转。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from engines.state.enums import LoopAction, StageType, VerificationStatus

if TYPE_CHECKING:
    from engines.state.models import RunState

logger = logging.getLogger(__name__)

# ── 阶段流转默认顺序 ──────────────────────────────────────────────

# 每个阶段完成后默认进入的下一个阶段（handler 可通过 decision 覆盖）
DEFAULT_FLOW: dict[StageType, StageType | None] = {
    StageType.INTAKE:         StageType.SPEC,
    StageType.SPEC:           StageType.PLAN,
    StageType.PLAN:           StageType.EXECUTE,
    StageType.EXECUTE:        StageType.VERIFY,
    StageType.VERIFY:         StageType.REVIEW,
    StageType.REPAIR:         StageType.VERIFY,   # 修复后回到验证
    StageType.REVIEW:         StageType.MEMORY,
    StageType.MEMORY:         StageType.COMPLETED,
    StageType.DIRECT_EXECUTE: StageType.VERIFY,
    StageType.COMPLETED:      None,               # 终端状态
    StageType.ABORTED:        None,               # 终端状态
}

# 完整标准流程（Direct Mode 除外）
STANDARD_STAGES: list[StageType] = [
    StageType.INTAKE,
    StageType.SPEC,
    StageType.PLAN,
    StageType.EXECUTE,
    StageType.VERIFY,
    StageType.REVIEW,
    StageType.MEMORY,
]

# Direct Mode 跳过 SPEC/PLAN，可选跳过 VERIFY
DIRECT_STAGES: list[StageType] = [
    StageType.INTAKE,
    StageType.DIRECT_EXECUTE,
    StageType.VERIFY,
    StageType.REVIEW,
]


def next_stage(current: StageType) -> StageType | None:
    """返回当前阶段默认的下一个阶段，不覆盖 handler 决策。"""
    return DEFAULT_FLOW.get(current)


def is_terminal(stage: StageType) -> bool:
    """判断是否为终端阶段（不再流转）。"""
    return DEFAULT_FLOW.get(stage) is None


# ── 抽象基类 ──────────────────────────────────────────────────────

class StageHandler(ABC):
    """阶段处理器抽象基类。

    每个具体阶段实现 handle() 方法，在其中：
    1. 执行本阶段逻辑（或委托给 Provider/Plugin）
    2. 更新 state 的相关字段
    3. 设置 state.decision 决定下一步
    4. 可选创建 Checkpoint
    """

    stage: StageType

    @abstractmethod
    def handle(self, state: RunState) -> RunState:
        """处理当前阶段，返回更新后的 RunState。"""
        ...

    def _advance_to(self, state: RunState, target: StageType, reason: str = "") -> RunState:
        """便捷方法：设置决策为进入指定阶段。"""
        from engines.state.models import LoopDecision

        state.decision = LoopDecision(
            action=LoopAction.NEXT_STAGE,
            target_stage=target,
            reason=reason or f"{self.stage.value} → {target.value}",
        )
        return state

    def _complete(self, state: RunState, reason: str = "") -> RunState:
        """标记当前阶段完成，由 runner 的 flow table 决定下一阶段。

        这是 handler 的默认出口：做完本阶段工作后调用 _complete()，
        不设置 decision，runner 按 flow table 流转。

        _advance_to() 只在需要覆盖 flow table 时使用（如路由决策、修复跳转）。
        """
        # 不设置 decision。runner 在 _apply_decision 中检测到 decision=None
        # 时会使用 flow table 决定下一阶段。
        state.decision = None
        return state

    def _advance_to(self, state: RunState, target: StageType, reason: str = "") -> RunState:
        """覆盖 flow table，强制进入指定阶段。

        仅用于以下场景：
        - Intake 根据 flow_mode 分流到 SPEC 或 DIRECT_EXECUTE
        - Verify 失败时跳转到 REPAIR
        - 其他需要偏离默认流转的场景
        """
        from engines.state.models import LoopDecision

        state.decision = LoopDecision(
            action=LoopAction.NEXT_STAGE,
            target_stage=target,
            reason=reason or f"{self.stage.value} -> {target.value}",
        )
        return state

    def _retry(self, state: RunState, reason: str) -> RunState:
        """设置决策为重试当前阶段。"""
        from engines.state.models import LoopDecision

        state.decision = LoopDecision(
            action=LoopAction.RETRY,
            target_stage=self.stage,
            reason=reason,
        )
        state.task_state.retry_count += 1
        return state

    def _stop_success(self, state: RunState, reason: str = "") -> RunState:
        """设置决策为成功终止。"""
        from engines.state.models import LoopDecision

        state.decision = LoopDecision(
            action=LoopAction.STOP_SUCCESS,
            target_stage=StageType.COMPLETED,
            reason=reason or "任务成功完成",
        )
        return state

    def _stop_failure(self, state: RunState, reason: str) -> RunState:
        """设置决策为失败终止。"""
        from engines.state.models import LoopDecision

        state.decision = LoopDecision(
            action=LoopAction.STOP_FAILURE,
            target_stage=StageType.ABORTED,
            reason=reason,
        )
        return state

    def _check_context_budget(self, state: RunState, estimated_tokens: int) -> bool:
        """上下文预算检查 —— 在加载上下文前检查是否超预算。

        如果预估 token 消耗超过预算上限，返回 False 并通过
        state.task_state.notes 记录警告。

        Args:
            state: 当前 RunState
            estimated_tokens: 本次预计消耗的 token 数

        Returns:
            True if within budget, False if over budget.
        """
        budget_max = state.context_budget_max or 8000
        current = state.context_budget_used or 0
        projected = current + estimated_tokens

        if projected > budget_max * 0.9:
            state.task_state.notes.append(
                f"[BUDGET WARN] 上下文预算紧张: {projected}/{budget_max} tokens "
                f"(本次 +{estimated_tokens})"
            )
        if projected > budget_max:
            state.task_state.notes.append(
                f"[BUDGET CRITICAL] 上下文预算超出: {projected}/{budget_max} tokens, "
                "建议简化上下文或拆分为更小的子任务"
            )
            return False
        return True

    def _track_context_usage(self, state: RunState, tokens_used: int) -> None:
        """跟踪上下文 token 使用量。"""
        state.context_budget_used = (state.context_budget_used or 0) + tokens_used


# ── 内置阶段处理器 ──────────────────────────────────────────────


class IntakeHandler(StageHandler):
    """任务入口处理器 —— 分析复杂度 / 风险 / 分流模式。

    Python 职责（架构定义）:
        分析输入类型、复杂度、风险等级
    AI 职责:
        输入模糊时向用户提问
    """

    stage = StageType.INTAKE

    def handle(self, state: RunState) -> RunState:
        from engines.state.models import TaskIntakeResult

        # 如果 task_intake 已由外部设置（如 CLI 直接指定），直接使用
        if state.task_intake is None:
            # 安全默认: 缺少 intake 时不应走最弱防护的 direct 模式
            # 应终止并要求提供有效的入口分析
            logger.error("No task_intake set — aborting for safety")
            state.task_state.notes.append(
                "[INTAKE] 缺少 task_intake，无法评估风险，终止执行。"
                "请通过 CLI --task 参数或 IntakeHandler 提供任务分析。"
            )
            return self._stop_failure(
                state,
                "缺少 task_intake: 无法评估复杂度和风险等级，拒绝以不安全默认值执行",
            )

        intake = state.task_intake

        # 根据风险等级调整 Guard 严格度 + 启用 worktree 隔离
        if intake.risk_level in ("L4", "L5"):
            logger.warning("Risk level %s — requires strict guard mode", intake.risk_level)
            state.task_state.notes.append(f"高风险任务 (L4-L5)，需要 strict guard 模式")
            state.use_worktree = True
            state.task_state.notes.append("[INTAKE] 已启用 Worktree 隔离 (L4/L5 强制)")

        # 记录入口分析结果
        logger.info(
            "Intake: mode=%s complexity=%s risk=%s needs_spec=%s needs_plan=%s",
            intake.flow_mode, intake.complexity, intake.risk_level,
            intake.needs_spec, intake.needs_plan,
        )

        # 根据 flow_mode 决定下一阶段
        if intake.flow_mode == "direct":
            return self._advance_to(state, StageType.DIRECT_EXECUTE,
                                    f"Direct Mode (risk={intake.risk_level}): {intake.reason}")
        else:
            return self._advance_to(state, StageType.SPEC,
                                    f"Standard flow (risk={intake.risk_level}): {intake.reason}")


class SpecHandler(StageHandler):
    """规格生成处理器 —— 完整编排 Spec 生成流程（架构 §8.5）。

    Python 职责:
      1. 判断是否需要 Brainstorm（模糊度/风险等级）
      2. 构造 Spec Context Packet（项目上下文 + domain terms + memory + impact domains）
      3. 调用 SpecQualityGate 校验 AI 产出
      4. 管理确认/修正循环

    AI 职责:
      1. 如果需要 Brainstorm: 生成方案选项/推荐方案/风险/问题
      2. 生成 Spec: goal/non_goals/acceptance_criteria/test_scenarios/business_rules/open_questions
      3. 根据 Quality Gate 反馈修正 Spec

    交互协议:
      Phase PREPARE:  Python 构造 pending_prompt → needs_ai_input=True → 暂停
      Phase VALIDATE: AI 提交结果到 metadata["spec_result"] → Python 校验 → 流转或重试
    """

    stage = StageType.SPEC

    # 需要 Brainstorm 的关键词
    BRAINSTORM_HINTS = [
        "方案", "设计", "架构", "怎么实现", "选型", "比较",
        "脑暴", "想想", "探索", "评估", "how to", "design",
    ]

    def handle(self, state: RunState) -> RunState:
        state.task_state.stage = StageType.SPEC

        # ── Phase VALIDATE: AI 已提交结果 ──
        submitted = state.metadata.get("spec_result")
        if submitted and isinstance(submitted, dict):
            return self._validate_and_advance(state, submitted)

        # ── Phase PREPARE: 构造 prompt ──
        return self._prepare(state)

    # ── PREPARE ────────────────────────────────────────────────

    def _prepare(self, state: RunState) -> RunState:
        """构造 Spec 生成 prompt。"""
        intake = state.task_intake

        # 1. 判断是否需要 Brainstorm
        needs_brainstorm = self._decide_brainstorm(state)
        if needs_brainstorm and not state.brainstorm_result:
            return self._prepare_brainstorm(state)

        # 2. 加载上下文
        bundle = self._load_context(state)

        # 3. 构造 Spec Context Packet
        packet = self._build_context_packet(state, bundle)

        # 4. 构造 AI prompt
        state.pending_action = "generate_spec"
        state.pending_prompt = {
            "instruction": (
                "基于以下 SpecContextPacket 生成 Spec。\n"
                "输出格式: JSON，包含 goal / non_goals / acceptance_criteria / "
                "test_scenarios / risk_level / business_rules / open_questions。\n"
                "按需包含: api_changes / data_changes / cache_changes / message_changes / "
                "permission_rules / config_changes。\n"
                "如果项目没有 Redis/MySQL/MQ，不要生成相关章节。\n"
                "如果任务不涉及权限/配置，不要生成相关章节。\n"
                "禁止使用模糊词: 尽量/可能/应该/也许/差不多/基本上/酌情/适当/相关"
            ),
            "context_packet": packet.model_dump(),
            "output_schema": {
                "goal": "string",
                "non_goals": ["string"],
                "acceptance_criteria": ["string"],
                "test_scenarios": ["string"],
                "risk_level": "L1|L2|L3|L4|L5",
                "business_rules": ["string"],
                "open_questions": ["string"],
                "api_changes": ["string (optional)"],
                "data_changes": ["string (optional)"],
                "cache_changes": ["string (optional)"],
                "message_changes": ["string (optional)"],
                "permission_rules": ["string (optional)"],
                "config_changes": ["string (optional)"],
            },
        }
        state.needs_ai_input = True
        state.task_state.notes.append(
            f"[SPEC] ContextPacket 已构造: modules={packet.relevant_modules}, "
            f"domain_terms={packet.domain_terms}, impact={packet.impact_domains.model_dump()}"
        )
        logger.info("Spec prompt ready — waiting for AI to generate Spec")
        return state

    def _prepare_brainstorm(self, state: RunState) -> RunState:
        """构造 Brainstorm prompt。"""
        bundle = self._load_context(state)

        state.pending_action = "brainstorm"
        state.pending_prompt = {
            "instruction": (
                "需求存在模糊性或多方向可能性，请先做 Brainstorm 再做 Spec。\n"
                "输出结构:\n"
                "- 方案选项 (options): 列出 2-4 个可行方案\n"
                "- 推荐方案 (recommended): 推荐哪个 + 理由\n"
                "- 不推荐方案 (not_recommended): 不推荐哪个 + 理由\n"
                "- 业务边界 (business_boundaries): 本次做什么不做什么\n"
                "- 关键风险 (key_risks): 潜在问题和风险\n"
                "- 需要澄清的问题 (clarification_needed): 不确定需要用户确认的\n"
                "- 测试思路 (test_ideas): 如何验证\n"
                "- 是否适合进入 Spec (ready_for_spec): true/false"
            ),
            "context": bundle.render() if bundle else "",
        }
        state.needs_ai_input = True
        state.task_state.notes.append("[SPEC] 需要先 Brainstorm — 输入模糊或多方向")
        logger.info("Brainstorm prompt ready")
        return state

    # ── VALIDATE ────────────────────────────────────────────────

    # Spec Quality Gate 最大重试次数（防止 AI 无限提交错误 JSON）
    MAX_QUALITY_RETRIES = 3

    def _validate_and_advance(self, state: RunState, submitted: dict) -> RunState:
        """校验 AI 提交的 Spec/Brainstorm 结果。"""
        # 判断是 Brainstorm 还是 Spec 提交
        if state.pending_action == "brainstorm":
            return self._handle_brainstorm_result(state, submitted)

        # 跟踪重试次数
        retry_count = state.metadata.get("spec_quality_retries", 0)

        # Spec 提交 → Quality Gate
        try:
            from engines.spec.models import SpecEntry
            from engines.spec.quality_gate import SpecQualityGate

            # 构造 SpecEntry
            spec = SpecEntry(**submitted)
            state.spec_entry = submitted

            # 跑 Quality Gate
            gate = SpecQualityGate(threshold=70.0)
            report = gate.evaluate(spec)
            state.spec_quality_report = report.model_dump()

            state.task_state.notes.append(
                f"[SPEC] Quality Gate: score={report.score}, passed={report.passed}, "
                f"fuzzy_words={len(report.fuzzy_words)}, missing={report.missing_sections}"
            )

            if report.passed:
                state.needs_ai_input = False
                state.pending_action = ""
                state.metadata.pop("spec_result", None)
                state.metadata.pop("spec_quality_retries", None)
                logger.info("Spec Quality Gate PASSED — advancing to PLAN")
                return self._complete(state, f"Spec 质量通过 (score={report.score})")
            else:
                retry_count += 1
                if retry_count >= self.MAX_QUALITY_RETRIES:
                    logger.error(
                        "Spec Quality Gate exceeded max retries (%d)", retry_count
                    )
                    state.task_state.notes.append(
                        f"[SPEC] Quality Gate 重试 {retry_count} 次仍不通过，终止"
                    )
                    state.needs_ai_input = False
                    state.metadata.pop("spec_result", None)
                    state.metadata.pop("spec_quality_retries", None)
                    return self._stop_failure(
                        state,
                        f"Spec Quality Gate 超过最大重试次数 ({self.MAX_QUALITY_RETRIES})",
                    )

                state.metadata["spec_quality_retries"] = retry_count
                # 返回问题列表给 AI 修正
                state.pending_action = "generate_spec"
                state.pending_prompt["quality_feedback"] = {
                    "score": report.score,
                    "fuzzy_words": [fw.model_dump() for fw in report.fuzzy_words],
                    "missing_sections": report.missing_sections,
                    "suggestions": report.suggestions,
                }
                state.pending_prompt["instruction"] = (
                    f"Spec 未通过 Quality Gate (attempt {retry_count}/{self.MAX_QUALITY_RETRIES})。"
                    "请根据 quality_feedback 修正:"
                    "\n1. 消除模糊词，改为明确表述"
                    "\n2. 补全缺失字段"
                )
                state.metadata.pop("spec_result", None)
                state.task_state.notes.append(
                    f"[SPEC] Quality Gate FAILED (attempt={retry_count}, score={report.score}) — 返回修正"
                )
                logger.warning("Spec Quality Gate FAILED: %s", report.suggestions[:3])
                return state  # needs_ai_input 保持 True
        except Exception as exc:
            retry_count += 1
            logger.error("Spec validation failed (attempt %d): %s", retry_count, exc)

            if retry_count >= self.MAX_QUALITY_RETRIES:
                state.needs_ai_input = False
                state.metadata.pop("spec_result", None)
                state.metadata.pop("spec_quality_retries", None)
                return self._stop_failure(
                    state,
                    f"Spec 校验异常超过最大重试次数 ({self.MAX_QUALITY_RETRIES}): {exc}",
                )

            state.metadata["spec_quality_retries"] = retry_count
            state.pending_action = "generate_spec"
            state.task_state.notes.append(
                f"[SPEC] 校验异常 (attempt={retry_count}): {exc}"
            )
            state.pending_prompt["validation_error"] = str(exc)
            state.pending_prompt["instruction"] = (
                f"上次提交格式有误 (attempt {retry_count}/{self.MAX_QUALITY_RETRIES})。"
                f"错误: {exc}\n请检查 JSON 格式后重新提交。"
            )
            state.metadata.pop("spec_result", None)
            return state

    def _handle_brainstorm_result(self, state: RunState, submitted: dict) -> RunState:
        """处理 Brainstorm 提交结果。"""
        from engines.spec.models import BrainstormResult

        try:
            result = BrainstormResult(**submitted)
            state.brainstorm_result = result.model_dump()
            state.task_state.notes.append(
                f"[SPEC] Brainstorm 完成: options={len(result.options)}, "
                f"ready_for_spec={result.ready_for_spec}, "
                f"clarification_needed={len(result.clarification_needed)}"
            )

            if not result.ready_for_spec:
                # 仍有未解决问题 → 暂停等待用户
                state.task_state.notes.append(
                    f"[SPEC] Brainstorm 后仍需澄清: {result.clarification_needed}"
                )
                state.needs_ai_input = False
                state.pending_action = "await_user_clarification"
                return self._stop_failure(
                    state,
                    f"Brainstorm 完成但有关键问题待澄清: {result.clarification_needed}",
                )

            # 可以进入 Spec 生成 → 回到 PREPARE 阶段（这次跳过 brainstorm）
            state.needs_ai_input = False
            state.pending_action = ""
            state.metadata.pop("spec_result", None)
            logger.info("Brainstorm passed, proceeding to Spec generation")
            return self._prepare(state)

        except Exception as exc:
            logger.error("Brainstorm result validation failed: %s", exc)
            state.task_state.notes.append(f"[SPEC] Brainstorm 校验异常: {exc}")
            state.pending_prompt["validation_error"] = str(exc)
            state.metadata.pop("spec_result", None)
            return state

    # ── 辅助 ────────────────────────────────────────────────────

    def _decide_brainstorm(self, state: RunState) -> bool:
        """判断是否需要先 Brainstorm（架构 §8.5.2）。

        触发条件:
        - 用户输入包含方案/设计/架构/选型等词
        - 风险等级 L4+
        - 复杂度 unknown 或 high
        """
        intake = state.task_intake
        if intake is None:
            return False

        # 高风险 → brainstorm
        if intake.risk_level in ("L4", "L5"):
            return True

        # 复杂度高/未知 → brainstorm
        if intake.complexity in ("high", "unknown"):
            return True

        # 用户输入含 Brainstorm 关键词
        user_input = state.metadata.get("user_input", "")
        if any(hint in user_input for hint in self.BRAINSTORM_HINTS):
            return True

        return False

    def _load_context(self, state: RunState):
        """加载 SPEC 阶段上下文。"""
        try:
            from engines.context.router import ContextRouter
            router = ContextRouter(state.project_root)
            bundle = router.route(stage=StageType.SPEC, run_state=state)
            if bundle:
                state.task_state.notes.append(
                    f"[SPEC context] tokens={bundle.total_tokens}, "
                    f"files={len(bundle.pieces)}"
                )
                logger.info("Spec context loaded: %d pieces, ~%d tokens",
                            len(bundle.pieces), bundle.total_tokens)
            return bundle
        except Exception as exc:
            logger.warning("ContextRouter failed for SPEC: %s", exc)
            state.task_state.notes.append(f"[SPEC] ContextRouter 不可用: {exc}")
            return None

    def _build_context_packet(self, state: RunState, bundle) -> Any:
        """构造 Spec Context Packet（架构 §8.5.3）。"""
        from engines.spec.models import ImpactDomain, SpecContextPacket

        intake = state.task_intake
        context_text = bundle.render() if bundle else ""

        # 从 ContextBundle 中提取模块和术语
        relevant_modules: list[str] = []
        domain_terms: list[str] = []
        relevant_memory: list[str] = []

        if bundle:
            for piece in bundle.pieces:
                if piece.source == "memory":
                    relevant_memory.append(piece.content[:200])
                if piece.metadata.get("module"):
                    mod = piece.metadata["module"]
                    if mod not in relevant_modules:
                        relevant_modules.append(mod)

        # 从 intake 推断影响域
        impact = ImpactDomain(
            api=intake.risk_level in ("L2", "L3", "L4") if intake else False,
            database=intake.risk_level in ("L4",) if intake else False,
            cache=intake.risk_level in ("L4",) if intake else False,
            message_queue=intake.risk_level in ("L4",) if intake else False,
            permission=intake.risk_level in ("L4", "L5") if intake else False,
        )

        return SpecContextPacket(
            user_input=state.metadata.get("user_input", state.task_id),
            task_intake=intake.model_dump() if intake else {},
            project_summary=state.project or state.project_root,
            relevant_modules=relevant_modules,
            domain_terms=domain_terms,
            relevant_memory=relevant_memory,
            existing_apis=[],
            impact_domains=impact,
            risk_level=intake.risk_level if intake else "",
        )


class PlanHandler(StageHandler):
    """计划生成处理器 —— 完整编排 Plan 生成流程（架构 §8.6）。

    Python 职责:
      1. 从 Spec 提取验收标准，预建 Task 框架
      2. 构造 Plan 生成 prompt（含 Spec + Task 框架 + Style/Ruse/Reuse 要求）
      3. 调用 PlanQualityGate 校验
      4. PlanLock.lock() 锁定
      5. 管理 Plan Change Request 审批

    AI 职责:
      1. 填充每个 Task 的具体内容（文件路径、实现步骤、doneWhen）
      2. 设置 Style Contract 约束
      3. 设置 Reuse Check 搜索词
      4. 绑定 Spec/Acceptance/Scenario

    交互协议:
      Phase PREPARE:  Python 构造 plan prompt → needs_ai_input=True → 暂停
      Phase VALIDATE: AI 提交 contracts JSON → PlanQualityGate → PlanLock.lock() → 流转
    """

    stage = StageType.PLAN

    def handle(self, state: RunState) -> RunState:
        state.task_state.stage = StageType.PLAN

        # ── Phase VALIDATE: AI 已提交结果 ──
        submitted = state.metadata.get("plan_result")
        if submitted and isinstance(submitted, dict):
            return self._validate_and_advance(state, submitted)

        # ── Phase PREPARE: 构造 prompt ──
        return self._prepare(state)

    # ── PREPARE ────────────────────────────────────────────────

    def _prepare(self, state: RunState) -> RunState:
        """构造 Plan 生成 prompt。"""
        # 1. 加载上下文
        self._load_context(state)

        # 2. 从 Spec 提取信息构建 Task 框架
        spec = state.spec_entry or {}
        # 2.5 检查 Spec 是否存在 — 没有 Spec 的 Plan 质量会下降
        if not spec:
            logger.warning("PlanHandler: spec_entry is empty — Plan quality may be degraded")
            state.task_state.notes.append(
                "[PLAN] ⚠️ spec_entry 为空 — 建议先运行 'loop spec' 生成 Spec，"
                "或通过 --state-file 传入含 Spec 的状态文件"
            )
        acceptance = spec.get("acceptance_criteria", [])
        scenarios = spec.get("test_scenarios", [])
        risk = spec.get("risk_level", state.task_intake.risk_level if state.task_intake else "L2")

        # 3. 默认预算
        complexity = state.task_intake.complexity if state.task_intake else "medium"
        budget = self._default_budget(complexity)

        # 4. 构造 AI prompt
        acceptance_yaml = "\n".join(f"  - {a}" for a in acceptance) if acceptance else "  (由 AI 从 Spec 提取)"
        scenarios_yaml = "\n".join(f"  - {s}" for s in scenarios) if scenarios else "  (待绑定)"

        state.pending_action = "generate_plan"
        state.pending_prompt = {
            "instruction": (
                "基于 Spec 生成 Plan。每个 Task 必须包含:\n"
                "1. Task ID (T1/T2/...)、标题、目标\n"
                "2. allowedFiles: 允许修改的文件 (glob pattern)\n"
                "3. forbiddenFiles: 禁止修改的文件/目录\n"
                "4. links: 绑定 Spec/Acceptance/Scenario\n"
                "5. styleContract: 引用风格规则 + must/forbidden 列表\n"
                "6. reuseCheck: search_for 列表（搜索已有实现）\n"
                "7. implementation: 具体实现步骤\n"
                "8. verification: 验证步骤\n"
                "9. doneWhen: 完成条件\n\n"
                f"任务粒度: 每个 Task 1-3 文件，1 个明确目标，1 个验证方式。\n"
                f"默认预算: maxFiles={budget['max_files']}, maxLinesChanged={budget['max_lines']}。\n"
                "如果 Spec 涉及 DB+Redis+MQ+权限+测试，必须拆分为多个 Task。\n"
                "禁止范围膨胀: 不要包含无关重构、格式化、新抽象。\n"
                "输出格式: {\"contracts\": [{...task...}, ...]}"
            ),
            "spec_summary": {
                "goal": spec.get("goal", ""),
                "acceptance_criteria": acceptance,
                "test_scenarios": scenarios,
                "business_rules": spec.get("business_rules", []),
                "risk_level": risk,
            },
            "task_framework": {
                "acceptance_count": len(acceptance),
                "suggested_task_count": max(1, len(acceptance)),
                "default_budget": budget,
                "must_bind_scenarios": scenarios,
                "style_sources": [
                    ".claude/aicode/style.md",
                    ".claude/rules/code-style.md",
                    ".claude/rules/testing.md",
                ],
                "reuse_required": True,
            },
            "output_schema": {
                "contracts": [{
                    "task_id": "T1",
                    "title": "string",
                    "goal": "string",
                    "allowed_files": ["glob/*.py"],
                    "forbidden_files": ["glob/**"],
                    "links": {
                        "spec_requirements": ["REQ-ID"],
                        "acceptance_criteria": ["AC-ID"],
                        "scenarios": ["scenario-id"],
                    },
                    "style_contract": {
                        "must": ["遵循规则"],
                        "forbidden": ["禁止模式"],
                    },
                    "reuse_check": {
                        "search_for": ["已有 validator/repository/helper"],
                    },
                    "implementation": ["步骤1", "步骤2"],
                    "verification": ["lint", "test", "scenario"],
                    "done_when": "可验证的自然语言描述",
                }],
            },
        }
        state.needs_ai_input = True
        state.task_state.notes.append(
            f"[PLAN] 框架已构建: acceptance={len(acceptance)}, "
            f"suggested_tasks={max(1, len(acceptance))}, "
            f"budget={budget}"
        )
        logger.info("Plan prompt ready — waiting for AI to generate Plan")
        return state

    # ── VALIDATE ────────────────────────────────────────────────

    def _validate_and_advance(self, state: RunState, submitted: dict) -> RunState:
        """校验 AI 提交的 Plan Contracts。"""
        try:
            from engines.plan.models import PlanContract
            from engines.plan.quality_gate import PlanQualityGate
            from engines.plan.lock import PlanLock

            # 解析 contracts
            contracts_data = submitted.get("contracts", [submitted])
            contracts: list[PlanContract] = []
            for cd in contracts_data:
                # 确保嵌套模型正确构造
                c = PlanContract(**cd)
                contracts.append(c)

            # 跑 Quality Gate
            gate = PlanQualityGate(threshold=70.0)
            report = gate.evaluate(contracts, state.spec_entry)
            state.plan_quality_report = report.model_dump()

            # 存到 state
            state.plan_contracts = [c.model_dump() for c in contracts]

            state.task_state.notes.append(
                f"[PLAN] Quality Gate: score={report.score}, passed={report.passed}, "
                f"covers_all={report.covers_all_acceptance}, "
                f"all_boundaries={report.all_tasks_have_boundaries}"
            )

            if report.passed:
                # PlanLock.lock()
                lock = PlanLock()
                # Lock all contracts
                for c in contracts:
                    lock.lock(c)
                state.plan_lock_state = "locked"

                state.needs_ai_input = False
                state.pending_action = ""
                state.metadata.pop("plan_result", None)

                logger.info("Plan Quality Gate PASSED — PlanLock LOCKED, advancing to EXECUTE")
                return self._complete(
                    state,
                    f"Plan 质量通过 (score={report.score}), {len(contracts)} tasks locked",
                )
            else:
                # 返回修正
                state.pending_action = "generate_plan"
                state.pending_prompt["quality_feedback"] = {
                    "score": report.score,
                    "suggestions": report.suggestions,
                    "missing_coverage": report.missing_coverage,
                    "oversized_tasks": report.oversized_tasks,
                    "unverified_tasks": report.unverified_tasks,
                }
                state.pending_prompt["instruction"] = (
                    "Plan 未通过 Quality Gate。请根据 quality_feedback 修正:\n"
                    "1. 确保每个 Task 有 allowedFiles/forbiddenFiles\n"
                    "2. 绑定 Scenario/验证方式到每个 Task\n"
                    "3. 拆分过大任务 (>5 files)\n"
                    "4. 覆盖所有 Spec 验收标准"
                )
                state.metadata.pop("plan_result", None)
                state.task_state.notes.append(
                    f"[PLAN] Quality Gate FAILED (score={report.score}) — 返回修正"
                )
                logger.warning("Plan Quality Gate FAILED: %s", report.suggestions[:3])
                return state
        except Exception as exc:
            logger.error("Plan validation failed: %s", exc)
            state.task_state.notes.append(f"[PLAN] 校验异常: {exc}")
            state.pending_prompt["validation_error"] = str(exc)
            state.metadata.pop("plan_result", None)
            return state

    # ── 辅助 ────────────────────────────────────────────────────

    def _load_context(self, state: RunState):
        """加载 PLAN 阶段上下文。"""
        try:
            from engines.context.router import ContextRouter
            router = ContextRouter(state.project_root)
            bundle = router.route(stage=StageType.PLAN, run_state=state)
            if bundle:
                state.task_state.notes.append(
                    f"[PLAN context] tokens={bundle.total_tokens}, "
                    f"files={len(bundle.pieces)}"
                )
        except Exception as exc:
            logger.warning("ContextRouter failed for PLAN: %s", exc)
            state.task_state.notes.append(f"[PLAN] ContextRouter 不可用: {exc}")

    @staticmethod
    def _default_budget(complexity: str) -> dict:
        if complexity == "low":
            return {"max_files": 3, "max_lines": 100}
        elif complexity == "medium":
            return {"max_files": 5, "max_lines": 300}
        return {"max_files": 8, "max_lines": 600}


class ExecuteHandler(StageHandler):
    """执行处理器 —— 逐 Task 执行 + 约束强制执行（架构 §8.7）。

    Python 职责:
      1. Per-task 循环：Task Start Gate → Guard → ContextRouter → 等待 AI 编码
      2. Diff Budget 强制执行（文件数/行数检查）
      3. Style Contract 简单检查（命名/异常/日志一致性）
      4. Reuse Check 结果验证
      5. Plan Change Request 管理
      6. Task Execution Log 记录

    AI 职责:
      1. 在每个 Task 允许范围内写代码
      2. 执行前确认 Implementation Checklist
      3. 超预算时发起 Plan Change Request

    交互协议:
      Phase PREPARE:  Python 输出当前 Task contract + context → pending_action="execute_task"
      Phase VALIDATE: AI 提交 changed_files → Python 校验 budget/scope/style → 下一 Task 或 Plan Change
    """

    stage = StageType.EXECUTE
    MAX_PLAN_CHANGE_REQUESTS = 3  # 每个任务最多发起 3 次变更请求

    def handle(self, state: RunState) -> RunState:
        state.task_state.stage = StageType.EXECUTE

        # 初始化 per-task 循环
        contracts = state.plan_contracts
        if not contracts:
            state.task_state.notes.append(
                "[EXECUTE] ⚠️ 无 Plan Contracts — 无法执行。"
                "请先运行 'loop plan' 或 'loop plan-only' 生成 Plan，"
                "或通过 --state-file 传入含 Plan 的状态文件"
            )
            return self._complete(state, "无 Plan Contracts — 需要先生成 Plan")

        # 0. Upstream Sync — 开始执行前检查上游变化（架构 §17.2）
        #    仅在第一个 Task 开始前执行一次
        if state.task_state.current_task_index == 0:
            sync_result = self._upstream_sync(state)
            if sync_result:
                state.task_state.notes.append(sync_result)
                if "冲突" in sync_result:
                    state.needs_ai_input = True
                    state.pending_action = "resolve_upstream_conflicts"
                    state.pending_prompt = {
                        "instruction": (
                            "检测到上游代码冲突，需要人工处理:\n"
                            f"{sync_result}\n"
                            "解决冲突后重新运行 loop continue 继续执行。"
                        ),
                        "sync_result": sync_result,
                    }
                    return state

        current_idx = state.task_state.current_task_index
        if current_idx >= len(contracts):
            # 所有 Task 完成
            logger.info("All %d tasks executed", len(contracts))
            state.task_state.notes.append(f"[EXECUTE] 全部 {len(contracts)} Tasks 执行完成")
            return self._complete(state, f"全部 {len(contracts)} Tasks 执行完成")

        # ── Phase VALIDATE: AI 已提交当前 Task 结果 ──
        submitted = state.metadata.get("execute_result")
        if submitted and isinstance(submitted, dict):
            return self._validate_task_result(state, submitted, contracts[current_idx])

        # ── Phase PREPARE: Task Start Gate + 构造 prompt ──
        return self._prepare_task(state, contracts[current_idx], current_idx, len(contracts))

    # ══════════════════════════════════════════════════════════════
    # PREPARE — Task Start Gate (架构 §8.7.2)
    # ══════════════════════════════════════════════════════════════

    def _prepare_task(
        self, state: RunState, contract: dict, idx: int, total: int,
    ) -> RunState:
        """构造当前 Task 的执行 prompt。"""
        task_id = contract.get("task_id", f"T{idx + 1}")

        # 1. Task Start Gate — 边界重新确认
        self._task_start_gate(state, contract, idx, total)

        # 1.5. Worktree 隔离检查 — L4/L5 或显式设置时创建隔离环境
        if state.use_worktree or (
            state.task_intake and state.task_intake.risk_level in ("L4", "L5")
        ):
            state.use_worktree = True
            if not self._ensure_worktree(state):
                return self._stop_failure(
                    state,
                    "Worktree 隔离环境创建失败，L4/L5 任务拒绝在主工作区执行",
                )

        # 2. Guard 前置检查
        if not self._pre_guard_check(state):
            return state  # Guard blocked

        # 3. ContextRouter 注入 EXECUTE 上下文（仅当前 Task 需要的文件）
        self._load_execute_context(state, contract)

        # 4. 检查 PlanLock 状态（架构 §8.6.4: AI 只能执行 approved plan）
        if state.plan_lock_state == "unlocked" and state.plan_contracts:
            # Plan 存在但未锁定 → 必须先锁定再执行
            state.pending_action = "lock_plan"
            state.pending_prompt = {
                "instruction": (
                    "Plan 尚未锁定 (plan_lock_state=unlocked)。"
                    "请先运行 /aicode-plan 确认 Plan，"
                    "或调用 loop continue --result '{\"lock_plan\": true}' 锁定后继续。"
                ),
                "plan_contracts": state.plan_contracts,
                "requires_lock": True,
            }
            state.needs_ai_input = True
            state.task_state.notes.append("[EXECUTE] 被阻: PlanLock=unlocked, Plan 未确认")
            return state

        if state.plan_lock_state == "change_requested":
            state.task_state.notes.append(
                f"[EXECUTE] PlanLock CHANGE_REQUESTED — 等待变更审批"
            )
            state.needs_ai_input = True
            state.pending_action = "await_plan_change_approval"
            return state

        if state.plan_lock_state == "breached":
            return self._stop_failure(state, "PlanLock BREACHED — 需要人工介入")

        # 5. 构造 AI prompt (增强: 可执行的 Implementation Checklist)
        checklist = self._build_checklist(contract)
        state.pending_action = "execute_task"
        state.pending_prompt = {
            "instruction": (
                f"执行 Task {task_id} ({idx + 1}/{total}): {contract.get('title', '')}\n\n"
                "## Implementation Checklist (每项编码前确认，完成时打勾):\n"
                + "\n".join(f"- [ ] {item}" for item in checklist) +
                "\n\n提交格式:\n"
                "{\n"
                '  "changed_files": ["path/to/file"],\n'
                '  "lines_added": N,\n'
                '  "lines_removed": N,\n'
                '  "summary": "变更说明",\n'
                '  "checklist_completed": ["已完成项1", "已完成项2"],\n'
                '  "style_contract_followed": true,\n'
                '  "reuse_check_passed": true,\n'
                '  "new_abstractions": [],\n'
                '  "new_dependencies": []\n'
                "}"
            ),
            "task_contract": contract,
            "style_contract": contract.get("style_contract", {}),
            "reuse_check": contract.get("reuse_check", {}),
            "implementation_checklist": checklist,
            "budget": {
                "max_files": contract.get("budget", {}).get("max_files", 3),
                "max_lines": contract.get("budget", {}).get("max_lines", 100),
                "allow_new_abstractions": contract.get("budget", {}).get("allow_new_abstractions", False),
                "allow_new_dependencies": contract.get("budget", {}).get("allow_new_dependencies", False),
            },
            "worktree": {
                "enabled": state.use_worktree,
                "path": state.metadata.get("worktree_path", ""),
            } if state.use_worktree else {"enabled": False},
        }
        state.needs_ai_input = True
        state.task_state.status = state.task_state.status.__class__.IN_PROGRESS
        state.task_state.notes.append(
            f"[EXECUTE] Task {task_id} ({idx + 1}/{total}): "
            f"allowed={contract.get('allowed_files', [])}, "
            f"budget={contract.get('budget', {}).get('max_files', '?')} files"
        )
        logger.info("Execute prompt ready for Task %s (%d/%d)", task_id, idx + 1, total)
        return state

    # ══════════════════════════════════════════════════════════════
    # VALIDATE (架构 §8.7.7 / §8.7.11)
    # ══════════════════════════════════════════════════════════════

    def _validate_task_result(
        self, state: RunState, submitted: dict, contract: dict,
    ) -> RunState:
        """校验 AI 提交的 Task 执行结果。"""
        task_id = contract.get("task_id", "?")

        changed_files = submitted.get("changed_files", [])
        summary = submitted.get("summary", "")
        plan_change = submitted.get("plan_change_request")

        # 1. 处理 Plan Change Request
        if plan_change:
            return self._handle_plan_change(state, plan_change, contract)

        # 2. Diff Budget 检查（完整: 文件数 + 行数 + 抽象 + 依赖）
        #    先做独立 diff 验证，而非直接信任 AI 自报
        actual_added, actual_removed = self._count_actual_diff(
            state, changed_files,
        )
        reported_added = submitted.get("lines_added", 0)
        reported_removed = submitted.get("lines_removed", 0)

        # 如果 AI 自报与实际差异过大，使用实际值并记录警告
        if actual_added is not None:
            if abs(reported_added - actual_added) > max(10, actual_added * 0.5):
                state.task_state.notes.append(
                    f"[EXECUTE] AI 自报 lines_added={reported_added}, "
                    f"实际 diff 统计={actual_added} — 使用实际值"
                )
            lines_added = max(reported_added, actual_added)  # 取较大值，不给 AI 钻空子
            lines_removed = max(reported_removed, actual_removed or 0)
        else:
            lines_added = reported_added
            lines_removed = reported_removed

        budget_ok, budget_msg = self._check_diff_budget(
            contract, changed_files,
            lines_added=lines_added,
            lines_removed=lines_removed,
            new_abstractions=submitted.get("new_abstractions"),
            new_dependencies=submitted.get("new_dependencies"),
        )
        if not budget_ok:
            state.task_state.notes.append(
                f"[EXECUTE] Task {task_id} Diff Budget 违规: {budget_msg}"
            )
            # 返回 AI 修正
            state.pending_prompt["budget_violation"] = budget_msg
            state.pending_prompt["instruction"] = (
                f"Diff Budget 违规: {budget_msg}\n"
                "请缩减修改范围或提交 Plan Change Request:\n"
                "{\"plan_change_request\": {\"reason\": \"...\", \"what_changes\": \"...\", "
                "\"affected_files\": [...], \"budget_delta\": N}}"
            )
            state.metadata.pop("execute_result", None)
            logger.warning("Task %s diff budget violated: %s", task_id, budget_msg)
            return state

        # 3. 记录 Task Execution Log
        from engines.state.models import TaskExecutionLog

        # 3.5. 增量验证 — Per-task 快速检查 (typecheck/compile/lint)
        quick_check = self._run_quick_check(state, changed_files)

        log = TaskExecutionLog(
            task_id=task_id,
            status="implemented",
            changed_files=changed_files,
            lines_added=lines_added,
            lines_removed=lines_removed,
            plan_compliance={
                "allowed_files_only": self._check_allowed_only(contract, changed_files),
                "diff_budget_exceeded": not budget_ok,
                "diff_budget_detail": budget_msg,
                "style_contract_followed": submitted.get("style_contract_followed", True),
                "reuse_check_passed": submitted.get("reuse_check_passed", True),
            },
            verification={"quick_check": quick_check},
        )
        state.task_state.task_logs.append(log)

        state.task_state.notes.append(
            f"[EXECUTE] Task {task_id} 完成: files={changed_files}, summary={summary[:100]}"
        )

        # 4. 进入下一个 Task
        state.task_state.current_task_index += 1
        state.needs_ai_input = False
        state.pending_action = ""
        state.metadata.pop("execute_result", None)

        # 检查是否还有下一个 Task
        if state.task_state.current_task_index >= len(state.plan_contracts):
            logger.info("All tasks executed, advancing to VERIFY")
            return self._complete(state, f"全部 {len(state.plan_contracts)} Tasks 执行完成")
        else:
            # 继续下一个 Task → 循环回到 PREPARE
            next_contract = state.plan_contracts[state.task_state.current_task_index]
            logger.info("Advancing to next task: %s", next_contract.get("task_id", "?"))
            return self._prepare_task(
                state, next_contract,
                state.task_state.current_task_index, len(state.plan_contracts),
            )

    # ══════════════════════════════════════════════════════════════
    # Plan Change Request (架构 §8.7.9)
    # ══════════════════════════════════════════════════════════════

    def _handle_plan_change(
        self, state: RunState, plan_change: dict, contract: dict,
    ) -> RunState:
        """处理 Plan Change Request。"""
        task_id = contract.get("task_id", "?")
        risk = state.task_intake.risk_level if state.task_intake else "L2"

        state.plan_lock_state = "change_requested"
        state.task_state.notes.append(
            f"[EXECUTE] Plan Change Request from Task {task_id}: "
            f"reason={plan_change.get('reason', '')[:80]}"
        )

        # L1/L2: 自动批准
        if risk in ("L1", "L2"):
            state.plan_lock_state = "locked"
            state.task_state.notes.append(f"[EXECUTE] Plan Change 自动批准 (risk={risk})")
            state.needs_ai_input = False
            state.metadata.pop("execute_result", None)
            logger.info("Plan change auto-approved for L1/L2 task")
            return state

        # L3: 记录但继续
        if risk == "L3":
            state.plan_lock_state = "locked"
            state.task_state.notes.append(
                f"[EXECUTE] Plan Change 已记录 (risk={risk}): {plan_change.get('reason', '')[:80]}"
            )
            state.needs_ai_input = False
            state.metadata.pop("execute_result", None)
            return state

        # L4/L5: 必须用户确认
        state.needs_ai_input = True
        state.pending_action = "await_plan_change_approval"
        state.pending_prompt = {
            "instruction": (
                f"Plan Change Request for Task {task_id} (risk={risk}):\n"
                f"Reason: {plan_change.get('reason', '')}\n"
                f"Changes: {plan_change.get('what_changes', '')}\n"
                f"Affected files: {plan_change.get('affected_files', [])}\n"
                "This requires user approval before continuing."
            ),
            "plan_change": plan_change,
            "requires_approval": True,
        }
        state.metadata.pop("execute_result", None)
        logger.warning("Plan change requires user approval (risk=%s)", risk)
        return state

    # ══════════════════════════════════════════════════════════════
    # 辅助检查
    # ══════════════════════════════════════════════════════════════

    @staticmethod
    def _build_checklist(contract: dict) -> list[str]:
        """从 Plan Contract 构建可执行的 Implementation Checklist。

        返回的检查项 AI 必须在编码前逐项确认。
        """
        checklist = []

        # 文件范围
        allowed = contract.get("allowed_files", [])
        checklist.append(f"只修改 allowed_files 范围内的文件: {allowed}")

        forbidden = contract.get("forbidden_files", [])
        if forbidden:
            checklist.append(f"不触碰 forbidden_files: {forbidden}")

        # 复用检查
        reuse = contract.get("reuse_check", {})
        if reuse:
            checklist.append(f"复用已有模式: {reuse.get('existing_patterns', [])}")

        # Style contract
        style = contract.get("style_contract", {})
        if style.get("naming"):
            checklist.append(f"遵守命名规范: {style['naming']}")
        if style.get("error_handling"):
            checklist.append(f"错误处理一致性: {style['error_handling']}")
        if style.get("logging"):
            checklist.append(f"日志一致性: {style['logging']}")

        # Budget
        budget = contract.get("budget", {})
        checklist.append(
            f"保持变更在预算内: max_files={budget.get('max_files', 3)}, "
            f"max_lines={budget.get('max_lines_changed', budget.get('max_lines', 200))}"
        )
        if not budget.get("allow_new_abstractions", False):
            checklist.append("不引入新抽象层/新类 (allow_new_abstractions=false)")
        if not budget.get("allow_new_dependencies", False):
            checklist.append("不引入新依赖 (allow_new_dependencies=false)")

        # 验证
        verification = contract.get("verification", [])
        if verification:
            checklist.append(f"运行验证: {verification}")

        # 不破坏已有行为
        checklist.append("保持已有测试通过，不删除/削弱已有断言")
        checklist.append("不进行无关格式化和重构")

        return checklist

    def _task_start_gate(
        self, state: RunState, contract: dict, idx: int, total: int,
    ) -> None:
        """Task Start Gate — 重新确认执行边界（架构 §8.7.2）。"""
        task_id = contract.get("task_id", f"T{idx + 1}")
        allowed = contract.get("allowed_files", [])
        forbidden = contract.get("forbidden_files", [])

        state.task_state.notes.append(
            f"[EXECUTE] Task Start Gate: {task_id} ({idx + 1}/{total})\n"
            f"  Allowed: {allowed}\n"
            f"  Forbidden: {forbidden}\n"
            f"  Goal: {contract.get('goal', '')}"
        )
        logger.info("Task Start Gate: %s", task_id)

    def _ensure_worktree(self, state: RunState) -> bool:
        """确保 Worktree 隔离环境已创建（架构 §17.3）。

        对于 L4/L5 任务，在独立 git worktree 中执行以隔离风险。

        Returns:
            True 如果隔离环境就绪或不需要隔离，False 如果需要但创建失败。
        """
        if not state.use_worktree:
            return True  # 不需要隔离
        if state.metadata.get("worktree_path"):
            return True  # 已创建

        try:
            from pathlib import Path

            from engines.runtime.worktree_isolator import WorktreeIsolator

            project_root = Path(state.project_root) if state.project_root else Path.cwd()
            isolator = WorktreeIsolator(project_root=project_root)

            if not isolator.available:
                # L4/L5: git worktree 不可用 → 不是 git 仓库，降级为 warning 但继续
                state.task_state.notes.append(
                    "[EXECUTE worktree] 非 git 仓库，无法创建 worktree 隔离"
                )
                # 非 git 仓库允许继续，因为无法使用 git 进行隔离
                return True

            result = isolator.create(task_id=state.task_id)
            if result.success:
                state.metadata["worktree_path"] = result.worktree_path
                state.metadata["worktree_branch"] = result.branch_name
                state.task_state.notes.append(
                    f"[EXECUTE worktree] 已创建隔离环境: {result.worktree_path} "
                    f"(branch={result.branch_name})"
                )
                logger.info("Worktree created: %s", result.worktree_path)
                return True
            else:
                state.task_state.notes.append(
                    f"[EXECUTE worktree] 创建失败: {result.message}"
                )
                return False
        except Exception as exc:
            logger.warning("Worktree setup skipped: %s", exc)
            state.task_state.notes.append(f"[EXECUTE worktree] 异常: {exc}")
            return False

    def _upstream_sync(self, state: RunState) -> str | None:
        """Upstream Sync — 检查上游是否有新提交（架构 §17.2）。

        Returns:
            同步结果摘要，无变化时返回 None。
        """
        try:
            from pathlib import Path

            from engines.runtime.git_sync import GitSyncer

            project_root = Path(state.project_root) if state.project_root else Path.cwd()
            syncer = GitSyncer(project_root=project_root)
            result = syncer.sync(auto_merge=False)  # 只检测，不自动合并

            if not result.success:
                return f"[EXECUTE upstream] 同步失败: {result.message}"
            if result.behind_count == 0:
                return None  # 已是最新
            if result.conflicts:
                return (
                    f"[EXECUTE upstream] ⚠️ 检测到冲突: {result.conflicts}, "
                    f"落后 {result.behind_count} 个提交"
                )
            return (
                f"[EXECUTE upstream] 落后 {result.behind_count} 个提交 "
                f"(无冲突, 可自动合并)"
            )
        except Exception as exc:
            logger.debug("Upstream sync skipped: %s", exc)
            return None

    def _pre_guard_check(self, state: RunState) -> bool:
        """Guard 前置检查。"""
        try:
            from engines.guard.engine import Guard
            from engines.guard.rules import ScopeBoundaryRule, RiskLevelRule, SanityCheckRule

            guard = Guard()
            guard.add_rule(ScopeBoundaryRule())
            guard.add_rule(RiskLevelRule())
            guard.add_rule(SanityCheckRule())

            result = guard.check(state)
            if result.block:
                state.task_state.notes.append(f"[EXECUTE] Guard 拦截: {result.reason}")
                state.decision = None  # force stop
                return False

            individual_results = result.details.get("results", [])
            passed = sum(1 for r in individual_results if getattr(r, 'passed', True))
            state.task_state.notes.append(
                f"[EXECUTE] Guard: {passed}/{len(individual_results)} passed"
            )
            return True
        except Exception as exc:
            logger.warning("Guard check failed (non-blocking): %s", exc)
            return True

    def _load_execute_context(self, state: RunState, contract: dict) -> None:
        """ContextRouter 注入当前 Task 需要的上下文。

        上下文预算感知: 加载前检查预算，加载后跟踪使用量。
        """
        try:
            from engines.context.router import ContextRouter
            router = ContextRouter(state.project_root)
            bundle = router.route(stage=StageType.EXECUTE, run_state=state)
            if bundle:
                # 上下文预算检查
                if not self._check_context_budget(state, bundle.total_tokens):
                    state.task_state.notes.append(
                        "[EXECUTE context] 上下文预算超限，已截断"
                    )
                self._track_context_usage(state, bundle.total_tokens)
                state.task_state.notes.append(
                    f"[EXECUTE context] tokens={bundle.total_tokens}, "
                    f"files={len(bundle.pieces)}, "
                    f"budget={state.context_budget_used}/{state.context_budget_max}"
                )
                # 如果 bundle 被截断，记录
                if bundle.trimmed:
                    state.task_state.notes.append(
                        f"[EXECUTE context] Context 已截断 (trimmed={bundle.trimmed})"
                    )
        except Exception as exc:
            logger.warning("ContextRouter failed for EXECUTE: %s", exc)

    def _count_actual_diff(
        self, state: RunState, changed_files: list[str],
    ) -> tuple[int | None, int | None]:
        """通过 git diff --stat 统计实际变更行数。

        用于交叉验证 AI 自报的 lines_added/lines_removed。
        返回 (added, removed) 或 (None, None) 如果 git 不可用。
        """
        if not changed_files:
            return 0, 0
        try:
            import subprocess
            from pathlib import Path

            project_root = Path(state.project_root) if state.project_root else Path.cwd()
            result = subprocess.run(
                ["git", "diff", "--stat", "HEAD", "--"] + changed_files,
                capture_output=True, text=True,
                cwd=str(project_root),
                timeout=10,
            )
            if result.returncode != 0:
                return None, None

            # git diff --stat 输出最后一行如: "3 files changed, 50 insertions(+), 12 deletions(-)"
            lines = result.stdout.strip().splitlines()
            if not lines:
                return 0, 0
            last = lines[-1]
            added = 0
            removed = 0
            import re
            m_add = re.search(r'(\d+)\s+insertions?\(\+\)', last)
            m_del = re.search(r'(\d+)\s+deletions?\(-\)', last)
            if m_add:
                added = int(m_add.group(1))
            if m_del:
                removed = int(m_del.group(1))
            return added, removed
        except Exception:
            return None, None

    def _check_diff_budget(
        self, contract: dict, changed_files: list[str],
        lines_added: int = 0, lines_removed: int = 0,
        new_abstractions: list[str] | None = None,
        new_dependencies: list[str] | None = None,
    ) -> tuple[bool, str]:
        """检查 Diff Budget（架构 §8.6.7, §8.7.7）。

        检查项: max_files / max_lines_changed / allow_new_abstractions / allow_new_dependencies
        """
        budget = contract.get("budget", {})
        violations: list[str] = []

        # 1. 文件数
        max_files = budget.get("max_files", 3)
        actual_files = len(changed_files)
        if actual_files > max_files:
            violations.append(f"文件数超预算: {actual_files} > {max_files}")

        # 2. 行数变更
        max_lines = budget.get("max_lines_changed", budget.get("max_lines", 200))
        total_lines = lines_added + lines_removed
        if total_lines > max_lines:
            violations.append(f"行数超预算: +{lines_added}/-{lines_removed} (total={total_lines}) > {max_lines}")

        # 3. 新抽象
        allow_abstractions = budget.get("allow_new_abstractions", False)
        if new_abstractions and not allow_abstractions:
            violations.append(f"不允许新抽象但检测到: {new_abstractions}")

        # 4. 新依赖
        allow_deps = budget.get("allow_new_dependencies", False)
        if new_dependencies and not allow_deps:
            violations.append(f"不允许新依赖但检测到: {new_dependencies}")

        if violations:
            return False, " | ".join(violations)
        return True, "OK"

    def _check_allowed_only(
        self, contract: dict, changed_files: list[str],
    ) -> bool:
        """检查修改的文件是否都在 allowedFiles 内。"""
        import fnmatch
        allowed = contract.get("allowed_files", [])
        if not allowed:
            return True
        for f in changed_files:
            if not any(fnmatch.fnmatch(f, pattern) for pattern in allowed):
                return False
        return True

    def _run_quick_check(
        self, state: RunState, changed_files: list[str],
    ) -> dict:
        """Per-task 增量验证 — 快速检查 typecheck/compile/lint。

        返回可序列化的 QuickCheckReport 摘要。
        """
        if not changed_files:
            return {"status": "skipped", "reason": "无变更文件"}
        try:
            from pathlib import Path

            from engines.guard.quick_check import QuickCheckRunner

            project_root = Path(state.project_root) if state.project_root else Path.cwd()
            runner = QuickCheckRunner(project_root=project_root)
            report = runner.run_checks(changed_files)

            result = {
                "status": "passed" if report.all_passed else "warning",
                "summary": report.summary(),
                "total_duration_ms": report.total_duration_ms,
                "checks": [
                    {
                        "name": r.check_name,
                        "status": r.status.value,
                        "message": r.message,
                        "errors": r.errors[:5] if r.errors else [],
                    }
                    for r in report.results
                ],
            }
            state.task_state.notes.append(
                f"[EXECUTE quick_check] {report.summary()}"
            )
            return result
        except Exception as exc:
            logger.debug("QuickCheck skipped: %s", exc)
            return {"status": "skipped", "reason": str(exc)}


class VerifyHandler(StageHandler):
    """验证处理器 —— 运行 ScenarioRunner + SanityChecker，判断通过/失败。

    Python 职责（架构定义）:
        ScenarioRunner 跑场景、SanityChecker 检查环境
    AI 职责:
        读失败报告、判断根因
    """

    stage = StageType.VERIFY

    def handle(self, state: RunState) -> RunState:
        logger.info("Verify — running scenario verification and sanity checks")

        state.task_state.status = state.task_state.status.__class__.VERIFYING
        state.task_state.stage = StageType.VERIFY

        # 1. 运行 Sanity Check（从项目配置读取检查项，fallback 到合理默认）
        sanity_failures: list[str] = []
        try:
            from engines.scenario.sanity import SanityChecker
            from engines.scenario.models import SanityCheckItem
            from engines.scenario.resources import default_adapters

            adapters = default_adapters()
            checker = SanityChecker(adapters=adapters)

            # 读取项目级配置或使用默认值（不再硬编码 localhost）
            check_items = self._load_sanity_check_items(state)
            if check_items:
                report = checker.check(check_items)
                if not report.all_passed:
                    for result in report.results:
                        if not result.passed:
                            msg = f"Sanity FAIL: {result.check_name} — {result.message}"
                            sanity_failures.append(msg)
                            logger.warning(msg)
                    state.task_state.notes.extend(sanity_failures)
            else:
                state.task_state.notes.append("[VERIFY] 无 Sanity 检查项配置，跳过")
        except Exception as exc:
            logger.warning("Sanity check failed: %s", exc)
            state.task_state.notes.append(f"[VERIFY] Sanity checker error: {exc}")

        # 2. 运行 Scenario 验证
        scenario_results: list = []
        try:
            from engines.scenario.runner import ScenarioRunner
            from engines.scenario.models import Scenario

            runner = ScenarioRunner()

            # 加载 .ai/scenarios/ 下的场景文件
            scenarios = self._load_scenarios(state.project_root)
            if scenarios:
                for scenario in scenarios:
                    result = runner.run(scenario)
                    scenario_results.append(result)
        except Exception as exc:
            logger.warning("Scenario runner failed: %s", exc)
            state.task_state.notes.append(f"[VERIFY] ScenarioRunner error: {exc}")

        # 3. 分析验证结果
        # 环境故障（sanity 失败）→ 不可自动修复
        if sanity_failures:
            from engines.state.enums import FailureCategory
            from engines.state.models import FailureRecord

            for msg in sanity_failures:
                state.failures.append(FailureRecord(
                    category=FailureCategory.ENVIRONMENT,
                    message=msg,
                    stage=StageType.VERIFY,
                    attempt_count=state.task_state.retry_count + 1,
                ))
            state.verification.status = VerificationStatus.FAILED
            state.verification.summary = "; ".join(sanity_failures)
            state.task_state.notes.append(
                "[VERIFY] 环境故障 — 不可自动修复, 请检查服务是否启动"
            )
            logger.warning("Verification failed: environment issues detected")
            return self._stop_failure(state, "环境故障: " + state.verification.summary)

        # 代码逻辑故障（scenario assertions 失败）
        if scenario_results:
            failed = [r for r in scenario_results if not getattr(r, 'passed', True)]
            if failed:
                from engines.state.enums import FailureCategory
                from engines.state.models import FailureRecord

                for fr in failed:
                    detail = getattr(fr, 'summary', str(fr))
                    state.failures.append(FailureRecord(
                        category=FailureCategory.CODE,
                        message=detail,
                        stage=StageType.VERIFY,
                        attempt_count=state.task_state.retry_count + 1,
                    ))
                state.verification.status = VerificationStatus.FAILED
                state.verification.summary = f"{len(failed)}/{len(scenario_results)} scenarios failed"
                state.task_state.notes.append(
                    f"[VERIFY] {len(failed)} scenarios failed — 进入 REPAIR"
                )
                logger.info("Verification failed: %d scenarios, entering REPAIR", len(failed))
                return self._advance_to(state, StageType.REPAIR,
                                        f"验证失败 ({len(failed)} scenarios), 进入修复")

        # 无场景文件时标记 SKIPPED（不是 PASSED）
        if not scenario_results:
            state.verification.status = VerificationStatus.SKIPPED \
                if hasattr(VerificationStatus, 'SKIPPED') else VerificationStatus.PASSED
            state.verification.summary = "无场景文件 (.ai/scenarios/*.yaml)，验证跳过"
            state.task_state.notes.append("[VERIFY] 无场景文件 — 建议添加场景以确保质量")
            logger.warning("No scenarios found, verification skipped")
            return self._complete(state, "验证跳过: 无场景文件")

        # 全部通过
        state.verification.status = VerificationStatus.PASSED
        state.verification.summary = f"All {len(scenario_results)} scenarios passed"
        state.verification.total_assertions = sum(
            getattr(r, 'total_assertions', 0) for r in scenario_results
        )
        state.verification.passed_assertions = state.verification.total_assertions
        state.task_state.notes.append("[VERIFY] 全部验证通过")

        logger.info("Verification passed: %d scenarios, %d assertions",
                     len(scenario_results), state.verification.total_assertions)
        return self._complete(state, f"验证通过: {state.verification.summary}")

    @staticmethod
    def _load_sanity_check_items(state: RunState) -> list:
        """从项目配置加载 Sanity 检查项，fallback 到默认值。

        检查 .ai/loop-config.json 中的 sanity_checks 字段，
        如果未配置则使用合理默认（localhost 常见端口）。
        """
        from pathlib import Path
        from engines.scenario.models import SanityCheckItem

        project_root = Path(state.project_root) if state.project_root else Path.cwd()
        config_path = project_root / ".ai" / "loop-config.json"

        if config_path.exists():
            try:
                import json
                config = json.loads(config_path.read_text(encoding="utf-8"))
                items_config = config.get("sanity_checks", [])
                if items_config:
                    return [
                        SanityCheckItem(**item) for item in items_config
                    ]
            except Exception:
                pass  # fallback to defaults

        # 默认检查项（常见配置）
        return [
            SanityCheckItem(name="http-local", resource="http", target="http://localhost:8080"),
            SanityCheckItem(name="port-3306", resource="port", target="localhost:3306"),
            SanityCheckItem(name="port-6379", resource="port", target="localhost:6379"),
        ]

    @staticmethod
    def _load_scenarios(project_root) -> list:
        """Load Scenario objects from .ai/scenarios/*.yaml files."""
        import json
        from pathlib import Path
        scenarios_dir = Path(project_root) / ".ai" / "scenarios"
        if not scenarios_dir.is_dir():
            return []

        loaded = []
        for yaml_file in sorted(scenarios_dir.glob("*.yaml")):
            try:
                # Simple YAML parsing without PyYAML dependency
                import yaml
                with open(yaml_file, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
            except ImportError:
                # JSON fallback
                try:
                    with open(yaml_file, encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    logger.debug("Cannot parse %s (no yaml/json parser)", yaml_file.name)
                    continue
            except Exception as exc:
                logger.warning("Failed to load scenario %s: %s", yaml_file.name, exc)
                continue

            if isinstance(data, dict):
                try:
                    from engines.scenario.models import Scenario
                    scenario = Scenario(**data)
                    loaded.append(scenario)
                except Exception as exc:
                    logger.warning("Invalid scenario in %s: %s", yaml_file.name, exc)

        return loaded


class RepairHandler(StageHandler):
    """修复处理器 —— 分析 FailureRecord，注入失败上下文。

    Python 职责（架构定义）:
        ContextRouter 注入失败上下文
    AI 职责:
        分析根因、最小修复
    """

    stage = StageType.REPAIR

    def handle(self, state: RunState) -> RunState:
        logger.info("Repair — analyzing failures and loading context")

        state.task_state.status = state.task_state.status.__class__.REPAIRING
        state.task_state.stage = StageType.REPAIR

        # 1. 检查重试次数
        max_retries = 3
        if state.task_state.retry_count >= max_retries:
            logger.error("Repair retry limit (%d) exceeded", max_retries)
            state.task_state.notes.append(
                f"[REPAIR] 超过最大重试次数 {max_retries}, 升级给用户"
            )
            return self._stop_failure(state, f"修复失败: 超过 {max_retries} 次重试")

        state.task_state.retry_count += 1

        # 2. 分析最近的 FailureRecord
        #    环境故障不可通过代码修复，直接终止
        if state.failures:
            latest = state.failures[-1]
            if latest.category.value == "environment":
                logger.error(
                    "Environment failure cannot be repaired automatically: %s",
                    latest.message[:120],
                )
                state.task_state.notes.append(
                    f"[REPAIR] 环境故障，无法自动修复: {latest.message[:100]}"
                )
                return self._stop_failure(
                    state,
                    f"环境故障不可自动修复: {latest.message[:200]}",
                )
            logger.info("Latest failure [%s]: %s", latest.category.value, latest.message[:120])
            state.task_state.notes.append(
                f"[REPAIR] attempt={state.task_state.retry_count}/{max_retries}, "
                f"category={latest.category.value}, message={latest.message[:100]}"
            )
        else:
            state.task_state.notes.append(
                f"[REPAIR] attempt={state.task_state.retry_count}/{max_retries}, 无 failure 记录"
            )

        # 3. 通过 ContextRouter 加载失败相关上下文
        try:
            from engines.context.router import ContextRouter
            router = ContextRouter(state.project_root)
            bundle = router.route(stage=StageType.REPAIR, run_state=state)
            if bundle:
                state.task_state.notes.append(
                    f"[REPAIR context] tokens={bundle.total_tokens}, "
                    f"files={len(bundle.pieces)}"
                )
        except Exception as exc:
            logger.warning("ContextRouter failed for REPAIR: %s", exc)
            state.task_state.notes.append(f"[REPAIR] ContextRouter 不可用: {exc}")

        # 4. 设置状态，AI 分析根因并修复
        state.task_state.notes.append(
            "[REPAIR] AI 需: 分析根因 → 最小修复 → 不修改 scenario 定义 → 不删除断言"
        )

        logger.info("Repair ready — AI should analyze root cause and apply minimal fix")
        return self._advance_to(state, StageType.VERIFY, f"修复 attempt {state.task_state.retry_count}, 重新验证")


class ReviewHandler(StageHandler):
    """审查处理器 —— Guard + Plan 合规 + Style Contract + Anti-Cheating（架构 §9.6）。

    Python 职责:
      1. Guard 检查（边界/风险等级/ScopeBoundary/RiskLevel）
      2. Plan 合规检查（forbidden files / allowed only / diff budget）
      3. Anti-Cheating 检查（TestIntegrity / AssertionWeakening / SkipModification）
      4. Task Execution Log 汇总
      5. 输出审查报告

    AI 职责:
      1. 判断是否需要 Plan Change
      2. 解释 Anti-Cheating 违规
    """

    stage = StageType.REVIEW

    def handle(self, state: RunState) -> RunState:
        logger.info("Review — running guard, compliance, anti-cheating, quality, and rollback checks")

        # 初始化实例级警告收集器
        self._plan_warnings: list[str] = []

        state.task_state.stage = StageType.REVIEW
        violations: list[str] = []
        warnings: list[str] = []

        # 1. Guard 检查（边界、风险等级）
        guard_violations, guard_warnings = self._run_guard_checks(state)
        violations.extend(guard_violations)
        warnings.extend(guard_warnings)

        # 2. Plan 合规检查（逐 Task，详细对比 allowedFiles/forbiddenFiles/diff budget）
        plan_violations = self._check_plan_compliance(state)
        violations.extend(plan_violations)

        # 3. Anti-Cheating 检查
        ac_violations, ac_warnings = self._run_anti_cheating(state)
        violations.extend(ac_violations)
        warnings.extend(ac_warnings)

        # 4. Code Quality Gate / Elegance Review（架构 §8.7.11）
        quality_violations, quality_warnings = self._run_code_quality_check(state)
        violations.extend(quality_violations)
        warnings.extend(quality_warnings)

        # 5. 高风险任务回滚方案生成（架构 §16.4）
        rollback_plan = self._generate_rollback_if_needed(state)
        if rollback_plan:
            state.task_state.notes.append(f"[REVIEW] 回滚方案已生成: {rollback_plan}")

        # 5.5. Schema Version 记录（DDL/migration 变更追踪）
        schema_record = self._record_schema_version(state)
        if schema_record:
            state.task_state.notes.append(f"[REVIEW] Schema 版本已记录: {schema_record}")

        # 6. Task Execution Log 汇总
        task_summary = self._summarize_task_logs(state)

        # 7. 输出审查报告
        total_issues = len(violations) + len(warnings)
        if total_issues > 0:
            state.task_state.notes.append(
                f"[REVIEW] {len(violations)} violations, {len(warnings)} warnings: "
                + "; ".join((violations + warnings)[:5])
            )
            logger.warning("Review: %d violations, %d warnings", len(violations), len(warnings))
        else:
            state.task_state.notes.append("[REVIEW] 审查通过, 无违规")
            logger.info("Review passed — no violations")

        state.task_state.notes.append(f"[REVIEW] {task_summary}")

        # 记录审查报告到 metadata 供 Memory 使用
        state.metadata["review_report"] = {
            "violations": violations,
            "warnings": warnings,
            "task_summary": task_summary,
            "rollback_plan": rollback_plan,
        }

        return self._complete(
            state,
            f"review: {len(violations)} violations, {len(warnings)} warnings, {task_summary}",
        )

    # ── Guard 检查 ────────────────────────────────────────────

    def _run_guard_checks(self, state: RunState) -> tuple[list[str], list[str]]:
        violations: list[str] = []
        warnings: list[str] = []
        try:
            from engines.guard.engine import Guard
            from engines.guard.rules import ScopeBoundaryRule, RiskLevelRule, SanityCheckRule

            guard = Guard()
            guard.add_rule(ScopeBoundaryRule())
            guard.add_rule(RiskLevelRule())
            guard.add_rule(SanityCheckRule())

            result = guard.check(state)
            individual_results = result.details.get("results", [])
            passed = sum(1 for r in individual_results if getattr(r, 'passed', True))
            state.task_state.notes.append(
                f"[REVIEW] Guard: {passed}/{len(individual_results)} passed, blocked={result.block}"
            )
            if result.block:
                violations.append(f"Guard blocked: {result.reason}")
            for r in individual_results:
                if getattr(r, 'severity', None) and str(r.severity) == 'WARN':
                    warnings.append(f"Guard warn [{getattr(r, 'rule_name', '?')}]: {getattr(r, 'reason', '')}")
        except Exception as exc:
            logger.warning("Guard review check failed: %s", exc)
            state.task_state.notes.append(f"[REVIEW] Guard 跳过: {exc}")
        return violations, warnings

    # ── Anti-Cheating 检查 (架构 §8.7.10 / §16.3) ────────────

    def _run_anti_cheating(self, state: RunState) -> tuple[list[str], list[str]]:
        """运行反作弊规则：TestIntegrity / AssertionWeakening / SkipModification。"""
        violations: list[str] = []
        warnings: list[str] = []
        try:
            from engines.guard.engine import Guard
            from engines.guard.rules import (
                AssertionWeakeningRule,
                SkipModificationRule,
                TestIntegrityRule,
            )

            guard = Guard()
            guard.add_rule(TestIntegrityRule())
            guard.add_rule(AssertionWeakeningRule())
            guard.add_rule(SkipModificationRule())

            result = guard.check(state)
            individual_results = result.details.get("results", [])
            for r in individual_results:
                rule_name = getattr(r, 'rule_name', '?')
                if not getattr(r, 'passed', True):
                    severity = str(getattr(r, 'severity', 'WARN'))
                    reason = getattr(r, 'reason', '')
                    if severity == 'BLOCK':
                        violations.append(f"Anti-Cheating [{rule_name}]: {reason}")
                    else:
                        warnings.append(f"Anti-Cheating [{rule_name}]: {reason}")

            anti_cheat_passed = sum(1 for r in individual_results if getattr(r, 'passed', True))
            state.task_state.notes.append(
                f"[REVIEW] Anti-Cheating: {anti_cheat_passed}/{len(individual_results)} passed"
            )
        except Exception as exc:
            logger.warning("Anti-cheating check failed: %s", exc)
            state.task_state.notes.append(f"[REVIEW] Anti-Cheating 跳过: {exc}")
        return violations, warnings

    # ── Plan 合规检查（增强: 逐 Task 对比 PlanContract） ─────

    def _check_plan_compliance(self, state: RunState) -> list[str]:
        """检查 Plan 合规性: 逐 Task 对比 Plan 合约（架构 §8.6.11）。"""
        violations: list[str] = []

        # 逐 Task 对比
        for i, contract in enumerate(state.plan_contracts):
            task_id = contract.get("task_id", f"T{i + 1}")
            allowed = contract.get("allowed_files", [])

            # 找对应的 TaskExecutionLog
            matching_logs = [l for l in state.task_state.task_logs if l.task_id == task_id]
            if not matching_logs:
                if i <= state.task_state.current_task_index:
                    violations.append(f"Task {task_id}: 无执行记录")
                continue

            log = matching_logs[0]

            # 检查 allowedFiles
            if not log.plan_compliance.get("allowed_files_only", True):
                violations.append(f"Task {task_id}: 修改了 allowedFiles 之外的文件 (allowed={allowed})")
            if log.plan_compliance.get("diff_budget_exceeded", False):
                violations.append(
                    f"Task {task_id}: Diff Budget 超限: {log.plan_compliance.get('diff_budget_detail', '')}"
                )

            # 检查是否引入了未计划的抽象（从 new_abstractions 字段）
            log_meta = log.verification if isinstance(log.verification, dict) else {}
            new_abstractions = log_meta.get("new_abstractions", [])
            if new_abstractions:
                violations.append(
                    f"Task {task_id}: 引入了新抽象 (未在 Plan 中声明): {new_abstractions}"
                )

            # Style Contract 检查
            if not log.plan_compliance.get("style_contract_followed", True):
                violations.append(f"Task {task_id}: 违反 Style Contract")
            if not log.plan_compliance.get("reuse_check_passed", True):
                violations.append(f"Task {task_id}: Reuse Check 未通过 (可能引入了重复代码)")

            # 检查无关格式化/重构迹象
            if log.lines_removed > 100 and not contract.get("is_refactor_task"):
                self._plan_warnings.append(
                    f"Task {task_id}: 变更行数大 ({log.lines_added}+/{log.lines_removed}-), "
                    "可能存在无关格式化/重构"
                )

            if log.issues:
                for issue in log.issues:
                    violations.append(f"Task {task_id}: {issue}")

        # 全局校验
        total_files = set()
        for log in state.task_state.task_logs:
            total_files.update(log.changed_files)
        plan_total_files = set()
        for c in state.plan_contracts:
            plan_total_files.update(c.get("allowed_files", []))
        extra_files = total_files - plan_total_files
        if extra_files:
            violations.append(f"修改了 Plan 未声明的文件: {list(extra_files)[:5]}")

        if state.task_state.retry_count > 5:
            violations.append("重试次数异常 (>5), 建议检查 Plan 是否合理")
        if len(state.failures) > 10:
            violations.append("失败记录过多 (>10), 建议重新评估方案")

        # 合并 plan_warnings（大变更等）
        if self._plan_warnings:
            violations.extend(self._plan_warnings)

        return violations

    # ── Code Quality Gate ──────────────────────────────────────

    def _run_code_quality_check(self, state: RunState) -> tuple[list[str], list[str]]:
        """运行 Code Quality Gate / Elegance Review（架构 §8.7.11）。

        检查 AI 是否已提交代码质量自评，如果已提交则评估，
        如果未提交则将检查项加入 pending_prompt。
        """
        violations: list[str] = []
        warnings: list[str] = []

        # 检查是否有 AI 提交的质量自评
        quality_assessment = state.metadata.get("code_quality_assessment")
        if not quality_assessment:
            # 将 Code Quality Gate prompt 加入审查输出
            try:
                from engines.guard.code_quality import CodeQualityGate
                gate = CodeQualityGate()
                state.metadata["code_quality_prompt"] = gate.render_prompt()
                state.task_state.notes.append(
                    "[REVIEW] Code Quality Gate prompt 已生成 — AI 需自评后提交"
                )
            except Exception as exc:
                logger.debug("CodeQualityGate not available: %s", exc)
            return violations, warnings

        # 评估 AI 的自评结果
        try:
            from engines.guard.code_quality import CodeQualityGate
            gate = CodeQualityGate()
            report = gate.evaluate(quality_assessment)

            state.metadata["code_quality_report"] = {
                "score": report.total_score,
                "max_score": report.max_score,
                "passed": report.passed,
                "critical": report.critical_violations,
                "suggestions": report.suggestions,
            }

            if not report.passed:
                violations.append(
                    f"Code Quality Gate 未通过: score={report.total_score}/{report.max_score}"
                )
                for s in report.suggestions[:3]:
                    violations.append(f"  - {s}")

            if report.critical_violations:
                violations.append(
                    f"严重代码质量问题: {', '.join(report.critical_violations)}"
                )

            state.task_state.notes.append(
                f"[REVIEW] Code Quality: {report.total_score}/{report.max_score} "
                f"({'PASS' if report.passed else 'FAIL'})"
            )
        except Exception as exc:
            logger.warning("Code quality evaluation failed: %s", exc)

        return violations, warnings

    # ── 回滚方案自动生成 ───────────────────────────────────────

    def _generate_rollback_if_needed(self, state: RunState) -> str | None:
        """高风险任务自动生成回滚方案（架构 §16.4）。

        L4/L5 任务或涉及 DDL 变更时强制生成。
        """
        intake = state.task_intake
        risk = intake.risk_level if intake else "L1"

        if risk not in ("L4", "L5"):
            return None

        try:
            from pathlib import Path

            from engines.guard.rollback import RollbackPlanner

            project_root = Path(state.project_root) if state.project_root else Path.cwd()
            planner = RollbackPlanner(project_root=project_root)
            plans = planner.generate(state)
            planner.write(plans)

            summary = RollbackPlanner.generate_summary(plans)
            state.metadata["rollback_plan"] = {
                "generated": True,
                "risk_level": risk,
                "steps": len(plans),
                "summary": summary,
            }
            logger.info("Rollback plan generated for L4/L5 task: %s", summary)
            return summary
        except Exception as exc:
            logger.warning("Rollback plan generation failed: %s", exc)
            return None

    # ── Schema Version 记录 ────────────────────────────────────

    def _record_schema_version(self, state: RunState) -> str | None:
        """检测 DDL/migration 变更并记录 Schema 版本（架构 §12）。

        从所有 Task 的 changed_files 中检测 migration 文件，
        自动写入 .ai/schema_version.md。
        """
        # 收集所有 changed_files
        all_files: list[str] = []
        for log in state.task_state.task_logs:
            all_files.extend(log.changed_files)
        if not all_files:
            return None

        try:
            from pathlib import Path

            from engines.guard.schema_version import SchemaVersionRecorder

            project_root = Path(state.project_root) if state.project_root else Path.cwd()
            recorder = SchemaVersionRecorder(project_root=project_root)
            return recorder.record_from_state(state)
        except Exception as exc:
            logger.debug("Schema version recording skipped: %s", exc)
            return None

    # ── Task Log 汇总 ─────────────────────────────────────────

    def _summarize_task_logs(self, state: RunState) -> str:
        """汇总 Task Execution Logs。"""
        logs = state.task_state.task_logs
        if not logs:
            return "无 Task 执行记录"

        total = len(logs)
        implemented = sum(1 for l in logs if l.status == "implemented")
        verified = sum(1 for l in logs if l.status == "verified")
        total_files = sum(len(l.changed_files) for l in logs)

        return (
            f"Tasks: {implemented}/{total} implemented, {verified} verified, "
            f"{total_files} files changed"
        )


class MemoryHandler(StageHandler):
    """记忆处理器 —— 三层存储：session → index + entries → projection。

    Python 职责:
        MemoryExtractor 提取候选 → MemoryStore 写入 entries/ + 更新索引
        → MemoryProjection 同步到 projections/
    AI 职责:
        判断哪些值得沉淀
    """

    stage = StageType.MEMORY

    def handle(self, state: RunState) -> RunState:
        logger.info("Memory — extracting learnings and syncing projections")

        state.task_state.stage = StageType.MEMORY

        try:
            from engines.memory.extractor import MemoryExtractor
            from engines.memory.store import MemoryStore
            from engines.memory.projection import MemoryProjection

            store = MemoryStore(project_root=state.project_root)

            # 0. 迁移旧格式（如果需要）
            store.migrate_if_needed()

            store.load_index()

            # 1. 提取候选 memory
            extractor = MemoryExtractor()
            candidates = extractor.extract(state)
            state.task_state.notes.append(
                f"[MEMORY] 提取 {len(candidates)} 条候选 memory"
            )

            # 2. 保存 session 原料 → .ai/memory/sessions/
            session = extractor.build_session_memory(state)
            store.save_session(session.model_dump() if hasattr(session, 'model_dump') else session)

            # 3. 写入 entries/ + 更新 memory.md 索引
            added = 0
            for entry in candidates:
                if store.add(entry):
                    added += 1

            if added > 0:
                all_tags: list[str] = []
                for entry in candidates:
                    all_tags.extend(entry.tags)
                promoted = store.promote_by_tags(list(set(all_tags)), min_matches=2)
                if promoted:
                    state.task_state.notes.append(
                        f"[MEMORY] 自动升级 {promoted} 条 DRAFT→CONFIRMED"
                    )
                state.task_state.notes.append(
                    f"[MEMORY] 写入 {added} 条新 memory → .ai/memory/entries/ + 索引更新"
                )
                logger.info("Memory: %d new entries written", added)

            # 4. 定期治理: 淘汰过期 draft、检查压缩
            stale_count = store.evict_stale_drafts()
            if stale_count:
                state.task_state.notes.append(
                    f"[MEMORY] 淘汰 {stale_count} 条过期 draft → archive/stale/"
                )
            compress_groups = store.compress_duplicates()
            if compress_groups:
                state.task_state.notes.append(
                    f"[MEMORY] 发现 {compress_groups} 组可压缩的同类记忆"
                )

            # 5. 同步投影 → .ai/memory/projections/ + CLAUDE.md 等
            projection = MemoryProjection(store)
            updated = projection.sync("claude")
            state.task_state.notes.append(
                f"[MEMORY] 已同步投影: {len(updated)} 文件"
            )

        except Exception as exc:
            logger.warning("Memory handler failed: %s", exc)
            state.task_state.notes.append(f"[MEMORY] Memory 系统错误: {exc}")

        return self._complete(state, f"记忆沉淀完成")


class DirectExecuteHandler(StageHandler):
    """Direct Mode 执行处理器 —— 快速通道：跳过 Spec/Plan 直接改码。

    轻量流程: Guard 前置检查 → AI 编码 → 可选验证 → Review
    """

    stage = StageType.DIRECT_EXECUTE

    def handle(self, state: RunState) -> RunState:
        logger.info("Direct Execute — fast path, skipping spec/plan")

        intake = state.task_intake

        # 1. 风险等级检查: Direct Mode 仅允许 L1-L2
        if intake and intake.risk_level in ("L4", "L5"):
            logger.warning("Risk %s too high for direct mode, switching to standard", intake.risk_level)
            state.task_state.notes.append(
                f"[DIRECT] 风险 {intake.risk_level} 过高, 建议使用 /aicode-full"
            )
            return self._advance_to(state, StageType.SPEC,
                                    f"风险过高 ({intake.risk_level}), 转标准流程")

        # ── Phase VALIDATE: AI 已提交结果 ──
        submitted = state.metadata.get("direct_execute_result")
        if submitted and isinstance(submitted, dict):
            return self._validate_direct_result(state, submitted, intake)

        # ── Phase PREPARE: 构造轻量执行 prompt ──
        return self._prepare_direct(state, intake)

    def _prepare_direct(self, state: RunState, intake) -> RunState:
        """Direct Mode PREPARE — 构造轻量执行 prompt。"""
        # 1. 轻量 Guard 检查
        try:
            from engines.guard.engine import Guard
            from engines.guard.rules import ScopeBoundaryRule, RiskLevelRule

            guard = Guard()
            guard.add_rule(ScopeBoundaryRule())
            guard.add_rule(RiskLevelRule())
            result = guard.check(state)
            if result.block:
                return self._stop_failure(state, f"Direct mode guard blocked: {result.reason}")
            individual_results = result.details.get("results", [])
            passed = sum(1 for r in individual_results if getattr(r, 'passed', True))
            state.task_state.notes.append(f"[DIRECT] Guard: {passed}/{len(individual_results)} passed")
        except Exception as exc:
            logger.warning("Guard check skipped in direct mode: %s", exc)

        # 2. 设置执行状态
        state.task_state.status = state.task_state.status.__class__.IN_PROGRESS
        state.task_state.stage = StageType.DIRECT_EXECUTE

        # 3. 构造 AI prompt
        user_input = state.metadata.get("user_input", "")
        state.pending_action = "direct_execute"
        state.pending_prompt = {
            "instruction": (
                "Direct Mode 快速执行:\n"
                f"需求: {user_input}\n\n"
                "约束:\n"
                "- 修改文件数 ≤ 3\n"
                "- 遵守项目已有代码风格\n"
                "- 不引入新的依赖或抽象\n"
                "- 保持已有行为不变\n\n"
                "提交格式:\n"
                "{\n"
                '  "changed_files": ["path/to/file"],\n'
                '  "lines_added": N,\n'
                '  "lines_removed": N,\n'
                '  "summary": "变更说明",\n'
                '  "style_contract_followed": true\n'
                "}"
            ),
            "risk_level": intake.risk_level if intake else "L1",
        }
        state.needs_ai_input = True
        state.task_state.notes.append(
            "[DIRECT] PREPARE: AI 直接编码, 更改 ≤3 文件, 遵守项目风格"
        )
        logger.info("Direct Execute prompt ready")
        return state

    def _validate_direct_result(
        self, state: RunState, submitted: dict, intake,
    ) -> RunState:
        """Direct Mode VALIDATE — 校验 AI 提交的执行结果。"""
        changed_files = submitted.get("changed_files", [])
        summary = submitted.get("summary", "")

        # 1. 文件数检查
        if len(changed_files) > 3:
            state.task_state.notes.append(
                f"[DIRECT] 文件数超限: {len(changed_files)} > 3"
            )
            # 不阻止，但记录

        # 2. 记录执行结果
        from engines.state.models import TaskExecutionLog
        log = TaskExecutionLog(
            task_id="direct-T1",
            status="implemented",
            changed_files=changed_files,
            lines_added=submitted.get("lines_added", 0),
            lines_removed=submitted.get("lines_removed", 0),
        )
        state.task_state.task_logs.append(log)

        state.task_state.notes.append(
            f"[DIRECT] 执行完成: files={changed_files}, summary={summary[:100]}"
        )

        state.needs_ai_input = False
        state.pending_action = ""
        state.metadata.pop("direct_execute_result", None)

        # 3. 可选跳过验证
        if intake and not intake.verification_required:
            logger.info("Direct mode: skipping verification")
            return self._advance_to(state, StageType.REVIEW, "Direct Mode: 跳过验证")

        return self._complete(state, f"Direct Mode: 完成 {len(changed_files)} 个文件")


# ── 默认 Handler 注册表 ──────────────────────────────────────────

def default_handlers() -> dict[StageType, StageHandler]:
    """返回内置的阶段处理器映射。

    每个 handler 实现 Python 引擎的确定性工作（context/guard/scenario/memory），
    创造性工作（spec/plan/code/root-cause）由 AI 完成。
    应用项目可通过注入自定义 handler 覆盖默认实现。
    """
    return {
        StageType.INTAKE:         IntakeHandler(),
        StageType.SPEC:           SpecHandler(),
        StageType.PLAN:           PlanHandler(),
        StageType.EXECUTE:        ExecuteHandler(),
        StageType.VERIFY:         VerifyHandler(),
        StageType.REPAIR:         RepairHandler(),
        StageType.REVIEW:         ReviewHandler(),
        StageType.MEMORY:         MemoryHandler(),
        StageType.DIRECT_EXECUTE: DirectExecuteHandler(),
    }
