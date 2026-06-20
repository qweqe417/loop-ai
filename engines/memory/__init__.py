"""Memory 模块 —— 项目经验持久化与跨工具同步。

三层架构：
1. SessionMemory — 单次任务的临时记忆
2. .ai/memory.md — 项目权威记忆（MemoryStore 读写）
3. 工具投影 — CLAUDE.md / .codex/ / .cursor/ (MemoryProjection 同步)

流程：
    RunState → MemoryExtractor → MemoryStore → MemoryProjection
"""

from .models import (
    Confidence,
    MemoryCategory,
    MemoryEntry,
    MemoryStats,
    SessionMemory,
)
from .store import MemoryStore
from .extractor import MemoryExtractor
from .projection import MemoryProjection

__all__ = [
    # 模型
    "MemoryCategory",
    "Confidence",
    "MemoryEntry",
    "SessionMemory",
    "MemoryStats",
    # 存储
    "MemoryStore",
    # 提取
    "MemoryExtractor",
    # 投影
    "MemoryProjection",
]
