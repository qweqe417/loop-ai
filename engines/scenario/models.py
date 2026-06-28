"""Scenario 数据模型。

定义验证场景的完整结构：场景定义、执行步骤、断言规则、
前置数据和环境健康检查。
"""

# 启用 Python 3.10+ 的延迟注解求值特性
from __future__ import annotations

# 导入 Enum 基类，用于定义枚举类型
from enum import Enum
# 导入 Any 类型，用于灵活的类型注解
from typing import Any

# 导入 Pydantic 的 BaseModel 和 Field，用于定义数据模型
from pydantic import BaseModel, Field


# ── 断言类型 ──────────────────────────────────────────────────────

class AssertionType(str, Enum):
    """断言类型 — 覆盖 HTTP / DB / Redis / MQ / 日志。"""

    # HTTP 状态码断言
    HTTP_STATUS = "http_status"
    # 响应体包含断言
    HTTP_BODY = "http_body"
    # JSON 路径匹配断言
    JSON_PATH = "json_path"
    # 响应头断言
    HEADER = "header"
    # 数据库查询结果断言
    DB_QUERY = "db_query"
    # 数据库行数断言
    DB_COUNT = "db_count"
    # Redis key 存在断言
    REDIS_KEY = "redis_key"
    # Redis value 匹配断言
    REDIS_VALUE = "redis_value"
    # 消息队列消息断言
    MQ_MESSAGE = "mq_message"
    # 日志包含断言
    LOG_CONTAINS = "log_contains"
    # 自定义脚本断言
    SCRIPT = "script"


class AssertionOperator(str, Enum):
    """断言比较运算符。"""

    # 等于
    EQ = "eq"
    # 不等于
    NE = "ne"
    # 大于
    GT = "gt"
    # 小于
    LT = "lt"
    # 大于等于
    GTE = "gte"
    # 小于等于
    LTE = "lte"
    # 包含
    CONTAINS = "contains"
    # 不包含
    NOT_CONTAINS = "not_contains"
    # 正则匹配
    MATCHES = "matches"
    # 存在
    EXISTS = "exists"
    # 不存在
    NOT_EXISTS = "not_exists"
    # 为空
    EMPTY = "empty"
    # 不为空
    NOT_EMPTY = "not_empty"


# ── 场景定义 ──────────────────────────────────────────────────────

class Assertion(BaseModel):
    """单条断言 —— 对某个目标执行一次判断。"""

    # 断言类型
    type: AssertionType = Field(description="断言类型")
    # 断言目标，如 json_path $.data.id / SQL / redis key
    target: str = Field(
        default="",
        description="断言目标，如 json_path $.data.id / SQL / redis key",
    )
    # 比较运算符，默认等于
    operator: AssertionOperator = Field(
        default=AssertionOperator.EQ, description="比较运算符"
    )
    # 期望值（exists/empty 类不需要）
    expected: Any = Field(default=None, description="期望值（exists/empty 类不需要）")
    # 断言失败时的说明
    message: str = Field(default="", description="断言失败时的说明")


class ScenarioStep(BaseModel):
    """场景执行步骤。"""

    # 步骤名称
    name: str = Field(description="步骤名称")
    # 步骤类型: http_call / wait / script / setup / teardown / ui_*
    type: str = Field(
        default="http_call",
        description="步骤类型: http_call / wait / script / setup / teardown",
    )
    # 步骤配置 (method, url, body, headers, duration, script 等)
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="步骤配置 (method, url, body, headers, duration, script 等)",
    )


class Fixture(BaseModel):
    """测试前置/后置数据。"""

    # fixture 名称
    name: str = Field(description="fixture 名称")
    # 资源类型: mysql / redis / http / script
    type: str = Field(description="资源类型: mysql / redis / http / script")
    # 操作: insert / upsert / set / call / exec
    action: str = Field(default="insert", description="操作: insert / upsert / set / call / exec")
    # 目标: 表名 / key / URL
    target: str = Field(default="", description="目标: 表名 / key / URL")
    # 数据内容
    data: Any = Field(default=None, description="数据内容")
    # 执行后是否清理
    cleanup: bool = Field(default=True, description="执行后是否清理")


class ScenarioScope(str, Enum):
    """测试范围。"""
    BACKEND = "backend"
    FRONTEND = "frontend"
    FULLSTACK = "fullstack"


class DeviceType(str, Enum):
    """设备类型。"""
    PC = "pc"
    MOBILE = "mobile"
    TABLET = "tablet"


class AuthConfig(BaseModel):
    """鉴权配置。"""
    token: str | None = Field(default=None, description="Bearer token，请求时自动带 Authorization header")


