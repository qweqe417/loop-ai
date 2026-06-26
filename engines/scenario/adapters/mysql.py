"""MySQL 数据库适配器。

连接参数从 loop-config.json data_sources 读取。
fallback: pymysql 未安装时给出明确提示。
"""

from __future__ import annotations

import logging
from typing import Any

from .base import ResourceAdapter

logger = logging.getLogger(__name__)


class MysqlAdapter(ResourceAdapter):
    """MySQL 数据库适配器 —— 只读查询 + 计数。"""

    adapter_type = "mysql"
    adapter_label = "MySQL"
    supported_assertions = {"db_query", "db_count"}
    default_port = 3306

    def __init__(
        self,
        host: str = "localhost",
        port: int = 3306,
        user: str = "root",
        password: str = "",
        database: str = "test",
        **kwargs: Any,
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._database = database
        self._conn: Any = None
        self._cursor: Any = None

    # ── 生命周期 ──

    def connect(self) -> bool:
        try:
            import pymysql
            self._conn = pymysql.connect(
                host=self._host,
                port=self._port,
                user=self._user,
                password=self._password,
                database=self._database,
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor,
            )
            self._cursor = self._conn.cursor()
            return True
        except ImportError:
            logger.error(
                "pymysql 未安装。请执行: pip install pymysql"
            )
            return False
        except Exception as exc:
            logger.error("MySQL 连接失败 [%s:%s/%s]: %s",
                         self._host, self._port, self._database, exc)
            return False

    def disconnect(self) -> None:
        if self._cursor:
            try:
                self._cursor.close()
            except Exception:
                pass
            self._cursor = None
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def is_healthy(self) -> bool:
        try:
            import pymysql
            conn = pymysql.connect(
                host=self._host,
                port=self._port,
                user=self._user,
                password=self._password,
                database=self._database,
                charset="utf8mb4",
                connect_timeout=5,
            )
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            conn.close()
            return True
        except ImportError:
            return False
        except Exception:
            return False

    # ── 核心操作 ──

    def execute(self, action: str, target: str, **params: Any) -> Any:
        """执行数据库操作。

        Args:
            action: query（SELECT，返回 list[dict]）
                    count（返回 int）
                    execute（INSERT/UPDATE/DELETE，返回 affected_rows）
            target: SQL 语句
            params: data（绑定参数元组）

        Returns:
            query: list[dict]
            count: int
            execute: {"affected_rows": int}
        """
        if self._conn is None:
            if not self.connect():
                return {"error": "MySQL 连接失败，请检查 loop-config.json data_sources.mysql 配置"}

        data = params.get("data") or params.get("params") or ()

        try:
            if action == "count":
                return self._do_count(target, data)
            elif action == "query":
                return self._do_query(target, data)
            elif action == "execute":
                return self._do_execute(target, data)
            elif action == "insert":
                return self._do_insert(target, data)
            elif action == "delete":
                return self._do_delete(target, data)
            else:
                return {"error": f"MysqlAdapter 不支持 action: {action}"}
        except Exception as exc:
            logger.error("MySQL 操作失败: %s", exc)
            return {"error": str(exc)}

    def _do_query(self, sql: str, data: Any) -> list[dict]:
        self._cursor.execute(sql, data)
        rows = self._cursor.fetchall()
        return [dict(r) for r in rows]

    def _do_count(self, sql: str, data: Any) -> int:
        # 尝试直接执行，失败则包装为 SELECT COUNT(*)
        try:
            self._cursor.execute(sql, data)
            row = self._cursor.fetchone()
            if row is not None:
                val = list(row.values())[0] if isinstance(row, dict) else row[0]
                try:
                    return int(val) if val is not None else 0
                except (TypeError, ValueError):
                    return 0
            return 0
        except Exception:
            wrapped = f"SELECT COUNT(*) FROM ({sql}) AS _count_sub"
            self._cursor.execute(wrapped, data)
            row = self._cursor.fetchone()
            if row is not None:
                val = list(row.values())[0] if isinstance(row, dict) else row[0]
                return int(val) if val else 0
            return 0

    def _do_execute(self, sql: str, data: Any) -> dict:
        """执行 INSERT/UPDATE/DELETE，返回 affected_rows。"""
        self._cursor.execute(sql, data)
        self._conn.commit()
        return {"affected_rows": self._cursor.rowcount}

    def _do_insert(self, table: str, rows: Any) -> dict:
        """INSERT INTO 表名，自动从 data 推断列名。

        Args:
            table: 表名
            rows: list[dict] 或 dict，每行一个 dict，key=列名

        Returns:
            {"affected_rows": int} 或 {"error": str}
        """
        if not rows:
            return {"error": "insert 缺少 data（需要 list[dict] 或 dict）"}
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list) or len(rows) == 0:
            return {"error": "insert data 必须是 list[dict] 或非空 dict"}

        columns = list(rows[0].keys())
        placeholders = ", ".join(["%s"] * len(columns))
        cols_str = ", ".join(columns)
        sql = f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders})"

        affected = 0
        for row in rows:
            values = [row.get(c) for c in columns]
            self._cursor.execute(sql, values)
            affected += self._cursor.rowcount
        self._conn.commit()
        return {"affected_rows": affected}

    def _do_delete(self, table: str, conditions: Any) -> dict:
        """DELETE FROM 表名 WHERE 条件。

        安全策略：禁止无条件 DELETE（必须传 WHERE 条件）。

        Args:
            table: 表名
            conditions: dict，key=列名 value=值，AND 连接

        Returns:
            {"affected_rows": int} 或 {"error": str}
        """
        if not conditions:
            return {"error": "delete 缺少 WHERE 条件（安全策略：禁止无条件删除）"}
        if not isinstance(conditions, dict):
            return {"error": "delete data 必须是 dict（WHERE 条件键值对）"}

        where_parts = [f"{k}=%s" for k in conditions.keys()]
        where_clause = " AND ".join(where_parts)
        values = list(conditions.values())

        sql = f"DELETE FROM {table} WHERE {where_clause}"
        self._cursor.execute(sql, values)
        self._conn.commit()
        return {"affected_rows": self._cursor.rowcount}

    def clear(self) -> None:
        """每个 Scenario 前重置连接状态。"""
        self.disconnect()
