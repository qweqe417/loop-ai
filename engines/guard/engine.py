"""Guard 引擎。

注册 Guard 规则 → 逐条检查 → 聚合成最终结果。
与 LoopRunner 集成，每个阶段前自动执行。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .models import GuardResult, GuardSeverity
from .rules import (
    GuardRule,
    RiskLevelRule,
    SanityCheckRule,
    ScopeBoundaryRule,
)

if TYPE_CHECKING:
    from engines.state.models import RunState

logger = logging.getLogger(__name__)

# 默认规则集
DEFAULT_RULES: tuple[type[GuardRule], ...] = (
    SanityCheckRule,
    RiskLevelRule,
    ScopeBoundaryRule,
)


class Guard:
    """Guard 引擎 —— 规则注册 + 批量检查。

    用法:
        guard = Guard()
        guard.add_rule(ScopeBoundaryRule(allowed_paths=["src/", "tests/"]))
        result = guard.check(state)
        if result.block:
            print(f"Blocked: {result.reason}")
    """

    def __init__(self, rules: list[GuardRule] | None = None) -> None:
        self._rules: list[GuardRule] = rules or self._create_defaults()

    # ── 规则管理 ──────────────────────────────────────────────

    def add_rule(self, rule: GuardRule) -> None:
        """添加一条规则。"""
        self._rules.append(rule)
        logger.debug("Guard rule added: %s", rule)

    def remove_rule(self, name: str) -> bool:
        """按名称移除规则，返回是否找到。"""
        before = len(self._rules)
        self._rules = [r for r in self._rules if r.name != name]
        removed = before - len(self._rules)
        if removed:
            logger.debug("Guard rule removed: %s (%d instances)", name, removed)
        return removed > 0

    @property
    def rules(self) -> list[GuardRule]:
        """返回当前注册的规则列表（只读副本）。"""
        return list(self._rules)

    # ── 检查入口 ──────────────────────────────────────────────

    def check(self, state: RunState) -> GuardResult:
        """逐条执行所有规则，返回聚合结果。

        策略：
        - 收集所有规则的检查结果
        - 只要有一条 BLOCK 且未通过 → 最终 block=True
        - 汇总所有 reason，拼成最终消息
        """
        results: list[GuardResult] = []
        blocked = False
        warnings: list[str] = []

        for rule in self._rules:
            try:
                result = rule.check(state)
                results.append(result)

                if result.block:
                    blocked = True
                    logger.warning("Guard BLOCKED by %s: %s", rule.name, result.reason)
                elif result.severity == GuardSeverity.WARN:
                    warnings.append(f"[{rule.name}] {result.reason}")
                    logger.info("Guard WARN from %s: %s", rule.name, result.reason)
                else:
                    logger.debug("Guard PASS: %s", rule.name)

            except Exception as exc:
                logger.exception("Guard rule %s raised exception", rule.name)
                # 规则自身异常 → 当作 BLOCK 处理（安全侧）
                results.append(
                    GuardResult.blocked(
                        rule.name,
                        f"规则执行异常: {exc}",
                        exception=str(exc),
                    )
                )
                blocked = True

        # 聚合
        return self._aggregate(results, blocked)

    # ── 内部方法 ──────────────────────────────────────────────

    def _aggregate(
        self, results: list[GuardResult], blocked: bool
    ) -> GuardResult:
        """聚合所有规则结果为一个 GuardResult。"""
        if not results:
            return GuardResult.ok("guard", "无规则注册")

        # 收集所有 reason
        parts: list[str] = []
        for r in results:
            parts.append(f"[{r.rule_name}] {r.reason}")

        # 收集详情
        details: dict = {
            "total_rules": len(results),
            "passed": sum(1 for r in results if r.passed),
            "blocked_count": sum(1 for r in results if r.block),
            "results": [
                {
                    "rule": r.rule_name,
                    "severity": r.severity.value,
                    "passed": r.passed,
                    "reason": r.reason,
                }
                for r in results
            ],
        }

        if blocked:
            return GuardResult(
                rule_name="guard",
                severity=GuardSeverity.BLOCK,
                passed=False,
                block=True,
                reason="\n".join(parts),
                details=details,
            )
        else:
            return GuardResult(
                rule_name="guard",
                severity=GuardSeverity.PASS,
                passed=True,
                block=False,
                reason="\n".join(parts),
                details=details,
            )

    @staticmethod
    def _create_defaults() -> list[GuardRule]:
        """创建默认规则集。"""
        return [
            SanityCheckRule(),
            RiskLevelRule(),
            ScopeBoundaryRule(),
        ]


# ── 便捷工厂 ──────────────────────────────────────────────────────

def create_guard(
    allowed_paths: list[str] | None = None,
    extra_rules: list[GuardRule] | None = None,
) -> Guard:
    """创建 Guard 实例的便捷方法。

    Args:
        allowed_paths: 授权路径白名单（ScopeBoundaryRule 使用）
        extra_rules: 额外的自定义规则
    """
    rules: list[GuardRule] = [
        SanityCheckRule(),
        RiskLevelRule(),
        ScopeBoundaryRule(allowed_paths=allowed_paths),
    ]
    if extra_rules:
        rules.extend(extra_rules)
    return Guard(rules=rules)
