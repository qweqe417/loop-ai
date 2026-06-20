"""Plan 执行合约数据模型。

架构 §8.6: Plan 不是简单 TODO 列表，而是 Execution Contract。
每个 Task 必须绑定 Spec/Acceptance/Scenario，引用 Style Contract，
包含 Reuse Check 和 Diff Budget。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class PlanLockState(str, Enum):
    """Plan 锁定状态。"""

    UNLOCKED = "unlocked"
    LOCKED = "locked"
    CHANGE_REQUESTED = "change_requested"
    BREACHED = "breached"


class DiffBudget(BaseModel):
    """变更预算 —— 限制单次执行的变更规模。"""

    max_files: int = Field(default=3, description="最多修改文件数")
    max_lines: int = Field(default=100, description="最多修改行数")
    files_changed: int = Field(default=0, description="实际修改文件数")
    lines_changed: int = Field(default=0, description="实际修改行数")
    allow_new_abstractions: bool = Field(default=False, description="是否允许新建抽象")
    allow_new_dependencies: bool = Field(default=False, description="是否允许新增依赖")

    @property
    def file_budget_remaining(self) -> int:
        return max(0, self.max_files - self.files_changed)

    @property
    def line_budget_remaining(self) -> int:
        return max(0, self.max_lines - self.lines_changed)

    @property
    def file_budget_exceeded(self) -> bool:
        return self.files_changed > self.max_files

    @property
    def line_budget_exceeded(self) -> bool:
        return self.lines_changed > self.max_lines

    @property
    def exceeded(self) -> bool:
        return self.file_budget_exceeded or self.line_budget_exceeded


# ── Task 绑定 (架构 §8.6.2) ──────────────────────────────────────

class TaskLinks(BaseModel):
    """Task → Spec / Acceptance / Scenario 绑定。

    目的: 防止 AI 忘记为什么修改；让 Review 可检查；让 Verify 知道跑哪些 Scenario。
    """

    spec_requirements: list[str] = Field(default_factory=list, description="关联的 Spec Requirement ID")
    acceptance_criteria: list[str] = Field(default_factory=list, description="关联的 Acceptance Criteria ID")
    scenarios: list[str] = Field(default_factory=list, description="关联的 Scenario ID")


# ── Style Contract (架构 §8.6.6) ─────────────────────────────────

class StyleContract(BaseModel):
    """风格约束 —— 每个 Task 引用项目确认过的风格规则。

    防止: 过度设计、新建不必要抽象、引入不一致风格。
    """

    sources: list[str] = Field(
        default_factory=lambda: [".claude/aicode/style.md", ".claude/rules/code-style.md"],
        description="引用的风格规则文件"
    )
    must: list[str] = Field(default_factory=list, description="必须遵守的写法")
    forbidden: list[str] = Field(default_factory=list, description="禁止引入的模式")
    good_examples: list[str] = Field(default_factory=list, description="可参考的文件/代码片段")


# ── Reuse Check (架构 §8.6.8) ────────────────────────────────────

class ReuseCheck(BaseModel):
    """复用检查 —— 执行前查找已有实现。

    规则: 已有可复用实现 → 优先复用；不复用 → 必须说明原因。
    """

    required: bool = Field(default=True, description="是否强制执行复用检查")
    search_for: list[str] = Field(default_factory=list, description="需要搜索的已有实现类型")


class PlanContract(BaseModel):
    """Plan 执行合约 —— 每个 Task 的完整约束声明。

    AI 在 EXECUTE 前接受此合约，REVIEW 阶段检查合规性。
    """

    task_id: str = Field(default="", description="Task ID: T1/T2/...")
    title: str = Field(default="", description="Task 标题")
    goal: str = Field(default="", description="Task 目标（一句话）")
    allowed_files: list[str] = Field(
        default_factory=list, description="允许修改的文件路径 (glob)"
    )
    forbidden_files: list[str] = Field(
        default_factory=list, description="禁止修改的文件路径 (glob)"
    )
    budget: DiffBudget = Field(default_factory=DiffBudget)
    # 绑定 (架构 §8.6.2)
    links: TaskLinks = Field(default_factory=TaskLinks, description="Spec/Acceptance/Scenario 绑定")
    # 风格约束 (架构 §8.6.6)
    style_contract: StyleContract = Field(default_factory=StyleContract, description="风格约束")
    # 复用检查 (架构 §8.6.8)
    reuse_check: ReuseCheck = Field(default_factory=ReuseCheck, description="复用检查要求")
    # 执行指令
    implementation: list[str] = Field(default_factory=list, description="具体实现步骤")
    verification: list[str] = Field(
        default_factory=list, description="验证步骤: lint / test / scenario"
    )
    done_when: str = Field(
        default="", description="完成条件: 可验证的自然语言描述"
    )


class PlanChangeRequest(BaseModel):
    """Plan 变更请求 —— 当 EXECUTE 发现必须偏离 Plan 时提交。"""

    task_id: str = Field(description="关联的 task id")
    reason: str = Field(description="变更原因")
    what_changes: str = Field(description="计划变更的内容")
    affected_files: list[str] = Field(
        default_factory=list, description="新增的变更文件"
    )
    budget_delta: int = Field(default=0, description="预算增量 (文件数)")
    risk_increased: bool = Field(default=False, description="风险是否升级")
    affects_spec: bool = Field(default=False, description="是否影响 Spec")
    affects_scenario: bool = Field(default=False, description="是否影响 Scenario")
    needs_user_approval: bool = Field(default=False, description="是否需要用户确认")
    approved: bool = Field(default=False, description="是否已批准")


class PlanComplianceReport(BaseModel):
    """Plan 合规性报告 —— REVIEW 阶段产出。"""

    contract_id: str = Field(description="关联的合约 id")
    compliant: bool = Field(default=True, description="是否合规")
    violations: list[str] = Field(default_factory=list, description="违规项")
    budget_status: str = Field(default="OK", description="预算状态: OK / WARN / EXCEEDED")
    files_out_of_scope: list[str] = Field(default_factory=list, description="越权修改的文件")
    style_violations: list[str] = Field(default_factory=list, description="风格违规")
    suggestions: list[str] = Field(default_factory=list)


# ── Plan Quality Gate (架构 §8.6.10) ─────────────────────────────

class PlanQualityReport(BaseModel):
    """Plan 质量门禁报告。"""

    plan_id: str = Field(default="", description="Plan ID")
    score: float = Field(default=0.0, description="质量分数 0-100")
    passed: bool = Field(default=False, description="是否通过门禁")
    # 检查项
    covers_all_acceptance: bool = Field(default=False, description="是否覆盖 Spec 所有验收标准")
    all_tasks_have_boundaries: bool = Field(default=False, description="是否每个 Task 都有 allowedFiles/forbiddenFiles")
    all_tasks_bound_to_scenario: bool = Field(default=False, description="是否每个 Task 都绑定 Scenario/验证方式")
    all_tasks_have_style_contract: bool = Field(default=False, description="是否每个 Task 都引用 Style Contract")
    all_tasks_have_reuse_check: bool = Field(default=False, description="是否每个 Task 都有 Reuse Check")
    no_oversized_tasks: bool = Field(default=False, description="是否存在过大任务 (>5 files)")
    scope_creep_detected: bool = Field(default=False, description="是否存在范围膨胀")
    # 详情
    oversized_tasks: list[str] = Field(default_factory=list, description="过大的 Task ID")
    unverified_tasks: list[str] = Field(default_factory=list, description="无法验证的 Task ID")
    missing_coverage: list[str] = Field(default_factory=list, description="未覆盖的 Acceptance Criteria")
    suggestions: list[str] = Field(default_factory=list, description="改进建议")
