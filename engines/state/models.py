"""Loop Engineering 核心数据模型。

所有模型基于 Pydantic v2，提供自动校验和 JSON 序列化。
RunState 是整个循环流程的顶级载体，贯穿所有阶段。

Python vs AI 职责：
  Python: 状态流转 / Guard 校验 / ContextRouter / Quality Gate / ScenarioRunner
  AI:    写 Spec / 填 Plan / 写代码 / 分析根因
  交互:   Python 设置 pending_prompt → AI 读取 → AI 做创造性工作 →
          AI 调 CLI 提交结果 → Python 校验 → 继续流转
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .enums import (
    FailureCategory,
    LoopAction,
    StageType,
    TaskStatus,
    VerificationStatus,
)


# ── 辅助模型 ──────────────────────────────────────────────────────

class LoopDecision(BaseModel):
    """循环流转决策 —— 每个阶段结束后的产物。"""

    action: LoopAction = Field(description="流转动作")
    target_stage: StageType | None = Field(
        default=None, description="目标阶段（NEXT_STAGE / BACKTRACK 时需要）"
    )
    reason: str = Field(default="", description="决策理由")
    context: dict[str, Any] = Field(
        default_factory=dict, description="携带的上下文数据"
    )


class TaskIntakeResult(BaseModel):
    """任务入口分析结果 —— INTAKE 阶段产出。"""

    input_type: str = Field(description="用户输入类型：prompt / document / issue")
    complexity: str = Field(description="复杂度评级：low / medium / high")
    risk_level: str = Field(description="风险等级：L1 ~ L5")
    flow_mode: str = Field(description="分流模式：direct / spec_from_prompt / spec_from_document")
    estimated_stages: list[StageType] = Field(
        default_factory=list, description="预计需要经过的阶段列表"
    )
    needs_spec: bool = Field(default=True, description="是否需要生成 Spec")
    needs_plan: bool = Field(default=True, description="是否需要生成 Plan")
    verification_required: bool = Field(
        default=True, description="是否需要场景验证"
    )
    guard_level: str = Field(default="normal", description="Guard 级别")
    reason: str = Field(default="", description="分流决策理由")


class VerificationState(BaseModel):
    """验证状态 —— VERIFY 阶段产出。"""

    status: VerificationStatus = Field(
        default=VerificationStatus.UNVERIFIED, description="验证状态"
    )
    summary: str = Field(default="", description="验证摘要")
    sanity_check_passed: bool = Field(
        default=False, description="冒烟检查是否通过（编译 / lint）"
    )
    test_output: str = Field(default="", description="测试输出原文")
    total_assertions: int = Field(default=0, description="断言总数")
    passed_assertions: int = Field(default=0, description="通过断言数")
    coverage: dict[str, Any] = Field(
        default_factory=dict, description="覆盖率数据 {lines, branches, ...}"
    )


class ScenarioResult(BaseModel):
    """场景验证结果 —— 单个场景的执行记录。"""

    scenario_id: str = Field(description="场景标识")
    name: str = Field(default="", description="场景名称")
    passed: bool = Field(default=False, description="是否通过")
    assertions_total: int = Field(default=0, description="断言总数")
    assertions_passed: int = Field(default=0, description="通过的断言数")
    errors: list[str] = Field(default_factory=list, description="错误信息列表")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="额外数据（HTTP 状态码 / 响应时间等）"
    )


class FailureRecord(BaseModel):
    """失败记录 —— REPAIR 阶段的输入，MEMORY 阶段的素材。"""

    category: FailureCategory = Field(
        default=FailureCategory.UNKNOWN, description="失败分类"
    )
    message: str = Field(description="错误消息")
    stage: StageType = Field(description="失败发生的阶段")
    attempt_count: int = Field(default=1, description="当前阶段第几次尝试")
    diff_snapshot: str = Field(
        default="", description="失败时的变更摘要（可回滚用）"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="额外上下文"
    )


class Checkpoint(BaseModel):
    """检查点 —— 关键阶段完成后保存快照，支持回溯。"""

    stage: StageType = Field(description="完成时所在的阶段")
    timestamp: datetime = Field(
        default_factory=datetime.now, description="快照时间"
    )
    diff: str = Field(default="", description="当前阶段的变更 diff")
    files_changed: list[str] = Field(
        default_factory=list, description="变更的文件列表"
    )
    reason: str = Field(default="", description="创建检查点的原因")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="额外上下文"
    )


class UserConfirmation(BaseModel):
    """用户确认请求（架构 §8.6.10）。

    用于 L4/L5 高风险操作的显式用户确认。
    Python 构造确认请求 → AI 展示给用户 → 用户确认后继续。
    """

    confirm_id: str = Field(description="确认请求 ID")
    action: str = Field(description="待确认动作: plan_lock / plan_change / execute_high_risk / delete / schema_change")
    risk_level: str = Field(default="L3", description="关联风险等级")
    title: str = Field(description="确认标题")
    description: str = Field(description="详细说明")
    affected_files: list[str] = Field(default_factory=list, description="影响的文件")
    consequences: list[str] = Field(default_factory=list, description="可能的后果")
    alternatives: list[str] = Field(default_factory=list, description="备选方案")
    auto_approve_deadline: str = Field(default="", description="自动批准截止 (ISO 8601)")
    confirmed: bool = Field(default=False, description="用户是否已确认")
    confirmed_at: datetime | None = Field(default=None, description="确认时间")
    user_note: str = Field(default="", description="用户备注")


class TaskExecutionLog(BaseModel):
    """单 Task 执行记录 —— 对应架构 §8.7.12 Task Execution Log。

    每个 Task 完成后写入一条，REVIEW 阶段用于合规检查。
    """

    task_id: str = Field(description="Task ID (T1/T2/...)")
    status: str = Field(default="pending", description="pending / in_progress / implemented / verified / blocked")
    changed_files: list[str] = Field(default_factory=list, description="实际修改的文件")
    lines_added: int = Field(default=0)
    lines_removed: int = Field(default=0)
    plan_compliance: dict[str, Any] = Field(default_factory=dict, description="合规检查结果")
    verification: dict[str, Any] = Field(default_factory=dict, description="验证结果")
    issues: list[str] = Field(default_factory=list)
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)


class TaskState(BaseModel):
    """任务执行状态 —— 跟踪单次任务的生命周期。"""

    status: TaskStatus = Field(default=TaskStatus.PENDING, description="任务状态")
    stage: StageType = Field(default=StageType.INTAKE, description="当前阶段")
    plan_compliance: str | None = Field(
        default=None, description="Plan 合规性评估"
    )
    verification: VerificationState = Field(
        default_factory=VerificationState, description="验证状态"
    )
    retry_count: int = Field(default=0, description="当前阶段重试次数")
    notes: list[str] = Field(default_factory=list, description="各阶段备注")
    # Per-task 执行追踪
    current_task_index: int = Field(default=0, description="当前执行的 Task 索引")
    task_logs: list[TaskExecutionLog] = Field(default_factory=list, description="各 Task 执行记录")
    started_at: datetime | None = Field(default=None, description="开始时间")
    completed_at: datetime | None = Field(default=None, description="完成时间")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="扩展元数据"
    )


# ── 顶级模型 ──────────────────────────────────────────────────────

class RunState(BaseModel):
    """循环运行时状态 —— 整个 Loop 的单一数据载体。

    从 INTAKE 到 COMPLETED/ABORTED，所有阶段共享同一个 RunState 实例，
    各阶段只读写自己关心的字段，阶段间通过检查点回溯。

    Python ↔ AI 交互机制:
      - pending_action: Python 设置，告诉 AI 当前需要做什么
      - pending_prompt: Python 构造的结构化上下文，AI 读取后做创造性工作
      - AI 提交结果通过 CLI: engines/run.sh loop continue --stage <s> --result '<json>'
      - Python 校验结果 → Quality Gate → 继续流转或要求修正
    """

    task_id: str = Field(description="任务唯一标识")
    project: str = Field(default="", description="项目标识")
    project_root: str = Field(default=".", description="项目根目录路径")
    current_stage: StageType = Field(
        default=StageType.INTAKE, description="当前阶段"
    )

    # 入口分析
    task_intake: TaskIntakeResult | None = Field(
        default=None, description="INTAKE 阶段分析结果"
    )

    # ── AI 交互 ──
    pending_action: str = Field(
        default="", description="当前等待 AI 执行的动作: brainstorm / generate_spec / generate_plan / execute_task / repair / review"
    )
    pending_prompt: dict[str, Any] = Field(
        default_factory=dict, description="构造给 AI 的结构化 prompt（ContextPacket + 输出格式要求）"
    )
    needs_ai_input: bool = Field(
        default=False, description="Loop 是否应暂停等待 AI 输入"
    )

    # ── Spec 阶段产物 ──
    spec_entry: dict[str, Any] | None = Field(
        default=None, description="AI 生成的 SpecEntry (JSON-serialized)"
    )
    spec_quality_report: dict[str, Any] | None = Field(
        default=None, description="SpecQualityGate.evaluate() 的报告"
    )
    brainstorm_result: dict[str, Any] | None = Field(
        default=None, description="Superpowers Brainstorm 输出"
    )

    # ── Plan 阶段产物 ──
    plan_contracts: list[dict[str, Any]] = Field(
        default_factory=list, description="PlanContract 列表 (JSON-serialized)"
    )
    plan_lock_state: str = Field(
        default="unlocked", description="PlanLock 状态快照: unlocked / locked / change_requested / breached"
    )
    plan_quality_report: dict[str, Any] | None = Field(
        default=None, description="PlanQualityGate 报告"
    )

    # ── 隔离与运行模式 ──
    use_worktree: bool = Field(
        default=False, description="是否使用 git worktree 隔离 (L4/L5 强制)"
    )
    daemon_mode: bool = Field(
        default=False, description="是否以 daemon 模式运行 (后台持续监听)"
    )
    context_budget_max: int = Field(
        default=8000, description="上下文 token 预算上限"
    )
    context_budget_used: int = Field(
        default=0, description="当前阶段已用 token 估算"
    )

    # 任务执行
    task_state: TaskState = Field(
        default_factory=TaskState, description="任务执行跟踪"
    )

    # 验证
    verification: VerificationState = Field(
        default_factory=VerificationState, description="验证状态"
    )
    scenario_results: list[ScenarioResult] = Field(
        default_factory=list, description="场景验证结果列表"
    )

    # 检查点与决策
    checkpoints: list[Checkpoint] = Field(
        default_factory=list, description="检查点历史"
    )
    decision: LoopDecision | None = Field(
        default=None, description="最近一次流转决策"
    )

    # 失败记录
    failures: list[FailureRecord] = Field(
        default_factory=list, description="失败记录列表"
    )

    # 时间与扩展
    created_at: datetime = Field(
        default_factory=datetime.now, description="创建时间"
    )
    confirmed_actions: list[UserConfirmation] = Field(
        default_factory=list, description="用户确认历史 (L4/L5 操作)"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="扩展元数据"
    )

