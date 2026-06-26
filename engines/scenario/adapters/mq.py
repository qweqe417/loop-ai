"""消息队列适配器。

支持 RabbitMQ（pika）真实连接，未安装时 fallback 到内存模拟。
"""

from __future__ import annotations

import logging
from typing import Any

from .base import ResourceAdapter

logger = logging.getLogger(__name__)


class MessageQueueAdapter(ResourceAdapter):
    """消息队列适配器 —— peek / count / publish / consume。"""

    adapter_type = "rabbitmq"
    adapter_label = "RabbitMQ"
    supported_assertions = {"mq_message"}
    default_port = 5672

    # ── 内存 fallback 存储（类级别共享）──
    _mem_queues: dict[str, list[dict[str, Any]]] = {}

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5672,
        user: str = "guest",
        password: str = "guest",
        virtual_host: str = "/",
        **kwargs: Any,
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._virtual_host = virtual_host
        self._connection: Any = None
        self._channel: Any = None
        self._real = False

    # ── 生命周期 ──

    def connect(self) -> bool:
        try:
            import pika
            credentials = pika.PlainCredentials(self._user, self._password)
            params = pika.ConnectionParameters(
                host=self._host,
                port=self._port,
                virtual_host=self._virtual_host,
                credentials=credentials,
                connection_attempts=2,
                retry_delay=2,
            )
            self._connection = pika.BlockingConnection(params)
            self._channel = self._connection.channel()
            self._real = True
            logger.info("RabbitMQ 连接成功: %s:%s", self._host, self._port)
            return True
        except ImportError:
            logger.warning("pika 未安装，使用内存模拟。pip install pika")
            self._real = False
            return True
        except Exception as exc:
            logger.warning("RabbitMQ 连接失败 [%s:%s]: %s，使用内存模拟",
                           self._host, self._port, exc)
            self._real = False
            return True

    def disconnect(self) -> None:
        if self._connection and self._real:
            try:
                self._connection.close()
            except Exception:
                pass
        self._connection = None
        self._channel = None
        self._real = False

    def is_healthy(self) -> bool:
        if self._real and self._connection:
            try:
                return self._connection.is_open
            except Exception:
                return False
        return True

    # ── 核心操作 ──

    def execute(self, action: str, target: str, **params: Any) -> Any:
        """执行 MQ 操作。

        Args:
            action: peek / count / publish / consume
            target: queue 名称
            params: data（消息内容）

        Returns:
            操作结果
        """
        if self._real and self._channel:
            return self._execute_real(action, target, **params)
        return self._execute_mem(action, target, **params)

    def _execute_real(self, action: str, target: str, **params: Any) -> Any:
        ch = self._channel
        if action == "peek":
            # RabbitMQ get + requeue
            method_frame, _header, body = ch.basic_get(queue=target, auto_ack=False)
            if method_frame:
                ch.basic_nack(delivery_tag=method_frame.delivery_tag, requeue=True)
                return {"id": method_frame.delivery_tag, "data": body.decode("utf-8", errors="replace")}
            return None
        elif action == "count":
            # 声明队列获取消息数
            result = ch.queue_declare(queue=target, passive=True)
            return result.method.message_count
        elif action == "publish":
            import json
            body = json.dumps(params.get("data", {}), ensure_ascii=False)
            ch.basic_publish(exchange="", routing_key=target, body=body)
            return {"published": True}
        elif action == "consume":
            method_frame, _header, body = ch.basic_get(queue=target, auto_ack=True)
            if method_frame:
                return {"id": method_frame.delivery_tag, "data": body.decode("utf-8", errors="replace")}
            return None
        else:
            return {"error": f"MessageQueueAdapter 不支持 action: {action}"}

    def _execute_mem(self, action: str, target: str, **params: Any) -> Any:
        if target not in self._mem_queues:
            self._mem_queues[target] = []

        queue = self._mem_queues[target]

        if action == "peek":
            return queue[0] if queue else None
        elif action == "count":
            return len(queue)
        elif action == "publish":
            msg = {
                "id": len(queue),
                "data": params.get("data"),
                "timestamp": params.get("timestamp", ""),
            }
            queue.append(msg)
            return {"published": True, "message_id": msg["id"]}
        elif action == "consume":
            return queue.pop(0) if queue else None
        else:
            return {"error": f"MessageQueueAdapter 不支持 action: {action}"}

    @classmethod
    def clear(cls) -> None:
        """重置内存队列（每个 Scenario 前调用）。"""
        cls._mem_queues.clear()
