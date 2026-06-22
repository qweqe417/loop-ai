"""Test Design 数据模型。

TestCase 是核心——同时支撑视图A（人读 Excel）和视图B（结构化 YAML）。
视图B 的 steps 采用 Action Pipeline 结构化设计，每步可独立执行和断言。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ── Scope ────────────────────────────────────────────────────────────

class Scope(str, Enum):
    BACKEND = "backend"
    FRONTEND = "frontend"
    FULLSTACK = "fullstack"


# ── 测试维度枚举 ────────────────────────────────────────────────────

class TestLevel(str, Enum):
    UNIT = "unit"
    API = "api"
    INTEGRATION = "integration"
    E2E = "e2e"
    SCENARIO = "scenario"
    MANUAL = "manual"


class TestType(str, Enum):
    FUNCTIONAL = "functional"
    NEGATIVE = "negative"
    BOUNDARY = "boundary"
    PERMISSION = "permission"
    STATE_TRANSITION = "state_transition"
    IDEMPOTENCY = "idempotency"
    CONCURRENCY = "concurrency"
    DATA_CONSISTENCY = "data_consistency"
    COMPATIBILITY = "compatibility"
    PERFORMANCE = "performance"
    SECURITY = "security"
    RECOVERY = "recovery"
    UI_INTERACTION = "ui_interaction"
    UI_VISUAL = "ui_visual"


class Priority(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class RiskLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CoverageStatus(str, Enum):
    COVERED = "covered"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"


class AutomationCandidateLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    MANUAL_ONLY = "manual_only"


# ── Action Pipeline ──────────────────────────────────────────────────

class StepAction(str, Enum):
    """步骤动作类型 —— 覆盖 UI / API / 数据层。"""
    UI_NAVIGATE = "ui_navigate"
    UI_CLICK = "ui_click"
    UI_FILL = "ui_fill"
    UI_SELECT = "ui_select"
    UI_HOVER = "ui_hover"
    UI_WAIT = "ui_wait"
    API_CALL = "api_call"
    DB_QUERY = "db_query"
    REDIS_GET = "redis_get"
    MQ_CHECK = "mq_check"
    LOG_CHECK = "log_check"
    SCRIPT = "script"


class StepAssertion(BaseModel):
    """步骤级断言 —— 该步执行后立即校验。"""
    type: str = Field(description="断言类型: http_status / http_body / dom_visible / dom_text / db_query / redis_value / mq_message / log_contains")
    target: str = Field(default="", description="断言目标: $.field / .selector / SQL / redis key")
    operator: str = Field(default="eq", description="比较运算符")
    expected: Any = Field(default=None, description="期望值")
    message: str = Field(default="", description="断言说明")


class Step(BaseModel):
    """单个执行步骤 —— Action Pipeline 的原子单元。

    视图A 用 description 展示给人看。
    视图B 用 action + config + assertions 让 Scenario Runner / Playwright 执行。
    """
    seq: int = Field(description="步骤序号，从 1 开始")
    action: StepAction = Field(description="动作类型")
    description: str = Field(default="", description="人读描述，视图A 表格用")
    config: dict[str, Any] = Field(default_factory=dict, description="动作配置，按 action 类型不同")
    assertions: list[StepAssertion] = Field(default_factory=list, description="该步执行后的即时断言")


# ── 数据断言（后端）─────────────────────────────────────────────────

class DataAssertion(BaseModel):
    """后端数据断言 —— 验证数据库/缓存/消息/日志的状态。"""
    type: str = Field(description="数据源: mysql / redis / mq / log / file")
    target: str = Field(default="", description="目标: 表名 / key / topic")
    operator: str = Field(default="eq", description="eq / exists / not_exists / count / contains")
    expected: Any = Field(default=None, description="期望值")
    message: str = Field(default="", description="断言说明")
    inferred_source: str = Field(default="", description="来源标注: spec | plan | codebase | ai")


# ── DOM 断言（前端）─────────────────────────────────────────────────

class DOMAssertion(BaseModel):
    """前端 DOM 断言 —— 验证页面元素。"""
    type: str = Field(description="dom_visible / dom_hidden / dom_text / dom_value / dom_attribute / dom_count")
    target: str = Field(description="选择器: .class / #id / [data-testid]")
    operator: str = Field(default="eq")
    expected: Any = Field(default=None, description="期望文案/属性值/数量")
    message: str = Field(default="", description="断言说明")


# ── 预期结果 ────────────────────────────────────────────────────────

class ExpectedResult(BaseModel):
    """预期结果 —— 覆盖后端+前端的最终断言。

    response: HTTP 响应断言（backend/fullstack）
    data_assertions: 后端数据层断言
    dom_assertions: 前端 DOM 断言
    """
    response: dict[str, Any] = Field(default_factory=dict, description="{status, body}")
    data_assertions: list[DataAssertion] = Field(default_factory=list, description="后端数据断言")
    dom_assertions: list[DOMAssertion] = Field(default_factory=list, description="前端 DOM 断言")


# ── 清理策略 ────────────────────────────────────────────────────────

class CleanupConfig(BaseModel):
    """测试数据清理策略 —— 强制约定，防止脏数据堆积。"""
    required: bool = Field(default=True, description="是否需要清理")
    strategy: str = Field(
        default="by_reference",
        description="by_reference（按ID回滚）/ truncate_tables（清表）/ not_required（纯前端）"
    )
    description: str = Field(default="", description="清理说明")


# ── 自动化候选 ──────────────────────────────────────────────────────

class AutomationCandidate(BaseModel):
    """自动化建议。"""
    candidate: AutomationCandidateLevel = Field(description="自动化适合度")
    target: str = Field(
        default="scenario",
        description="目标框架: scenario / jest / pytest / playwright / cypress / manual"
    )
    reason: str = Field(default="", description="原因")


# ── 核心模型 ────────────────────────────────────────────────────────

class RequirementItem(BaseModel):
    """从需求文档中提取的单个需求项。"""
    id: str = Field(description="需求编号，如 REQ-001")
    title: str = Field(description="需求标题")
    type: str = Field(default="functional", description="functional / non_functional / constraint")
    risk_level: RiskLevel = Field(default=RiskLevel.MEDIUM)
    description: str = Field(default="")
    acceptance_criteria: list[str] = Field(default_factory=list)
    source: str = Field(default="spec", description="业务规则来源: spec | prd | ai_inferred")


class TestCase(BaseModel):
    """单条测试用例 —— 核心数据结构。

    视图A 用: id, title, priority, preconditions, steps[].description, expected
    视图B 用: 全部字段，steps 是结构化 Action Pipeline
    """
    id: str = Field(description="用例编号，如 TC-ORDER-001")
    title: str = Field(description="用例标题")
    scope: Scope = Field(default=Scope.BACKEND, description="测试范围")
    requirement_refs: list[str] = Field(default_factory=list, description="关联需求/验收标准 ID")
    priority: Priority = Field(default=Priority.P2)
    risk_level: RiskLevel = Field(default=RiskLevel.MEDIUM)
    test_level: TestLevel = Field(default=TestLevel.SCENARIO)
    test_types: list[TestType] = Field(default_factory=list)

    automation: AutomationCandidate | None = Field(default=None, description="自动化建议")

    preconditions: list[str] = Field(default_factory=list, description="前置条件（自然语言）")
    dependencies: list[str] = Field(default_factory=list, description="依赖资源: http_service / mysql / redis / browser / auth")
    test_data: dict[str, Any] = Field(default_factory=dict, description="测试数据定义")

    steps: list[Step] = Field(default_factory=list, description="Action Pipeline 步骤序列")
    expected: ExpectedResult = Field(default_factory=ExpectedResult, description="最终预期结果")

    cleanup: CleanupConfig = Field(default_factory=CleanupConfig, description="数据清理策略")

    notes: list[str] = Field(default_factory=list, description="备注")
    open_questions: list[str] = Field(default_factory=list, description="关联未决问题 ID")


class CoverageEntry(BaseModel):
    """覆盖矩阵条目。"""
    requirement_ref: str = Field(description="需求项 ID")
    test_case_ids: list[str] = Field(default_factory=list, description="覆盖该需求的用例 ID")
    status: CoverageStatus = Field(default=CoverageStatus.COVERED)
    notes: str = Field(default="", description="备注")


class OpenQuestion(BaseModel):
    """未决问题 —— 需求不明确时记录，未解决前阻断落盘。"""
    id: str = Field(description="问题编号，如 Q-001")
    question: str = Field(description="问题描述")
    impact: str = Field(default="", description="影响范围")
    blocks: list[str] = Field(default_factory=list, description="被阻塞的用例 ID")


class QualityReport(BaseModel):
    """质量门禁报告。errors 阻断流程，warnings 继续但标黄。"""
    passed: bool = Field(default=False, description="硬性检查是否全部通过")
    errors: list[str] = Field(default_factory=list, description="硬阻断原因（必须修复）")
    warnings: list[str] = Field(default_factory=list, description="软警告（继续但标注）")
    summary: dict[str, Any] = Field(default_factory=dict)
    open_questions_count: int = Field(default=0)
    blocked_requirements: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.now)


class TestDesignBundle(BaseModel):
    """测试设计完整产物包 —— 视图B 的主数据源。"""
    version: int = Field(default=1)
    feature: str = Field(default="", description="特性名称")
    scope: Scope = Field(default=Scope.BACKEND, description="测试范围")
    source: dict[str, Any] = Field(
        default_factory=dict,
        description="{spec: {type, path}, plan: {path, status: full|degraded}}"
    )

    requirements: list[RequirementItem] = Field(default_factory=list)
    test_cases: list[TestCase] = Field(default_factory=list)
    coverage: list[CoverageEntry] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)

    metadata: dict[str, Any] = Field(default_factory=dict)
