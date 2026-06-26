"""失败分类器 —— 将场景失败自动分为 4 类。

分类规则（确定性，0 token）：
- TIMING:      异步未完成，字段存在但为 None/空
- ENVIRONMENT: 服务不可达、连接拒绝、DNS 失败
- ASSERTION:   期望值与实际类型一致、值接近，可能是断言路径/期望值写错
- REAL_BUG:    期望值与实际明显不符，代码逻辑错误
"""

# 启用 Python 3.10+ 的延迟注解求值特性
from __future__ import annotations

# 导入 Enum 基类，用于定义失败分类枚举
from enum import Enum
# 导入 Any 类型，用于灵活的类型注解
from typing import Any


class FailureCategory(str, Enum):
    """失败分类枚举 —— 确定失败类型的根本原因。"""
    # 异步未完成（数据尚未就绪）
    TIMING = "TIMING"
    # 环境故障（服务/数据库/中间件不可达）
    ENVIRONMENT = "ENVIRONMENT"
    # 断言本身有问题（期望值写错）
    ASSERTION = "ASSERTION"
    # 代码逻辑错误（真正的 Bug）
    REAL_BUG = "REAL_BUG"


def classify_failure(
    expected: Any,
    actual: Any,
    error_message: str = "",
) -> FailureCategory:
    """根据 expected vs actual 特征自动分类失败类型。

    >>> classify_failure({"stock": 9}, {"stock": 10})
    REAL_BUG
    >>> classify_failure({"stock": 9}, None)
    TIMING
    >>> classify_failure({"stock": 9}, {"error": "connection refused"})
    ENVIRONMENT

    Args:
        expected: 期望值
        actual: 实际值
        error_message: 错误消息（辅助分类）

    Returns:
        FailureCategory: 失败分类
    """
    # ── 环境故障检测 ──
    # 检查 actual 中是否包含环境故障关键词
    env_keywords = (
        "connection refused", "timed out", "timeout",
        "unreachable", "not found", "name resolution",
        "no route to host", "connection reset",
    )
    if actual is None or (isinstance(actual, dict) and actual.get("error")):
        # 提取错误消息字符串
        error_str = str(
            actual.get("error", error_message) if isinstance(actual, dict)
            else error_message
        ).lower()
        # 匹配环境故障关键词
        if any(kw in error_str for kw in env_keywords):
            return FailureCategory.ENVIRONMENT

    # ── 时序问题检测 ──
    # actual 为 None 或所有字段值为 None → 数据尚未就绪
    if actual is None:
        return FailureCategory.TIMING
    if isinstance(actual, dict) and len(actual) > 0 and all(
        v is None for v in actual.values()
    ):
        return FailureCategory.TIMING
    if isinstance(actual, list) and len(actual) == 0 and expected not in (None, [], {}):
        return FailureCategory.TIMING

    # ── 断言偏差检测 ──
    # 类型相同且值接近（数值偏差 < 30% 或字符串包含关系）→ 可能是断言写错了
    if type(expected) is type(actual):
        if isinstance(expected, (int, float)):
            # 数值比较：偏差 < 30% 认为接近
            denom = max(1.0, abs(float(expected)))
            ratio = abs(float(expected) - float(actual)) / denom
            if ratio < 0.3:
                return FailureCategory.ASSERTION
        if isinstance(expected, str) and isinstance(actual, str) and actual:
            # 字符串包含关系：期望值包含在实际值中或反之
            if expected.lower() in actual.lower() or actual.lower() in expected.lower():
                return FailureCategory.ASSERTION

    # ── 默认：真实 Bug ──
    return FailureCategory.REAL_BUG


def classify_assertion_failures(
    failed_assertions: list[dict],
) -> list[dict]:
    """为每个失败的断言添加 failure_category 字段。

    Args:
        failed_assertions: [{"expected": ..., "actual": ..., "message": ...}, ...]

    Returns:
        添加了 "failure_category" 字段的断言列表
    """
    for assertion in failed_assertions:
        # 为每条失败断言调用 classify_failure 进行分类
        assertion["failure_category"] = classify_failure(
            expected=assertion.get("expected"),
            actual=assertion.get("actual"),
            error_message=assertion.get("message", ""),
        ).value
    return failed_assertions