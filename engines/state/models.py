"""Loop Engineering 核心数据模型。

所有模型基于 Pydantic v2，提供自动校验和 JSON 序列化。
RunState 是整个循环流程的顶级载体，贯穿所有阶段。

Python vs AI 职责：
  Python: 状态流转 / Guard 校验 / ContextRouter / Quality Gate / ScenarioRunner
  AI:    写 Spec / 填 Plan / 写代码 / 分析根因
  交互:   Python 设置 pending_prompt → AI 读取 → AI 做创造性工作 →
          AI 调 CLI 提交结果 → Python 校验 → 继续流转
"""

# 启用延迟注解求值，允许在类型注解中使用尚未定义的类型
from __future__ import annotations

# 导入 datetime 用于时间戳字段
from datetime import datetime
# 导入 Any 类型用于灵活的字典值类型
from typing import Any

# 导入 Pydantic v2 的 BaseModel 基类和 Field 字段描述器
from pydantic import BaseModel, Field

# 从同包的 enums 模块导入所有枚举类型
from .enums import (
    FailureCategory,       # 失败分类枚举
    LoopAction,            # 循环流转动作枚举
    StageType,             # 循环阶段类型枚举
    TaskStatus,            # 任务执行状态枚举
    VerificationStatus,    # 验证状态枚举
)


# ── 辅助模型 ──────────────────────────────────────────────────────

# 循环流转决策模型：每个阶段结束后的产物
class LoopDecision(BaseModel):
    """循环流转决策 —— 每个阶段结束后的产物。"""

    # 流转动作：决定下一步做什么（继续/下一阶段/重试/回溯/终止等）
    action: LoopAction = Field(description="流转动作")
    # 目标阶段：当 action 为 NEXT_STAGE 或 BACKTRACK 时需要指定
    target_stage: StageType | None = Field(
        default=None, description="目标阶段（NEXT_STAGE / BACKTRACK 时需要）"
    )
    # 决策理由：解释为什么做出这个决策
    reason: str = Field(default="", description="决策理由")
    # 携带的上下文数据：可传递额外信息给下一阶段
    context: dict[str, Any] = Field(
        default_factory=dict, description="携带的上下文数据"
    )


# 任务入口分析结果模型：INTAKE 阶段产出
class TaskIntakeResult(BaseModel):
    """任务入口分析结果 —— INTAKE 阶段产出。"""

    # 用户输入类型：纯文本 prompt / 文档 / issue
    input_type: str = Field(description="用户输入类型：prompt / document / issue")
    # 复杂度评级：low / medium / high
    complexity: str = Field(description="复杂度评级：low / medium / high")
    # 风险等级：L1 到 L5
    risk_level: str = Field(description="风险等级：L1 ~ L5")
    # 分流模式：direct（直接执行）/ spec_from_prompt（从 prompt 生成 spec）/ spec_from_document（从文档生成 spec）
    flow_mode: str = Field(description="分流模式：direct / spec_from_prompt / spec_from_document")
    # 预计需要经过的阶段列表
    estimated_stages: list[StageType] = Field(
        default_factory=list, description="预计需要经过的阶段列表"
    )
    # 是否需要生成 Spec 文档
    needs_spec: bool = Field(default=True, description="是否需要生成 Spec")
    # 是否需要生成 Plan 计划
    needs_plan: bool = Field(default=True, description="是否需要生成 Plan")
    # 是否需要场景验证
    verification_required: bool = Field(
        default=True, description="是否需要场景验证"
    )
    # Guard 级别，控制审查的严格程度
    guard_level: str = Field(default="normal", description="Guard 级别")
    # 分流决策的理由说明
    reason: str = Field(default="", description="分流决策理由")


