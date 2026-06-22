"""Review 数据模型。"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ReviewSeverity(str, Enum):
    """审查规则严重级别。"""

    PASS = "pass"
    WARN = "warn"
    BLOCK = "block"


class ReviewResult(BaseModel):
    """单条审查规则的检查结果。"""

    rule_name: str = Field(description="规则名称")
    severity: ReviewSeverity = Field(description="规则严重级别")
    passed: bool = Field(default=True, description="是否通过")
    block: bool = Field(default=False, description="是否阻止流程继续")
    reason: str = Field(default="", description="检查结论说明")
    details: dict[str, Any] = Field(
        default_factory=dict, description="检查详情（具体违规点）"
    )

    @classmethod
    def ok(cls, rule_name: str, reason: str = "") -> ReviewResult:
        return cls(
            rule_name=rule_name,
            severity=ReviewSeverity.PASS,
            passed=True,
            block=False,
            reason=reason or f"[{rule_name}] 检查通过",
        )

    @classmethod
    def warn(cls, rule_name: str, reason: str, **details: Any) -> ReviewResult:
        return cls(
            rule_name=rule_name,
            severity=ReviewSeverity.WARN,
            passed=True,
            block=False,
            reason=reason,
            details=details,
        )

    @classmethod
    def blocked(cls, rule_name: str, reason: str, **details: Any) -> ReviewResult:
        return cls(
            rule_name=rule_name,
            severity=ReviewSeverity.BLOCK,
            passed=False,
            block=True,
            reason=reason,
            details=details,
        )
