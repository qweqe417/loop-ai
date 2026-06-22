"""Memory 数据模型。

三层架构：
1. SessionMemory — 单次任务的临时记忆 → .ai/memory/sessions/
2. Canonical Memory — 项目权威记忆（.ai/memory.md 索引 + entries/ 明细）
3. Tool Projection — 工具投影（.ai/memory/projections/）
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MemoryCategory(str, Enum):
    """记忆条目分类。"""

    RULE = "rule"                        # 通用开发规则
    PITFALL = "pitfall"                  # 历史坑和易错点
    VERIFICATION = "verification"        # 验证方式、场景、回归检查
    TESTING = "testing"                  # 测试经验
    MODULE_BOUNDARY = "module_boundary"  # 模块职责边界
    ARCHITECTURE = "architecture"        # 架构决策和原则
    FAILURE_PATTERN = "failure_pattern"  # 常见失败模式及修复路径
    PROHIBITED = "prohibited"            # 明确禁止事项
    CODE_STYLE = "code_style"            # 稳定的风格规范


class Confidence(str, Enum):
    """条目置信度。"""
    CONFIRMED = "confirmed"     # 已验证有效，可投影
    DRAFT = "draft"             # 候选记忆，存但不强投影
    DEPRECATED = "deprecated"   # 已过时，保留历史，不参与默认召回


class MemoryEntry(BaseModel):
    """单条持久化记忆。

    memory.md 索引行只放摘要；完整正文存 entries/{id}.md。

    3 段式结构（格式校验强制要求）：
    - trigger_conditions: 触发条件（何时相关）
    - error_pattern: 错误模式（发生了什么）
    - fix_rule: 修复规则（具体怎么做）
    """

    id: str = Field(description="唯一标识，如 rule-001, pitfall-003")
    category: MemoryCategory = Field(description="分类")
    title: str = Field(description="简短标题（1 句话）")
    content: str = Field(description="1~3 句结论（存于 memory.md 索引行）")
    source: str = Field(default="manual", description="来源 task_id 或 manual")
    confidence: Confidence = Field(default=Confidence.DRAFT)
    tags: list[str] = Field(default_factory=list, description="标签")
    hit_count: int = Field(default=0, description="召回命中次数")
    last_hit_at: datetime | None = Field(default=None, description="最近一次被召回的时间")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    # ── 3 段式字段 ──────────────────────────────────────
    trigger_conditions: str = Field(default="", description="触发条件：什么场景下这条记忆相关")
    error_pattern: str = Field(default="", description="错误模式：踩了什么坑、发生了什么")
    fix_rule: str = Field(default="", description="修复规则：必须/禁止/检查/确保 做什么")

    # ── 关系图谱 ────────────────────────────────────────
    relates_to: list[str] = Field(default_factory=list, description="关联记忆 ID（双向）")
    caused_by: list[str] = Field(default_factory=list, description="由哪些记忆导致（因果）")
    fixed_by: list[str] = Field(default_factory=list, description="通过哪些记忆修复")

    # ── 效果追踪 ────────────────────────────────────────
    effective_count: int = Field(default=0, description="有效次数（修复规则被应用且通过验证）")
    ineffective_count: int = Field(default=0, description="无效次数（本该应用但被忽略，验证失败）")

    def summary_line(self) -> str:
        """生成索引行，写入 memory.md。只放摘要，不放元数据。"""
        conf = self.confidence.value
        tags_str = ",".join(self.tags) if self.tags else ""
        return f"- [{self.id}] {self.title} `[{conf}]` `[{tags_str}]`"

    def record_hit(self) -> None:
        """记录一次召回命中。"""
        self.hit_count += 1
        self.last_hit_at = datetime.now()

    def record_effective(self) -> None:
        """记录一次有效应用。"""
        self.effective_count += 1

    def record_ineffective(self) -> None:
        """记录一次无效（被忽略）。"""
        self.ineffective_count += 1

    @property
    def is_3segment_valid(self) -> bool:
        """3 段式格式校验：每段至少 20 字符。"""
        return (
            len(self.trigger_conditions.strip()) >= 20
            and len(self.error_pattern.strip()) >= 20
            and len(self.fix_rule.strip()) >= 20
        )


class SessionMemory(BaseModel):
    """单次 Loop 任务的临时记录 → .ai/memory/sessions/{task_id}.json。"""

    task_id: str = Field(description="关联的任务 ID")
    related_spec: str = Field(default="", description="关联的 Spec 标识")
    failures: list[dict[str, Any]] = Field(
        default_factory=list, description="失败记录摘要"
    )
    decisions: list[dict[str, Any]] = Field(
        default_factory=list, description="关键决策摘要"
    )
    patterns_observed: list[str] = Field(
        default_factory=list, description="观察到的模式"
    )
    candidates: list[dict[str, Any]] = Field(
        default_factory=list, description="待沉淀的记忆候选"
    )
    notes: list[str] = Field(default_factory=list, description="备注")
    started_at: datetime = Field(default_factory=datetime.now)
    completed_at: datetime | None = Field(default=None)


class MemoryGovernance(BaseModel):
    """记忆系统运营面板数据 → .ai/memory/stats.json。

    不是给 AI 读正文，而是给系统管理 memory 用的。
    """

    total_entries: int = 0
    by_category: dict[str, int] = Field(default_factory=dict)
    confirmed: int = 0
    draft: int = 0
    deprecated: int = 0
    archived: int = 0
    last_updated: str = ""
    last_compression: str = ""           # 最近一次压缩时间
    last_archival: str = ""              # 最近一次归档时间
    last_projection: str = ""            # 最近一次投影时间
    hot_tags: list[dict[str, Any]] = Field(default_factory=list)  # [{tag, count}]
    cold_entries: list[str] = Field(default_factory=list)  # 长期未命中的 entry id


class MemoryStats(BaseModel):
    """记忆库统计（兼容旧接口）。"""

    total_entries: int = 0
    by_category: dict[str, int] = Field(default_factory=dict)
    confirmed: int = 0
    draft: int = 0
    deprecated: int = 0
    last_updated: str = ""