# 验证状态模型：VERIFY 阶段产出
class VerificationState(BaseModel):
    """验证状态 —— VERIFY 阶段产出。"""

    # 验证状态：未验证 / 通过 / 失败 / 部分通过 / 跳过
    status: VerificationStatus = Field(
        default=VerificationStatus.UNVERIFIED, description="验证状态"
    )
    # 验证摘要：简要描述验证结果
    summary: str = Field(default="", description="验证摘要")
    # 冒烟检查是否通过：编译 / lint 等基础检查
    sanity_check_passed: bool = Field(
        default=False, description="冒烟检查是否通过（编译 / lint）"
    )
    # 测试输出原文：完整的测试运行输出
    test_output: str = Field(default="", description="测试输出原文")
    # 断言总数
    total_assertions: int = Field(default=0, description="断言总数")
    # 通过断言数
    passed_assertions: int = Field(default=0, description="通过断言数")
    # 覆盖率数据：包含 lines / branches 等覆盖率指标
    coverage: dict[str, Any] = Field(
        default_factory=dict, description="覆盖率数据 {lines, branches, ...}"
    )


# 场景验证结果模型：单个场景的执行记录
class ScenarioResult(BaseModel):
    """场景验证结果 —— 单个场景的执行记录。"""

    # 场景唯一标识
    scenario_id: str = Field(description="场景标识")
    # 场景名称
    name: str = Field(default="", description="场景名称")
    # 是否通过验证
    passed: bool = Field(default=False, description="是否通过")
    # 该场景的断言总数
    assertions_total: int = Field(default=0, description="断言总数")
    # 通过的断言数
    assertions_passed: int = Field(default=0, description="通过的断言数")
    # 错误信息列表
    errors: list[str] = Field(default_factory=list, description="错误信息列表")
    # 额外元数据：HTTP 状态码 / 响应时间等
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="额外数据（HTTP 状态码 / 响应时间等）"
    )


# 失败记录模型：REPAIR 阶段的输入，MEMORY 阶段的素材
class FailureRecord(BaseModel):
    """失败记录 —— REPAIR 阶段的输入，MEMORY 阶段的素材。"""

    # 失败分类：环境/测试数据/代码逻辑/范围越界/计划不足/未知
    category: FailureCategory = Field(
        default=FailureCategory.UNKNOWN, description="失败分类"
    )
    # 错误消息：失败的详细描述
    message: str = Field(description="错误消息")
    # 失败发生的阶段
    stage: StageType = Field(description="失败发生的阶段")
    # 当前阶段第几次尝试
    attempt_count: int = Field(default=1, description="当前阶段第几次尝试")
    # 失败时的变更摘要：可用于回滚操作
    diff_snapshot: str = Field(
        default="", description="失败时的变更摘要（可回滚用）"
    )
    # 额外上下文信息
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="额外上下文"
    )


# 检查点模型：关键阶段完成后保存快照，支持回溯
class Checkpoint(BaseModel):
    """检查点 —— 关键阶段完成后保存快照，支持回溯。"""

    # 完成时所在的阶段
    stage: StageType = Field(description="完成时所在的阶段")
    # 快照时间戳
    timestamp: datetime = Field(
        default_factory=datetime.now, description="快照时间"
    )
    # 当前阶段的变更 diff
    diff: str = Field(default="", description="当前阶段的变更 diff")
    # 变更的文件列表
    files_changed: list[str] = Field(
        default_factory=list, description="变更的文件列表"
    )
    # 创建检查点的原因
    reason: str = Field(default="", description="创建检查点的原因")
    # 额外上下文信息
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="额外上下文"
    )


