"""Redis 缓存适配器。

连接参数从 loop-config.json data_sources 读取。
真实连接使用 redis-py；未安装时 fallback 到内存模拟。
"""

from __future__ import annotations

import logging
from typing import Any

from .base import ResourceAdapter

logger = logging.getLogger(__name__)


class RedisAdapter(ResourceAdapter):
    """Redis 缓存适配器 —— 读/写/存在性检查。"""

    adapter_type = "redis"
    adapter_label = "Redis"
    supported_assertions = {"redis_key", "redis_value"}
    default_port = 6379

    # ── 内存 fallback 存储（类级别共享）──
    _mem_store: dict[str, Any] = {}
    _mem_hash: dict[str, dict[str, Any]] = {}
    _mem_ttl: dict[str, float] = {}

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        password: str = "",
        db: int = 0,
        **kwargs: Any,
    ) -> None:
        self._host = host
        self._port = port
        self._password = password or None
        self._db = db
        self._client: Any = None
        self._real = False  # 是否连接了真实 Redis

    # ── 生命周期 ──

    def connect(self) -> bool:
        try:
            import redis
            self._client = redis.Redis(
                host=self._host,
                port=self._port,
                password=self._password,
                db=self._db,
                decode_responses=True,
                socket_connect_timeout=5,
            )
            self._client.ping()
            self._real = True
            logger.info("Redis 连接成功: %s:%s db=%s", self._host, self._port, self._db)
            return True
        except ImportError:
            logger.warning("redis-py 未安装，使用内存模拟。pip install redis")
            self._real = False
            return True  # 内存模式也算可用
        except Exception as exc:
            logger.warning("Redis 连接失败 [%s:%s]: %s，使用内存模拟",
                           self._host, self._port, exc)
            self._real = False
            return True  # 降级到内存模式

    def disconnect(self) -> None:
        if self._client and self._real:
            try:
                self._client.close()
            except Exception:
                pass
        self._client = None
        self._real = False

    def is_healthy(self) -> bool:
        if self._real and self._client:
            try:
                self._client.ping()
                return True
            except Exception:
                return False
        return True  # 内存模式始终"健康"

    # ── 核心操作 ──

    def execute(self, action: str, target: str, **params: Any) -> Any:
        """执行 Redis 操作。

        Args:
            action: get / set / exists / del / ttl / keys / hget / hset
            target: key 名
            params: value, field, ttl

        Returns:
            操作结果
        """
        if self._real and self._client:
            return self._execute_real(action, target, **params)
        return self._execute_mem(action, target, **params)

    def _execute_real(self, action: str, target: str, **params: Any) -> Any:
        # CLI 通用 action 映射
        if action == "query":
            # 智能判断：target 含 * 或 ? → keys, 否则 → get
            if "*" in target or "?" in target:
                return r.keys(target)
            return r.get(target)
        elif action == "execute":
            # 有 value → set, 无 value → del
            if "value" in params:
                return r.set(target, params["value"])
            return r.delete(target)

        r = self._client
        if action == "get":
            return r.get(target)
        elif action == "set":
            value = params.get("value")
            ttl = params.get("ttl") or params.get("expire")
            if ttl:
                return r.setex(target, int(ttl), value)
            return r.set(target, value)
        elif action == "exists":
            return r.exists(target)
        elif action == "del":
            return r.delete(target)
        elif action == "ttl":
            return r.ttl(target)
        elif action == "keys":
            return r.keys(target or "*")
        elif action == "hget":
            return r.hget(target, params.get("field", ""))
        elif action == "hset":
            field = params.get("field", "")
            value = params.get("value")
            return r.hset(target, field, value)
        else:
            return {"error": f"RedisAdapter 不支持 action: {action}"}

    def _execute_mem(self, action: str, target: str, **params: Any) -> Any:
        import fnmatch
        import time as _time

        store = self._mem_store
        hash_store = self._mem_hash
        ttl_store = self._mem_ttl

        # CLI 通用 action 映射
        if action == "query":
            if "*" in target or "?" in target:
                pattern = target
                matched = []
                for k in list(store.keys()) + list(hash_store.keys()):
                    if fnmatch.fnmatch(k, pattern):
                        matched.append(k)
                return list(dict.fromkeys(matched))
            return store.get(target)
        elif action == "execute":
            if "value" in params:
                store[target] = params["value"]
                return "OK"
            count = 0
            if target in store:
                del store[target]
                count += 1
            if target in hash_store:
                del hash_store[target]
                count += 1
            return count

        if action == "get":
            return store.get(target)
        elif action == "set":
            value = params.get("value")
            store[target] = value
            ttl = params.get("ttl") or params.get("expire")
            if ttl is not None:
                ttl_store[target] = _time.time() + float(ttl)
            return "OK"
        elif action == "exists":
            return 1 if target in store or target in hash_store else 0
        elif action == "del":
            count = 0
            if target in store:
                del store[target]
                count += 1
            if target in hash_store:
                del hash_store[target]
                count += 1
            return count
        elif action == "ttl":
            expire_at = ttl_store.get(target)
            if expire_at is None:
                return -1
            return max(0, int(expire_at - _time.time()))
        elif action == "keys":
            pattern = target or "*"
            matched = []
            for k in list(store.keys()) + list(hash_store.keys()):
                if fnmatch.fnmatch(k, pattern):
                    matched.append(k)
            return list(dict.fromkeys(matched))
        elif action == "hget":
            if target not in hash_store:
                return None
            return hash_store[target].get(params.get("field", ""))
        elif action == "hset":
            if target not in hash_store:
                hash_store[target] = {}
            field = params.get("field", "")
            value = params.get("value")
            is_new = field not in hash_store[target]
            hash_store[target][field] = value
            return 1 if is_new else 0
        else:
            return {"error": f"RedisAdapter 不支持 action: {action}"}

    @classmethod
    def clear(cls) -> None:
        """重置内存存储（每个 Scenario 前调用）。"""
        cls._mem_store.clear()
        cls._mem_hash.clear()
        cls._mem_ttl.clear()
