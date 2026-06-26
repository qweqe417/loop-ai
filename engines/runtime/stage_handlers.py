"""阶段处理器基类与阶段流转定义。

每个 StageHandler 对应一个循环阶段，负责处理该阶段的逻辑，
并在完成后设置 RunState.decision 决定下一步流转。
"""

# 启用 Python 3.10+ 的延迟注解求值特性
from __future__ import annotations

# 导入日志模块，用于记录阶段处理过程
import logging
# 导入 ABC（抽象基类）和 abstractmethod（抽象方法装饰器）
from abc import ABC, abstractmethod
# 导入 TYPE_CHECKING 常量，用于类型注解的条件导入
from typing import TYPE_CHECKING

# 导入状态枚举类型：LoopAction（循环动作）、StageType（阶段类型）、VerificationStatus（验证状态）
from engines.state.enums import LoopAction, StageType, VerificationStatus

# 仅在类型检查时导入 RunState，避免循环导入
if TYPE_CHECKING:
    from engines.state.models import RunState

# 获取当前模块的日志记录器
logger = logging.getLogger(__name__)

# ── 阶段流转默认顺序 ──────────────────────────────────────────────

# 每个阶段完成后默认进入的下一个阶段（handler 可通过 decision 覆盖）
# None 表示流程终点
# 默认阶段流转表：定义每个阶段完成后的默认下一阶段
# None 表示流程终点
DEFAULT_FLOW: dict[StageType, StageType | None] = {
    StageType.INTAKE:         StageType.SPEC,
    StageType.SPEC:           StageType.PLAN,
    StageType.PLAN:           StageType.TEST_DESIGN,
    StageType.TEST_DESIGN:    StageType.EXECUTE,
    StageType.EXECUTE:        StageType.REVIEW,       # 先审查（快速门禁）
    StageType.REVIEW:         StageType.VERIFY,        # 审查通过 → 场景验证（可 override 跳 MEMORY）
    StageType.VERIFY:         StageType.MEMORY,        # 验证通过 → 沉淀记忆
    StageType.REPAIR:         StageType.REVIEW,        # 修复后 → 回审查再过门禁再验证
    StageType.MEMORY:         StageType.COMPLETED,
    StageType.DIRECT_EXECUTE: StageType.REVIEW,        # Direct 也先过审查
    StageType.COMPLETED:      None,
    StageType.ABORTED:        None,
}

# 完整标准流程：INTAKE → SPEC → PLAN → TEST_DESIGN → EXECUTE → REVIEW → VERIFY → MEMORY
# REVIEW 在 VERIFY 之前：先快速门禁（Python规则），通过后再跑场景测试
STANDARD_STAGES: list[StageType] = [
    StageType.INTAKE,
    StageType.SPEC,
    StageType.PLAN,
    StageType.TEST_DESIGN,
    StageType.EXECUTE,
    StageType.REVIEW,
    StageType.VERIFY,
    StageType.MEMORY,
]

# Direct Mode 跳过 SPEC/PLAN/TEST_DESIGN，使用更短的阶段列表
DIRECT_STAGES: list[StageType] = [
    StageType.INTAKE,
    StageType.DIRECT_EXECUTE,
    StageType.REVIEW,
    StageType.VERIFY,
]


def next_stage(current: StageType) -> StageType | None:
    """返回当前阶段默认的下一个阶段，不覆盖 handler 决策。

    Args:
        current: 当前阶段类型

    Returns:
        StageType | None: 下一阶段，None 表示流程终点
    """
    return DEFAULT_FLOW.get(current)


