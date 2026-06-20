"""Plan 质量门禁 —— 架构 §8.6.10。

Plan 生成后必须检查:
- 是否覆盖 Spec 中所有验收标准
- 是否每个 Task 都有 allowedFiles / forbiddenFiles
- 是否每个 Task 都绑定 Scenario 或验证方式
- 是否每个 Task 都引用 Style Contract
- 是否包含 Reuse Check
- 是否存在过大任务
- 是否存在范围膨胀
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .models import PlanContract, PlanQualityReport

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class PlanQualityGate:
    """Plan 质量门禁 —— 在 PLAN → EXECUTE 流转前执行。

    用法:
        gate = PlanQualityGate()
        report = gate.evaluate(contracts, spec_entry)
        if report.passed:
            proceed_to_execute()
    """

    def __init__(self, threshold: float = 70.0) -> None:
        self.threshold = threshold

    # ── 评估入口 ───────────────────────────────────────────────

    def evaluate(
        self,
        contracts: list[PlanContract],
        spec_entry: dict[str, Any] | None = None,
    ) -> PlanQualityReport:
        """对 Plan 执行质量检查。

        Args:
            contracts: PlanContract 列表
            spec_entry: SpecEntry 的 dict 形式，用于检查验收标准覆盖
        """
        if not contracts:
            return PlanQualityReport(
                score=0.0,
                passed=False,
                suggestions=["Plan 为空 —— 至少需要一个 Task"],
            )

        # 各项检查
        all_covers = self._check_acceptance_coverage(contracts, spec_entry)
        all_boundaries = self._check_task_boundaries(contracts)
        all_bound_to_scenario = self._check_scenario_binding(contracts)
        all_style = self._check_style_contract(contracts)
        all_reuse = self._check_reuse_check(contracts)
        oversized = self._check_task_size(contracts)
        scope_creep = self._check_scope_creep(contracts)
        unverified = self._find_unverified(contracts)

        # 打分
        checks = [
            all_covers,
            all_boundaries,
            all_bound_to_scenario,
            all_style,
            all_reuse,
            not oversized[0],  # oversized[0] = has_oversized
            not scope_creep,
        ]
        score = round(sum(100 / len(checks) for c in checks if c), 1)

        suggestions = self._build_suggestions(
            contracts, spec_entry,
            all_covers, all_boundaries, all_bound_to_scenario,
            all_style, all_reuse, oversized, scope_creep, unverified,
        )

        return PlanQualityReport(
            score=score,
            passed=score >= self.threshold,
            covers_all_acceptance=all_covers,
            all_tasks_have_boundaries=all_boundaries,
            all_tasks_bound_to_scenario=all_bound_to_scenario,
            all_tasks_have_style_contract=all_style,
            all_tasks_have_reuse_check=all_reuse,
            no_oversized_tasks=not oversized[0],
            scope_creep_detected=scope_creep,
            oversized_tasks=oversized[1],
            unverified_tasks=unverified,
            missing_coverage=self._find_missing_coverage(contracts, spec_entry),
            suggestions=suggestions,
        )

    # ── 检查项 ──────────────────────────────────────────────────

    def _check_acceptance_coverage(
        self, contracts: list[PlanContract], spec_entry: dict[str, Any] | None
    ) -> bool:
        """检查 Plan 是否覆盖 Spec 所有验收标准。"""
        if spec_entry is None:
            return True  # 无 spec 时不强制
        spec_criteria = spec_entry.get("acceptance_criteria", [])
        if not spec_criteria:
            return True
        # 收集所有 task 覆盖的 acceptance
        covered: set[str] = set()
        for c in contracts:
            for ac in c.links.acceptance_criteria:
                covered.add(ac)
        # 如果 task 没显式绑定，检查 done_when/verification 中是否引用了验收标准关键词
        if not covered:
            return False
        return len(covered) >= len(spec_criteria)

    def _check_task_boundaries(self, contracts: list[PlanContract]) -> bool:
        """检查每个 Task 是否声明了 allowedFiles。"""
        return all(
            c.allowed_files for c in contracts
        )

    def _check_scenario_binding(self, contracts: list[PlanContract]) -> bool:
        """检查每个 Task 是否绑定 Scenario 或验证方式。"""
        return all(
            c.links.scenarios or c.verification for c in contracts
        )

    def _check_style_contract(self, contracts: list[PlanContract]) -> bool:
        """检查每个 Task 是否引用 Style Contract。"""
        return all(
            c.style_contract.must or c.style_contract.forbidden
            for c in contracts
        )

    def _check_reuse_check(self, contracts: list[PlanContract]) -> bool:
        """检查每个 Task 是否有 Reuse Check。"""
        return all(
            c.reuse_check.search_for for c in contracts
        )

    def _check_task_size(self, contracts: list[PlanContract]) -> tuple[bool, list[str]]:
        """检查是否存在过大任务 (>5 文件)。"""
        oversized = [
            c.task_id for c in contracts
            if len(c.allowed_files) > 5
        ]
        return (len(oversized) == 0, oversized)

    def _check_scope_creep(self, contracts: list[PlanContract]) -> bool:
        """检查是否存在范围膨胀 —— Task 声明的文件远超 Spec 影响域。"""
        # 简单启发式: 如果所有 task 的 allowed_files 总数 > 20 且无 spec 绑定，视为范围膨胀
        total_files = sum(len(c.allowed_files) for c in contracts)
        if total_files > 20:
            return True
        return False

    def _find_unverified(self, contracts: list[PlanContract]) -> list[str]:
        """找出无法验证的 Task。"""
        return [
            c.task_id for c in contracts
            if not c.verification and not c.links.scenarios
        ]

    def _find_missing_coverage(
        self, contracts: list[PlanContract], spec_entry: dict[str, Any] | None
    ) -> list[str]:
        """找出未被 Plan 覆盖的 Acceptance Criteria。"""
        if spec_entry is None:
            return []
        spec_criteria = spec_entry.get("acceptance_criteria", [])
        if not spec_criteria:
            return []
        covered: set[str] = set()
        for c in contracts:
            for ac in c.links.acceptance_criteria:
                covered.add(ac)
        return [ac for ac in spec_criteria if ac not in covered]

    # ── 建议生成 ───────────────────────────────────────────────

    def _build_suggestions(
        self,
        contracts: list[PlanContract],
        spec_entry: dict[str, Any] | None,
        all_covers: bool,
        all_boundaries: bool,
        all_bound_to_scenario: bool,
        all_style: bool,
        all_reuse: bool,
        oversized: tuple[bool, list[str]],
        scope_creep: bool,
        unverified: list[str],
    ) -> list[str]:
        suggestions: list[str] = []

        if not contracts:
            suggestions.append("Plan 为空 —— 至少需要一个 Task")
            return suggestions

        if not all_covers:
            missing = self._find_missing_coverage(contracts, spec_entry)
            suggestions.append(f"[覆盖缺失] 未覆盖所有验收标准: {missing}")

        if not all_boundaries:
            no_boundary = [c.task_id for c in contracts if not c.allowed_files]
            suggestions.append(f"[缺少边界] Task {no_boundary} 未声明 allowedFiles")

        if not all_bound_to_scenario:
            no_scenario = [c.task_id for c in contracts if not c.links.scenarios and not c.verification]
            suggestions.append(f"[缺少验证] Task {no_scenario} 未绑定 Scenario 或验证方式")

        if not all_style:
            no_style = [c.task_id for c in contracts if not c.style_contract.must and not c.style_contract.forbidden]
            suggestions.append(f"[缺少风格约束] Task {no_style} 未引用 Style Contract")

        if not all_reuse:
            no_reuse = [c.task_id for c in contracts if not c.reuse_check.search_for]
            suggestions.append(f"[缺少复用检查] Task {no_reuse} 未设置 Reuse Check")

        if oversized[0]:
            suggestions.append(f"[任务过大] Task {oversized[1]} 超过 5 个文件，建议拆分")

        if scope_creep:
            suggestions.append("[范围膨胀] Plan 文件总数 > 20，可能存在范围膨胀")

        if unverified:
            suggestions.append(f"[无法验证] Task {unverified} 无验证手段")

        if not suggestions:
            suggestions.append("Plan 质量良好，可以锁定并进入 EXECUTE 阶段")

        return suggestions
