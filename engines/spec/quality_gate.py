"""Spec 质量门禁。

检测 Spec 内容中的:
- 模糊词 (fuzzy words): 尽量、可能、应该、maybe、probably 等
- 缺失必填字段
- 可量化程度

输出 SpecQualityReport，决定是否放行到 PLAN 阶段。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .models import FuzzyWord, SpecEntry, SpecQualityReport, SpecSection

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ── 模糊词库 ──────────────────────────────────────────────────────

FUZZY_WORDS_CN: dict[str, str] = {
    "尽量":   "明确定义具体行为",
    "可能":   "明确条件或概率",
    "大概":   "给出精确数值",
    "应该":   "明确判定规则",
    "也许":   "明确是否必须",
    "差不多": "给出精确范围",
    "基本上": "明确边界条件",
    "一般而言": "明确具体场景",
    "酌情":   "定义决策标准",
    "适当":   "给出具体数值或比例",
    "相关":   "指明具体对象",
}

FUZZY_WORDS_EN: dict[str, str] = {
    "maybe":    "Use 'must' or 'will' for definite behavior",
    "probably": "Specify the exact condition or probability",
    "should":   "Use 'must' or 'shall' for requirements",
    "could":    "Use 'must' or 'will' for required behavior",
    "might":    "Define exact conditions",
    "approximately": "Give exact value or acceptable range",
    "about":    "Specify precise value or range",
    "roughly":  "Give exact number or tolerance",
    "generally": "Define specific cases",
    "usually":  "Specify exact behavior",
}

ALL_FUZZY = {**FUZZY_WORDS_CN, **FUZZY_WORDS_EN}

# 必填字段及权重
REQUIRED_SECTIONS: dict[str, float] = {
    SpecSection.GOAL.value:               25.0,
    SpecSection.NON_GOALS.value:         10.0,
    SpecSection.ACCEPTANCE_CRITERIA.value: 25.0,
    SpecSection.TEST_SCENARIOS.value:     15.0,
    SpecSection.RISK_LEVEL.value:         10.0,
    SpecSection.BUSINESS_RULES.value:     10.0,
    SpecSection.OPEN_QUESTIONS.value:      5.0,
}


class SpecQualityGate:
    """Spec 质量门禁 —— 在 SPEC→PLAN 流转前执行。

    用法:
        gate = SpecQualityGate()
        spec = SpecEntry(goal="...", acceptance_criteria=["..."])
        report = gate.evaluate(spec)
        if report.passed:
            proceed_to_plan()
    """

    def __init__(self, threshold: float = 70.0) -> None:
        self.threshold = threshold

    # ── 评估入口 ───────────────────────────────────────────────

    def evaluate(self, spec: SpecEntry) -> SpecQualityReport:
        """对 Spec 执行质量检查，返回报告。"""
        fuzzy_words = self._detect_fuzzy(spec)
        missing = self._check_completeness(spec)

        clarity_score = self._calc_clarity(fuzzy_words)
        completeness_score = self._calc_completeness(missing)
        score = round((clarity_score + completeness_score) / 2, 1)

        suggestions = self._build_suggestions(fuzzy_words, missing)

        return SpecQualityReport(
            score=score,
            passed=score >= self.threshold,
            fuzzy_words=fuzzy_words,
            missing_sections=missing,
            completeness_score=completeness_score,
            clarity_score=clarity_score,
            suggestions=suggestions,
            threshold=self.threshold,
        )

    # ── 模糊词检测 ─────────────────────────────────────────────

    def _detect_fuzzy(self, spec: SpecEntry) -> list[FuzzyWord]:
        """在所有文本字段中检测模糊词。"""
        found: list[FuzzyWord] = []
        seen: set[str] = set()

        # 合并所有文本
        texts = [
            spec.goal,
            " ".join(spec.non_goals),
            " ".join(spec.acceptance_criteria),
            " ".join(spec.test_scenarios),
            " ".join(spec.business_rules),
            " ".join(spec.open_questions),
        ]
        combined = " ".join(texts)

        for word, suggestion in ALL_FUZZY.items():
            if word in combined and word not in seen:
                seen.add(word)
                # 提取上下文
                idx = combined.find(word)
                start = max(0, idx - 25)
                end = min(len(combined), idx + len(word) + 25)
                context = combined[start:end]

                found.append(FuzzyWord(
                    word=word,
                    context=context,
                    suggestion=suggestion,
                ))

        return found

    # ── 完整性检查 ─────────────────────────────────────────────

    def _check_completeness(self, spec: SpecEntry) -> list[str]:
        """检查必填字段是否为空。"""
        missing: list[str] = []

        if not spec.goal.strip():
            missing.append(SpecSection.GOAL.value)
        if not spec.non_goals:
            missing.append(SpecSection.NON_GOALS.value)
        if not spec.acceptance_criteria:
            missing.append(SpecSection.ACCEPTANCE_CRITERIA.value)
        if not spec.test_scenarios:
            missing.append(SpecSection.TEST_SCENARIOS.value)
        if not spec.risk_level:
            missing.append(SpecSection.RISK_LEVEL.value)
        if not spec.business_rules:
            missing.append(SpecSection.BUSINESS_RULES.value)

        return missing

    def _calc_completeness(self, missing: list[str]) -> float:
        """计算完整性分数。"""
        if not REQUIRED_SECTIONS:
            return 100.0
        deducted = sum(
            REQUIRED_SECTIONS.get(m, 0) for m in missing
        )
        return max(0.0, 100.0 - deducted)

    def _calc_clarity(self, fuzzy_words: list[FuzzyWord]) -> float:
        """计算清晰度分数（模糊词越少越高）。"""
        if not fuzzy_words:
            return 100.0
        # 每个模糊词扣 8 分，保底 0
        return max(0.0, 100.0 - len(fuzzy_words) * 8.0)

    # ── 建议生成 ───────────────────────────────────────────────

    def _build_suggestions(
        self, fuzzy_words: list[FuzzyWord], missing: list[str]
    ) -> list[str]:
        suggestions: list[str] = []

        for fw in fuzzy_words[:5]:
            suggestions.append(
                f"[模糊词] \"{fw.word}\" → {fw.suggestion}"
            )

        for section in missing:
            display = {
                "goal": "目标 (goal)",
                "non_goals": "非目标 (non_goals)",
                "acceptance_criteria": "验收标准 (acceptance_criteria)",
                "test_scenarios": "测试场景 (test_scenarios)",
                "risk_level": "风险等级 (risk_level)",
                "business_rules": "业务规则 (business_rules)",
            }.get(section, section)
            suggestions.append(f"[缺失] 必填字段: {display}")

        if not suggestions:
            suggestions.append("Spec 质量良好，可以进入 PLAN 阶段")

        return suggestions