class FixtureEntry(BaseModel):
    """单条前置数据。"""
    table: str = Field(description="表名")
    data: dict[str, Any] = Field(default_factory=dict, description="行数据")


class GivenConfig(BaseModel):
    """测试前置数据。"""
    database: list[FixtureEntry] = Field(default_factory=list)


class CleanupConfig(BaseModel):
    """数据清理策略。"""
    strategy: str = Field(default="rollback", description="rollback | not_required | full_cleanup")
    description: str = Field(default="", description="清理说明")


class DomAssertion(BaseModel):
    """前端 DOM 断言。"""
    type: str = Field(description="dom_visible | dom_text | dom_count | dom_value | dom_hidden")
    target: str = Field(description="CSS selector")
    operator: str = Field(default="eq", description="eq | ne | contains | gt | gte | lt | lte | exists | not_exists")
    expected: Any = Field(default=None, description="期望值")
    message: str = Field(default="", description="断言描述")


class ScenarioParams(BaseModel):
    """单组参数化数据。"""
    name: str = Field(description="参数组名称")
    values: list[Any] = Field(description="参数值列表，Runner 展开后逐条执行")


class Scenario(BaseModel):
    """验证场景 —— 完整定义，存放在 .ai/scenarios/**/*.yaml，由 ScenarioRunner 加载执行。"""

    id: str = Field(description="场景唯一标识，如 order-refund-success")
    name: str = Field(description="场景名称")
    description: str = Field(default="", description="场景描述")
    requires: list[str] = Field(default_factory=list, description="所需资源: mysql / redis / mq / http_service 等")
    fixtures: list[Fixture] = Field(default_factory=list, description="前置测试数据")
    params: list[dict[str, Any]] = Field(default_factory=list, description="参数化数据，每组展开执行一次。示例: [{sku: 'A001', qty: 1}, {sku: 'A002', qty: 5}]")
    steps: list[ScenarioStep] = Field(default_factory=list, description="执行步骤（按序）")
    assertions: list[Assertion] = Field(default_factory=list, description="断言列表")
    teardown: list[Fixture] = Field(default_factory=list, description="后置清理")
    metadata: dict[str, Any] = Field(default_factory=dict, description="额外元数据")

    # ── 增强字段 ──
    scope: ScenarioScope = Field(default=ScenarioScope.BACKEND, description="测试范围")
    device: DeviceType | None = Field(default=None, description="设备类型（前端）")
    viewport: str | None = Field(default=None, description="视口名称，如 iPhone 14")
    auth_required: bool = Field(default=True, description="是否需要全局鉴权 token（注册/登录场景设为 false）")
    auth: AuthConfig | None = Field(default=None, description="鉴权配置")
    given: GivenConfig | None = Field(default=None, description="前置测试数据")
    dom_assertions: list[DomAssertion] = Field(default_factory=list, description="前端 DOM 断言")
    cleanup: CleanupConfig | None = Field(default=None, description="数据清理策略")


# ── 环境检查 ──────────────────────────────────────────────────────

class SanityCheckItem(BaseModel):
    """单条环境健康检查。"""

    # 检查项名称
    name: str = Field(description="检查项名称")
    # 资源类型: port / http / mysql / redis / mq / env
    resource: str = Field(description="资源类型: port / http / mysql / redis / mq / env")
    # 检查目标: localhost:8080 / DB_HOST / REDIS_URL 等
    target: str = Field(description="检查目标: localhost:8080 / DB_HOST / REDIS_URL 等")
    # 超时秒数，默认 5 秒
    timeout_seconds: int = Field(default=5, description="超时秒数")
    # 是否必须通过
    required: bool = Field(default=True, description="是否必须通过")


class SanityCheckResult(BaseModel):
    """单条环境检查结果。"""

    # 检查项名称
    check_name: str = Field(description="检查项名称")
    # 是否通过
    passed: bool = Field(description="是否通过")
    # 结果说明
    message: str = Field(default="", description="结果说明")
    # 详情
    details: dict[str, Any] = Field(default_factory=dict, description="详情")
    # 耗时毫秒
    duration_ms: float = Field(default=0.0, description="耗时毫秒")


class SanityReport(BaseModel):
    """环境健康检查汇总报告。"""

    # 是否全部通过
    all_passed: bool = Field(description="是否全部通过")
    # 检查总数
    total: int = Field(default=0)
    # 通过数
    passed: int = Field(default=0)
    # 失败数
    failed: int = Field(default=0)
    # 各检查项结果列表
    results: list[SanityCheckResult] = Field(default_factory=list)
    # 失败项是否可以自动修复（False 表示需要人工介入）
    actionable: bool = Field(
        default=True,
        description="失败项是否可以自动修复（False 表示需要人工介入）",
    )