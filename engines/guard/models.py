"""Guard 数据模型。

定义 Guard 检查结果的严重级别和数据模型。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class GuardSeverity(str, Enum):
    """Guard 规则严重级别。"""

    PASS = "pass"    # 通过，无需关注
    WARN = "warn"    # 警告，记录日志但放行
    BLOCK = "block"  # 阻止，不允许继续


class GuardResult(BaseModel):
    """单条 Guard 规则的检查结果。"""

    rule_name: str = Field(description="规则名称")
    severity: GuardSeverity = Field(description="规则严重级别")
    passed: bool = Field(default=True, description="是否通过")
    block: bool = Field(default=False, description="是否阻止流程继续")
    reason: str = Field(default="", description="检查结论说明")
    details: dict[str, Any] = Field(
        default_factory=dict, description="检查详情（具体违规点）"
    )

    @classmethod
    def ok(cls, rule_name: str, reason: str = "") -> GuardResult:
        """快速构造：通过。"""
        return cls(
            rule_name=rule_name,
            severity=GuardSeverity.PASS,
            passed=True,
            block=False,
            reason=reason or f"[{rule_name}] 检查通过",
        )

    @classmethod
    def warn(cls, rule_name: str, reason: str, **details: Any) -> GuardResult:
        """快速构造：警告。"""
        return cls(
            rule_name=rule_name,
            severity=GuardSeverity.WARN,
            passed=True,
            block=False,
            reason=reason,
            details=details,
        )

    @classmethod
    def blocked(cls, rule_name: str, reason: str, **details: Any) -> GuardResult:
        """快速构造：阻止。"""
        return cls(
            rule_name=rule_name,
            severity=GuardSeverity.BLOCK,
            passed=False,
            block=True,
            reason=reason,
            details=details,
        )
