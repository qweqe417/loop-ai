"""资源适配器抽象层。

定义连接外部资源（HTTP 服务、MySQL、Redis、MQ、日志）的抽象接口。
具体实现由 Plugin 层通过 MCP / CLI / SDK 提供。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ResourceAdapter(ABC):
    """资源适配器基类。

    每种资源类型一个子类实现，ScenarioRunner 通过适配器访问外部资源。
    默认安全策略：只读、只连测试环境、不禁用生产连接。
    """

    name: str = ""

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
        """健康检查。"""
        ...

    @abstractmethod
    def execute(self, action: str, target: str, **params: Any) -> Any:
        """执行资源操作，返回结果。"""
        ...


class HttpAdapter(ResourceAdapter):
    """HTTP 服务适配器 —— 调用被测服务的 API。"""

    name = "http"

    def __init__(self, base_url: str = "http://localhost:8080", timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def connect(self) -> bool:
        # TODO: 实际通过 requests / httpx 连接
        return True

    def disconnect(self) -> None:
        pass

    def is_healthy(self) -> bool:
        import urllib.request
        try:
            urllib.request.urlopen(f"{self.base_url}/", timeout=self.timeout)
            return True
        except Exception:
            return False

    def execute(self, action: str, target: str, **params: Any) -> Any:
        """执行 HTTP 请求。

        action: GET / POST / PUT / DELETE / PATCH
        target: /api/xxx
        params: body, headers, query
        """
        import json as _json
        import urllib.error
        import urllib.request as _request

        url = f"{self.base_url}{target}"
        body_data = params.get("body")
        headers = {k.lower(): v for k, v in (params.get("headers") or {}).items()}
        query = params.get("query") or {}

        # 添加 query string
        if query:
            from urllib.parse import urlencode
            url = f"{url}?{urlencode(query)}"

        # 编码 body
        data_bytes: bytes | None = None
        if body_data is not None:
            if isinstance(body_data, (dict, list)):
                data_bytes = _json.dumps(body_data, ensure_ascii=False).encode("utf-8")
                headers.setdefault("content-type", "application/json")
            elif isinstance(body_data, bytes):
                data_bytes = body_data
            else:
                data_bytes = str(body_data).encode("utf-8")

        method = action.upper()
        req = _request.Request(url, data=data_bytes, method=method)
        for k, v in headers.items():
            req.add_header(k, v)

        try:
            with _request.urlopen(req, timeout=self.timeout) as resp:
                raw_body = resp.read()
                status = resp.status
                resp_headers = dict(resp.headers.items())
        except urllib.error.HTTPError as exc:
            raw_body = exc.read()
            status = exc.code
            resp_headers = dict(exc.headers.items())
        except urllib.error.URLError as exc:
            return {"status": 0, "body": None, "headers": {}, "error": str(exc.reason)}

        # 解析 body
        content_type = resp_headers.get("content-type", resp_headers.get("Content-Type", ""))
        parsed_body: Any = raw_body.decode("utf-8", errors="replace")
        if "json" in content_type and raw_body:
            try:
                parsed_body = _json.loads(raw_body)
            except _json.JSONDecodeError:
                pass

        return {"status": status, "body": parsed_body, "headers": resp_headers}


class DatabaseAdapter(ResourceAdapter):
    """数据库适配器 —— 查询 MySQL / PostgreSQL / SQLite 等。"""

    name = "database"

    def __init__(self, dsn: str = ":memory:") -> None:
        self.dsn = dsn
        self._conn: Any = None

    def connect(self) -> bool:
        import sqlite3
        try:
            self._conn = sqlite3.connect(self.dsn, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            return True
        except Exception:
            return False

    def disconnect(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def is_healthy(self) -> bool:
        try:
            import sqlite3
            conn = sqlite3.connect(self.dsn, check_same_thread=False)
            conn.execute("SELECT 1")
            conn.close()
            return True
        except Exception:
            return False

    def execute(self, action: str, target: str, **params: Any) -> Any:
        """执行数据库操作。

        action: query / count / exec
        target: SQL 语句
        params: data (绑定参数)
        """
        import sqlite3

        if self._conn is None:
            self.connect()
        if self._conn is None:
            raise RuntimeError("DatabaseAdapter: 无法连接到数据库")

        conn = self._conn
        data = params.get("data") or params.get("params") or ()

        if action == "count":
            try:
                cursor = conn.execute(target, data)
                row = cursor.fetchone()
                if row is not None:
                    # sqlite3.Row / tuple / list — 取第一列
                    val = row[0]
                    try:
                        return int(val) if val is not None else 0
                    except (TypeError, ValueError):
                        return 0
                return 0
            except sqlite3.Error:
                try:
                    wrapped = f"SELECT COUNT(*) FROM ({target})"
                    cursor = conn.execute(wrapped, data)
                    row = cursor.fetchone()
                    return int(row[0]) if row else 0
                except Exception as exc:
                    return {"error": str(exc), "rows": []}

        elif action == "query":
            try:
                cursor = conn.execute(target, data)
                rows = cursor.fetchall()
                return [dict(r) for r in rows]
            except Exception as exc:
                return {"error": str(exc), "rows": []}

        elif action == "exec":
            try:
                cursor = conn.execute(target, data)
                conn.commit()
                return cursor.rowcount
            except Exception as exc:
                return {"error": str(exc), "rowcount": 0}

        else:
            raise ValueError(f"DatabaseAdapter 不支持 action: {action}")


class RedisAdapter(ResourceAdapter):
    """Redis 适配器 —— 查询缓存状态（内存模拟）。"""

    name = "redis"

    # 会话级共享存储，使 scenario 的 setup 和 assertion 可共享同一份数据
    _store: dict[str, Any] = {}
    _hash_store: dict[str, dict[str, Any]] = {}
    _ttl_store: dict[str, float] = {}

    def __init__(self, url: str = "redis://localhost:6379") -> None:
        self.url = url

    def connect(self) -> bool:
        return True

    def disconnect(self) -> None:
        pass

    def is_healthy(self) -> bool:
        return True

    def execute(self, action: str, target: str, **params: Any) -> Any:
        """执行 Redis 操作（内存模拟）。

        action: get / set / exists / del / ttl / keys / hget / hset / lrange
        target: key 名
        params: value, field, start, stop
        """
        import fnmatch
        import time as _time

        if action == "get":
            return self._store.get(target)

        elif action == "set":
            value = params.get("value")
            self._store[target] = value
            ttl = params.get("ttl") or params.get("expire")
            if ttl is not None:
                self._ttl_store[target] = _time.time() + float(ttl)
            return "OK"

        elif action == "exists":
            return 1 if target in self._store or target in self._hash_store else 0

        elif action == "del":
            count = 0
            keys = [target] if target != "*" else list(self._store.keys())
            for k in keys:
                if k in self._store:
                    del self._store[k]
                    count += 1
                if k in self._hash_store:
                    del self._hash_store[k]
                    count += 1
            return count

        elif action == "ttl":
            expire_at = self._ttl_store.get(target)
            if expire_at is None:
                return -1
            remaining = expire_at - _time.time()
            return max(0, int(remaining))

        elif action == "keys":
            pattern = target or "*"
            matched = []
            for k in list(self._store.keys()) + list(self._hash_store.keys()):
                if fnmatch.fnmatch(k, pattern):
                    matched.append(k)
            # deduplicate
            return list(dict.fromkeys(matched))

        elif action == "hget":
            if target not in self._hash_store:
                return None
            field = params.get("field", "")
            return self._hash_store[target].get(field)

        elif action == "hset":
            if target not in self._hash_store:
                self._hash_store[target] = {}
            field = params.get("field", "")
            value = params.get("value")
            is_new = field not in self._hash_store[target]
            self._hash_store[target][field] = value
            return 1 if is_new else 0

        elif action == "lrange":
            lst = self._store.get(target, [])
            if not isinstance(lst, list):
                return []
            start = int(params.get("start", 0))
            stop = int(params.get("stop", -1))
            if stop == -1:
                stop = len(lst)
            else:
                stop += 1  # Redis inclusive → Python exclusive
            return lst[start:stop]

        else:
            raise ValueError(f"RedisAdapter 不支持 action: {action}")


class MessageQueueAdapter(ResourceAdapter):
    """消息队列适配器 —— 验证消息发送/消费（内存模拟）。"""

    name = "mq"

    # 会话级共享存储
    _queues: dict[str, list[dict[str, Any]]] = {}

    def __init__(self) -> None:
        pass

    def connect(self) -> bool:
        return True

    def disconnect(self) -> None:
        pass

    def is_healthy(self) -> bool:
        return True

    def execute(self, action: str, target: str, **params: Any) -> Any:
        """执行 MQ 操作（内存模拟）。

        action: publish / consume / peek / count
        target: queue / topic 名称
        params: data (消息内容)
        """
        if target not in self._queues:
            self._queues[target] = []

        if action == "publish":
            msg = {
                "id": len(self._queues[target]),
                "data": params.get("data"),
                "timestamp": params.get("timestamp", ""),
            }
            self._queues[target].append(msg)
            return {"published": True, "message_id": msg["id"]}

        elif action == "consume":
            if self._queues[target]:
                return self._queues[target].pop(0)
            return None

        elif action == "peek":
            if self._queues[target]:
                return self._queues[target][0]
            return None

        elif action == "count":
            return len(self._queues[target])

        else:
            raise ValueError(f"MessageQueueAdapter 不支持 action: {action}")


class LogAdapter(ResourceAdapter):
    """日志适配器 —— 查询应用日志（文件 I/O）。"""

    name = "log"

    # 可配置的日志文件路径，通过 fixture 或参数设置
    _log_file: str = ""

    def __init__(self, log_file: str = "") -> None:
        self._log_file = log_file or "app.log"

    def connect(self) -> bool:
        from pathlib import Path
        return Path(self._log_file).exists()

    def disconnect(self) -> None:
        pass

    def is_healthy(self) -> bool:
        from pathlib import Path
        return Path(self._log_file).exists()

    def execute(self, action: str, target: str, **params: Any) -> Any:
        """执行日志查询。

        action: search / tail
        target: 搜索关键词 (search) 或忽略 (tail)
        params: file (日志文件路径，覆盖默认), lines (tail 行数), max_lines (search 最大行数)
        """
        file_path = params.get("file") or self._log_file

        try:
            with open(file_path, encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
        except FileNotFoundError:
            return {"error": f"日志文件不存在: {file_path}", "lines": []}
        except Exception as exc:
            return {"error": str(exc), "lines": []}

        if action == "search":
            max_lines = int(params.get("max_lines", 500))
            matched = []
            for line in all_lines[:max_lines]:
                if target in line:
                    matched.append(line.rstrip("\n"))
            return {"matches": len(matched), "lines": matched}

        elif action == "tail":
            n = int(params.get("lines", 50))
            return {"lines": [line.rstrip("\n") for line in all_lines[-n:]]}

        else:
            raise ValueError(f"LogAdapter 不支持 action: {action}")


# ── 适配器注册表 ──────────────────────────────────────────────

def default_adapters() -> dict[str, ResourceAdapter]:
    """返回默认的资源适配器集合。"""
    return {
        "http": HttpAdapter(),
        "database": DatabaseAdapter(),
        "redis": RedisAdapter(),
        "mq": MessageQueueAdapter(),
        "log": LogAdapter(),
    }
