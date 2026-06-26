"""ReviewEngine —— Layer1 机械规则引擎。

只做 Python 确定性检测，供 GateHandler 使用。
Layer2 AI 语义审查由 SDD code-reviewer subagent 完成。

用法:
    engine = ReviewEngine()
    results = engine.run_layer1(state)
    blocked = any(r.block for r in results)
"""

# 启用延迟注解求值
from __future__ import annotations

# 导入 logging 库，用于日志记录
import logging
# 导入 TYPE_CHECKING，用于类型检查时避免循环导入
from typing import TYPE_CHECKING

# 导入审查结果模型
from .models import ReviewResult
# 导入所有内置审查规则
from .rules import (
    AssertionDeletionRule,
    DiffBudgetRule,
    LintIntegrationRule,
    ReviewRule,
    ScopeBoundaryRule,
    SecretScanRule,
    SkipDetectionRule,
    TestIntegrityRule,
)

# 仅在类型检查时导入，避免运行时循环导入
if TYPE_CHECKING:
    from engines.state.models import RunState

# 创建当前模块的日志记录器
logger = logging.getLogger(__name__)


class ReviewEngine:
    """Layer1 机械规则引擎。

    运行 7 条 Python 确定性检测规则，供 GateHandler 使用。
    支持通过 extra_rules 注入自定义规则，disabled_rules 禁用规则。
    """

    # ── 内置规则列表 ─────────────────────────────────
    # 所有内置规则，按注册顺序执行
    _BUILTIN_RULES: list[type[ReviewRule]] = [
        SecretScanRule,          # 硬编码凭证扫描
        ScopeBoundaryRule,       # Plan 越界检查
        TestIntegrityRule,       # 测试完整性
        SkipDetectionRule,       # Skip 标记检测
        AssertionDeletionRule,   # 断言删除检测
        DiffBudgetRule,          # 变更预算检查
        LintIntegrationRule,     # Lint 集成
    ]

    def __init__(
        self,
        extra_rules: list[ReviewRule] | None = None,
        disabled_rules: list[str] | None = None,
    ) -> None:
        # 额外规则列表（下游项目注入）
        self._extra_rules: list[ReviewRule] = extra_rules or []
        # 禁用的规则名称集合
        self._disabled_rules: set[str] = set(disabled_rules or [])

    def run_layer1(self, state: RunState) -> list[ReviewResult]:
        """仅运行 Layer1 确定性规则（供外部独立调用）。

        Args:
            state: 运行状态

        Returns:
            审查结果列表
        """
        return self._run_layer1(state)

    # ── Layer1 实现 ───────────────────────────────────

    def _run_layer1(self, state: RunState) -> list[ReviewResult]:
        """运行 Layer1 确定性规则。

        依次执行内置规则和额外规则，跳过禁用的规则。

        Args:
            state: 运行状态

        Returns:
            审查结果列表
        """
        results: list[ReviewResult] = []

        # 实例化并执行内置规则
        for rule_cls in self._BUILTIN_RULES:
            rule = rule_cls()
            # 跳过被禁用的规则
            if rule.name in self._disabled_rules:
                logger.info("Layer1: skipping disabled rule %s", rule.name)
                continue
            try:
                # 执行规则检查
                result = rule.check(state)
                results.append(result)
                # 记录结果等级
                logger.info(
                    "Layer1: %s → %s",
                    rule.name,
                    result.severity.value.upper() if not result.passed else "PASS",
                )
            except Exception as e:
                # 规则执行异常时转为 WARN 结果
                logger.exception("Layer1 rule %s failed with exception", rule.name)
                results.append(ReviewResult.warn(
                    rule.name,
                    f"规则执行异常: {e}",
                ))

        # 执行额外规则（下游项目注入）
        for rule in self._extra_rules:
            if rule.name in self._disabled_rules:
                continue
            try:
                result = rule.check(state)
                results.append(result)
            except Exception as e:
                logger.exception("Extra rule %s failed", rule.name)
                results.append(ReviewResult.warn(
                    rule.name,
                    f"额外规则执行异常: {e}",
                ))

        return results


# ── 便捷工厂函数 ──────────────────────────────────────

def create_review_engine(
    extra_rules: list[ReviewRule] | None = None,
    disabled_rules: list[str] | None = None,
) -> ReviewEngine:
    """创建 ReviewEngine 实例的便捷工厂函数。

    Args:
        extra_rules: 额外规则列表
        disabled_rules: 禁用的规则名称列表

    Returns:
        ReviewEngine 实例
    """
    return ReviewEngine(extra_rules=extra_rules, disabled_rules=disabled_rules)