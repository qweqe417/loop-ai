"""ReviewEngine —— 编排 Layer1 (Python 规则) + Layer2 (AI 审查 prompt)。

用法:
    engine = create_review_engine()
    result = engine.check(state)             # 跑 4 条 Python 规则
    prompt = engine.build_ai_review_prompt(state, diff_text, result)  # 组装 AI 审查 prompt
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .models import ReviewResult, ReviewSeverity
from .rules import (
    ReviewRule,
    ScopeBoundaryRule,
    SecretScanRule,
    SkipDetectionRule,
    TestIntegrityRule,
)

if TYPE_CHECKING:
    from engines.state.models import RunState

logger = logging.getLogger(__name__)

# 默认规则集
DEFAULT_RULES: tuple[type[ReviewRule], ...] = (
    SecretScanRule,
    TestIntegrityRule,
    ScopeBoundaryRule,
    SkipDetectionRule,
)


class ReviewEngine:
    """审查引擎 —— 规则注册 + 批量检查 + AI review prompt 构造。

    用法:
        engine = ReviewEngine()
        engine.add_rule(MyCustomRule())
        result = engine.check(state)
        if result.block:
            print(f"Blocked: {result.reason}")

    扩展:
        from engines.review import create_review_engine, ReviewRule

        class MyRule(ReviewRule):
            name = "my-rule"
            severity = ReviewSeverity.WARN
            def check(self, state):
                ...

        engine = create_review_engine(extra_rules=[MyRule()])
    """

    def __init__(self, rules: list[ReviewRule] | None = None) -> None:
        self._rules: list[ReviewRule] = rules or self._create_defaults()

    # ── 规则管理 ──────────────────────────────────────────────

    def add_rule(self, rule: ReviewRule) -> None:
        self._rules.append(rule)
        logger.debug("Review rule added: %s", rule)

    def remove_rule(self, name: str) -> bool:
        before = len(self._rules)
        self._rules = [r for r in self._rules if r.name != name]
        return len(self._rules) < before

    @property
    def rules(self) -> list[ReviewRule]:
        return list(self._rules)

    # ── Layer 1: Python 规则检查 ──────────────────────────────

    def check(self, state: RunState) -> ReviewResult:
        """逐条执行所有规则，返回聚合结果。

        有一条 BLOCK 且未通过 → 最终 block=True。
        WARN 收集但不阻断。
        """
        results: list[ReviewResult] = []
        blocked = False

        for rule in self._rules:
            try:
                result = rule.check(state)
                results.append(result)
                if result.block:
                    blocked = True
                    logger.warning("Review BLOCKED by %s: %s", rule.name, result.reason)
                elif result.severity == ReviewSeverity.WARN:
                    logger.info("Review WARN from %s: %s", rule.name, result.reason)
                else:
                    logger.debug("Review PASS: %s", rule.name)
            except Exception as exc:
                logger.exception("Review rule %s raised exception", rule.name)
                results.append(
                    ReviewResult.blocked(rule.name, f"规则执行异常: {exc}", exception=str(exc))
                )
                blocked = True

        return self._aggregate(results, blocked)

    # ── Layer 2: AI 审查 prompt 构造 ──────────────────────────

    def build_ai_review_prompt(
        self,
        state: RunState,
        diff_text: str,
        layer1_result: ReviewResult,
    ) -> str:
        """基于 Layer1 结果 + git diff + Plan 合约 + Memory 构造 AI 审查 prompt。"""

        parts: list[str] = [
            "## 代码审查",
            "",
            "请逐文件审查以下 git diff，从以下维度判断：",
            "",
            "1. **逻辑正确性** — 实现是否符合 Plan 预期？有没有明显的逻辑错误？",
            "2. **安全性** — 有没有注入风险、越权、敏感数据泄露？",
            "3. **破坏性变更** — 是否修改了现有接口签名？会不会影响调用方？",
            "4. **性能** — 有没有 N+1 查询、不必要的循环、阻塞 I/O？",
            "5. **错误处理** — 异常是否正确处理？有没有吞掉关键错误？",
            "6. **不必要的抽象** — 有没有为单一用途引入的过度抽象？",
            "",
        ]

        # Layer1 结果摘要
        layer1_results = layer1_result.details.get("results", [])
        failed = [r for r in layer1_results if not r.get("passed")]
        warnings_list = [r for r in layer1_results if r.get("severity") == "warn"]

        if failed:
            parts.append("## 阻断项（必须先修复）")
            for r in failed:
                parts.append(f"- [{r['rule']}] {r['reason']}")
            parts.append("")

        if warnings_list:
            parts.append("## 需要解释/修复的警告")
            for r in warnings_list:
                parts.append(f"- [{r['rule']}] {r['reason']}")
            parts.append("")

        # Plan 合约摘要
        contracts = state.plan_contracts
        if contracts:
            parts.append("## Plan 合约")
            for c in contracts:
                task_id = c.get("task_id", "?")
                allowed = c.get("allowed_files", [])
                parts.append(f"- **{task_id}**: allowed_files={allowed}")
            parts.append("")

        # Git diff
        if diff_text:
            max_diff = 8000
            truncated = diff_text[:max_diff]
            parts.append("## Git Diff")
            parts.append("```diff")
            parts.append(truncated)
            if len(diff_text) > max_diff:
                parts.append(f"... (truncated, {len(diff_text)} chars total)")
            parts.append("```")
            parts.append("")

        # 输出格式要求
        parts.extend([
            "## 输出格式",
            "返回 JSON:",
            "```json",
            "{",
            '  "passed": true/false,',
            '  "violations": [{"file": "...", "severity": "BLOCK|WARN", "description": "...", "fix_suggestion": "..."}],',
            '  "summary": "一句话总结"',
            "}",
            "```",
        ])

        return "\n".join(parts)

    # ── 内部 ──────────────────────────────────────────────────

    def _aggregate(self, results: list[ReviewResult], blocked: bool) -> ReviewResult:
        if not results:
            return ReviewResult.ok("review", "无规则注册")

        parts = [f"[{r.rule_name}] {r.reason}" for r in results]
        details = {
            "total_rules": len(results),
            "passed": sum(1 for r in results if r.passed),
            "blocked_count": sum(1 for r in results if r.block),
            "results": [
                {"rule": r.rule_name, "severity": r.severity.value, "passed": r.passed, "reason": r.reason}
                for r in results
            ],
        }

        if blocked:
            return ReviewResult(
                rule_name="review", severity=ReviewSeverity.BLOCK,
                passed=False, block=True, reason="\n".join(parts), details=details,
            )
        return ReviewResult(
            rule_name="review", severity=ReviewSeverity.PASS,
            passed=True, block=False, reason="\n".join(parts), details=details,
        )

    @staticmethod
    def _create_defaults() -> list[ReviewRule]:
        return [cls() for cls in DEFAULT_RULES]


# ── 便捷工厂 ──────────────────────────────────────────────────────

def create_review_engine(extra_rules: list[ReviewRule] | None = None) -> ReviewEngine:
    """创建 ReviewEngine —— 自动注册 4 条默认规则。"""
    rules = ReviewEngine._create_defaults()
    if extra_rules:
        rules.extend(extra_rules)
    return ReviewEngine(rules=rules)
