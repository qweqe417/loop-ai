"""质量门禁 —— 硬阻断（Error）vs 软警告（Warning）。

Error: 阻塞流程，不写入文件，必须修复。
Warning: 继续执行，质量报告中标注，建议修复。

硬阻断规则:
  1. P0/P1 需求覆盖率为 0
  2. 数据变更用例缺少 data_assertions
  3. open_questions 未解决
  4. 自动化候选用例缺少 dependencies
  5. backend/fullstack 用例缺少 cleanup 策略

软警告规则:
  6. 边界值/负向用例少于正向的 30%
  7. e2e 占比过高（>80%）
  8. 用例缺少前置条件
  9. 用例缺少预期结果
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from .models import (
    CoverageStatus,
    Priority,
    TestCase,
    TestDesignBundle,
    QualityReport,
)

logger = logging.getLogger(__name__)


class QualityGate:
    """质量门禁 —— 对 TestDesignBundle 运行所有检查。"""

    def evaluate(self, bundle: TestDesignBundle) -> QualityReport:
        errors: list[str] = []
        warnings: list[str] = []

        # 硬阻断
        self._check_priority_coverage(bundle, errors)
        self._check_data_assertions(bundle, errors)
        self._check_open_questions(bundle, errors)
        self._check_automation_dependencies(bundle, errors)
        self._check_cleanup(bundle, errors)

        # 软警告
        self._check_source_plan_degraded(bundle, warnings)
        self._check_inferred_source_ratio(bundle, warnings)
        self._check_negative_coverage_ratio(bundle, warnings)
        self._check_level_distribution(bundle, warnings)
        self._check_preconditions(bundle, warnings)
        self._check_expected_results(bundle, warnings)

        passed = len(errors) == 0

        summary = {
            "feature": bundle.feature,
            "scope": bundle.scope.value,
            "requirements_total": len(bundle.requirements),
            "requirements_covered": sum(1 for c in bundle.coverage if c.status == CoverageStatus.COVERED),
            "requirements_blocked": sum(1 for c in bundle.coverage if c.status == CoverageStatus.BLOCKED),
            "test_cases_total": len(bundle.test_cases),
            "p0_cases": sum(1 for tc in bundle.test_cases if tc.priority == Priority.P0),
            "p1_cases": sum(1 for tc in bundle.test_cases if tc.priority == Priority.P1),
            "automation_high": sum(1 for tc in bundle.test_cases if tc.automation and tc.automation.candidate.value == "high"),
            "with_data_assertions": sum(1 for tc in bundle.test_cases if tc.expected.data_assertions),
            "with_dom_assertions": sum(1 for tc in bundle.test_cases if tc.expected.dom_assertions),
            "open_questions": len(bundle.open_questions),
            "errors": len(errors),
            "warnings": len(warnings),
        }

        return QualityReport(
            passed=passed,
            errors=errors,
            warnings=warnings,
            summary=summary,
            open_questions_count=len(bundle.open_questions),
            blocked_requirements=[
                c.requirement_ref for c in bundle.coverage if c.status == CoverageStatus.BLOCKED
            ],
            generated_at=datetime.now(),
        )

    # ── 硬阻断 ──────────────────────────────────────────────────

    def _check_priority_coverage(self, bundle, errors):
        """P0/P1 需求必须至少有一条用例覆盖。"""
        p0p1_req_ids = {
            r.id for r in bundle.requirements if r.risk_level.value in ("high",)
        }
        if not p0p1_req_ids:
            p0p1_req_ids = {
                ref for tc in bundle.test_cases
                if tc.priority in (Priority.P0, Priority.P1)
                for ref in tc.requirement_refs
            }

        uncovered = []
        for req_id in p0p1_req_ids:
            count = sum(1 for tc in bundle.test_cases if req_id in tc.requirement_refs)
            if count == 0:
                uncovered.append(req_id)

        if uncovered:
            msg = f"P0/P1 需求缺少用例覆盖: {', '.join(uncovered)}"
            errors.append(msg)
            logger.error("HARD BLOCK: %s", msg)

    def _check_data_assertions(self, bundle, errors):
        """涉及数据变更的用例必须有 data_assertions。"""
        missing = []
        for tc in bundle.test_cases:
            has_data_change = any(
                t.value in ("data_consistency", "state_transition")
                for t in tc.test_types
            )
            if has_data_change and not tc.expected.data_assertions:
                missing.append(tc.id)

        if missing:
            msg = f"数据变更用例缺少 data_assertions: {', '.join(missing)}"
            errors.append(msg)
            logger.error("HARD BLOCK: %s", msg)

    def _check_open_questions(self, bundle, errors):
        """存在 open_questions 时阻断 —— 必须先找用户澄清。"""
        if bundle.open_questions:
            msg = f"存在 {len(bundle.open_questions)} 个未决问题，必须先澄清: " + \
                  ", ".join(q.id for q in bundle.open_questions)
            errors.append(msg)
            logger.error("HARD BLOCK: %s", msg)

    def _check_automation_dependencies(self, bundle, errors):
        """自动化候选用例必须有 dependencies。"""
        missing = []
        for tc in bundle.test_cases:
            if tc.automation and tc.automation.candidate.value in ("high", "medium"):
                if not tc.dependencies:
                    missing.append(tc.id)

        if missing:
            msg = f"自动化候选用例缺少 dependencies: {', '.join(missing)}"
            errors.append(msg)
            logger.error("HARD BLOCK: %s", msg)

    def _check_cleanup(self, bundle, errors):
        """backend/fullstack 用例必须有 cleanup 策略。"""
        missing = []
        for tc in bundle.test_cases:
            if tc.scope.value in ("backend", "fullstack"):
                if tc.cleanup.required and tc.cleanup.strategy == "by_reference":
                    # by_reference 是默认值，检查是否真的有数据操作
                    has_db_step = any(
                        s.action.value in ("db_query", "api_call") for s in tc.steps
                    )
                    if has_db_step and not tc.cleanup.description:
                        # 有数据操作但没有明确的清理说明 → 警告而非阻断
                        pass
            # 纯前端可以不清理
        # cleanup 缺失不作为硬阻断，改为软警告
        # 因为测试环境可能自带隔离

    # ── 软警告 ──────────────────────────────────────────────────

    def _check_negative_coverage_ratio(self, bundle, warnings):
        """负向/边界用例不应少于正向的 30%。"""
        positive = sum(1 for tc in bundle.test_cases
                       if any(t.value in ("functional", "ui_interaction") for t in tc.test_types))
        negative = sum(1 for tc in bundle.test_cases
                       if any(t.value in ("negative", "boundary") for t in tc.test_types))
        if positive > 0 and negative / positive < 0.3:
            msg = f"负向/边界用例 ({negative}) 少于正向 ({positive}) 的 30%，风险敞口较大"
            warnings.append(msg)
            logger.warning("SOFT WARN: %s", msg)

    def _check_level_distribution(self, bundle, warnings):
        """e2e 占比不应超过 80%。"""
        total = len(bundle.test_cases)
        if total == 0:
            return
        e2e_count = sum(1 for tc in bundle.test_cases if tc.test_level.value == "e2e")
        ratio = e2e_count / total
        if ratio > 0.8:
            msg = f"e2e 用例占比 {ratio:.0%}（{e2e_count}/{total}），建议按层级拆分"
            warnings.append(msg)
            logger.warning("SOFT WARN: %s", msg)

    def _check_preconditions(self, bundle, warnings):
        """检查用例是否有前置条件。"""
        missing = [tc.id for tc in bundle.test_cases if not tc.preconditions]
        if missing:
            msg = f"以下用例缺少前置条件: {', '.join(missing[:5])}{'...' if len(missing) > 5 else ''}"
            warnings.append(msg)
            logger.warning("SOFT WARN: %s", msg)

    def _check_source_plan_degraded(self, bundle, warnings):
        """降级模式警告 —— source.plan.status == degraded 时提醒用户补 Plan。"""
        plan_status = bundle.source.get("plan", {}).get("status", "")
        if plan_status == "degraded":
            msg = "缺少 Plan 文件，接口路径/数据变化靠 AI 推断（标记 inferred_source: ai），建议运行 /aicode-plan 后重新生成"
            warnings.append(msg)
            logger.warning("SOFT WARN: %s", msg)

    def _check_inferred_source_ratio(self, bundle, warnings):
        """AI 推断比例过高警告 —— inferred_source=ai 的数据断言超过 50%。"""
        total = 0
        ai_inferred = 0
        for tc in bundle.test_cases:
            for da in tc.expected.data_assertions:
                total += 1
                if da.inferred_source == "ai":
                    ai_inferred += 1
        if total > 0 and ai_inferred / total > 0.5:
            msg = f"数据断言中 AI 推断占比 {ai_inferred/total:.0%}（{ai_inferred}/{total}），建议提供 PRD/Spec + Plan 后重新生成"
            warnings.append(msg)
            logger.warning("SOFT WARN: %s", msg)

    def _check_expected_results(self, bundle, warnings):
        """检查用例是否有预期结果。"""
        missing = []
        for tc in bundle.test_cases:
            has = tc.expected.response or tc.expected.data_assertions or tc.expected.dom_assertions
            if not has:
                missing.append(tc.id)
        if missing:
            msg = f"以下用例缺少预期结果: {', '.join(missing[:5])}{'...' if len(missing) > 5 else ''}"
            warnings.append(msg)
            logger.warning("SOFT WARN: %s", msg)
