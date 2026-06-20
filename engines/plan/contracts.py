"""Plan 合约验证与合规检查。

Plan → accept → EXECUTE → verify compliance → REVIEW
"""

from __future__ import annotations

import fnmatch
import logging
from typing import TYPE_CHECKING

from .models import (
    DiffBudget,
    PlanChangeRequest,
    PlanComplianceReport,
    PlanContract,
    PlanLockState,
)

if TYPE_CHECKING:
    from engines.state.models import RunState

logger = logging.getLogger(__name__)


class ContractValidator:
    """Plan 合约验证器。

    用法:
        validator = ContractValidator()
        contract = PlanContract(allowed_files=["src/*.py"], budget=DiffBudget(max_files=3))
        report = validator.validate(contract, changed_files=["src/app.py"])
    """

    def validate(
        self,
        contract: PlanContract,
        changed_files: list[str],
        lines_changed: int = 0,
    ) -> PlanComplianceReport:
        """验证变更是否符合 Plan 合约。

        Args:
            contract: Plan 执行合约
            changed_files: 实际变更的文件列表
            lines_changed: 实际变更的行数
        """
        violations: list[str] = []
        files_out_of_scope: list[str] = []

        # 1. 检查禁止文件
        for f in changed_files:
            for forbidden in contract.forbidden_files:
                if fnmatch.fnmatch(f, forbidden):
                    violations.append(f"修改了禁止文件: {f} (规则: {forbidden})")
                    files_out_of_scope.append(f)

        # 2. 检查是否在允许范围内
        if contract.allowed_files:
            for f in changed_files:
                if not any(
                    fnmatch.fnmatch(f, allowed)
                    for allowed in contract.allowed_files
                ):
                    violations.append(f"文件超出授权范围: {f}")
                    files_out_of_scope.append(f)

        # 3. 检查 Diff Budget
        budget = contract.budget
        actual_files = len(changed_files)
        budget.files_changed = actual_files
        budget.lines_changed = lines_changed

        if actual_files > budget.max_files:
            violations.append(
                f"文件数超预算: {actual_files} > {budget.max_files}"
            )
        if lines_changed > budget.max_lines:
            violations.append(
                f"行数超预算: {lines_changed} > {budget.max_lines}"
            )

        # 4. 预算状态
        if budget.exceeded:
            budget_status = "EXCEEDED"
        elif budget.file_budget_remaining <= 1 or budget.line_budget_remaining <= 20:
            budget_status = "WARN"
        else:
            budget_status = "OK"

        suggestions: list[str] = []
        if files_out_of_scope:
            suggestions.append(
                f"越权文件 {files_out_of_scope} — 提交 PlanChangeRequest 或回滚变更"
            )
        if budget.file_budget_exceeded:
            suggestions.append(
                f"文件数超出预算 {budget.max_files} — 拆分为多个 task"
            )
        if budget.line_budget_exceeded:
            suggestions.append(
                f"行数超出预算 {budget.max_lines} — 简化实现或拆 task"
            )

        return PlanComplianceReport(
            contract_id=contract.task_id,
            compliant=len(violations) == 0,
            violations=violations,
            budget_status=budget_status,
            files_out_of_scope=files_out_of_scope,
            suggestions=suggestions,
        )

    def evaluate_change_request(
        self,
        contract: PlanContract,
        request: PlanChangeRequest,
    ) -> bool:
        """评估 Plan 变更请求是否可以批准。

        自动批准条件:
        - 预算不超原始合同 2x
        - 不触及 forbidden_files
        """
        # 检查预算
        new_budget = contract.budget.max_files + request.budget_delta
        if new_budget > contract.budget.max_files * 2:
            logger.warning(
                "变更请求预算超限: %d > %d",
                new_budget, contract.budget.max_files * 2,
            )
            return False

        # 检查禁止文件
        for f in request.affected_files:
            for forbidden in contract.forbidden_files:
                if fnmatch.fnmatch(f, forbidden):
                    logger.warning("变更请求触及禁止文件: %s", f)
                    return False

        return True

    @staticmethod
    def build_default_contract(
        task_id: str = "",
        complexity: str = "medium",
    ) -> PlanContract:
        """根据复杂度构建默认执行合约。"""
        if complexity == "low":
            budget = DiffBudget(max_files=3, max_lines=100)
        elif complexity == "medium":
            budget = DiffBudget(max_files=5, max_lines=300)
        else:
            budget = DiffBudget(max_files=8, max_lines=600)

        return PlanContract(
            task_id=task_id,
            budget=budget,
            verification=["lint"] if complexity == "low" else ["lint", "test"],
            done_when="所有验证通过且场景断言全部通过",
        )
