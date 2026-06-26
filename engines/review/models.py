"""Review 数据模型。"""

# 启用延迟注解求值
from __future__ import annotations

# 导入 Enum 用于定义审查严重级别枚举
from enum import Enum
# 导入 Any 类型，用于灵活的类型注解
from typing import Any

# 导入 Pydantic 基类和字段描述器，用于定义数据模型
from pydantic import BaseModel, Field


class ReviewSeverity(str, Enum):
    """审查规则严重级别。

    三种级别:
    - PASS: 通过，无问题
    - WARN: 警告，不阻断流程
    - BLOCK: 阻断，必须修复才能继续
    """

    # 通过
    PASS = "pass"
    # 警告
    WARN = "warn"
    # 阻断
    BLOCK = "block"


class ReviewResult(BaseModel):
    """单条审查规则的检查结果。"""

    # 规则名称
    rule_name: str = Field(description="规则名称")
    # 规则严重级别
    severity: ReviewSeverity = Field(description="规则严重级别")
    # 是否通过
    passed: bool = Field(default=True, description="是否通过")
    # 是否阻止流程继续
    block: bool = Field(default=False, description="是否阻止流程继续")
    # 检查结论说明
    reason: str = Field(default="", description="检查结论说明")
    # 检查详情（具体违规点）
    details: dict[str, Any] = Field(
        default_factory=dict, description="检查详情（具体违规点）"
    )

    @classmethod
    def ok(cls, rule_name: str, reason: str = "", **details: Any) -> ReviewResult:
        """创建 PASS 级别的检查结果。

        Args:
            rule_name: 规则名称
            reason: 检查结论（可选）
            **details: 额外详情（如 diff_stats、lint_issues 等）

        Returns:
            ReviewResult 对象
        """
        return cls(
            rule_name=rule_name,
            severity=ReviewSeverity.PASS,
            passed=True,
            block=False,
            reason=reason or f"[{rule_name}] 检查通过",
            details=details,
        )

    @classmethod
    def warn(cls, rule_name: str, reason: str, **details: Any) -> ReviewResult:
        """创建 WARN 级别的检查结果。

        Args:
            rule_name: 规则名称
            reason: 警告原因
            **details: 额外详情

        Returns:
            ReviewResult 对象
        """
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
        """创建 BLOCK 级别的检查结果。

        Args:
            rule_name: 规则名称
            reason: 阻断原因
            **details: 额外详情

        Returns:
            ReviewResult 对象
        """
        return cls(
            rule_name=rule_name,
            severity=ReviewSeverity.BLOCK,
            passed=False,
            block=True,
            reason=reason,
            details=details,
        )