"""Memory 模块 —— 项目经验持久化与跨工具同步。

三层架构：
1. SessionMemory — 单次任务的临时记忆 → .ai/memory/sessions/
2. Canonical Memory — 权威源 .ai/memory.md (索引) + entries/ (明细)
3. Tool Projection — .ai/memory/projections/ + 工具文件注入

流程：
    RunState → MemoryExtractor → MemoryStore → MemoryProjection
"""

from .models import (
    Confidence,
    MemoryCategory,
    MemoryEntry,
    MemoryGovernance,
    MemoryStats,
    SessionMemory,
)
from .store import (
    MemoryStore,
    CATEGORY_TO_SECTION,
    SECTION_ORDER,
    STAGE_RECALL_PRIORITY,
)
from .extractor import MemoryExtractor
from .projection import MemoryProjection

__all__ = [
    # 模型
    "MemoryCategory",
    "Confidence",
    "MemoryEntry",
    "SessionMemory",
    "MemoryStats",
    "MemoryGovernance",
    # 存储
    "MemoryStore",
    "CATEGORY_TO_SECTION",
    "SECTION_ORDER",
    "STAGE_RECALL_PRIORITY",
    # 提取
    "MemoryExtractor",
    # 投影
    "MemoryProjection",
]
