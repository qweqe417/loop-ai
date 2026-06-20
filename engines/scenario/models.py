"""Scenario 数据模型。

定义验证场景的完整结构：场景定义、执行步骤、断言规则、
前置数据和环境健康检查。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ── 断言类型 ──────────────────────────────────────────────────────

class AssertionType(str, Enum):
    """断言类型 — 覆盖 HTTP / DB / Redis / MQ / 日志。"""

    HTTP_STATUS = "http_status"       # HTTP 状态码
    HTTP_BODY = "http_body"           # 响应体包含
    JSON_PATH = "json_path"           # JSON 路径匹配
    HEADER = "header"                 # 响应头
    DB_QUERY = "db_query"             # 数据库查询结果
    DB_COUNT = "db_count"             # 数据库行数
    REDIS_KEY = "redis_key"           # Redis key 存在
    REDIS_VALUE = "redis_value"       # Redis value 匹配
    MQ_MESSAGE = "mq_message"         # 消息队列消息
    LOG_CONTAINS = "log_contains"     # 日志包含
    SCRIPT = "script"                 # 自定义脚本断言


class AssertionOperator(str, Enum):
    """断言比较运算符。"""

    EQ = "eq"
    NE = "ne"
    GT = "gt"
    LT = "lt"
    GTE = "gte"
    LTE = "lte"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    MATCHES = "matches"       # regex
    EXISTS = "exists"
    NOT_EXISTS = "not_exists"
    EMPTY = "empty"
    NOT_EMPTY = "not_empty"


# ── 场景定义 ──────────────────────────────────────────────────────

class Assertion(BaseModel):
    """单条断言 —— 对某个目标执行一次判断。"""

    type: AssertionType = Field(description="断言类型")
    target: str = Field(
        default="",
        description="断言目标，如 json_path $.data.id / SQL / redis key",
    )
    operator: AssertionOperator = Field(
        default=AssertionOperator.EQ, description="比较运算符"
    )
    expected: Any = Field(default=None, description="期望值（exists/empty 类不需要）")
    message: str = Field(default="", description="断言失败时的说明")


class ScenarioStep(BaseModel):
    """场景执行步骤。"""

    name: str = Field(description="步骤名称")
    type: str = Field(
        default="http_call",
        description="步骤类型: http_call / wait / script / setup / teardown",
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="步骤配置 (method, url, body, headers, duration, script 等)",
    )


class Fixture(BaseModel):
    """测试前置/后置数据。"""

    name: str = Field(description="fixture 名称")
    type: str = Field(description="资源类型: mysql / redis / http / script")
    action: str = Field(default="insert", description="操作: insert / upsert / set / call / exec")
    target: str = Field(default="", description="目标: 表名 / key / URL")
    data: Any = Field(default=None, description="数据内容")
    cleanup: bool = Field(default=True, description="执行后是否清理")


class Scenario(BaseModel):
    """验证场景 —— 一组步骤 + 断言 + 前后置数据的完整定义。

    通常存放在 .ai/scenarios/*.yaml，由 ScenarioRunner 加载执行。
    """

    id: str = Field(description="场景唯一标识，如 order-refund-success")
    name: str = Field(description="场景名称")
    description: str = Field(default="", description="场景描述")
    requires: list[str] = Field(
        default_factory=list,
        description="所需资源: mysql / redis / mq / http_service 等",
    )
    fixtures: list[Fixture] = Field(
        default_factory=list, description="前置测试数据"
    )
    steps: list[ScenarioStep] = Field(
        default_factory=list, description="执行步骤（按序）"
    )
    assertions: list[Assertion] = Field(
        default_factory=list, description="断言列表"
    )
    teardown: list[Fixture] = Field(
        default_factory=list, description="后置清理"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="额外元数据"
    )


# ── 环境检查 ──────────────────────────────────────────────────────

class SanityCheckItem(BaseModel):
    """单条环境健康检查。"""

    name: str = Field(description="检查项名称")
    resource: str = Field(description="资源类型: port / http / mysql / redis / mq / env")
    target: str = Field(description="检查目标: localhost:8080 / DB_HOST / REDIS_URL 等")
    timeout_seconds: int = Field(default=5, description="超时秒数")
    required: bool = Field(default=True, description="是否必须通过")


class SanityCheckResult(BaseModel):
    """单条环境检查结果。"""

    check_name: str = Field(description="检查项名称")
    passed: bool = Field(description="是否通过")
    message: str = Field(default="", description="结果说明")
    details: dict[str, Any] = Field(default_factory=dict, description="详情")
    duration_ms: float = Field(default=0.0, description="耗时毫秒")


class SanityReport(BaseModel):
    """环境健康检查汇总报告。"""

    all_passed: bool = Field(description="是否全部通过")
    total: int = Field(default=0)
    passed: int = Field(default=0)
    failed: int = Field(default=0)
    results: list[SanityCheckResult] = Field(default_factory=list)
    actionable: bool = Field(
        default=True,
        description="失败项是否可以自动修复（False 表示需要人工介入）",
    )
