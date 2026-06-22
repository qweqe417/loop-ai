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

# Direct Mode 跳过 SPEC/PLAN/TEST_DESIGN
DIRECT_STAGES: list[StageType] = [
    StageType.INTAKE,
    StageType.DIRECT_EXECUTE,
    StageType.REVIEW,
    StageType.VERIFY,
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

    def _load_preflight_warnings(self, state: RunState) -> list[str]:
        """从项目记忆加载编码前反模式提示。

        召回 PITFALL / PROHIBITED / FAILURE_PATTERN 类记忆，
        优先加载 entries/{id}.md 正文以获得更详细的反模式说明。
        限制 2 条，每条 ≤ 120 字符。
        """
        warnings: list[str] = []
        try:
            from pathlib import Path
            from engines.memory import MemoryCategory
            from engines.memory.store import MemoryStore

            project_root = Path(state.project_root) if state.project_root else Path.cwd()
            store = MemoryStore(project_root=project_root)
            entries = store.recall_by_category(
                [MemoryCategory.PITFALL, MemoryCategory.PROHIBITED,
                 MemoryCategory.FAILURE_PATTERN],
                limit=3,
            )
            for e in entries:
                # 尝试加载 entry 正文以获得更多细节
                body = store.load_entry(e.id)
                if body and body.content and len(body.content) > len(e.title):
                    detail = body.content  # 来自 entries/{id}.md 的详细内容
                else:
                    detail = e.content or e.title  # fallback 到索引摘要

                if len(detail) > 120:
                    detail = detail[:120] + "..."
                tag = e.tags[0] if e.tags else "注意"
                warnings.append(f"[{tag}] {detail}")

            if warnings:
                logger.info("Preflight: loaded %d warning(s) from memory", len(warnings))
        except Exception as exc:
            logger.debug("Preflight warnings unavailable: %s", exc)

        return warnings[:2]

    def _load_specification(self, state: RunState, task_id: str = "") -> dict:
        """定位 Spec/Plan 文件路径 + 简要摘要（供 superpowers 子Agent 读取）。

        superpowers:subagent-driven-development 内部自己读 plan/spec 文件，
        这里只提供路径引用，不注入全文（避免冗余 token）。
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
    """Spec 生成处理器 —— 透传桩。

    Spec 生成已移至 AI skill（/aicode-spec），Python 侧不再编排 Spec 流程。
    该 handler 仅标记阶段并直接流转到 PLAN。
    """

    stage = StageType.SPEC

    def handle(self, state: RunState) -> RunState:
        state.task_state.stage = StageType.SPEC
        state.task_state.notes.append("[SPEC] 由 AI skill 处理 (/aicode-spec)，Python 侧透传")
        logger.info("SpecHandler: pass-through to PLAN")
        return self._complete(state, "Spec 由 AI skill 处理")


class TestDesignStageHandler(StageHandler):
    """测试设计处理器 —— 透传桩。

    测试用例生成由 AI skill（/aicode-test-design）完成。
    Python 侧仅在 AI 提交结果后进行校验和门禁检查。

    AI 职责:
      1. 读取 spec 产物（state.spec_entry）
      2. 按 Schema 生成 TestDesignBundle YAML
      3. 调用 test-design process --input <yaml> 一键校验+门禁+映射
      4. 提交结果到 state
    """

    stage = StageType.TEST_DESIGN

    def handle(self, state: RunState) -> RunState:
        state.task_state.stage = StageType.TEST_DESIGN
        state.task_state.notes.append(
            "[TEST_DESIGN] 由 AI skill 处理 (/aicode-test-design)，Python 侧透传"
        )
        logger.info("TestDesignStageHandler: pass-through to EXECUTE")

        # 如果已经有 test_design_bundle（从 AI 提交的 continue 恢复），直接流转
        if state.test_design_bundle:
            state.task_state.notes.append(
                f"[TEST_DESIGN] 已生成 {len(state.test_case_refs)} 条用例，"
                f"{len(state.scenario_candidate_refs)} 条 Scenario 候选"
            )

        return self._complete(state, "Test Design 由 AI skill 处理")


class PlanHandler(StageHandler):
    """计划生成处理器 —— 透传桩。

    Plan 生成已移至 AI skill（/aicode-plan），Python 侧不再编排 Plan 流程。
    该 handler 仅标记阶段并直接流转到 EXECUTE。
    """

    stage = StageType.PLAN

    def handle(self, state: RunState) -> RunState:
        state.task_state.stage = StageType.PLAN
        state.task_state.notes.append("[PLAN] 由 AI skill 处理 (/aicode-plan)，Python 侧透传")
        logger.info("PlanHandler: pass-through to EXECUTE")
        return self._complete(state, "Plan 由 AI skill 处理")


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
            # PlanLock 恢复路径: AI 提交 lock_plan 指令
            if submitted.get("lock_plan"):
                state.plan_lock_state = "locked"
                state.needs_ai_input = False
                state.metadata.pop("execute_result", None)
                state.task_state.notes.append("[EXECUTE] PlanLock → locked (AI 确认)")
                logger.info("Plan locked by AI confirmation")
                # 重新进入 PREPARE 构造真正的编码 prompt
                return self._prepare_task(state, contracts[current_idx], current_idx, len(contracts))
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
            f"上限: {budget.get('max_files', 3)} files / {budget.get('max_lines', 100)} lines",
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
                "max_lines": budget.get("max_lines", 100),
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
        """审查前置检查 —— 在 AI 编码前运行默认规则集。"""
        try:
            from engines.review import create_review_engine

            review = create_review_engine()
            result = review.check(state)
            if result.block:
                state.task_state.notes.append(f"[EXECUTE] Review 拦截: {result.reason}")
                state.decision = None
                return False

            individual_results = result.details.get("results", [])
            passed = sum(1 for r in individual_results if getattr(r, 'passed', True))
            state.task_state.notes.append(
                f"[EXECUTE] Review: {passed}/{len(individual_results)} passed"
            )
            return True
        except Exception as exc:
            logger.error("Guard check raised exception, BLOCKING: %s", exc)
            state.task_state.notes.append(
                f"[EXECUTE] Review 异常，阻止执行: {type(exc).__name__}: {exc}"
            )
            return False

    def _load_execute_context(self, state: RunState, contract: dict) -> str:
        """ContextRouter 注入当前 Task 需要的上下文。

        上下文预算感知: 加载前检查预算，加载后跟踪使用量。
        返回渲染后的上下文文本，可直接注入 AI prompt。

        同时写入 .ai/memory/context/{task_id}-memory.md（Path A 文件注入），
        供 superpowers 路径按需读取。不污染规则文件。
        """
        try:
            from engines.context.router import ContextRouter
            router = self._get_context_router(state)
            bundle = router.route(stage=StageType.EXECUTE, run_state=state)
            if bundle and bundle.pieces:
                # 上下文预算检查
                if not self._check_context_budget(state, bundle.total_tokens):
                    state.task_state.notes.append(
                        "[EXECUTE context] 上下文预算超限，已截断"
                    )
                self._track_context_usage(state, bundle.total_tokens)
                state.task_state.notes.append(
                    f"[EXECUTE context] tokens={bundle.total_tokens}, "
                    f"files={len(bundle.pieces)}, "
                    f"pointers={len(bundle.trimmed_pointers)}, "
                    f"budget={state.context_budget_used}/{state.context_budget_max}"
                )
                if bundle.trimmed:
                    state.task_state.notes.append(
                        f"[EXECUTE context] Context 已截断 (trimmed={bundle.trimmed}, "
                        f"pointers={len(bundle.trimmed_pointers)})"
                    )

                # ── 记录注入的记忆 ID（供 VERIFY 阶段效果评估）──
                injected_ids = [
                    p.path for p in bundle.pieces
                    if p.source == "memory" and p.path
                ]
                if injected_ids:
                    existing = state.metadata.get("injected_memory_ids", [])
                    state.metadata["injected_memory_ids"] = list(dict.fromkeys(existing + injected_ids))

                # ── Path A 文件注入 ──
                task_id = contract.get("task_id", state.task_id)
                context_file = self._inject_context_file(bundle, task_id, state.project_root)
                if context_file:
                    state.task_state.notes.append(
                        f"[EXECUTE context] 记忆上下文文件已写入 {context_file}"
                    )

                return bundle.render()
            return ""
        except Exception as exc:
            logger.warning("ContextRouter failed for EXECUTE: %s", exc)
            return ""

    def _inject_context_file(
        self, bundle, task_id: str, project_root: str
    ) -> str | None:
        """Path A 文件注入: 将记忆和 pointer 写入独立文件。

        不污染 CLAUDE.md / rules/*.md。
        文件路径: .ai/memory/context/{task_id}-memory.md
        """
        from pathlib import Path
        try:
            context_dir = Path(project_root) / ".ai" / "memory" / "context"
            context_dir.mkdir(parents=True, exist_ok=True)

            filepath = context_dir / f"{task_id}-memory.md"

            lines = [
                f"# 任务上下文 — {task_id}",
                "",
                "> 此文件由 Loop Runtime 自动生成。可按需读取，不强制加载。",
                "",
            ]

            # 记忆条目摘要
            mem_pieces = [p for p in bundle.pieces if p.source == "memory"]
            if mem_pieces:
                lines.append("## 相关项目记忆")
                lines.append("")
                for mp in mem_pieces:
                    lines.append(f"- {mp.content}")
                lines.append("")

            # 被裁剪的 pointers
            if bundle.trimmed_pointers:
                lines.append("## 可回捞内容（被裁剪）")
                lines.append("")
                for tp in bundle.trimmed_pointers:
                    lines.append(f"- **[{tp.type}]** {tp.summary}")
                    if tp.why_relevant:
                        lines.append(f"  - 关联: {tp.why_relevant}")
                    if tp.retrieval_hint:
                        lines.append(f"  - 回捞: `{tp.retrieval_hint}`")
                lines.append("")

            filepath.write_text("\n".join(lines), encoding="utf-8")
            return str(filepath)
        except Exception as exc:
            logger.warning("Failed to write context file: %s", exc)
            return None

    # ContextRouter 实例缓存（per-handler 复用，避免重复初始化）
    _cached_router = None

    def _get_context_router(self, state: RunState):
        """获取复用的 ContextRouter 实例（P3 优化：避免 per-task 重复初始化）。"""
        if self._cached_router is None:
            from engines.context.router import ContextRouter
            self._cached_router = ContextRouter(state.project_root)
        return self._cached_router

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

                # ── 记忆效果评估（失败 = 记忆被忽略）──
                self._evaluate_memory_effectiveness(state, success=False)

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

        # ── 记忆效果自动评估 ──
        self._evaluate_memory_effectiveness(state, success=True)

        logger.info("Verification passed: %d scenarios, %d assertions",
                     len(scenario_results), state.verification.total_assertions)
        return self._complete(state, f"验证通过: {state.verification.summary}")

    def _evaluate_memory_effectiveness(self, state: RunState, success: bool) -> None:
        """VERIFY 阶段自动评估注入记忆的效果。

        - 验证通过 → 注入的记忆标记 effective（修复规则被正确应用）
        - 验证失败 → 注入的记忆标记 ineffective（本该用但被忽略）
        """
        try:
            from engines.memory.store import MemoryStore
            store = MemoryStore(project_root=state.project_root)
            store.load_index()

            # 从 run_state 获取本任务注入的记忆 ID 列表
            injected_ids = state.metadata.get("injected_memory_ids", [])
            if not injected_ids:
                return

            updated = 0
            for mem_id in injected_ids:
                store.record_effectiveness(mem_id, effective=success)
                updated += 1

            if updated:
                label = "effective" if success else "ineffective"
                state.task_state.notes.append(
                    f"[VERIFY] 记忆效果评估: {updated} 条标记为 {label}"
                )
                logger.info("Memory effectiveness: %d entries marked %s", updated, label)
        except Exception as exc:
            logger.warning("Memory effectiveness evaluation failed: %s", exc)

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
    MAX_REPAIR_RETRIES = 3

    def handle(self, state: RunState) -> RunState:
        logger.info("Repair — analyzing failures and loading context")

        state.task_state.status = state.task_state.status.__class__.REPAIRING
        state.task_state.stage = StageType.REPAIR

        # 1. 检查重试次数
        if state.task_state.retry_count >= self.MAX_REPAIR_RETRIES:
            logger.error("Repair retry limit (%d) exceeded", self.MAX_REPAIR_RETRIES)
            state.task_state.notes.append(
                f"[REPAIR] 超过最大重试次数 {self.MAX_REPAIR_RETRIES}, 升级给用户"
            )
            return self._stop_failure(state, f"修复失败: 超过 {self.MAX_REPAIR_RETRIES} 次重试")

        state.task_state.retry_count += 1

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
                f"[REPAIR] attempt={state.task_state.retry_count}/{self.MAX_REPAIR_RETRIES}, 无 failure 记录"
            )

        # ── Phase VALIDATE: AI 已提交修复结果 ──
        submitted = state.metadata.get("repair_result")
        if submitted and isinstance(submitted, dict):
            return self._validate_repair_result(state, submitted)

        # ── Phase PREPARE: 构造修复 prompt ──
        return self._prepare_repair(state)

    def _prepare_repair(self, state: RunState) -> RunState:
        """构造修复 prompt，注入失败上下文 + preflight warnings。"""
        # 1. 通过 ContextRouter 加载失败相关上下文
        repair_context = ""
        try:
            from engines.context.router import ContextRouter
            router = ContextRouter(state.project_root)
            bundle = router.route(stage=StageType.REPAIR, run_state=state)
            if bundle and bundle.pieces:
                repair_context = bundle.render()
                state.task_state.notes.append(
                    f"[REPAIR context] tokens={bundle.total_tokens}, "
                    f"files={len(bundle.pieces)}"
                )
        except Exception as exc:
            logger.warning("ContextRouter failed for REPAIR: %s", exc)
            state.task_state.notes.append(f"[REPAIR] ContextRouter 不可用: {exc}")

        # 2. 构建失败摘要
        failure_text = "**Recent Failures:**\n"
        if state.failures:
            for f in state.failures[-3:]:
                failure_text += f"- [{f.category.value}] {f.message[:150]}\n"
        else:
            failure_text += "(无详细 failure 记录)\n"

        # 3. Preflight warnings — 修复时更需要历史教训
        preflight = self._load_preflight_warnings(state)

        # 4. 变更文件列表
        changed_files: list[str] = []
        for cp in state.checkpoints:
            changed_files.extend(cp.files_changed)
        changed_files = list(dict.fromkeys(changed_files))

        instruction_parts = [
            f"修复尝试 {state.task_state.retry_count}/{self.MAX_REPAIR_RETRIES}",
            "",
            failure_text,
        ]
        if changed_files:
            instruction_parts.append(f"**变更过的文件:** {changed_files}")
        if preflight:
            instruction_parts.extend(["", "## 历史教训 (避免重犯)", *preflight])
        instruction_parts.extend([
            "",
            "## 约束",
            "- 分析根因，最小修复（≤ 30 行变更）",
            "- 不修改 scenario 定义文件",
            "- 不删除或削弱已有测试断言",
            "- 修复后运行对应测试确认通过",
            "",
            "提交格式: {\"changed_files\": [...], \"summary\": \"...\", \"root_cause\": \"...\"}",
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
            "repair_constraints": {
                "max_files": 3,
                "max_lines": 50,
                "no_scenario_modification": True,
                "no_assertion_deletion": True,
            },
        }
        state.needs_ai_input = True
        state.task_state.notes.append(
            f"[REPAIR] PREPARE: attempt={state.task_state.retry_count}/{self.MAX_REPAIR_RETRIES}"
        )
        logger.info("Repair prompt ready, waiting for AI fix")
        return state

    def _validate_repair_result(
        self, state: RunState, submitted: dict,
    ) -> RunState:
        """校验 AI 修复结果。"""
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

        # 4. 清理并进入 VERIFY
        state.needs_ai_input = False
        state.pending_action = ""
        state.metadata.pop("repair_result", None)

        logger.info("Repair validated, re-entering VERIFY")
        return self._advance_to(
            state, StageType.VERIFY,
            f"修复 applied (attempt {state.task_state.retry_count}), 重新验证",
        )


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
        """PREPARE: Layer1 检查 + Plan 合规 + 构建 AI 审查 prompt。"""
        violations: list[str] = []
        warnings: list[str] = []

        # 1. Layer1: Python 规则检查（跑一次，结果同时用于 violations 列表和 AI prompt）
        layer1_violations, layer1_warnings, layer1_result = self._run_layer1_checks(state)
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

        # 5. 获取 git diff
        diff_text = self._get_git_diff(state)

        # 6. 构建 AI 审查 prompt（复用 Layer1 结果，不再重复 check）
        try:
            from engines.review.engine import ReviewEngine

            review_engine = ReviewEngine()
            if layer1_result is None:
                layer1_result = review_engine.check(state)
            ai_prompt = review_engine.build_ai_review_prompt(state, diff_text, layer1_result)
        except Exception as exc:
            logger.warning("Failed to build AI review prompt: %s", exc)
            ai_prompt = self._build_fallback_review_prompt(state, diff_text, violations, warnings)

        # 7. 记录 Layer1 结果
        state.metadata["review_report"] = {
            "layer1_violations": violations,
            "layer1_warnings": warnings,
            "task_summary": task_summary,
        }
        state.metadata["review_meta"] = {"retry_count": 0, "layer1_blocked": len(violations) > 0}

        # 8. 设置 AI review 请求
        state.pending_action = "review"
        state.pending_prompt = {
            "instruction": ai_prompt,
            "layer1_violations": violations,
            "layer1_warnings": warnings,
        }
        state.needs_ai_input = True

        state.task_state.notes.append(
            f"[REVIEW] PREPARE: Layer1 → {len(violations)} violations, "
            f"{len(warnings)} warnings → AI 深度审查"
        )
        logger.info("Review PREPARE: AI review prompt ready (%d chars)", len(ai_prompt))
        return state

    # ═══════════════════════════════════════════════════════════════
    # Phase VALIDATE
    # ═══════════════════════════════════════════════════════════════

    def _validate_review(
        self, state: RunState, ai_result: dict, retry_count: int
    ) -> RunState:
        """VALIDATE: 解析 AI 审查结果 → 决定是否需要修复。"""
        # 清理 metadata 中的 AI 结果（避免重复处理）
        state.metadata.pop("review_ai_result", None)

        passed = ai_result.get("passed", True)
        ai_violations = ai_result.get("violations", [])
        summary = ai_result.get("summary", "")

        block_violations = [v for v in ai_violations if v.get("severity") == "BLOCK"]
        warn_violations = [v for v in ai_violations if v.get("severity") == "WARN"]

        state.task_state.notes.append(
            f"[REVIEW] AI 审查: passed={passed}, "
            f"BLOCK={len(block_violations)}, WARN={len(warn_violations)}"
        )

        # 更新 review report
        report = state.metadata.setdefault("review_report", {})
        report["ai_passed"] = passed
        report["ai_violations"] = ai_violations
        report["ai_summary"] = summary

        if passed and not block_violations:
            # 审查通过 → 推进到下一阶段
            state.task_state.notes.append("[REVIEW] AI 审查通过")
            logger.info("Review passed — advancing to next stage")
            return self._finish_review(state)

        # 有 BLOCK 违规 → 判断是否需要 AI 修复
        if block_violations and retry_count < self.MAX_REVIEW_RETRIES:
            return self._request_fix(state, block_violations, retry_count)

        # 重试次数耗尽 或 仅有 WARN → 记录并推进
        if retry_count >= self.MAX_REVIEW_RETRIES:
            state.task_state.notes.append(
                f"[REVIEW] Auto-fix 重试 {retry_count} 次已达上限，带警告推进"
            )
        else:
            state.task_state.notes.append(
                f"[REVIEW] {len(warn_violations)} warnings (非阻断)，推进到下一阶段"
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

        # 判断是否跳过 VERIFY（纯 docs/config 变更）
        if self._is_docs_only(state):
            state.task_state.notes.append("[REVIEW] 纯文档/配置变更，跳过 VERIFY → MEMORY")
            state.metadata["skip_verify"] = True

        return self._complete(
            state,
            f"review: {len(violations)} violations, {len(warnings)} warnings, {task_summary}",
        )

    # ═══════════════════════════════════════════════════════════════
    # Helpers
    # ═══════════════════════════════════════════════════════════════

    def _run_layer1_checks(self, state: RunState) -> tuple[list[str], list[str], object]:
        """运行 Layer1 检查 —— 使用默认规则集（SecretScan / TestIntegrity / ScopeBoundary / SkipDetection）。

        Returns: (violations, warnings, review_result)
        """
        violations: list[str] = []
        warnings: list[str] = []
        layer1_result = None
        try:
            from engines.review.engine import ReviewEngine

            review = ReviewEngine()
            layer1_result = review.check(state)
            individual_results = layer1_result.details.get("results", [])
            passed_count = sum(1 for r in individual_results if r.get("passed", True))
            state.task_state.notes.append(
                f"[REVIEW] Layer1: {passed_count}/{len(individual_results)} passed, blocked={layer1_result.block}"
            )
            if layer1_result.block:
                violations.append(f"Review blocked: {layer1_result.reason}")
            for r in individual_results:
                if r.get("severity") == "warn":
                    warnings.append(f"Review warn [{r.get('rule', '?')}]: {r.get('reason', '')}")
        except Exception as exc:
            logger.warning("Review Layer1 check failed: %s", exc)
            state.task_state.notes.append(f"[REVIEW] Layer1 跳过: {exc}")
        return violations, warnings, layer1_result

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
        # 1. 轻量 Review 检查
        try:
            from engines.review.engine import ReviewEngine

            review = ReviewEngine()
            result = review.check(state)
            if result.block:
                return self._stop_failure(state, f"Direct mode review blocked: {result.reason}")
            individual_results = result.details.get("results", [])
            passed = sum(1 for r in individual_results if r.get("passed", True))
            state.task_state.notes.append(f"[DIRECT] Review: {passed}/{len(individual_results)} passed")
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
        """Direct Mode 上下文 — 浅层上下文注入（至少 codegraph 定位）。

        比 EXECUTE 策略更轻量，仅加载项目地图 + codegraph 相关上下文。
        复用 ContextRouter 实例避免重复初始化。
        """
        try:
            from engines.context.router import ContextRouter
            # 复用缓存实例
            if not hasattr(self, '_cached_router') or self._cached_router is None:
                self._cached_router = ContextRouter(state.project_root)
            router = self._cached_router
            # 使用 DIRECT_EXECUTE 的轻量策略
            bundle = router.route(stage=StageType.DIRECT_EXECUTE, run_state=state)
            if bundle and bundle.pieces:
                state.task_state.notes.append(
                    f"[DIRECT context] tokens={bundle.total_tokens}, "
                    f"files={len(bundle.pieces)}"
                )
                return bundle.render()
            return ""
        except Exception as exc:
            logger.warning("ContextRouter failed for DIRECT_EXECUTE: %s", exc)
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
        StageType.TEST_DESIGN:    TestDesignStageHandler(),
        StageType.PLAN:           PlanHandler(),
        StageType.EXECUTE:        ExecuteHandler(),
        StageType.VERIFY:         VerifyHandler(),
        StageType.REPAIR:         RepairHandler(),
        StageType.REVIEW:         ReviewHandler(),
        StageType.MEMORY:         MemoryHandler(),
        StageType.DIRECT_EXECUTE: DirectExecuteHandler(),
    }
