"""资源适配器基类。

每种外部资源（HTTP、MySQL、Redis、MQ、ES ...）一个 Adapter 子类。
项目级扩展丢到 .ai/adapters/*.py，引擎启动时自动发现。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ResourceAdapter(ABC):
    """资源适配器抽象基类。

    子类需声明:
      - adapter_type:   对应 loop-config.json data_sources.<key>.type
      - adapter_label:  人类可读名称
      - supported_assertions: 能处理的断言类型集合 (db_query / redis_key / ...)

    默认安全策略：只读、只连测试环境。
    """

    # ── 子类必须覆盖的类属性 ──
    adapter_type: str = ""           # "mysql" / "redis" / "rabbitmq" / "elasticsearch"
    adapter_label: str = ""          # "MySQL" / "Redis" / "RabbitMQ"
    supported_assertions: set[str] = set()  # {"db_query", "db_count"} / {"redis_key", "redis_value"}
    default_port: int = 0            # 默认端口号，sanity check 用

    # ── 生命周期 ──

    @abstractmethod
    def connect(self) -> bool:
        """建立连接，返回是否成功。"""
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """断开连接。"""
        ...

    @abstractmethod
    def is_healthy(self) -> bool:
        """健康检查，返回资源是否可用。"""
        ...

    @abstractmethod
    def execute(self, action: str, target: str, **params: Any) -> Any:
        """执行资源操作。

        Args:
            action: 操作类型（query / count / get / set / peek / ...）
            target: 操作目标（SQL / key / queue / ...）
            **params: 额外参数

        Returns:
            操作结果
        """
        ...

    def clear(self) -> None:
        """重置适配器状态（每个 Scenario 执行前调用）。"""
        pass