# 用户确认请求模型：用于 L4/L5 高风险操作的显式用户确认
class UserConfirmation(BaseModel):
    """用户确认请求（架构 §8.6.10）。

    用于 L4/L5 高风险操作的显式用户确认。
    Python 构造确认请求 → AI 展示给用户 → 用户确认后继续。
    """

    # 确认请求唯一 ID
    confirm_id: str = Field(description="确认请求 ID")
    # 待确认的动作类型：plan_lock / plan_change / execute_high_risk / delete / schema_change
    action: str = Field(description="待确认动作: plan_lock / plan_change / execute_high_risk / delete / schema_change")
    # 关联风险等级，默认 L3
    risk_level: str = Field(default="L3", description="关联风险等级")
    # 确认标题
    title: str = Field(description="确认标题")
    # 详细说明
    description: str = Field(description="详细说明")
    # 影响的文件列表
    affected_files: list[str] = Field(default_factory=list, description="影响的文件")
    # 可能的后果列表
    consequences: list[str] = Field(default_factory=list, description="可能的后果")
    # 备选方案列表
    alternatives: list[str] = Field(default_factory=list, description="备选方案")
    # 自动批准截止时间（ISO 8601 格式）
    auto_approve_deadline: str = Field(default="", description="自动批准截止 (ISO 8601)")
    # 用户是否已确认
    confirmed: bool = Field(default=False, description="用户是否已确认")
    # 确认时间
    confirmed_at: datetime | None = Field(default=None, description="确认时间")
    # 用户备注
    user_note: str = Field(default="", description="用户备注")


# 任务执行日志模型：每个 Task 完成后写入一条，REVIEW 阶段用于合规检查
class TaskExecutionLog(BaseModel):
    """单 Task 执行记录 —— 对应架构 §8.7.12 Task Execution Log。

    每个 Task 完成后写入一条，REVIEW 阶段用于合规检查。
    """

    # Task ID（T1/T2/...）
    task_id: str = Field(description="Task ID (T1/T2/...)")
    # 任务状态：pending / in_progress / implemented / verified / blocked
    status: str = Field(default="pending", description="pending / in_progress / implemented / verified / blocked")
    # 实际修改的文件列表
    changed_files: list[str] = Field(default_factory=list, description="实际修改的文件")
    # 新增代码行数
    lines_added: int = Field(default=0)
    # 删除代码行数
    lines_removed: int = Field(default=0)
    # 合规检查结果
    plan_compliance: dict[str, Any] = Field(default_factory=dict, description="合规检查结果")
    # 验证结果
    verification: dict[str, Any] = Field(default_factory=dict, description="验证结果")
    # 问题列表
    issues: list[str] = Field(default_factory=list)
    # 任务开始时间
    started_at: datetime | None = Field(default=None)
    # 任务完成时间
    completed_at: datetime | None = Field(default=None)


# 任务执行状态模型：跟踪单次任务的生命周期
class TaskState(BaseModel):
    """任务执行状态 —— 跟踪单次任务的生命周期。"""

    # 当前任务状态
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="任务状态")
    # 当前所处阶段
    stage: StageType = Field(default=StageType.INTAKE, description="当前阶段")
    # Plan 合规性评估
    plan_compliance: str | None = Field(
        default=None, description="Plan 合规性评估"
    )
    # 验证状态
    verification: VerificationState = Field(
        default_factory=VerificationState, description="验证状态"
    )
    # 当前阶段重试次数
    retry_count: int = Field(default=0, description="当前阶段重试次数")
    # 各阶段备注
    notes: list[str] = Field(default_factory=list, description="各阶段备注")
    # Per-task 执行追踪
    # 当前执行的 Task 索引
    current_task_index: int = Field(default=0, description="当前执行的 Task 索引")
    # 各 Task 执行记录
    task_logs: list[TaskExecutionLog] = Field(default_factory=list, description="各 Task 执行记录")
    # 任务开始时间
    started_at: datetime | None = Field(default=None, description="开始时间")
    # 任务完成时间
    completed_at: datetime | None = Field(default=None, description="完成时间")
    # 扩展元数据
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="扩展元数据"
    )


# ── 顶级模型 ──────────────────────────────────────────────────────

