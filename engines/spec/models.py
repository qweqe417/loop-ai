"""Spec 质量门禁数据模型。"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class FuzzyWord(BaseModel):
    """模糊词检测结果。"""

    word: str = Field(description="模糊词")
    context: str = Field(default="", description="所在上下文（周围 50 字符）")
    suggestion: str = Field(default="", description="替换建议")


class SpecSection(str, Enum):
    """Spec 必填字段。"""

    GOAL = "goal"
    NON_GOALS = "non_goals"
    ACCEPTANCE_CRITERIA = "acceptance_criteria"
    TEST_SCENARIOS = "test_scenarios"
    RISK_LEVEL = "risk_level"
    BUSINESS_RULES = "business_rules"
    OPEN_QUESTIONS = "open_questions"


class SpecQualityReport(BaseModel):
    """Spec 质量报告。"""

    score: float = Field(default=0.0, description="质量分数 0-100")
    passed: bool = Field(default=False, description="是否通过门禁")
    fuzzy_words: list[FuzzyWord] = Field(default_factory=list)
    missing_sections: list[str] = Field(default_factory=list)
    completeness_score: float = Field(default=0.0, description="完整性分数 0-100")
    clarity_score: float = Field(default=0.0, description="清晰度分数 0-100")
    suggestions: list[str] = Field(default_factory=list, description="改进建议")
    threshold: float = Field(default=70.0, description="通过阈值")


class SpecEntry(BaseModel):
    """Spec 条目 —— 质量门禁的输入。"""

    goal: str = Field(default="", description="目标描述")
    non_goals: list[str] = Field(default_factory=list, description="非目标")
    acceptance_criteria: list[str] = Field(default_factory=list, description="验收标准")
    test_scenarios: list[str] = Field(default_factory=list, description="测试场景")
    risk_level: str = Field(default="", description="风险等级 L1-L5")
    business_rules: list[str] = Field(default_factory=list, description="业务规则")
    open_questions: list[str] = Field(default_factory=list, description="开放问题")
    # 按需字段 (架构 §11.2)
    api_changes: list[str] = Field(default_factory=list, description="接口变化")
    data_changes: list[str] = Field(default_factory=list, description="数据变化")
    cache_changes: list[str] = Field(default_factory=list, description="缓存变化")
    message_changes: list[str] = Field(default_factory=list, description="消息变化")
    permission_rules: list[str] = Field(default_factory=list, description="权限规则")
    config_changes: list[str] = Field(default_factory=list, description="配置变化")
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Spec Context Packet (架构 §8.5.3) ──────────────────────────

class ImpactDomain(BaseModel):
    """影响域判断。"""
    api: bool = Field(default=False, description="是否影响 API 接口")
    database: bool = Field(default=False, description="是否影响数据库")
    cache: bool = Field(default=False, description="是否影响缓存")
    message_queue: bool = Field(default=False, description="是否影响消息队列")
    permission: bool = Field(default=False, description="是否影响权限")
    config: bool = Field(default=False, description="是否影响配置")
    external_service: bool = Field(default=False, description="是否影响外部服务")


class SpecContextPacket(BaseModel):
    """Spec 生成上下文包 —— 在调用 Superpowers/Provider 前构造。

    架构 §8.5.3: 提供足够但不过量的上下文。
    不应该包含: 全量代码、完整历史 runs、无关 Memory、大量日志。
    """

    user_input: str = Field(default="", description="用户原始需求")
    task_intake: dict[str, Any] = Field(default_factory=dict, description="TaskIntakeResult 摘要")
    project_summary: str = Field(default="", description="项目一句话说明")
    relevant_modules: list[str] = Field(default_factory=list, description="相关模块名")
    domain_terms: list[str] = Field(default_factory=list, description="相关业务术语")
    relevant_memory: list[str] = Field(default_factory=list, description="相关历史 Memory 条目")
    existing_apis: list[str] = Field(default_factory=list, description="现有相关接口/功能摘要")
    impact_domains: ImpactDomain = Field(default_factory=ImpactDomain, description="影响域判断")
    risk_level: str = Field(default="", description="风险等级 L1-L5")
    spec_output_format: dict[str, Any] = Field(
        default_factory=lambda: {
            "must_include": [
                "goal", "non_goals", "business_rules", "acceptance_criteria",
                "test_scenarios", "risk_level", "open_questions",
            ],
            "optional": [
                "api_changes", "data_changes", "cache_changes", "message_changes",
                "permission_rules", "config_changes",
            ],
        },
        description="Spec 输出格式要求",
    )


class BrainstormResult(BaseModel):
    """Brainstorm 输出 —— 架构 §8.5.2 定义的固定结构。

    Superpowers Brainstorm 的输出从自由文本映射到此结构。
    """

    options: list[str] = Field(default_factory=list, description="方案选项列表")
    recommended: str = Field(default="", description="推荐方案")
    not_recommended: list[str] = Field(default_factory=list, description="不推荐方案及原因")
    business_boundaries: list[str] = Field(default_factory=list, description="业务边界")
    key_risks: list[str] = Field(default_factory=list, description="关键风险")
    clarification_needed: list[str] = Field(default_factory=list, description="需要澄清的问题")
    test_ideas: list[str] = Field(default_factory=list, description="测试思路")
    ready_for_spec: bool = Field(default=False, description="是否适合进入 Spec")
    raw_output: str = Field(default="", description="Superpowers 原始输出")