def is_terminal(stage: StageType) -> bool:
    """判断是否为终端阶段（不再流转）。

    Args:
        stage: 阶段类型

    Returns:
        bool: 是否为终端阶段
    """
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

    # 阶段类型标识，由子类覆盖
    stage: StageType

    @abstractmethod
    def handle(self, state: RunState) -> RunState:
        """处理当前阶段，返回更新后的 RunState。

        Args:
            state: 当前运行状态

        Returns:
            RunState: 更新后的运行状态
        """
        ...

    def _advance_to(self, state: RunState, target: StageType, reason: str = "") -> RunState:
        """便捷方法：设置决策为进入指定阶段。

        Args:
            state: 当前运行状态
            target: 目标阶段
            reason: 进入原因说明

        Returns:
            RunState: 更新后的运行状态
        """
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

        Args:
            state: 当前运行状态
            reason: 完成原因说明

        Returns:
            RunState: 更新后的运行状态
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

        Args:
            state: 当前运行状态
            target: 目标阶段
            reason: 跳转原因说明

        Returns:
            RunState: 更新后的运行状态
        """
        from engines.state.models import LoopDecision

        state.decision = LoopDecision(
            action=LoopAction.NEXT_STAGE,
            target_stage=target,
            reason=reason or f"{self.stage.value} -> {target.value}",
        )
        return state

    def _retry(self, state: RunState, reason: str) -> RunState:
        """设置决策为重试当前阶段。

        Args:
            state: 当前运行状态
            reason: 重试原因说明

        Returns:
            RunState: 更新后的运行状态
        """
        from engines.state.models import LoopDecision

        state.decision = LoopDecision(
            action=LoopAction.RETRY,
            target_stage=self.stage,
            reason=reason,
        )
        # 增加重试计数
        state.task_state.retry_count += 1
        return state

    def _stop_success(self, state: RunState, reason: str = "") -> RunState:
        """设置决策为成功终止。

        Args:
            state: 当前运行状态
            reason: 成功原因说明

        Returns:
            RunState: 更新后的运行状态
        """
        from engines.state.models import LoopDecision

        state.decision = LoopDecision(
            action=LoopAction.STOP_SUCCESS,
            target_stage=StageType.COMPLETED,
            reason=reason or "任务成功完成",
        )
        return state

    def _stop_failure(self, state: RunState, reason: str) -> RunState:
        """设置决策为失败终止。

        Args:
            state: 当前运行状态
            reason: 失败原因说明

        Returns:
            RunState: 更新后的运行状态
        """
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
            # 使用超过 90%，发出警告
            state.task_state.notes.append(
                f"[BUDGET WARN] 上下文预算紧张: {projected}/{budget_max} tokens "
                f"(本次 +{estimated_tokens})"
            )
        if projected > budget_max:
            # 超出预算，记录严重警告
            state.task_state.notes.append(
                f"[BUDGET CRITICAL] 上下文预算超出: {projected}/{budget_max} tokens, "
                "建议简化上下文或拆分为更小的子任务"
            )
            return False
        return True

    def _track_context_usage(self, state: RunState, tokens_used: int) -> None:
        """跟踪上下文 token 使用量。

        Args:
            state: 当前 RunState
            tokens_used: 本次使用的 token 数
        """
        state.context_budget_used = (state.context_budget_used or 0) + tokens_used

    def _load_preflight_warnings(self, state: RunState) -> list[str]:
        """loop-memory 已通过 .claude/rules/ 自动加载，无需 Python 召回。"""
        return []

    def _load_specification(self, state: RunState, task_id: str = "") -> dict:
        """定位 Spec/Plan 文件路径 + 简要摘要（供 superpowers 子Agent 读取）。

        superpowers:subagent-driven-development 内部自己读 plan/spec 文件，
        这里只提供路径引用，不注入全文（避免冗余 token）。

        Args:
            state: 当前 RunState
            task_id: 任务 ID

        Returns:
            dict: 包含 spec_path, plan_path, spec_summary, plan_summary 的字典
        """
        result: dict = {"spec_path": "", "plan_path": "", "spec_summary": "", "plan_summary": ""}

        try:
            from pathlib import Path
            project_root = Path(state.project_root) if state.project_root else Path.cwd()

            # ── Spec 路径 ──
            spec_dir = project_root / "docs" / "spec"
            spec_files = sorted(spec_dir.glob("*.md")) if spec_dir.exists() else []
            if spec_files:
                latest = max(spec_files, key=lambda p: p.stat().st_mtime)
                result["spec_path"] = str(latest.relative_to(project_root))
            else:
                alt = project_root / ".ai" / "spec.md"
                if alt.exists():
                    result["spec_path"] = ".ai/spec.md"
            if result["spec_path"]:
                full_path = project_root / result["spec_path"]
                raw = full_path.read_text(encoding="utf-8")[:1000]
                lines = [l for l in raw.split("\n") if l.strip() and not l.startswith("#")][:3]
                result["spec_summary"] = " ".join(lines)[:200] if lines else ""

            # ── Plan 路径 ──
            plan_dir = project_root / "docs" / "plan"
            plan_files = sorted(plan_dir.glob("*.md")) if plan_dir.exists() else []
            if plan_files:
                latest = max(plan_files, key=lambda p: p.stat().st_mtime)
                result["plan_path"] = str(latest.relative_to(project_root))
            else:
                alt = project_root / ".ai" / "plan.md"
                if alt.exists():
                    result["plan_path"] = ".ai/plan.md"
            if result["plan_path"] and state.plan_contracts and task_id:
                result["plan_summary"] = f"共 {len(state.plan_contracts)} 个 Task，当前: {task_id}"

        except Exception as exc:
            logger.debug("Specification path loading unavailable: %s", exc)

        return result


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
        """处理 INTAKE 阶段：根据风险等级和 flow_mode 决定下一阶段。

        Args:
            state: 当前运行状态

        Returns:
            RunState: 更新后的运行状态
        """
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

        # 根据风险等级调整 Guard 严格度
        if intake.risk_level in ("L4", "L5"):
            # 高风险任务需要严格审查
            logger.warning("Risk level %s — requires strict guard mode", intake.risk_level)
            state.task_state.notes.append(f"高风险任务 (L4-L5)，需要 strict guard 模式")

        # 记录入口分析结果
        logger.info(
            "Intake: mode=%s complexity=%s risk=%s needs_spec=%s needs_plan=%s",
            intake.flow_mode, intake.complexity, intake.risk_level,
            intake.needs_spec, intake.needs_plan,
        )

        # 根据 flow_mode 决定下一阶段
        if intake.flow_mode == "direct":
            # Direct 模式：跳过 SPEC/PLAN，直接进入 DIRECT_EXECUTE
            return self._advance_to(state, StageType.DIRECT_EXECUTE,
                                    f"Direct Mode (risk={intake.risk_level}): {intake.reason}")
        else:
            # 标准流程：进入 SPEC 阶段
            return self._advance_to(state, StageType.SPEC,
                                    f"Standard flow (risk={intake.risk_level}): {intake.reason}")


class SpecHandler(StageHandler):
    """Spec 生成处理器 —— Gate 检查 → AI skill → 产物校验 → 流转。"""

    stage = StageType.SPEC
    MAX_RETRIES = 3

    def handle(self, state: RunState) -> RunState:
        state.task_state.stage = StageType.SPEC

        from engines.runtime.completion_gate import _check_spec
        gate = _check_spec(state)

        if not gate.passed:
            retries = state.metadata.get("spec_gate_retries", 0)
            if retries >= self.MAX_RETRIES:
                logger.error("SpecHandler: gate failed %d times, aborting", retries)
                state.task_state.notes.append(f"[SPEC] Gate 失败 {retries} 次，中止")
                return self._stop_failure(state, f"Spec gate 失败 {retries} 次: {gate.message}")
            state.metadata["spec_gate_retries"] = retries + 1
            logger.info("SpecHandler: gate failed (retry %d/%d), asking AI — %s", retries + 1, self.MAX_RETRIES, gate.message)
            state.needs_ai_input = True
            state.pending_action = "generate_spec"
            state.pending_prompt = {
                "instruction": f"请运行 /aicode-spec 生成 Spec。\n上次校验失败 (第{retries+1}次): {gate.message}",
            }
            state.task_state.notes.append(f"[SPEC] Gate 未通过 (第{retries+1}次): {gate.message}")
            return state

        logger.info("SpecHandler: gate passed, advancing to PLAN")
        state.task_state.notes.append("[SPEC] Spec 校验通过 → PLAN")
        return self._complete(state, "Spec 校验通过")


class TestDesignStageHandler(StageHandler):
    """测试设计处理器 —— Gate 检查 → AI skill → 场景校验 → 流转。

    Gate 通过后自动扫描 .ai/scenarios/ 子目录，记录到 state.metadata["scenario_dir"]，
    供后续 VERIFY 阶段精确加载对应场景。
    """

    stage = StageType.TEST_DESIGN
    MAX_RETRIES = 3

    def handle(self, state: RunState) -> RunState:
        state.task_state.stage = StageType.TEST_DESIGN

        # resume 时：AI 返回了 scenario_dir → 写入 metadata
        sr = state.metadata.get("scenarios_result") or {}
        if isinstance(sr, dict) and sr.get("scenario_dir"):
            state.metadata["scenario_dir"] = sr["scenario_dir"]
            state.task_state.notes.append(
                f"[TEST_DESIGN] AI 指定场景目录: .ai/scenarios/{sr['scenario_dir']}/"
            )

        from engines.runtime.completion_gate import _check_test_design
        gate = _check_test_design(state)

        if not gate.passed:
            retries = state.metadata.get("td_gate_retries", 0)
            if retries >= self.MAX_RETRIES:
                logger.error("TestDesignStageHandler: gate failed %d times, aborting", retries)
                state.task_state.notes.append(f"[TEST_DESIGN] Gate 失败 {retries} 次，中止")
                return self._stop_failure(state, f"Test Design gate 失败 {retries} 次: {gate.message}")
            state.metadata["td_gate_retries"] = retries + 1
            state.metadata["scenarios_generated"] = True  # 标记已触发，resume 后检查实际文件
            logger.info("TestDesignStageHandler: gate failed (retry %d/%d), asking AI — %s", retries + 1, self.MAX_RETRIES, gate.message)

            # 从 user_input 或 SPEC 产物中提取 feature 名，给 AI 更明确的目录提示
            feature_hint = self._extract_feature_name(state)
            dir_hint = f".ai/scenarios/{feature_hint}/" if feature_hint else ".ai/scenarios/<feature>/"

            state.needs_ai_input = True
            state.pending_action = "generate_scenarios"
            state.pending_prompt = {
                "instruction": (
                    f"请运行 /aicode-test-design --mode full，生成 Scenario YAML 到 {dir_hint}。\n"
                    f"上次校验失败 (第{retries+1}次): {gate.message}\n"
                    f"完成后返回: {{\"scenario_dir\": \"<子目录名>\"}}"
                ),
            }
            state.task_state.notes.append(f"[TEST_DESIGN] Gate 未通过 (第{retries+1}次): {gate.message}")
            return state

        logger.info("TestDesignStageHandler: gate passed, advancing to EXECUTE")
        state.metadata["td_gate_passed"] = True

        # ── 自动记录场景子目录，传给后续 VERIFY 阶段 ──
        self._record_scenario_dir(state)

        state.task_state.notes.append("[TEST_DESIGN] 场景校验通过 → EXECUTE")
        return self._complete(state, "Test Design 校验通过")

    @staticmethod
    def _extract_feature_name(state: RunState) -> str:
        """从 user_input 或 SPEC 文档中提取 feature 名，用作场景子目录名。"""
        user_input = (state.metadata or {}).get("user_input", "")
        if user_input:
            # 简单提取：取中文关键词或英文模块名
            import re
            # 匹配常见模式：实现XX功能、XX模块
            m = re.search(r'(?:实现|开发|修复)([一-龥a-zA-Z0-9_]+?)(?:功能|模块|接口|流程|逻辑|页面|API|api)?', user_input)
            if m:
                return m.group(1).strip().lower().replace(" ", "-")
            # 取前几个词
            words = user_input.strip().split()
            if words:
                return words[0].strip('"\'""''').lower()
        return ""

    @staticmethod
    def _record_scenario_dir(state: RunState) -> None:
        """记录场景子目录到 state.metadata 供 VERIFY 使用。

        优先用 handler 已提取的 feature_hint，不扫描全目录避免拿到旧场景。
        """
        from pathlib import Path
        try:
            # 优先：直接拿刚才 AI 生成的子目录名
            feature_hint = state.metadata.get("_feature_hint", "").strip()
            if feature_hint:
                target = Path(state.project_root) / ".ai" / "scenarios" / feature_hint
                if target.is_dir() and any(target.rglob("*.yaml")):
                    state.metadata["scenario_dir"] = feature_hint
                    state.task_state.notes.append(
                        f"[TEST_DESIGN] 场景目录: .ai/scenarios/{feature_hint}/ → VERIFY 使用"
                    )
                    return

            # 回退：扫描目录
            scenarios_dir = Path(state.project_root) / ".ai" / "scenarios"
            subdirs = sorted([
                d.name for d in scenarios_dir.iterdir()
                if d.is_dir() and any(d.rglob("*.yaml"))
            ])
            if len(subdirs) == 1:
                state.metadata["scenario_dir"] = subdirs[0]
                state.task_state.notes.append(
                    f"[TEST_DESIGN] 场景目录: .ai/scenarios/{subdirs[0]}/"
                )
            elif len(subdirs) > 1:
                state.metadata["scenario_dirs"] = subdirs
                state.task_state.notes.append(
                    f"[TEST_DESIGN] 多场景目录: {subdirs}"
                )
        except Exception as exc:
            logger.debug("Record scenario dir skipped: %s", exc)


class PlanHandler(StageHandler):
    """计划生成处理器 —— Gate 检查 → AI skill → 产物校验 → 流转。"""

    stage = StageType.PLAN
    MAX_RETRIES = 3

    def handle(self, state: RunState) -> RunState:
        state.task_state.stage = StageType.PLAN

        from engines.runtime.completion_gate import _check_plan
        gate = _check_plan(state)

        if not gate.passed:
            retries = state.metadata.get("plan_gate_retries", 0)
            if retries >= self.MAX_RETRIES:
                logger.error("PlanHandler: gate failed %d times, aborting", retries)
                state.task_state.notes.append(f"[PLAN] Gate 失败 {retries} 次，中止")
                return self._stop_failure(state, f"Plan gate 失败 {retries} 次: {gate.message}")
            state.metadata["plan_gate_retries"] = retries + 1
            logger.info("PlanHandler: gate failed (retry %d/%d), asking AI — %s", retries + 1, self.MAX_RETRIES, gate.message)
            state.needs_ai_input = True
            state.pending_action = "generate_plan"
            state.pending_prompt = {
                "instruction": f"请运行 /aicode-plan 生成 Plan。\n上次校验失败 (第{retries+1}次): {gate.message}",
            }
            state.task_state.notes.append(f"[PLAN] Gate 未通过 (第{retries+1}次): {gate.message}")
            return state

        # Gate 通过 = Plan 文件存在，但还需检查 contracts 是否已提取
        if not state.plan_contracts:
            retries = state.metadata.get("plan_contract_retries", 0)
            if retries >= self.MAX_RETRIES:
                logger.error("PlanHandler: contract extraction failed %d times, aborting", retries)
                state.task_state.notes.append(f"[PLAN] Contract 提取失败 {retries} 次，中止")
                return self._stop_failure(state, f"Plan Contract 提取失败 {retries} 次: 请检查 Plan 文件内容是否包含可执行任务")
            state.metadata["plan_contract_retries"] = retries + 1
            plan_file = state.metadata.get("plan_file", "")
            logger.info("PlanHandler: gate passed but plan_contracts empty, asking AI to extract contracts (retry %d/%d)", retries + 1, self.MAX_RETRIES)
            state.needs_ai_input = True
            state.pending_action = "generate_plan"
            state.pending_prompt = {
                "instruction": (
                    f"请运行 /aicode-plan --from {plan_file}，从 Plan 文件提取 Task Contracts。\n"
                    f"Plan 文件 gate 已通过，但 plan_contracts 为空 (第{retries+1}次提取)。\n"
                    f"返回格式: {{\"contracts\": [{{\"task_id\": \"...\", \"goal\": \"...\", \"allowed_files\": [...], \"budget\": {{...}}}}, ...]}}"
                ),
            }
            state.task_state.notes.append(f"[PLAN] Gate 通过但 plan_contracts 为空，等待 AI 提取 Contracts (第{retries+1}次)")
            return state

        logger.info("PlanHandler: gate passed + contracts ready (%d tasks), advancing to TEST_DESIGN", len(state.plan_contracts))
        state.task_state.notes.append(f"[PLAN] Plan 校验通过 ({len(state.plan_contracts)} Contracts) → TEST_DESIGN")
        return self._complete(state, "Plan 校验通过")


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
        """处理 EXECUTE 阶段：逐 Task 执行的主循环。

        支持三个阶段：PREPARE（确认约束）、CONFIRM（确认 Checklist）、VALIDATE（校验结果）。

        Args:
            state: 当前运行状态

        Returns:
            RunState: 更新后的运行状态
        """
        state.task_state.stage = StageType.EXECUTE

        # 初始化 per-task 循环
        contracts = state.plan_contracts
        if not contracts:
            # 无 Plan Contracts，无法执行 — 停止并告知用户
            plan_file = state.metadata.get("plan_file", "")
            if plan_file:
                msg = (
                    f"[EXECUTE] ❌ Plan 文件已指定 ({plan_file}) 但 plan_contracts 为空。"
                    f"请运行 /aicode-plan --from {plan_file} 提取 Contracts。"
                )
            else:
                msg = (
                    "[EXECUTE] ❌ 无 Plan Contracts 且未指定 --plan-file。"
                    "请通过 --plan-file <路径> 指定 Plan 文件。"
                )
            state.task_state.notes.append(msg)
            logger.error(msg)
            return self._stop_failure(state, msg)

        current_idx = state.task_state.current_task_index
        if current_idx >= len(contracts):
            # 所有 Task 完成
            logger.info("All %d tasks executed", len(contracts))
            state.task_state.notes.append(f"[EXECUTE] 全部 {len(contracts)} Tasks 执行完成")
            return self._complete(state, f"全部 {len(contracts)} Tasks 执行完成")

        # ── Phase VALIDATE: AI 已提交当前 Task 结果 ──
        submitted = state.metadata.get("execute_result")
        if submitted and isinstance(submitted, dict):
            # 确认回复处理: AI 提交了 checklist 确认 → 直接进入编码阶段
            if submitted.get("confirmed"):
                state.metadata.pop("execute_result", None)
                confirmed_notes = submitted.get("notes", "")
                state.task_state.notes.append(
                    f"[EXECUTE] ✅ Checklist 已确认: {confirmed_notes[:100]}"
                )
                logger.info("Checklist confirmed, advancing to full task prompt")
                return self._prepare_full_task(state, contracts[current_idx], current_idx, len(contracts))

            # PlanLock 恢复路径: AI 提交 lock_plan 指令
            if submitted.get("lock_plan"):
                state.plan_lock_state = "locked"
                state.needs_ai_input = False
                state.metadata.pop("execute_result", None)
                state.task_state.notes.append("[EXECUTE] PlanLock → locked (AI 确认)")
                logger.info("Plan locked by AI confirmation")
                return self._prepare_full_task(state, contracts[current_idx], current_idx, len(contracts))
            return self._validate_task_result(state, submitted, contracts[current_idx])

        # ── Phase CONFIRM: AI 已确认 Checklist ──
        checklist_confirmed = state.metadata.get("execute_checklist_confirmed")
        if checklist_confirmed:
            # 清除确认标记，进入完整编码阶段
            state.metadata.pop("execute_checklist_confirmed", None)
            return self._prepare_full_task(state, contracts[current_idx], current_idx, len(contracts))

        # ── Phase PREPARE: 先让 AI 确认约束，再给编码指令 ──
        return self._prepare_checklist(state, contracts[current_idx], current_idx, len(contracts))

    # ══════════════════════════════════════════════════════════════
    # PREPARE — Task Start Gate (架构 §8.7.2)
    # ══════════════════════════════════════════════════════════════

    def _prepare_checklist(
        self, state: RunState, contract: dict, idx: int, total: int,
    ) -> RunState:
        """Phase 1: 先让 AI 确认任务约束，防止范围膨胀。AI 必须先回复确认才能编码。

        Args:
            state: 当前运行状态
            contract: Plan 合约字典
            idx: 当前 Task 索引
            total: Task 总数

        Returns:
            RunState: 更新后的运行状态
        """
        task_id = contract.get("task_id", f"T{idx + 1}")
        allowed = contract.get("allowed_files", [])
        forbidden = contract.get("forbidden_files", [])
        budget = contract.get("budget", {})
        task_summary = contract.get("goal", contract.get("title", ""))
        # 构建实现检查清单
        checklist = self._build_checklist(contract)

        # 构建下游影响字符串
        requires = contract.get("requires", [])
        requires_str = ", ".join(requires) if requires else "无"

        # 加载编码前反模式警告
        preflight = self._load_preflight_warnings(state)

        instruction = (
            f"## Task {task_id} ({idx + 1}/{total}): {task_summary}\n\n"
            "**在编码之前，你必须逐项验证以下约束，发现问题必须指出。验证通过方可开始写代码。**\n\n"
            f"### 1. 修改范围 — Plan 声明\n"
            f"- ✅ 允许: {allowed}\n"
            f"- ❌ 禁止: {forbidden}\n"
            f"- 📏 预算: ≤{budget.get('max_files', 3)} files / "
            f"≤{budget.get('max_lines_changed', budget.get('max_lines', 200))} lines\n"
            f"- 🚫 新抽象: {'禁止' if not budget.get('allow_new_abstractions', False) else '允许'}\n"
            f"- 📦 新依赖: {'禁止' if not budget.get('allow_new_dependencies', False) else '允许'}\n"
            f"\n### 2. 逐项验证（你必须对每一项给出确切回答，不能只说'OK'）\n"
            f"- 允许改的文件真的存在吗？需要改吗？\n"
            f"- 禁止区域里有没有本次必须碰的文件？（如果有 → 要求 Plan Change）\n"
            f"- 预算够不够？如果不够 → 说明原因并要求 Plan Change\n"
            f"- 项目中是否已有可复用的实现？（搜索后给出具体函数名/文件名）\n"
            f"- 有没有可能影响被依赖 Task（{requires_str}）的接口？\n"
            f"\n### 3. 回复格式（必须逐项回答）\n"
            f"\"验证 Task {task_id}:\n"
            f" 1. 文件范围: [已验证，只改 {allowed} / 有疑问，xxx需要额外修改]\n"
            f" 2. 禁止区域: [无冲突 / 冲突: xxx文件在禁止列表但必须改，原因: ...]\n"
            f" 3. 预算: [够用，预计 N files ~M lines / 不够，原因: ...]\n"
            f" 4. 复用: [找到可复用: XxxUtil.method() / 搜索后未找到]\n"
            f" 5. 下游影响: [不影响 / 会影响 requires_str 的 xxx 接口]\n"
            f" → 全部验证通过，请求编码\""
        )

        if preflight:
            instruction += "\n\n### ⚠️ 项目记忆警告\n" + "\n".join(f"- {w}" for w in preflight)

        # REVIEW→EXECUTE 反馈闭环: 注入同模块的历史审查发现
        review_findings = state.metadata.get("review_findings_by_module", {})
        module_warnings: list[str] = []
        for f in allowed:
            module = self._infer_module_from_file(f)
            if module and module in review_findings:
                module_warnings.extend(review_findings[module])
        if module_warnings:
            unique = list(dict.fromkeys(module_warnings))[:5]  # 去重 + 限5条
            instruction += (
                "\n\n### 🔁 REVIEW 反馈（同模块历史审查发现，注意不要重犯）\n"
                + "\n".join(f"- {w}" for w in unique)
            )

        state.pending_action = "confirm_checklist"
        state.pending_prompt = {
            "instruction": instruction,
            "submission_format": {"confirmed": True, "notes": ""},
            "checklist_items": checklist,
        }
        state.needs_ai_input = True
        state.task_state.notes.append(
            f"[EXECUTE] CONFIRM: Task {task_id} ({idx + 1}/{total}) — 等待 AI 确认约束"
        )
        logger.info("Checklist confirmation requested for Task %s", task_id)
        return state

    def _prepare_full_task(
        self, state: RunState, contract: dict, idx: int, total: int,
    ) -> RunState:
        """Phase 2: AI 确认通过后，构造完整编码 prompt。

        Args:
            state: 当前运行状态
            contract: Plan 合约字典
            idx: 当前 Task 索引
            total: Task 总数

        Returns:
            RunState: 更新后的运行状态
        """
        task_id = contract.get("task_id", f"T{idx + 1}")

        # 1. Task Start Gate — 边界重新确认
        self._task_start_gate(state, contract, idx, total)

        # 2. Guard 前置检查
        if not self._pre_guard_check(state):
            return state  # Guard blocked

        # 3. ContextRouter 注入 EXECUTE 上下文（仅当前 Task 需要的文件）
        execute_context = self._load_execute_context(state, contract)

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

        # 5. 构造 superpowers 模式 prompt
        preflight = self._load_preflight_warnings(state)
        specification = self._load_specification(state, task_id=task_id)

        # ── 构造执行指令 ──
        plan_ref = specification.get("plan_path", "docs/plan/*.md")
        spec_ref = specification.get("spec_path", "docs/spec/*.md")
        position_info = f"{idx + 1}/{total}"
        depends_str = state.plan_contracts[idx - 1].get("task_id", "") if idx > 0 else "无"
        requires_str = state.plan_contracts[idx + 1].get("task_id", "") if idx + 1 < total else "无"

        task_summary = contract.get("goal", contract.get("title", ""))
        allowed = contract.get("allowed_files", [])
        forbidden = contract.get("forbidden_files", [])
        budget = contract.get("budget", {})

        instruction_parts = [
            f"Task {task_id} ({position_info}): {task_summary}",
            "",
            f"修改文件: {allowed}",
            f"禁止修改: {forbidden}",
            f"上限: {budget.get('max_files', 3)} files / "
            f"{budget.get('max_lines_changed', budget.get('max_lines', 200))} lines",
            f"新抽象: {budget.get('allow_new_abstractions', False)} | 新依赖: {budget.get('allow_new_dependencies', False)}",
            f"依赖: {depends_str} | 被依赖: {requires_str}",
            "",
            f"Plan: {plan_ref} | Spec: {spec_ref}",
            "上下文: 见 `context` 字段 (ContextRouter 已组装)",
            f"记忆: .ai/memory/context/{task_id}-memory.md",
        ]
        if preflight:
            instruction_parts.extend([
                "",
                "⚠ 项目记忆警告:",
                *[f"  - {w}" for w in preflight],
            ])
        instruction_parts.append("")

        state.pending_action = "execute_task"
        state.pending_prompt = {
            "instruction": "\n".join(instruction_parts),
            "specification": specification,
            "context": execute_context,
            "goal_context": {
                "task_goal": task_summary,
                "overall_reason": state.task_intake.reason if state.task_intake else "",
                "position": position_info,
                "depends_on": [state.plan_contracts[idx - 1].get("task_id", "")] if idx > 0 else [],
                "required_by": [state.plan_contracts[idx + 1].get("task_id", "")] if idx + 1 < total else [],
            },
            "preflight_warnings": preflight,
            "task_contract": contract,
            "style_contract": contract.get("style_contract", {}),
            "budget": {
                "max_files": budget.get("max_files", 3),
                "max_lines": budget.get("max_lines_changed", budget.get("max_lines", 200)),
                "allow_new_abstractions": budget.get("allow_new_abstractions", False),
                "allow_new_dependencies": budget.get("allow_new_dependencies", False),
            },
            "submission_format": {
                "changed_files": ["path/to/file"],
                "lines_added": 0,
                "lines_removed": 0,
                "summary": "变更说明",
                "style_contract_followed": True,
                "reuse_check_passed": True,
                "new_abstractions": [],
                "new_dependencies": [],
            },
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

        # 3.6. Python 侧验证 style_contract / reuse_check（P1 fix: 不完全信任 AI 自报）
        style_verified, style_issues = self._verify_style_contract(
            state, contract, changed_files
        )
        reuse_verified, reuse_issues = self._verify_reuse_check(
            state, contract, changed_files
        )

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
                "style_contract_followed": style_verified,
                "style_contract_ai_reported": submitted.get("style_contract_followed", True),
                "style_contract_issues": style_issues,
                "reuse_check_passed": reuse_verified,
                "reuse_check_ai_reported": submitted.get("reuse_check_passed", True),
                "reuse_check_issues": reuse_issues,
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
            # 继续下一个 Task → 先过 Checklist 确认
            next_contract = state.plan_contracts[state.task_state.current_task_index]
            logger.info("Advancing to next task: %s", next_contract.get("task_id", "?"))
            return self._prepare_checklist(
                state, next_contract,
                state.task_state.current_task_index, len(state.plan_contracts),
            )

    # ══════════════════════════════════════════════════════════════
    # Plan Change Request (架构 §8.7.9)
    # ══════════════════════════════════════════════════════════════

    def _handle_plan_change(
        self, state: RunState, plan_change: dict, contract: dict,
    ) -> RunState:
        """处理 Plan Change Request。

        强制执行 MAX_PLAN_CHANGE_REQUESTS 上限（默认 3）。
        """
        task_id = contract.get("task_id", "?")
        risk = state.task_intake.risk_level if state.task_intake else "L2"

        # Plan Change 计数器检查（P1 fix: 强制执行上限）
        plan_change_count = state.metadata.get("plan_change_count", 0) + 1
        state.metadata["plan_change_count"] = plan_change_count
        if plan_change_count > self.MAX_PLAN_CHANGE_REQUESTS:
            state.plan_lock_state = "breached"
            state.task_state.notes.append(
                f"[EXECUTE] Plan Change 次数超限: {plan_change_count} > "
                f"{self.MAX_PLAN_CHANGE_REQUESTS} → PlanLock BREACHED"
            )
            logger.warning("Plan change limit exceeded: %d", plan_change_count)
            return self._stop_failure(
                state,
                f"Plan Change 次数超过上限 ({self.MAX_PLAN_CHANGE_REQUESTS})，需人工介入",
            )

        state.plan_lock_state = "change_requested"
        state.task_state.notes.append(
            f"[EXECUTE] Plan Change Request #{plan_change_count} from Task {task_id}: "
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
    def _infer_module_from_file(file_path: str) -> str:
        parts = file_path.replace("\\", "/").split("/")
        if "src" in parts:
            idx = parts.index("src")
            if idx + 1 < len(parts):
                return parts[idx + 1]
        if len(parts) > 1:
            return parts[0]
        return ""

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

        # Karpathy 行为准则（短标签唤醒，原文在 .claude/rules/karpathy.md）
        checklist.append("极简: 无未要求的抽象/配置/异常处理？")
        checklist.append("纯粹: 每行改动都能追溯到需求？不动相邻代码")
        checklist.append("确定: 不确定的地方是否已标出而非猜测？")

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


    def _pre_guard_check(self, state: RunState) -> bool:
        """审查前置检查 —— 在 AI 编码前运行默认规则集。

        预飞检查不阻断流程，只记录警告。硬阻断规则在 REVIEW 阶段执行。
        """
        try:
            from engines.review import create_review_engine

            review = create_review_engine()
            results = review.run_layer1(state)
            blocked = [r for r in results if r.block]
            if blocked:
                state.task_state.notes.append(
                    f"[EXECUTE] Review 预飞警告: {[r.rule_name for r in blocked]}"
                )
            return True  # 预飞检查不阻断执行
        except Exception as exc:
            logger.warning("Guard check exception (non-blocking): %s", exc)
            return True  # 异常也不阻断，放行编码

    def _load_execute_context(self, state: RunState, contract: dict) -> str:
        """AI 自行使用 Read / CodeGraph MCP 获取上下文，Python 不注入。"""
        return ""

    # ContextRouter 已移除 — AI 自行使用 Read / CodeGraph MCP。

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

    def _verify_style_contract(
        self, state: RunState, contract: dict, changed_files: list[str],
    ) -> tuple[bool, list[str]]:
        """Python 侧验证 Style Contract — 不完全信任 AI 自报。

        检查项:
        - 命名规范一致性（snake_case vs camelCase）
        - 不允许新类/抽象时是否引入了新类定义
        """
        import re
        from pathlib import Path

        issues: list[str] = []
        style = contract.get("style_contract", {})
        if not style or not changed_files:
            return True, []

        project_root = Path(state.project_root) if state.project_root else Path.cwd()

        for fpath in changed_files:
            full_path = project_root / fpath
            if not full_path.exists():
                continue
            try:
                content = full_path.read_text(encoding="utf-8")
            except Exception:
                continue

            # 1. 命名规范检查
            naming = style.get("naming", "")
            if naming and "snake_case" in naming:
                camel_funcs = re.findall(r'^\s*def\s+([a-z]+[A-Z][a-zA-Z]*)', content, re.MULTILINE)
                if camel_funcs:
                    issues.append(
                        f"{fpath}: camelCase 函数定义 {camel_funcs} 违反 snake_case 规范"
                    )

            # 2. 新类/抽象检查
            budget = contract.get("budget", {})
            if not budget.get("allow_new_abstractions", False):
                new_classes = re.findall(r'^\s*class\s+(\w+)', content, re.MULTILINE)
                if new_classes:
                    issues.append(
                        f"{fpath}: 不允许新抽象但检测到新类: {new_classes}"
                    )

            # 3. 错误处理一致性
            error_handling = style.get("error_handling", "")
            if error_handling == "raise" or "raise" in str(error_handling):
                if "except:" in content:
                    issues.append(f"{fpath}: 不允许 bare except (应使用具体异常类型)")

        return len(issues) == 0, issues

    def _verify_reuse_check(
        self, state: RunState, contract: dict, changed_files: list[str],
    ) -> tuple[bool, list[str]]:
        """Python 侧验证 Reuse Check — 检查是否引入了项目已有的依赖之外的导入。

        检查项:
        - 新依赖检测：扫描新增 import，与项目已有依赖对比
        """
        import re
        from pathlib import Path

        issues: list[str] = []
        if not changed_files:
            return True, []

        budget = contract.get("budget", {})
        allow_new_deps = budget.get("allow_new_dependencies", False)
        if allow_new_deps:
            return True, []

        project_root = Path(state.project_root) if state.project_root else Path.cwd()

        # 收集项目中已有的顶层包依赖（仅扫描项目根目录下 py 文件，不做递归）
        existing_deps: set[str] = set()
        try:
            for f in project_root.rglob("*.py"):
                if ".git" in f.parts or "__pycache__" in f.parts:
                    continue
                try:
                    for line in f.read_text(encoding="utf-8").splitlines():
                        m = re.match(r'^(?:from|import)\s+(\w+)', line.strip())
                        if m:
                            existing_deps.add(m.group(1))
                except Exception:
                    pass
        except Exception:
            pass

        # 检查变更文件的新导入
        for fpath in changed_files:
            full_path = project_root / fpath
            if not full_path.exists():
                continue
            try:
                content = full_path.read_text(encoding="utf-8")
            except Exception:
                continue

            new_imports: list[str] = []
            for line in content.splitlines():
                m = re.match(r'^(?:from|import)\s+(\w+)', line.strip())
                if m:
                    dep = m.group(1)
                    if dep not in existing_deps and dep not in ("__future__",):
                        new_imports.append(dep)

            if new_imports:
                issues.append(
                    f"{fpath}: 疑似新依赖 {new_imports} (不在项目已有依赖中)"
                )

        return len(issues) == 0, issues

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

            from engines.validation import QuickCheckRunner

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


def _auto_detect_related_scenarios(state, scenarios_dir) -> set[str]:
    """从 changed_files 推断模块，找到关联的 Scenario ID 集合。

    复用 RepairHandler 的推断逻辑：changed_files → module → 匹配 Scenario id/name/steps。
    返回空集合表示无法推断（应加载全部）。
    """
    try:
        from pathlib import Path

        module = _infer_module_from_state(state)
        if not module:
            return set()

        # 检查是否有同名子目录
        module_dir = scenarios_dir / module
        if module_dir.is_dir() and any(module_dir.rglob("*.yaml")):
            logger.info("Auto-detected module=%s, found matching subdir .ai/scenarios/%s/", module, module)
            return set()  # 不按 id 过滤，后面直接用子目录加载

        # 查找关联 Scenario（复用 RepairHandler 的静态方法）
        related = RepairHandler._find_related_scenarios(state, module)
        logger.info(
            "Auto-detected module=%s → %d related scenarios (by name match)",
            module, len(related),
        )
        return set(related)
    except Exception as exc:
        logger.debug("Auto-detect scenarios skipped: %s", exc)
        return set()


def _infer_module_from_state(state) -> str:
    """从 state.checkpoints 收集 changed_files，推断所属模块名。"""
    changed_files: list[str] = []
    for cp in (state.checkpoints or []):
        changed_files.extend(cp.files_changed)
    changed_files = list(dict.fromkeys(changed_files))  # 去重保序

    if not changed_files:
        return ""

    return RepairHandler._infer_module(changed_files)


def _get_service_base_url(project_root) -> str:
    """从 loop-config.json 读取服务基础地址。

    services[0].health = "http://localhost:8089/actuator/health" → "http://localhost:8089"
    没配就报错，不 fallback。
    """
    import json as _json
    from pathlib import Path
    from urllib.parse import urlparse

    root = Path(project_root)
    config_path = root / ".ai" / "loop-config.json"
    if not config_path.exists():
        raise RuntimeError("未找到 .ai/loop-config.json，请先运行 aicode-init")

    cfg = _json.loads(config_path.read_text(encoding="utf-8"))
    services = cfg.get("services", [])
    if not services or not services[0].get("health"):
        raise RuntimeError("loop-config.json 中未配置 services[0].health，请检查配置")

    parsed = urlparse(services[0]["health"])
    return f"{parsed.scheme}://{parsed.netloc}"


def _find_mcp_json(project_root) -> Path | None:
    """自动探测当前项目的 mcp.json 路径。

    搜索顺序:
      1. .ai/loop-config.json 的 target_tool → 项目级 mcp.json
      2. 项目根目录 .claude/.codex/.cursor/mcp.json
      3. 全局 ~/.claude/mcp.json (Claude Code 全局配置)
    """
    from pathlib import Path
    import json as _json

    root = Path(project_root)

    # 1. loop-config.json 指定的工具 → 项目级 mcp.json
    loop_config = root / ".ai" / "loop-config.json"
    if loop_config.exists():
        try:
            cfg = _json.loads(loop_config.read_text(encoding="utf-8"))
            target = cfg.get("target_tool", "")
            path_map = {
                "claude_code": ".claude/mcp.json",
                "codex": ".codex/mcp.json",
                "cursor": ".cursor/mcp.json",
            }
            if target in path_map:
                mcp_path = root / path_map[target]
                if mcp_path.exists():
                    return mcp_path
        except Exception:
            pass

    # 2. 按目录探测项目级 mcp.json
    for dir_name in (".claude", ".codex", ".cursor"):
        mcp_path = root / dir_name / "mcp.json"
        if mcp_path.exists():
            return mcp_path

    # 3. 全局 ~/.claude/mcp.json (Claude Code 全局 MCP 配置)
    home = Path.home()
    for global_path in (
        home / ".claude" / "mcp.json",
        home / ".codex" / "mcp.json",
        home / ".cursor" / "mcp.json",
    ):
        if global_path.exists():
            return global_path

    return None


class VerifyHandler(StageHandler):
    """验证处理器 —— 完整自动化验证流水线。

    流程: skip_verify 检查 → ServiceManager 启停 → SanityChecker →
          AuthProvider → ScenarioRunner(HTTP/DB/Playwright) →
          FailureClassifier → ReportGenerator

    Python 全自动（0 token），AI 仅在 REAL_BUG 失败时介入 REPAIR。
    """

    stage = StageType.VERIFY

    def handle(self, state: RunState) -> RunState:
        """处理 VERIFY 阶段：执行完整自动化验证流水线。

        Args:
            state: 当前运行状态

        Returns:
            RunState: 更新后的运行状态
        """
        logger.info("Verify — full automated verification pipeline")

        state.task_state.status = state.task_state.status.__class__.VERIFYING
        state.task_state.stage = StageType.VERIFY

        # 0. skip_verify 检查（纯 docs/config 变更）
        if state.metadata.get("skip_verify"):
            state.task_state.notes.append("[VERIFY] skip_verify=True，跳过验证 → MEMORY")
            state.verification.status = VerificationStatus.SKIPPED
            state.verification.summary = "纯文档/配置变更，已跳过"
            return self._complete(state, "skip_verify: 跳过验证")

        # 0.5. ServiceManager — 启动测试服务
        service_manager = None
        try:
            from engines.scenario.service_manager import ServiceManager

            sm = ServiceManager(state.project_root)
            if sm.load_config():
                ok, svc_errors = sm.start_all()
                if not ok:
                    state.task_state.notes.append(
                        f"[VERIFY] 服务启动失败: {'; '.join(svc_errors)}"
                    )
                    state.verification.status = VerificationStatus.FAILED
                    state.verification.summary = "服务启动失败"
                    return self._stop_failure(state, f"服务启动失败: {'; '.join(svc_errors)}")
                service_manager = sm
                state.task_state.notes.append(
                    f"[VERIFY] 已启动 {len(sm._configs)} 个服务"
                )
        except Exception as exc:
            logger.debug("ServiceManager skipped: %s", exc)

        # 1. Sanity Check — 环境健康检查
        sanity_failures: list[str] = []
        try:
            from engines.scenario.sanity import SanityChecker
            from engines.scenario.resources import default_adapters

            adapters = default_adapters()
            checker = SanityChecker(adapters=adapters)

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
        except Exception as exc:
            logger.warning("Sanity check failed: %s", exc)
            state.task_state.notes.append(f"[VERIFY] Sanity checker error: {exc}")

        # 1.5. AuthProvider — 读取用户配置的 token
        try:
            from engines.scenario.auth_provider import AuthProvider

            auth = AuthProvider(state.project_root)
            if auth.load_config() and auth.token:
                state.metadata["auth_token"] = auth.token
                state.task_state.notes.append("[VERIFY] Auth token 已加载")
            else:
                state.task_state.notes.append("[VERIFY] 未配置 token，请求不带鉴权")
        except Exception as exc:
            logger.debug("AuthProvider skipped: %s", exc)

        # 2. ScenarioRunner — 执行场景
        scenario_results: list = []
        try:
            from engines.scenario.runner import ScenarioRunner
            from engines.scenario.models import Scenario

            # 从 loop-config.json 读取服务地址
            base_url = _get_service_base_url(state.project_root)
            from engines.scenario.resources import HttpAdapter
            custom_adapters = {"http": HttpAdapter(base_url=base_url)}

            # 加载 DataSourceRegistry（DB/Redis/MQ 适配器）
            from engines.scenario.adapters import DataSourceRegistry
            ds_registry = DataSourceRegistry.load(state.project_root)
            if ds_registry._adapters:
                if not ds_registry.health_check_all():
                    state.task_state.notes.append(
                        "[VERIFY] ⚠️ 部分数据源健康检查失败，相关断言将报错"
                    )

            # 合并 DataSourceRegistry 适配器(含 mysql/redis)到 adapters，
            # 使 fixture/teardown 能通过 fixture.type 找到对应适配器
            adapters = ds_registry.to_adapter_dict()
            adapters["http"] = custom_adapters["http"]  # 保留带 base_url 的 http
            runner = ScenarioRunner(adapters=adapters, registry=ds_registry)
            # 注入 auth token 到 runner
            auth_token = state.metadata.get("auth_token")
            if auth_token:
                http_adapter = adapters.get("http")
                if http_adapter:
                    http_adapter._auth_token = auth_token

            scenarios = self._load_scenarios(state)

            # REPAIR 回归检查：优先跑关联 Scenario，验证修复是否引入新问题
            related_ids = state.metadata.get("repair_related_scenarios", [])
            if related_ids and scenarios:
                # 关联场景排前面
                ordered = sorted(
                    scenarios,
                    key=lambda s: 0 if (s.id in related_ids or s.name in related_ids) else 1,
                )
                related_count = len([s for s in ordered
                                     if s.id in related_ids or s.name in related_ids])
                state.task_state.notes.append(
                    f"[VERIFY] 回归检查: 优先执行 {related_count} 个关联 Scenario"
                )
                scenarios = ordered

            if scenarios:
                report = runner.run_all(scenarios)
                scenario_results = report.results
                state.task_state.notes.append(
                    f"[VERIFY] {report.summary()}"
                )
        except Exception as exc:
            logger.warning("ScenarioRunner failed: %s", exc)
            state.task_state.notes.append(f"[VERIFY] ScenarioRunner error: {exc}")

        # 3. 分析验证结果 + 失败分类
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
                "[VERIFY] 环境故障 — 不可自动修复"
            )
            self._cleanup(state, service_manager)
            return self._stop_failure(state, "环境故障: " + state.verification.summary)

        # 写入 state.scenario_results
        state.scenario_results = [
            r.to_state_model() if hasattr(r, 'to_state_model') else r
            for r in scenario_results
        ]

        # 失败分类 + 处理
        if scenario_results:
            failed = [r for r in scenario_results if not getattr(r, 'passed', True)]

            if failed:
                from engines.state.enums import FailureCategory
                from engines.state.models import FailureRecord

                env_failures = 0
                code_failures = 0
                repair_contexts: list[dict] = []

                for fr in failed:
                    # 使用 runner 已计算好的 failure_category（不丢弃重算）
                    fc_raw = getattr(fr, 'failure_category', None)
                    if fc_raw == "ENVIRONMENT":
                        fc = FailureCategory.ENVIRONMENT
                        env_failures += 1
                    elif fc_raw in ("TIMING", "ASSERTION"):
                        fc = FailureCategory.TEST_DATA
                    else:
                        fc = FailureCategory.CODE_LOGIC
                        code_failures += 1

                    # 调用 repair_context() 获取结构化修复上下文
                    rc_method = getattr(fr, 'repair_context', None)
                    if callable(rc_method):
                        try:
                            repair_contexts.append(rc_method())
                        except Exception:
                            pass

                    errors = getattr(fr, 'errors', [])
                    state.failures.append(FailureRecord(
                        category=fc,
                        message=str(errors) if errors else str(fr),
                        stage=StageType.VERIFY,
                        attempt_count=state.task_state.retry_count + 1,
                    ))

                # 捕获服务日志片段（失败时供 AI 分析）
                if service_manager:
                    log_snippet = service_manager.get_log_snippet(
                        service_manager._configs[0].name if service_manager._configs else "",
                        max_chars=3000,
                        errors_only=True,
                    )
                    if log_snippet:
                        state.metadata["service_log_snippet"] = log_snippet
                        state.task_state.notes.append(
                            f"[VERIFY] 服务日志已捕获 ({len(log_snippet.splitlines())} 行错误)"
                        )

                # 存储结构化修复上下文
                if repair_contexts:
                    state.metadata["repair_contexts"] = repair_contexts

                state.verification.status = VerificationStatus.FAILED
                state.verification.summary = (
                    f"{len(failed)}/{len(scenario_results)} scenarios failed "
                    f"(env={env_failures}, code={code_failures})"
                )
                state.task_state.notes.append(
                    f"[VERIFY] {len(failed)} scenarios failed — "
                    f"ENVIRONMENT={env_failures}, CODE={code_failures}"
                )

                self._evaluate_memory_effectiveness(state, success=False)

                # 失败时也要生成报告，让用户看到哪些场景挂了
                self._generate_report(state, report=None, scenario_results=scenario_results)

                self._cleanup(state, service_manager)
                logger.info("Verification failed, entering REPAIR")
                # 仅代码逻辑错误进 REPAIR
                if code_failures > 0:
                    return self._advance_to(state, StageType.REPAIR,
                                            f"验证失败 ({code_failures} code failures), 进入修复")
                else:
                    return self._stop_failure(state,
                                              f"环境/时序/断言问题 ({env_failures}), 非代码错误不修复")

        # 无场景文件
        if not scenario_results:
            self._cleanup(state, service_manager)
            if state.metadata.get("td_gate_passed"):
                # TEST_DESIGN gate 通过了但场景不见了 → 异常
                msg = "TEST_DESIGN 通过了 Gate 但 VERIFY 找不到任何场景文件，可能被误删"
                state.verification.status = VerificationStatus.FAILED
                state.verification.summary = msg
                state.task_state.notes.append(f"[VERIFY] ❌ {msg}")
                return self._stop_failure(state, msg)
            # 正常情况：项目还没有场景
            state.verification.status = VerificationStatus.SKIPPED
            state.verification.summary = "无场景文件 (.ai/scenarios/**/*.yaml)，验证跳过"
            state.task_state.notes.append("[VERIFY] 无场景文件 — 建议添加场景")
            return self._complete(state, "验证跳过: 无场景文件")

        # 全部通过
        state.verification.status = VerificationStatus.PASSED
        state.verification.summary = f"All {len(scenario_results)} scenarios passed"
        state.verification.total_assertions = sum(
            getattr(r, 'assertions_total', 0) for r in scenario_results
        )
        state.verification.passed_assertions = state.verification.total_assertions
        state.task_state.notes.append("[VERIFY] 全部验证通过")

        self._evaluate_memory_effectiveness(state, success=True)

        # 3.5. 覆盖率门禁 — 场景全过但代码覆盖率够吗？
        self._check_coverage(state)

        # 4. ReportGenerator — 生成测试报告
        self._generate_report(state, report=None, scenario_results=scenario_results)

        self._cleanup(state, service_manager)

        logger.info("Verification passed: %d scenarios", len(scenario_results))
        return self._complete(state, f"验证通过: {state.verification.summary}")

    # ── Cleanup ──

    def _cleanup(self, state: RunState, service_manager=None) -> None:
        """停止服务 + 生成报告。"""
        if service_manager:
            try:
                service_manager.stop_all()
                state.task_state.notes.append("[VERIFY] 服务已停止")
            except Exception as exc:
                logger.warning("Service stop failed: %s", exc)

    # ── Report ──

    def _generate_report(
        self, state: RunState, report, scenario_results: list,
    ) -> None:
        """生成 HTML/JSON/MD 测试报告。"""
        try:
            from pathlib import Path
            from engines.scenario.report_generator import ReportGenerator
            from engines.scenario.runner import ScenarioReport

            # 构造 ScenarioReport
            if report is None:
                sr = ScenarioReport()
                for r in scenario_results:
                    sr.add(r)
                report = sr

            gen = ReportGenerator(
                Path(state.project_root) / ".ai" / "reports"
            )
            paths = gen.generate(
                report,
                failures=[
                    {"category": f.category.value, "message": f.message}
                    for f in state.failures[-10:]
                ],
            )
            state.metadata["test_report_paths"] = paths
            state.task_state.notes.append(
                f"[VERIFY] 测试报告: {paths.get('html', '')}"
            )
        except Exception as exc:
            logger.warning("Report generation failed: %s", exc)

    def _check_coverage(self, state: RunState) -> None:
        """场景全过后，检查变更文件的代码覆盖率。低于阈值 → 标记为建议补充测试。"""
        try:
            import re
            import subprocess
            from pathlib import Path

            project_root = Path(state.project_root) if state.project_root else Path.cwd()
            changed_files = []
            for log in state.task_state.task_logs:
                changed_files.extend(log.changed_files)

            if not changed_files:
                return

            # 按语言检测覆盖率工具
            cov_threshold = 0.70

            # Python: pytest-cov
            py_files = [f for f in changed_files if f.endswith(".py")]
            if py_files:
                result = subprocess.run(
                    ["python", "-m", "pytest", "--cov", "--cov-report=term-missing"]
                    + [str(project_root / f) for f in py_files[:10]],
                    capture_output=True, text=True, cwd=str(project_root),
                    timeout=60,
                )
                # 解析 TOTAL 行: "TOTAL    45    10    78%"
                match = re.search(r"TOTAL\s+\d+\s+\d+\s+(\d+)%", result.stdout)
                if match:
                    pct = int(match.group(1)) / 100.0
                    if pct < cov_threshold:
                        state.metadata["coverage_warning"] = f"Python 覆盖率 {pct:.0%} < {cov_threshold:.0%}，建议补充测试"
                        state.task_state.notes.append(f"[VERIFY] ⚠️ {state.metadata['coverage_warning']}")
                    else:
                        state.task_state.notes.append(f"[VERIFY] 覆盖率 {pct:.0%} ✅")

            # JavaScript/TypeScript: jest --coverage
            js_files = [f for f in changed_files if f.endswith((".js", ".ts", ".tsx"))]
            if js_files:
                # 只检查 jest config 是否存在
                if (project_root / "jest.config.js").exists() or (project_root / "jest.config.ts").exists():
                    result = subprocess.run(
                        ["npx", "jest", "--coverage", "--collectCoverageFrom", " ".join(js_files[:10])],
                        capture_output=True, text=True, cwd=str(project_root), timeout=60,
                    )
                    match = re.search(r"All files\s+\|\s+([\d.]+)\s+\|\s+([\d.]+)\s+\|\s+([\d.]+)", result.stdout)
                    if match:
                        pct = float(match.group(3)) / 100.0
                        if pct < cov_threshold:
                            state.metadata["coverage_warning"] = f"JS 覆盖率 {pct:.0%} < {cov_threshold:.0%}，建议补充测试"
                            state.task_state.notes.append(f"[VERIFY] ⚠️ {state.metadata['coverage_warning']}")
                        else:
                            state.task_state.notes.append(f"[VERIFY] 覆盖率 {pct:.0%} ✅")

        except FileNotFoundError:
            logger.debug("Coverage tool not available")
        except Exception as exc:
            logger.debug("Coverage check skipped: %s", exc)

    def _evaluate_memory_effectiveness(self, state: RunState, success: bool) -> None:
        """效果追踪已移除。记忆效果通过 git diff 人工审核判断。"""
        pass

    @staticmethod
    def _load_sanity_check_items(state: RunState) -> list:
        """从 loop-config.json data_sources + MCP 配置生成中间件端口检查项。

        HTTP 服务由 ServiceManager 负责启停和健康检查，不在这里重复。
        这里只检查外部中间件（MySQL/Redis/...）的端口可达性。
        """
        import json
        from pathlib import Path
        from engines.scenario.models import SanityCheckItem

        project_root = Path(state.project_root) if state.project_root else Path.cwd()
        items: list = []

        # ── 用户显式配置的 sanity_checks（最高优先级）──
        loop_config_path = project_root / ".ai" / "loop-config.json"
        loop_cfg: dict = {}
        if loop_config_path.exists():
            try:
                loop_cfg = json.loads(loop_config_path.read_text(encoding="utf-8"))
                user_checks = loop_cfg.get("sanity_checks", [])
                if user_checks:
                    return [SanityCheckItem(**item) for item in user_checks]
            except Exception:
                pass

        # ── data_sources 中间件检查 — 从 loop-config.json data_sources 获取 host:port ──
        data_sources = loop_cfg.get("data_sources", {})
        # 从 Adapter 类动态获取默认端口（内置 + 项目级扩展）
        type_default_ports = _build_adapter_port_map(project_root)
        for ds_name, ds_cfg in data_sources.items():
            if not isinstance(ds_cfg, dict):
                continue
            host = ds_cfg.get("host")
            if not host:
                continue
            ds_type = ds_cfg.get("type", "")
            port = ds_cfg.get("port", type_default_ports.get(ds_type, 0))
            items.append(SanityCheckItem(
                name=f"ds-{ds_name}",
                resource="port",
                target=f"{host}:{port}",
                required=True,
            ))

        # ── MCP 中间件检查（fallback）— 从 mcp.json env 拿 host:port ──
        mcp_path = _find_mcp_json(project_root)
        if mcp_path:
            try:
                mcp_cfg = json.loads(mcp_path.read_text(encoding="utf-8"))
                servers = mcp_cfg.get("mcpServers", {})
            except Exception:
                servers = {}

            known = {
                "MYSQL_HOST":      ("MYSQL_PORT", 3306),
                "PG_HOST":         ("PG_PORT", 5432),
                "REDIS_HOST":      ("REDIS_PORT", 6379),
                "MONGO_HOST":      ("MONGO_PORT", 27017),
                "ES_HOST":         ("ES_PORT", 9200),
                "RABBITMQ_HOST":   ("RABBITMQ_PORT", 5672),
            }
            for server_name, cfg in servers.items():
                if not isinstance(cfg, dict) or cfg.get("disabled"):
                    continue
                env_vars = cfg.get("env", {})
                for host_key, (port_key, default_port) in known.items():
                    host = env_vars.get(host_key)
                    if host:
                        port = env_vars.get(port_key, str(default_port))
                        items.append(SanityCheckItem(
                            name=f"mcp-{server_name}",
                            resource="port",
                            target=f"{host}:{port}",
                            required=True,
                        ))
                        break  # 一个 server 只加一条

        return items

    @staticmethod
    def _load_scenarios(state) -> list:
        """Load Scenario objects from .ai/scenarios/**/*.yaml files.

        子目录解析优先级（由高到低）:
        1. state.metadata["scenario_dir"] — 手动 --scenario-dir 或 TEST_DESIGN 自动记录
        2. state.metadata["scenario_dirs"] — 多个子目录时，从 changed_files 推断模块匹配
        3. changed_files → 推断模块 → 检查同名子目录是否存在
        4. changed_files → 推断模块 → 按场景 id/name 模糊匹配
        5. 以上全无 → 加载全部（等同 --all）
        6. 推断结果为空 → fallback 加载全部
        """
        import json
        from pathlib import Path

        project_root = state.project_root if hasattr(state, 'project_root') else state
        if isinstance(project_root, str):
            project_root = Path(project_root)

        base_dir = Path(project_root) / ".ai" / "scenarios"
        if not base_dir.is_dir():
            return []

        meta = state.metadata if hasattr(state, 'metadata') else {}
        meta = meta or {}

        # ── 解析目标子目录 ──
        target_dir = base_dir  # 默认扫描根目录
        subdir = ""

        # 1. 单子目录（手动 --scenario-dir 或 TEST_DESIGN 自动记录）
        explicit = meta.get("scenario_dir", "")
        if explicit:
            candidate = base_dir / explicit
            if candidate.is_dir():
                target_dir = candidate
                subdir = explicit
            else:
                logger.warning("Scenario dir not found: %s, fallback to all", candidate)

        # 2. 多子目录 → 从 changed_files 推断匹配
        if not subdir:
            scenario_dirs = meta.get("scenario_dirs", [])
            if scenario_dirs:
                module = _infer_module_from_state(state)
                if module:
                    matched = [d for d in scenario_dirs if d == module]
                    if not matched:
                        matched = [d for d in scenario_dirs if module in d or d in module]
                    if len(matched) == 1:
                        target_dir = base_dir / matched[0]
                        subdir = matched[0]
                        logger.info("Matched scenario dir: %s", subdir)

        # 3. 从 changed_files 推断模块，检查同名子目录
        if not subdir:
            module = _infer_module_from_state(state)
            if module:
                module_dir = base_dir / module
                if module_dir.is_dir() and any(module_dir.rglob("*.yaml")):
                    target_dir = module_dir
                    subdir = module
                    logger.info("Auto-detected subdir: .ai/scenarios/%s/", module)

        # ── 加载场景 ──
        # 4. 无子目录匹配 → 按场景 id/name 模糊匹配
        related_ids: set[str] = set()
        if not subdir:
            module = _infer_module_from_state(state)  # 可能已有，但轻量
            if module:
                related_ids = set(
                    RepairHandler._find_related_scenarios(state, module)
                )

        loaded = []
        for yaml_file in sorted(target_dir.rglob("*.yaml")):
            try:
                import yaml
                with open(yaml_file, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
            except ImportError:
                try:
                    with open(yaml_file, encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    logger.debug("Cannot parse %s (no yaml/json parser)", yaml_file.name)
                    continue
            except Exception as exc:
                logger.warning("Failed to load scenario %s: %s", yaml_file.name, exc)
                continue

            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                try:
                    from engines.scenario.models import Scenario
                    scenario = Scenario(**item)
                    # 名称过滤：仅在没有子目录匹配时才生效
                    if related_ids and scenario.id not in related_ids and scenario.name not in related_ids:
                        continue
                    loaded.append(scenario)
                except Exception as exc:
                    logger.warning("Invalid scenario in %s: %s", yaml_file.name, exc)

        # fallback: 推断过滤结果为空 → 加载全部
        if (related_ids or subdir) and not loaded:
            logger.info("Filtered scenarios returned empty, loading all")
            return VerifyHandler._load_scenarios_raw(project_root)

        return loaded

    @staticmethod
    def _load_scenarios_raw(project_root) -> list:
        """加载全部 Scenario（无过滤），供 fallback 使用。"""
        import json
        from pathlib import Path

        scenarios_dir = Path(project_root) / ".ai" / "scenarios"
        if not scenarios_dir.is_dir():
            return []

        loaded = []
        for yaml_file in sorted(scenarios_dir.rglob("*.yaml")):
            try:
                import yaml
                with open(yaml_file, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
            except ImportError:
                try:
                    with open(yaml_file, encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    continue
            except Exception:
                continue

            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                try:
                    from engines.scenario.models import Scenario
                    loaded.append(Scenario(**item))
                except Exception:
                    pass

        return loaded


class RepairHandler(StageHandler):
    """修复处理器 —— 两阶段协议: PREPARE (构造修复 prompt) → VALIDATE (AI 提交修复)。

    Python 职责:
      1. Gate 检查: 重试次数、环境故障
      2. ContextRouter 注入失败上下文
      3. 构造 pending_prompt 给 AI 修复
      4. 校验 AI 修复结果（至少验证不再触发同一 failure）

    AI 职责:
      1. 分析根因
      2. 最小修复（不删断言、不改 scenario）
      3. 提交 changed_files + summary
    """

    stage = StageType.REPAIR
    _DEFAULT_MAX_RETRIES = 3

    # ── 反篡改计数器 ──
    # retry_count 存在 run.json 里，AI 删文件就能重置。
    # 这里额外维护 .ai/.retry_state，独立于 run.json，删不掉。
    _RETRY_STATE_DIR = ".ai"
    _RETRY_STATE_FILE = ".retry_state"

    @classmethod
    def _get_max_retries(cls, state: RunState) -> int:
        """从 loop-config.json 读取 max_repair_retries，默认 3。"""
        import json
        from pathlib import Path
        root = state.project_root or "."
        config_path = Path(root) / ".ai" / "loop-config.json"
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            return int(config.get("max_repair_retries", cls._DEFAULT_MAX_RETRIES))
        except Exception:
            return cls._DEFAULT_MAX_RETRIES

    @classmethod
    def _read_retry_count(cls, state: RunState) -> int:
        """读取反篡改计数器（独立于 run.json，按 task_id 隔离）。"""
        import json
        from pathlib import Path
        root = Path(state.project_root or ".")
        counter_file = root / cls._RETRY_STATE_DIR / cls._RETRY_STATE_FILE
        try:
            data = json.loads(counter_file.read_text(encoding="utf-8"))
            # 不同任务 → 重置计数
            if data.get("task_id") != state.task_id:
                return 0
            return int(data.get("retry_count", 0))
        except Exception:
            return 0

    @classmethod
    def _write_retry_count(cls, state: RunState, count: int) -> None:
        """写入反篡改计数器。"""
        import json
        from pathlib import Path
        root = Path(state.project_root or ".")
        counter_file = root / cls._RETRY_STATE_DIR / cls._RETRY_STATE_FILE
        counter_file.parent.mkdir(parents=True, exist_ok=True)
        counter_file.write_text(
            json.dumps({"retry_count": count, "task_id": state.task_id}, indent=2),
            encoding="utf-8",
        )

    def handle(self, state: RunState) -> RunState:
        """处理 REPAIR 阶段：分析失败，构造修复 prompt 或校验修复结果。

        Args:
            state: 当前运行状态

        Returns:
            RunState: 更新后的运行状态
        """
        logger.info("Repair — analyzing failures and loading context")

        state.task_state.status = state.task_state.status.__class__.REPAIRING
        state.task_state.stage = StageType.REPAIR

        max_retries = self._get_max_retries(state)
        state.metadata["repair_max_retries"] = max_retries

        # 2. 分析最近的 FailureRecord
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
        else:
            state.task_state.notes.append(
                f"[REPAIR] attempt={state.task_state.retry_count}/{max_retries}, 无 failure 记录"
            )

        # ── Phase VALIDATE: AI 已提交修复结果 ──
        submitted = state.metadata.get("repair_result")
        if submitted and isinstance(submitted, dict):
            return self._validate_repair_result(state, submitted)

        # ── Phase PREPARE: 检查重试次数 + 构造修复 prompt ──
        max_retries = state.metadata.get("repair_max_retries", 3)
        persistent_count = self._read_retry_count(state)
        effective_count = max(state.task_state.retry_count, persistent_count)

        if effective_count >= max_retries:
            logger.error("Repair retry limit (%d) exceeded (effective=%d)", max_retries, effective_count)
            state.task_state.notes.append(
                f"[REPAIR] 超过最大重试次数 {max_retries}, 升级给用户"
            )
            return self._stop_failure(state, f"修复失败: 超过 {max_retries} 次重试")

        effective_count += 1
        state.task_state.retry_count = effective_count
        self._write_retry_count(state, effective_count)
        state.metadata["repair_effective_count"] = effective_count

        return self._prepare_repair(state)

    def _prepare_repair(self, state: RunState) -> RunState:
        """构造修复 prompt，注入失败上下文 + 服务日志路径 + preflight warnings。"""
        # AI 自行使用 Read / CodeGraph MCP 获取上下文
        repair_context = ""

        # 1. 构建失败摘要（含结构化修复上下文）
        failure_text = "**Recent Failures:**\n"
        repair_contexts = state.metadata.get("repair_contexts", [])
        if repair_contexts:
            for rc in repair_contexts:
                failure_text += f"\n### Scenario: {rc.get('scenario_id', '?')} ({rc.get('failure_category', '?')})\n"
                failure_text += f"Summary: {rc.get('summary', '')}\n"
                for hint in rc.get("repair_hints", [])[:5]:
                    failure_text += (
                        f"- [{hint.get('type', '?')}] {hint.get('hint', '')}\n"
                        f"  expected={hint.get('expected')}, actual={hint.get('actual')}\n"
                    )
        elif state.failures:
            for f in state.failures[-3:]:
                failure_text += f"- [{f.category.value}] {f.message[:200]}\n"
        else:
            failure_text += "(无详细 failure 记录)\n"

        # 1.5. 服务日志引用（已过滤 + 截断，≤3000 字符）
        service_log_info = ""
        log_snippet = state.metadata.get("service_log_snippet", "")
        if log_snippet:
            service_log_info = (
                f"\n**服务错误日志 (已过滤关键行):**\n```\n{log_snippet}\n```\n"
                f"完整日志: Read .ai/logs/*.log\n"
            )

        # 3. Preflight warnings
        preflight = self._load_preflight_warnings(state)

        # 4. 变更文件列表
        changed_files: list[str] = []
        for cp in state.checkpoints:
            changed_files.extend(cp.files_changed)
        changed_files = list(dict.fromkeys(changed_files))

        effective_count = state.metadata.get("repair_effective_count", 1)
        max_retries = state.metadata.get("repair_max_retries", 3)

        instruction_parts = [
            f"修复尝试 {effective_count}/{max_retries} (达上限后停止，不可重置)",
            "",
            failure_text,
        ]
        # 2. 数据源信息（AI 可查询验证数据是否存在）
        ds_info = self._build_data_source_info(state)
        if ds_info:
            instruction_parts.append(ds_info)

        if service_log_info:
            instruction_parts.append(service_log_info)

        if changed_files:
            instruction_parts.append(f"**变更过的文件:** {changed_files}")
        if preflight:
            instruction_parts.extend(["", "## 历史教训 (避免重犯)", *preflight])
        instruction_parts.extend([
            "",
            "## 步骤（按顺序）",
            "1. 先查表结构: data query --source <name> --target \"SHOW COLUMNS FROM table\"",
            "2. 再查数据:   data query --source <name> --target \"SELECT * FROM table LIMIT 5\"",
            "3. 确认数据缺失后用 data execute 补齐",
            "4. 如数据存在但接口报错 → 读 .ai/logs/*.log 定位异常堆栈，修复代码",
            "5. 提交前运行对应测试确认通过",
            "",
            "## 约束",
            "- 禁止猜列名/表名，必须先 SHOW COLUMNS / SELECT * LIMIT 1 确认结构",
            "- 不要从日志 SQL 输出推断数据存在性，必须实际查询数据库",
            "- 最小修复（≤ 50 行变更），不修改 scenario 定义文件",
            "- 提交格式: {\"changed_files\": [...], \"summary\": \"...\", \"root_cause\": \"...\"}",
        ])

        state.pending_action = "repair"
        state.pending_prompt = {
            "instruction": "\n".join(instruction_parts),
            "context": repair_context,
            "preflight_warnings": preflight,
            "failures": [
                {"category": f.category.value, "message": f.message, "stage": f.stage.value}
                for f in (state.failures or [])[-5:]
            ],
            "changed_files": changed_files,
            "repair_contexts": repair_contexts[-3:] if repair_contexts else [],
            "service_log_tail_lines": 20,
            "service_log_hint": "完整日志在 .ai/logs/*.log，用 Read 工具查看",
            "repair_constraints": {
                "max_files": 3,
                "max_lines": 50,
                "no_scenario_modification": True,
                "no_assertion_deletion": True,
            },
        }
        state.needs_ai_input = True
        state.task_state.notes.append(
            f"[REPAIR] PREPARE: attempt={state.task_state.retry_count}/{self._get_max_retries(state)}"
        )
        logger.info("Repair prompt ready, waiting for AI fix")
        return state

    @staticmethod
    @staticmethod
    def _build_data_source_info(state: RunState) -> str:
        """读取数据源配置，生成查询提示，供 AI 验证数据是否存在。"""
        import json
        from pathlib import Path

        root = state.project_root or "."
        config_path = Path(root) / ".ai" / "loop-config.json"
        if not config_path.exists():
            return ""

        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            return ""

        data_sources = config.get("data_sources", {})
        if not data_sources:
            return ""

        lines = [
            "",
            "## 数据源操作",
            "查询: engines/run.sh data query  --source <name> --target \"<SQL/key>\"",
            "写入: engines/run.sh data execute --source <name> --target \"<SQL/key>\" --value \"<value>\"",
            "",
            "已配置的数据源:",
        ]
        for name, ds in data_sources.items():
            ds_type = ds.get("type", "")
            host = ds.get("host", "")
            port = ds.get("port", "")
            database = ds.get("database", "")
            label = f"{ds_type}://{host}:{port}"
            if database:
                label += f"/{database}"
            examples: dict[str, str] = {
                "mysql":    f'--target "SELECT * FROM table"',
                "redis":    f'--target "key" 或 --target "key:*" 查所有匹配',
                "mongodb":  f'--target \'{{"find": "coll", "filter": {{}}}}\'',
                "rabbitmq": f'--target "queue_name"',
            }
            hint = examples.get(ds_type, f'--target "..."')
            lines.append(f"  {name} ({label})  例: {hint}")

        return "\n".join(lines)

    def _validate_repair_result(
        self, state: RunState, submitted: dict,
    ) -> RunState:
        """校验 AI 修复结果 + 回归影响分析（Test-Fixing Skill 思路）。"""
        changed_files = submitted.get("changed_files", [])
        summary = submitted.get("summary", "")
        root_cause = submitted.get("root_cause", "")

        # 1. 文件数检查
        if len(changed_files) > 5:
            state.task_state.notes.append(
                f"[REPAIR] 修复涉及 {len(changed_files)} 个文件, 可能是过度修复"
            )

        # 2. 检查是否改了 scenario 文件
        scenario_files = [f for f in changed_files if "scenario" in f or ".ai/" in f]
        if scenario_files:
            state.task_state.notes.append(
                f"[REPAIR] 警告: 修复修改了 scenario 相关文件: {scenario_files}"
            )

        # 3. 记录修复日志
        state.task_state.notes.append(
            f"[REPAIR] 修复完成: files={changed_files}, "
            f"root_cause={root_cause[:100]}, summary={summary[:100]}"
        )

        # 4. 交叉影响分析（Test-Fixing Skill 思路）
        # 修复后需要复测的不只是报错的那个 Scenario，而是所有相关模块的 Scenario
        module = self._infer_module(changed_files)
        if module:
            related = self._find_related_scenarios(state, module)
            state.metadata["repair_related_scenarios"] = related
            state.task_state.notes.append(
                f"[REPAIR] 交叉影响分析: 模块 '{module}' 关联 {len(related)} 个 Scenario, "
                f"复测时将全量验证以防止回归"
            )
        else:
            state.metadata["repair_related_scenarios"] = []

        # 5. 清理并进入 VERIFY
        state.needs_ai_input = False
        state.pending_action = ""
        state.metadata.pop("repair_result", None)

        logger.info("Repair validated, re-entering VERIFY")
        return self._advance_to(
            state, StageType.VERIFY,
            f"修复 applied (attempt {state.task_state.retry_count}), 重新验证",
        )

    @staticmethod
    def _infer_module(changed_files: list[str]) -> str:
        """从变更文件路径推断所属模块。"""
        for f in changed_files:
            parts = f.replace("\\", "/").split("/")
            # 找 src/ 后的第一级目录作为模块名
            if "src" in parts:
                idx = parts.index("src")
                if idx + 1 < len(parts):
                    return parts[idx + 1]
            # 或直接用第一级目录
            if len(parts) > 1:
                return parts[0]
        return ""

    @staticmethod
    def _find_related_scenarios(state: RunState, module: str) -> list[str]:
        """找到与修改模块相关的所有 Scenario。"""
        try:
            import json
            from pathlib import Path

            project_root = Path(state.project_root) if state.project_root else Path.cwd()
            scenarios_dir = project_root / ".ai" / "scenarios"
            if not scenarios_dir.is_dir():
                return []

            related: list[str] = []
            for yaml_file in sorted(scenarios_dir.rglob("*.yaml")):
                try:
                    import yaml as _yaml
                    data = _yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
                except Exception:
                    continue

                if not isinstance(data, dict):
                    continue

                # 检查 scenario 的 id/name/steps 是否含相关模块关键词
                scenario_id = str(data.get("id", ""))
                name = str(data.get("name", ""))
                steps = data.get("steps", [])

                module_lower = module.lower()
                if (module_lower in scenario_id.lower()
                    or module_lower in name.lower()
                    or any(
                        module_lower in str(s.get("config", {})).lower()
                        for s in steps
                    )):
                    related.append(scenario_id or name or yaml_file.stem)

            return related
        except Exception:
            return []


class GateHandler(StageHandler):
    """机械门禁处理器 —— 纯 Python Layer1 检查，不调 AI。

    在 SDD 完成执行后、VERIFY 之前运行。
    只做确定性检测：SecretScan / TestIntegrity / ScopeBoundary / SkipDetection。
    通过 → 推进 VERIFY，拦截 → 返回 violations 列表。
    """

    stage = StageType.GATE

    def handle(self, state: RunState) -> RunState:
        """运行 Layer1 机械检查，通过则推进。

        Args:
            state: 当前运行状态

        Returns:
            RunState: 更新后的运行状态
        """
        state.task_state.stage = StageType.GATE
        logger.info("Gate — Layer1 mechanical checks")

        violations: list[str] = []
        warnings: list[str] = []

        try:
            from engines.review.engine import ReviewEngine

            review = ReviewEngine()
            layer1_results = review.run_layer1(state)
            blocked = any(r.block for r in layer1_results)
            passed_count = sum(1 for r in layer1_results if r.passed)
            state.task_state.notes.append(
                f"[GATE] Layer1: {passed_count}/{len(layer1_results)} passed, "
                f"blocked={blocked}"
            )

            if blocked:
                violations.append(
                    f"Gate blocked: {[r.reason for r in layer1_results if r.block]}"
                )
            for r in layer1_results:
                if r.severity.value == "warn":
                    warnings.append(f"Gate warn [{r.rule_name}]: {r.reason}")
        except Exception as exc:
            logger.warning("Gate Layer1 check failed: %s", exc)
            state.task_state.notes.append(f"[GATE] Layer1 异常，放行: {exc}")

        # 记录结果
        state.metadata["gate_report"] = {
            "violations": violations,
            "warnings": warnings,
        }

        if violations:
            state.task_state.notes.append(
                f"[GATE] BLOCKED — {len(violations)} violations: {violations}"
            )
            return self._stop_failure(state, "; ".join(violations))

        state.task_state.notes.append(
            f"[GATE] PASSED — {len(warnings)} warnings"
        )
        return self._complete(state, "Gate passed")


class ReviewHandler(StageHandler):
    """审查处理器 —— 两层审查架构。

    Layer 1 (Python): 确定性检测 — SecretScan / TestIntegrity / ScopeBoundary / SkipDetection
    Layer 2 (AI):   语义审查 — 读 git diff 做深度代码审查

    三阶段协议（支持 auto-repair loop）：
      PREPARE:  运行 Layer1 → 构建 AI review prompt（含 Layer1 结果 + diff + Plan 合约）
      VALIDATE: AI 提交审查结果 → 有 BLOCK 违规进入 fix 循环(max 3)
      FIX:      AI 修复后 → 重新运行 Layer1 → 通过则推进，否则回到 VALIDATE
    """

    stage = StageType.REVIEW
    MAX_REVIEW_RETRIES = 3

    def handle(self, state: RunState) -> RunState:
        """处理 REVIEW 阶段：运行两层审查，支持自动修复循环。

        Args:
            state: 当前运行状态

        Returns:
            RunState: 更新后的运行状态
        """
        logger.info("Review — two-layer review (Layer1 deterministic + Layer2 AI semantic)")

        self._plan_warnings: list[str] = []
        state.task_state.stage = StageType.REVIEW

        # 初始化 review_retry 计数
        review_meta = state.metadata.setdefault("review_meta", {})
        retry_count = review_meta.get("retry_count", 0)

        # ── Phase FIX: AI 已提交修复 → 重新验证 ──
        fix_result = state.metadata.get("review_fix_result")
        if fix_result and isinstance(fix_result, dict):
            return self._validate_fix(state, fix_result, retry_count)

        # ── Phase VALIDATE: AI 已提交审查结果 ──
        ai_result = state.metadata.get("review_ai_result")
        if ai_result and isinstance(ai_result, dict):
            return self._validate_review(state, ai_result, retry_count)

        # ── Phase PREPARE: 运行 Layer1 + 构建 AI review prompt ──
        return self._prepare_review(state)

    # ═══════════════════════════════════════════════════════════════
    # Phase PREPARE
    # ═══════════════════════════════════════════════════════════════

    def _prepare_review(self, state: RunState) -> RunState:
        """PREPARE: Layer1 检查 + Plan 合规 + 指令 AI 调用 /aicode-review。"""
        violations: list[str] = []
        warnings: list[str] = []

        # 1. Layer1: Python 规则检查
        layer1_violations, layer1_warnings, _layer1_result = self._run_layer1_checks(state)
        violations.extend(layer1_violations)
        warnings.extend(layer1_warnings)

        # 2. Plan 合规检查
        plan_violations = self._check_plan_compliance(state)
        violations.extend(plan_violations)

        # 3. Schema Version 记录
        schema_record = self._record_schema_version(state)
        if schema_record:
            state.task_state.notes.append(f"[REVIEW] Schema 版本已记录: {schema_record}")

        # 4. Task Execution Log 汇总
        task_summary = self._summarize_task_logs(state)

        # 5. 记录 Layer1 结果
        state.metadata["review_report"] = {
            "layer1_violations": violations,
            "layer1_warnings": warnings,
            "task_summary": task_summary,
        }
        state.metadata["review_meta"] = {"retry_count": 0, "layer1_blocked": len(violations) > 0}

        # 6. 指令 AI 调用 /aicode-review skill 做 6 维深度审查
        layer1_summary = (
            f"Layer1 结果: {len(violations)} violations, {len(warnings)} warnings"
        )
        if violations:
            layer1_summary += f"\nViolations: {', '.join(violations[:5])}"
        if warnings:
            layer1_summary += f"\nWarnings: {', '.join(warnings[:5])}"

        state.pending_action = "review"
        state.pending_prompt = {
            "instruction": (
                f"请执行 /aicode-review，对当前所有变更进行 6 维深度审查。\n\n"
                f"{layer1_summary}\n\n"
                "审查完成后返回结构化结果。"
            ),
            "layer1_violations": violations,
            "layer1_warnings": warnings,
        }
        state.needs_ai_input = True

        state.task_state.notes.append(
            f"[REVIEW] PREPARE: Layer1 → {len(violations)} violations, "
            f"{len(warnings)} warnings → AI 执行 /aicode-review"
        )
        logger.info("Review PREPARE: instructing AI to run /aicode-review")
        return state

    # ═══════════════════════════════════════════════════════════════
    # Phase VALIDATE
    # ═══════════════════════════════════════════════════════════════

    def _validate_review(
        self, state: RunState, ai_result: dict, retry_count: int
    ) -> RunState:
        """VALIDATE: 解析 AI 审查结果 → 决定是否需要修复。

        支持新旧两种严重级别：
        - 新（6维审查）: Critical / Important → 阻断；Minor → 放行
        - 旧（Layer1）：BLOCK → 阻断；WARN → 放行
        """
        # 清理 metadata 中的 AI 结果（避免重复处理）
        state.metadata.pop("review_ai_result", None)

        passed = ai_result.get("passed", True)
        ai_violations = ai_result.get("violations", [])
        summary = ai_result.get("summary", "")
        critical_count = ai_result.get("critical_count", 0)
        important_count = ai_result.get("important_count", 0)
        minor_count = ai_result.get("minor_count", 0)

        # Critical / Important / BLOCK → 需要修复
        block_violations = [
            v for v in ai_violations
            if v.get("severity") in ("Critical", "Important", "BLOCK")
        ]
        # Minor / WARN → 记录但不阻断
        minor_violations = [
            v for v in ai_violations
            if v.get("severity") in ("Minor", "WARN")
        ]

        state.task_state.notes.append(
            f"[REVIEW] AI 审查: passed={passed}, "
            f"Critical={critical_count}, Important={important_count}, Minor={minor_count}"
        )

        # 更新 review report
        report = state.metadata.setdefault("review_report", {})
        report["ai_passed"] = passed
        report["ai_violations"] = ai_violations
        report["ai_summary"] = summary
        report["critical_count"] = critical_count
        report["important_count"] = important_count
        report["minor_count"] = minor_count

        if passed and not block_violations:
            # 审查通过 → 推进到下一阶段
            state.task_state.notes.append(
                f"[REVIEW] AI 审查通过 ({minor_count} Minor 问题记录但不阻断)"
            )
            logger.info("Review passed — advancing to VERIFY")
            return self._finish_review(state)

        # 有 Critical/Important/BLOCK 违规 → 判断是否需要 AI 修复
        if block_violations and retry_count < self.MAX_REVIEW_RETRIES:
            # 显式更新 review_meta，不依赖 _request_fix 的副作用
            state.metadata["review_meta"]["retry_count"] = retry_count + 1
            return self._request_fix(state, block_violations, retry_count)

        # 重试次数耗尽 或 仅有 Minor → 记录并推进
        if retry_count >= self.MAX_REVIEW_RETRIES:
            state.task_state.notes.append(
                f"[REVIEW] Auto-fix 重试 {retry_count} 次已达上限，带 {len(block_violations)} 个违规推进"
            )
        else:
            state.task_state.notes.append(
                f"[REVIEW] {len(minor_violations)} Minor (非阻断)，推进到 VERIFY"
            )

        return self._finish_review(state)

    # ═══════════════════════════════════════════════════════════════
    # Auto-Fix 循环
    # ═══════════════════════════════════════════════════════════════

    def _request_fix(
        self, state: RunState, block_violations: list[dict], retry_count: int
    ) -> RunState:
        """构造 AI 修复 prompt，请求 AI 修复 BLOCK 违规。"""
        new_retry = retry_count + 1

        fix_instruction_parts = [
            "## 修复代码审查违规",
            "",
            f"以下 {len(block_violations)} 个 BLOCK 级别违规需要修复（第 {new_retry}/{self.MAX_REVIEW_RETRIES} 次尝试）：",
            "",
        ]
        for i, v in enumerate(block_violations):
            file_path = v.get("file", "?")
            desc = v.get("description", "")
            suggestion = v.get("fix_suggestion", "")
            fix_instruction_parts.append(
                f"{i + 1}. **{file_path}**: {desc}"
            )
            if suggestion:
                fix_instruction_parts.append(f"   修复建议: {suggestion}")
        fix_instruction_parts.extend([
            "",
            "## 修复要求",
            "- 只修改有违规的文件",
            "- 每处修改需确保不引入新问题",
            "- 修复后检查相关测试是否仍然通过",
            "- 输出 JSON: {\"fixed\": true/false, \"changes\": [{\"file\": \"...\", \"description\": \"...\"}], \"summary\": \"...\"}",
        ])

        state.pending_action = "review_fix"
        state.pending_prompt = {
            "instruction": "\n".join(fix_instruction_parts),
            "violations": block_violations,
            "retry": new_retry,
            "max_retries": self.MAX_REVIEW_RETRIES,
        }
        state.needs_ai_input = True
        state.metadata["review_meta"]["retry_count"] = new_retry

        state.task_state.notes.append(
            f"[REVIEW] Auto-fix 第 {new_retry}/{self.MAX_REVIEW_RETRIES} 次: "
            f"修复 {len(block_violations)} 个 BLOCK 违规"
        )
        logger.info("Review: requesting AI fix (attempt %d/%d)", new_retry, self.MAX_REVIEW_RETRIES)
        return state

    def _validate_fix(
        self, state: RunState, fix_result: dict, retry_count: int
    ) -> RunState:
        """验证 AI 修复结果 → 重新运行 Layer1 → 决定是否推进。"""
        state.metadata.pop("review_fix_result", None)

        fixed = fix_result.get("fixed", False)
        changes = fix_result.get("changes", [])
        summary = fix_result.get("summary", "")

        state.task_state.notes.append(
            f"[REVIEW] FIX 验证: fixed={fixed}, changes={len(changes)}, {summary[:100]}"
        )

        # 重新运行 Layer1 检查
        layer1_violations, layer1_warnings, _ = self._run_layer1_checks(state)

        if not layer1_violations:
            state.task_state.notes.append("[REVIEW] Layer1 重新检查通过，修复成功")
            logger.info("Review fix validated — Layer1 passed")
            return self._finish_review(state)

        # Layer1 仍然失败 → 判断是否重试
        if retry_count < self.MAX_REVIEW_RETRIES:
            new_retry = retry_count + 1
            # 显式更新 review_meta，不依赖 _request_fix 的副作用
            state.metadata["review_meta"]["retry_count"] = new_retry
            state.task_state.notes.append(
                f"[REVIEW] Layer1 仍有 {len(layer1_violations)} violations, 继续修复"
            )
            # 构造 block_violations 格式以便 _request_fix 使用
            still_blocked = [
                {"file": "?", "severity": "BLOCK", "description": v}
                for v in layer1_violations
            ]
            return self._request_fix(state, still_blocked, retry_count)

        # 重试耗尽
        state.task_state.notes.append(
            f"[REVIEW] Auto-fix 重试耗尽, Layer1 仍有 {len(layer1_violations)} violations, 带警告推进"
        )
        return self._finish_review(state)

    # ═══════════════════════════════════════════════════════════════
    # 完成
    # ═══════════════════════════════════════════════════════════════

    def _finish_review(self, state: RunState) -> RunState:
        """审查完成 —— 清空 pending 状态，推进到下一阶段。"""
        state.needs_ai_input = False
        state.pending_action = ""
        state.pending_prompt = {}

        report = state.metadata.get("review_report", {})
        violations = report.get("layer1_violations", [])
        warnings = report.get("layer1_warnings", [])
        task_summary = report.get("task_summary", "")

        # ── 反馈闭环: 保存模块级发现，供后续 EXECUTE 警告 ──
        self._save_review_findings(state, report)

        # 判断是否跳过 VERIFY（纯 docs/config 变更）
        if self._is_docs_only(state):
            state.task_state.notes.append("[REVIEW] 纯文档/配置变更，跳过 VERIFY → MEMORY")
            state.metadata["skip_verify"] = True

        return self._complete(
            state,
            f"review: {len(violations)} violations, {len(warnings)} warnings, {task_summary}",
        )

    def _save_review_findings(self, state: RunState, report: dict) -> None:
        """将 REVIEW 发现按模块保存，供后续 EXECUTE 阶段警告。"""
        ai_violations = report.get("ai_violations", [])
        if not ai_violations:
            return

        findings_by_module: dict[str, list[str]] = state.metadata.get(
            "review_findings_by_module", {},
        )

        for v in ai_violations:
            file_path = v.get("file", "")
            if not file_path:
                continue
            module = self._infer_module_from_file(file_path)
            if not module:
                continue
            severity = v.get("severity", "Minor")
            desc = v.get("description", "")
            if module not in findings_by_module:
                findings_by_module[module] = []
            findings_by_module[module].append(f"[{severity}] {desc}")

        if findings_by_module:
            state.metadata["review_findings_by_module"] = findings_by_module
            total = sum(len(v) for v in findings_by_module.values())
            state.task_state.notes.append(
                f"[REVIEW] 已记录 {total} 条模块级发现，后续 EXECUTE 将自动警告"
            )

    @staticmethod
    def _infer_module_from_file(file_path: str) -> str:
        parts = file_path.replace("\\", "/").split("/")
        if "src" in parts:
            idx = parts.index("src")
            if idx + 1 < len(parts):
                return parts[idx + 1]
        if len(parts) > 1:
            return parts[0]
        return ""

    # ═══════════════════════════════════════════════════════════════
    # Helpers
    # ═══════════════════════════════════════════════════════════════

    def _run_layer1_checks(self, state: RunState) -> tuple[list[str], list[str], object]:
        """运行 Layer1 检查 —— 7 条 Python 确定性规则。

        Returns: (violations, warnings, results_list)
        """
        violations: list[str] = []
        warnings: list[str] = []
        results: list = []
        try:
            from engines.review.engine import ReviewEngine

            review = ReviewEngine()
            results = review.run_layer1(state)
            blocked = [r for r in results if r.block]
            warn_items = [r for r in results if not r.passed and not r.block]
            passed = sum(1 for r in results if r.passed)
            state.task_state.notes.append(
                f"[REVIEW] Layer1: {passed}/{len(results)} passed, "
                f"{len(blocked)} blocked, {len(warn_items)} warned"
            )
            for r in blocked:
                violations.append(f"[{r.rule_name}] BLOCK: {r.reason}")
            for r in warn_items:
                warnings.append(f"[{r.rule_name}] WARN: {r.reason}")
        except Exception as exc:
            logger.warning("Review Layer1 check failed: %s", exc)
            state.task_state.notes.append(f"[REVIEW] Layer1 跳过: {exc}")
        return violations, warnings, results

    def _get_git_diff(self, state: RunState) -> str:
        """获取 git diff 文本供 AI 审查使用。"""
        try:
            import subprocess
            from pathlib import Path

            project_root = Path(state.project_root) if state.project_root else Path.cwd()
            if not (project_root / ".git").is_dir():
                return ""
            result = subprocess.run(
                ["git", "diff", "HEAD"],
                capture_output=True, text=True, cwd=str(project_root), timeout=15,
            )
            if result.returncode == 0:
                return result.stdout
        except Exception as exc:
            logger.debug("Failed to get git diff: %s", exc)
        return ""

    def _build_fallback_review_prompt(
        self, state: RunState, diff_text: str, violations: list[str], warnings: list[str]
    ) -> str:
        """当 ReviewEngine 不可用时，构造降级版 AI 审查 prompt。"""
        parts: list[str] = [
            "## 代码审查（降级模式）",
            "",
            "请逐文件审查以下 git diff，从以下维度判断：",
            "1. 逻辑正确性 / 2. 安全性 / 3. 破坏性变更 / 4. 性能 / 5. 错误处理 / 6. 不必要的抽象",
            "",
        ]
        if violations:
            parts.append("## Layer1 阻断项")
            for v in violations:
                parts.append(f"- {v}")
            parts.append("")
        if warnings:
            parts.append("## Layer1 警告")
            for w in warnings:
                parts.append(f"- {w}")
            parts.append("")
        if diff_text:
            parts.append("## Git Diff")
            parts.append("```diff")
            parts.append(diff_text[:8000])
            parts.append("```")
            parts.append("")
        parts.extend([
            "## 输出格式",
            '返回 JSON: {"passed": true/false, "violations": [{"file": "...", "severity": "BLOCK|WARN", "description": "...", "fix_suggestion": "..."}], "summary": "..."}',
        ])
        return "\n".join(parts)

    @staticmethod
    def _is_docs_only(state: RunState) -> bool:
        """检查变更是否仅涉及文档/配置文件（可跳过 VERIFY）。"""
        docs_suffixes = {".md", ".rst", ".txt", ".adoc"}
        config_only_patterns = {".github/", ".ai/", "docs/", "README"}
        all_files: list[str] = []
        for log in state.task_state.task_logs:
            all_files.extend(log.changed_files)
        if not all_files:
            return True
        for f in all_files:
            if f.endswith(tuple(docs_suffixes)):
                continue
            if any(f.startswith(p) or p in f for p in config_only_patterns):
                continue
            return False
        return True

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

            from engines.review.schema_version import SchemaVersionRecorder

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
    """记忆处理器 —— 触发 /memory skill，AI 直接写入 loop-memory-*.md。

    loop-memory 通过 .claude/rules/ 自动加载，无需 Python 投影。
    写入后人工 git diff 审核。
    """

    stage = StageType.MEMORY

    def handle(self, state: RunState) -> RunState:
        """Gate 检查 → /memory skill → 文件验证 → 流转。"""
        logger.info("Memory — checking gate then triggering /memory skill")
        state.task_state.stage = StageType.MEMORY

        from engines.runtime.completion_gate import _check_memory
        gate = _check_memory(state)

        if not gate.passed:
            # 提取本轮关键事件供 /memory 分析
            memory_context = self._build_memory_context(state)
            state.needs_ai_input = True
            state.pending_action = "memory"
            state.pending_prompt = {
                "instruction": (
                    "请运行 /memory skill，从本轮开发中提取可复用经验。\n\n"
                    f"Gate 状态: {gate.message}\n\n"
                    f"本轮关键事件（供参考）：\n{memory_context}\n\n"
                    "返回格式: {\"files\": [\".claude/rules/loop-memory-xxx.md\", ...]} "
                    "或 {\"skipped\": true, \"reason\": \"无值得沉淀的经验\"}"
                ),
            }
            state.task_state.notes.append(f"[MEMORY] Gate: {gate.message}，等待 AI")
            return state

        state.task_state.notes.append("[MEMORY] 记忆沉淀完成 → COMPLETED")
        return self._complete(state, "记忆沉淀完成")

    @staticmethod
    def _build_memory_context(state: RunState) -> str:
        """从 RunState 提取本轮关键事件摘要，供 /memory skill 分析。"""
        parts: list[str] = []

        # 失败记录
        if state.failures:
            parts.append(f"失败记录 ({len(state.failures)} 条):")
            for f in state.failures[-5:]:
                parts.append(f"  - [{f.category.value}] {f.stage.value}: {f.message[:120]}")

        # 修复记录
        repair_log = state.metadata.get("repair_result")
        if repair_log and isinstance(repair_log, dict):
            parts.append(f"修复: {repair_log.get('summary', repair_log.get('root_cause', ''))[:200]}")

        # 审查发现
        review = state.metadata.get("review_report") or {}
        if review.get("layer1_violations"):
            parts.append(f"审查 violations: {review['layer1_violations'][:3]}")
        if review.get("layer1_warnings"):
            parts.append(f"审查 warnings: {review['layer1_warnings'][:3]}")

        # 验证结果
        v = state.verification
        if v.status and v.status.value != "pending":
            parts.append(f"验证: {v.status.value} - {v.summary[:200] if v.summary else ''}")

        # 变更摘要
        task_logs = state.task_state.task_logs
        if task_logs:
            files = []
            for tl in task_logs:
                files.extend(tl.changed_files)
            if files:
                parts.append(f"变更文件: {', '.join(files[:10])}")

        return "\n".join(parts) if parts else "（本轮无特殊事件）"


class DirectExecuteHandler(StageHandler):
    """Direct Mode 执行处理器 —— 快速通道：跳过 Spec/Plan 直接改码。

    轻量流程: Guard 前置检查 → AI 编码 → 可选验证 → Review
    """

    stage = StageType.DIRECT_EXECUTE

    def handle(self, state: RunState) -> RunState:
        """处理 DIRECT_EXECUTE 阶段：Direct Mode 快速执行。

        Args:
            state: 当前运行状态

        Returns:
            RunState: 更新后的运行状态
        """
        logger.info("Direct Execute — fast path, skipping spec/plan")

        # 0. 场景检查：direct 跳过了 TEST_DESIGN，首次进入时让 AI 生成场景
        if not state.metadata.get("scenarios_generated"):
            state.metadata["scenarios_generated"] = True
            state.needs_ai_input = True
            state.pending_action = "generate_scenarios"
            state.pending_prompt = {
                "instruction": (
                    "请调用 /aicode-test-design 为此改动生成 1~2 个最小场景 YAML，"
                    "然后 loop continue。"
                ),
            }
            state.task_state.notes.append("[DIRECT] 首次进入，等待 AI 生成场景")
            return state

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
        # 1. 轻量 Review 检查
        try:
            from engines.review.engine import ReviewEngine

            review = ReviewEngine()
            results = review.run_layer1(state)
            blocked = [r for r in results if r.block]
            if blocked:
                reasons = "; ".join(r.reason for r in blocked)
                return self._stop_failure(state, f"Direct mode review blocked: {reasons}")
            passed = sum(1 for r in results if r.passed)
            state.task_state.notes.append(f"[DIRECT] Review: {passed}/{len(results)} passed")
        except Exception as exc:
            logger.warning("Review check skipped in direct mode: %s", exc)

        # 2. 设置执行状态
        state.task_state.status = state.task_state.status.__class__.IN_PROGRESS
        state.task_state.stage = StageType.DIRECT_EXECUTE

        # 2.5. ContextRouter 注入 DIRECT_EXECUTE 上下文（至少做 codegraph 定位 + 相关文件）
        direct_context = self._load_direct_context(state)

        # 3. 构造 AI prompt — 精简指令 + 结构化字段（与 EXECUTE 对齐）
        user_input = state.metadata.get("user_input", "")
        checklist = [
            "只修改需求相关的文件 ≤ 3",
            "遵守项目已有代码风格和命名规范",
            "不引入新依赖或新抽象层",
            "保持已有测试通过，不删除/削弱已有断言",
            "不进行无关格式化和重构",
            "极简: 无未要求的抽象/配置/异常处理？",
            "纯粹: 每行改动都能追溯到需求？不动相邻代码",
            "确定: 不确定的地方是否已标出而非猜测？",
        ]
        preflight = self._load_preflight_warnings(state)
        specification = self._load_specification(state)
        instruction_parts = [
            f"Direct Mode — 需求: {user_input}",
            f"风险等级: {intake.risk_level if intake else 'L1'}",
        ]
        if preflight:
            instruction_parts.extend(["", "## 编码前注意", *preflight])
        instruction_parts.extend([
            "",
            "## Implementation Checklist (逐项确认后编码)",
            *[f"- [ ] {item}" for item in checklist],
        ])
        state.pending_action = "direct_execute"
        state.pending_prompt = {
            "instruction": "\n".join(instruction_parts),
            "specification": specification,
            "context": direct_context,
            "preflight_warnings": preflight,
            "implementation_checklist": checklist,
            "risk_level": intake.risk_level if intake else "L1",
            "budget": {
                "max_files": 3,
                "max_lines": 100,
                "allow_new_abstractions": False,
                "allow_new_dependencies": False,
            },
        }
        state.needs_ai_input = True
        state.task_state.notes.append(
            "[DIRECT] PREPARE: AI 直接编码, 更改 ≤3 文件, 遵守项目风格"
        )
        logger.info("Direct Execute prompt ready")
        return state

    def _load_direct_context(self, state: RunState) -> str:
        """AI 自行使用 Read / CodeGraph MCP 获取上下文，Python 不注入。"""
        return ""

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


# ── Adapter 端口映射（动态，避免硬编码）────────────────────────

def _build_adapter_port_map(project_root: Path) -> dict[str, int]:
    """扫描内置 + 项目级 Adapter 类，构建 {adapter_type: default_port} 映射。

    Args:
        project_root: 项目根目录（用于发现 .ai/adapters/）

    Returns:
        {adapter_type: default_port} 字典
    """
    result: dict[str, int] = {}
    try:
        from engines.scenario.adapters.base import ResourceAdapter
        from engines.scenario.adapters import _BUILTIN_ADAPTERS

        # 内置适配器
        for cls in _BUILTIN_ADAPTERS.values():
            if cls.adapter_type and cls.default_port:
                result[cls.adapter_type] = cls.default_port

        # 项目级适配器 (.ai/adapters/*.py)
        from engines.scenario.adapters import DataSourceRegistry
        DataSourceRegistry._discover_project_adapters(project_root)
        for cls in DataSourceRegistry._PROJECT_ADAPTERS.values():
            if cls.adapter_type and cls.default_port:
                result[cls.adapter_type] = cls.default_port
    except Exception:
        pass
    return result


# ── 默认 Handler 注册表 ──────────────────────────────────────────

def default_handlers() -> dict[StageType, StageHandler]:
    """返回内置的阶段处理器映射。

    每个 handler 实现 Python 引擎的确定性工作（context/guard/scenario/memory），
    创造性工作（spec/plan/code/root-cause）由 AI 完成。
    应用项目可通过注入自定义 handler 覆盖默认实现。

    Returns:
        dict[StageType, StageHandler]: 阶段类型到处理器的映射字典
    """
    return {
        StageType.INTAKE:         IntakeHandler(),
        StageType.SPEC:           SpecHandler(),
        StageType.TEST_DESIGN:    TestDesignStageHandler(),
        StageType.PLAN:           PlanHandler(),
        StageType.EXECUTE:        ExecuteHandler(),
        StageType.VERIFY:         VerifyHandler(),
        StageType.REPAIR:         RepairHandler(),
        StageType.REVIEW:         ReviewHandler(),
        StageType.MEMORY:         MemoryHandler(),
        StageType.DIRECT_EXECUTE: DirectExecuteHandler(),
    }
