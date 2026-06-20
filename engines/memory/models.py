"""Memory 数据模型。

定义记忆条目的分类、结构和会话记忆。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MemoryCategory(str, Enum):
    """记忆条目分类。"""

    CODE_STYLE = "code_style"            # 代码风格规范
    PITFALL = "pitfall"                  # 历史坑 / 踩过的坑
    MODULE_BOUNDARY = "module_boundary"  # 模块边界 / 职责划分
    TESTING = "testing"                  # 测试经验 / 验证方式
    ARCHITECTURE = "architecture"        # 架构决策 / 设计原则
    PROHIBITED = "prohibited"            # 禁止事项
    VERIFICATION = "verification"        # 验证模式 / scenario 模板
    FAILURE_PATTERN = "failure_pattern"  # 已识别的失败模式+修复方案
    RULE = "rule"                        # 通用规则


class Confidence(str, Enum):
    """条目置信度。"""
    CONFIRMED = "confirmed"   # 已验证，可投影到工具文件
    DRAFT = "draft"           # 待确认，只存 .ai/memory.md
    DEPRECATED = "deprecated"  # 已废弃，保留但不同步


class MemoryEntry(BaseModel):
    """单条持久化记忆 —— 存储在 .ai/memory.md。"""

    id: str = Field(description="唯一标识，如 style-001, pitfall-003")
    category: MemoryCategory = Field(description="分类")
    title: str = Field(description="简短标题")
    content: str = Field(description="完整内容（1-3 句话）")
    source: str = Field(default="manual", description="来源 task_id 或 manual")
    confidence: Confidence = Field(default=Confidence.CONFIRMED)
    tags: list[str] = Field(default_factory=list, description="标签")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def summary_line(self) -> str:
        """生成单行摘要，用于 markdown 渲染。"""
        return f"- [{self.id}] {self.title} (source: {self.source})"


class SessionMemory(BaseModel):
    """会话记忆 —— 单次 Loop 任务的临时记录。

    任务结束后，MemoryExtractor 从中筛选可沉淀的内容，
    转化为 MemoryEntry 写入 .ai/memory.md。
    """

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
    candidates: list[MemoryEntry] = Field(
        default_factory=list, description="待沉淀的记忆候选"
    )
    notes: list[str] = Field(default_factory=list, description="备注")
    started_at: datetime = Field(default_factory=datetime.now)
    completed_at: datetime | None = Field(default=None)


class MemoryStats(BaseModel):
    """记忆库统计。"""

    total_entries: int = 0
    by_category: dict[str, int] = Field(default_factory=dict)
    confirmed: int = 0
    draft: int = 0
    deprecated: int = 0
    last_updated: datetime | None = None