# 循环运行时状态模型：整个 Loop 的单一数据载体
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

    # 任务唯一标识
    task_id: str = Field(description="任务唯一标识")
    # 项目标识
    project: str = Field(default="", description="项目标识")
    # 项目根目录路径
    project_root: str = Field(default=".", description="项目根目录路径")
    # 当前所处的阶段
    current_stage: StageType = Field(
        default=StageType.INTAKE, description="当前阶段"
    )

    # 入口分析
    # INTAKE 阶段分析结果，初始为 None
    task_intake: TaskIntakeResult | None = Field(
        default=None, description="INTAKE 阶段分析结果"
    )

    # ── AI 交互 ──
    # 当前等待 AI 执行的动作：brainstorm / generate_spec / generate_plan / execute_task / repair / review
    pending_action: str = Field(
        default="", description="当前等待 AI 执行的动作: brainstorm / generate_spec / generate_plan / execute_task / repair / review"
    )
    # 构造给 AI 的结构化 prompt（ContextPacket + 输出格式要求）
    pending_prompt: dict[str, Any] = Field(
        default_factory=dict, description="构造给 AI 的结构化 prompt（ContextPacket + 输出格式要求）"
    )
    # Loop 是否应暂停等待 AI 输入
    needs_ai_input: bool = Field(
        default=False, description="Loop 是否应暂停等待 AI 输入"
    )

    # ── Spec 阶段产物 ──
    # AI 生成的 SpecEntry（JSON 序列化格式）
    spec_entry: dict[str, Any] | None = Field(
        default=None, description="AI 生成的 SpecEntry (JSON-serialized)"
    )
    # SpecQualityGate.evaluate() 的报告
    spec_quality_report: dict[str, Any] | None = Field(
        default=None, description="SpecQualityGate.evaluate() 的报告"
    )
    # Superpowers Brainstorm 输出
    brainstorm_result: dict[str, Any] | None = Field(
        default=None, description="Superpowers Brainstorm 输出"
    )

    # ── Plan 阶段产物 ──
    # PlanContract 列表（JSON 序列化格式）
    plan_contracts: list[dict[str, Any]] = Field(
        default_factory=list, description="PlanContract 列表 (JSON-serialized)"
    )
    # PlanLock 状态快照：unlocked / locked / change_requested / breached
    plan_lock_state: str = Field(
        default="unlocked", description="PlanLock 状态快照: unlocked / locked / change_requested / breached"
    )
    # PlanQualityGate 报告
    plan_quality_report: dict[str, Any] | None = Field(
        default=None, description="PlanQualityGate 报告"
    )

    # ── 运行模式 ──
    # 是否以 daemon 模式运行（后台持续监听）
    daemon_mode: bool = Field(
        default=False, description="是否以 daemon 模式运行 (后台持续监听)"
    )
    # 上下文 token 预算上限
    context_budget_max: int = Field(
        default=8000, description="上下文 token 预算上限"
    )
    # 当前阶段已用 token 估算
    context_budget_used: int = Field(
        default=0, description="当前阶段已用 token 估算"
    )

    # 任务执行
    # 任务执行跟踪状态
    task_state: TaskState = Field(
        default_factory=TaskState, description="任务执行跟踪"
    )

    # 验证
    # 验证状态
    verification: VerificationState = Field(
        default_factory=VerificationState, description="验证状态"
    )
    # 场景验证结果列表
    scenario_results: list[ScenarioResult] = Field(
        default_factory=list, description="场景验证结果列表"
    )

    # 检查点与决策
    # 检查点历史列表
    checkpoints: list[Checkpoint] = Field(
        default_factory=list, description="检查点历史"
    )
    # 最近一次流转决策
    decision: LoopDecision | None = Field(
        default=None, description="最近一次流转决策"
    )

    # 失败记录
    # 失败记录列表
    failures: list[FailureRecord] = Field(
        default_factory=list, description="失败记录列表"
    )

    # 时间与扩展
    # 创建时间
    created_at: datetime = Field(
        default_factory=datetime.now, description="创建时间"
    )
    # 最后更新时间
    updated_at: datetime = Field(
        default_factory=datetime.now, description="最后更新时间"
    )
    # 用户确认历史（L4/L5 操作）
    confirmed_actions: list[UserConfirmation] = Field(
        default_factory=list, description="用户确认历史 (L4/L5 操作)"
    )
    # 扩展元数据
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="扩展元数据"
    )