"""资源适配器抽象层（兼容层）。

实际实现已迁移到 engines.scenario.adapters 包。
本文件保留为向后兼容的 re-export 层。
"""

from __future__ import annotations

# Re-export from new adapters package
from .adapters.base import ResourceAdapter
from .adapters.http import HttpAdapter
from .adapters.log import LogAdapter
from .adapters.mq import MessageQueueAdapter
from .adapters.mysql import MysqlAdapter as DatabaseAdapter  # 向后兼容别名
from .adapters.redis_adapter import RedisAdapter
from .adapters import default_adapters

__all__ = [
    "ResourceAdapter",
    "HttpAdapter",
    "DatabaseAdapter",
    "RedisAdapter",
    "MessageQueueAdapter",
    "LogAdapter",
    "default_adapters",
]
