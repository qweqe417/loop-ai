"""Code Quality Gate / Elegance Review（架构 §8.7.11）。

代码写完后不只看能不能跑，还要检查代码质量。
Python 定义检查维度，AI 逐项自评并提交结构化结果，
Python 做阈值判断和违规统计。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class CodeQualityCheck:
    """单项质量检查结果。"""

    dimension: str
    passed: bool
    score: int  # 0-10
    detail: str = ""
    evidence: list[str] = field(default_factory=list)


@dataclass
class CodeQualityReport:
    """代码质量综合报告。"""

    checks: list[CodeQualityCheck] = field(default_factory=list)
    total_score: int = 0
    max_score: int = 0
    passed: bool = False
    critical_violations: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if not self.checks:
            return "Code Quality: 未检查"
        pct = round(self.total_score / self.max_score * 100, 1) if self.max_score else 0
        status = "✅ 通过" if self.passed else "❌ 未通过"
        return f"Code Quality: {self.total_score}/{self.max_score} ({pct}%) {status}"


class CodeQualityGate:
    """代码质量门禁（架构 §8.7.11）。

    检查维度（对应架构 §8.7.11）:
    1. 简洁性 — 是否简洁，不冗余
    2. 模式复用 — 是否复用已有模式
    3. 无重复 — 是否没有重复逻辑
    4. 无无用抽象 — 是否没有不必要的抽象层
    5. 无未使用代码 — 是否没有死代码
    6. 无过度封装 — 是否没有过度包装
    7. 分层合规 — 是否遵守项目分层
    8. 可读性 — 命名清晰，边界清楚
    9. 错误处理 — 是否一致
    10. 新依赖 — 是否引入不必要依赖

    用法:
        gate = CodeQualityGate()
        report = gate.evaluate(ai_assessment)
        if not report.passed:
            print(report.suggestions)
    """

    # 检查维度定义（架构 §8.7.11 的 10 项）
    DIMENSIONS = [
        ("simplicity", "简洁性", "是否简洁，没有不必要代码", 10),
        ("pattern_reuse", "模式复用", "是否复用了项目已有模式", 8),
        ("no_duplication", "无重复逻辑", "是否没有重复代码", 10),
        ("no_useless_abstraction", "无无用抽象", "是否没有不必要的抽象层", 8),
        ("no_dead_code", "无未使用代码", "是否没有注释掉的代码或死代码", 6),
        ("no_over_encapsulation", "无过度封装", "是否没有过度包装", 6),
        ("layering", "分层合规", "Controller/Service/Repository 分层是否正确", 10),
        ("readability", "可读性", "命名清晰，边界清楚", 8),
        ("error_handling", "错误处理", "错误处理是否与项目一致", 8),
        ("no_new_deps", "无新依赖", "是否引入不必要的依赖", 6),
    ]

    # 通过阈值
    PASS_THRESHOLD = 0.7  # 总分 70% 以上通过

    def evaluate(self, assessment: dict) -> CodeQualityReport:
        """根据 AI 自评结果生成质量报告。

        Args:
            assessment: AI 提交的自评结果，格式:
                {
                    "simplicity": {"score": 8, "detail": "...", "evidence": [...]},
                    "pattern_reuse": {"score": 7, ...},
                    ...
                }

        Returns:
            CodeQualityReport
        """
        checks: list[CodeQualityCheck] = []
        total = 0
        max_total = 0
        critical: list[str] = []
        suggestions: list[str] = []

        for dim_key, dim_name, dim_desc, max_score in self.DIMENSIONS:
            dim_data = assessment.get(dim_key, {})
            if isinstance(dim_data, (int, float)):
                score = int(dim_data)
                detail = ""
                evidence = []
            elif isinstance(dim_data, dict):
                score = int(dim_data.get("score", 0))
                detail = dim_data.get("detail", "")
                evidence = dim_data.get("evidence", [])
            else:
                score = 0
                detail = f"未评估: {dim_desc}"
                evidence = []

            passed = score >= max_score * 0.6  # 单项 60% 即为通过
            check = CodeQualityCheck(
                dimension=dim_name,
                passed=passed,
                score=score,
                detail=detail or dim_desc,
                evidence=evidence,
            )
            checks.append(check)
            total += score
            max_total += max_score

            if not passed:
                suggestions.append(f"[{dim_name}] {detail or dim_desc} (score={score}/{max_score})")
            if score <= 3:
                critical.append(dim_name)

        overall_passed = (total / max_total) >= self.PASS_THRESHOLD if max_total else False

        if critical:
            suggestions.insert(0, f"严重违规: {', '.join(critical)}")

        report = CodeQualityReport(
            checks=checks,
            total_score=total,
            max_score=max_total,
            passed=overall_passed,
            critical_violations=critical,
            suggestions=suggestions,
        )

        logger.info(
            "CodeQualityGate: score=%d/%d passed=%s critical=%d",
            total, max_total, overall_passed, len(critical),
        )
        return report

    def render_prompt(self) -> str:
        """生成 AI 自评用的 prompt 模板。"""
        lines = [
            "## Code Quality Gate / Elegance Review",
            "",
            "请对本次修改逐项自评（每项 0-10 分，附简要说明）:",
            "",
        ]
        for dim_key, dim_name, dim_desc, max_score in self.DIMENSIONS:
            lines.append(f"- **{dim_name}** ({dim_key}, max={max_score}): {dim_desc}")
        lines.extend([
            "",
            "输出格式:",
            "{",
            '  "simplicity": {"score": 8, "detail": "...", "evidence": ["file:line"]},',
            '  "pattern_reuse": {"score": 7, "detail": "...", "evidence": [...]},',
            "  ...",
            "}",
            "",
            "检查原则: 少即是多、贴合项目风格、没有过度设计、没有重复、命名清晰、边界清楚。",
        ])
        return "\n".join(lines)
