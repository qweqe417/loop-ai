"""环境健康检查（Sanity Check）。

在 Scenario 执行前检查所需资源是否可用。
如果环境不可用，不进入代码修复 Loop，暂停并提示人工处理。
"""

from __future__ import annotations

import logging
import socket
import time
from typing import Any

from .models import SanityCheckItem, SanityCheckResult, SanityReport
from .resources import ResourceAdapter

logger = logging.getLogger(__name__)


class SanityChecker:
    """环境健康检查器。

    用法:
        checker = SanityChecker(adapters={"http": HttpAdapter(), ...})
        report = checker.check([
            SanityCheckItem(name="port-8080", resource="port", target="localhost:8080"),
            SanityCheckItem(name="mysql", resource="mysql", target="localhost:3306"),
        ])
        if not report.all_passed:
            raise EnvironmentError("环境不健康，暂停执行")
    """

    def __init__(
        self,
        adapters: dict[str, ResourceAdapter] | None = None,
    ) -> None:
        self._adapters = adapters or {}

    def check(self, items: list[SanityCheckItem]) -> SanityReport:
        """逐条执行健康检查，返回汇总报告。"""
        results: list[SanityCheckResult] = []
        passed_count = 0
        failed_count = 0
        actionable = True

        for item in items:
            start = time.perf_counter()
            try:
                passed, message, details = self._check_one(item)
            except Exception as exc:
                passed = False
                message = f"检查异常: {exc}"
                details = {"exception": str(exc)}
            elapsed = (time.perf_counter() - start) * 1000

            result = SanityCheckResult(
                check_name=item.name,
                passed=passed,
                message=message,
                details=details,
                duration_ms=round(elapsed, 1),
            )
            results.append(result)

            if passed:
                passed_count += 1
                logger.debug("Sanity PASS: %s (%.1fms)", item.name, elapsed)
            else:
                failed_count += 1
                # 环境故障无法自动修复 → 需要人工介入
                if item.required:
                    actionable = False
                logger.warning("Sanity FAIL: %s — %s", item.name, message)

        return SanityReport(
            all_passed=failed_count == 0,
            total=len(items),
            passed=passed_count,
            failed=failed_count,
            results=results,
            actionable=actionable,
        )

    def _check_one(
        self, item: SanityCheckItem
    ) -> tuple[bool, str, dict[str, Any]]:
        """执行单条检查。"""
        resource_type = item.resource

        if resource_type == "port":
            return self._check_port(item)
        elif resource_type == "http":
            return self._check_http(item)
        elif resource_type == "mysql":
            return self._check_adapter(item, "database")
        elif resource_type == "redis":
            return self._check_adapter(item, "redis")
        elif resource_type == "mq":
            return self._check_adapter(item, "mq")
        elif resource_type == "env":
            return self._check_env(item)
        else:
            return False, f"未知资源类型: {resource_type}", {}

    def _check_port(self, item: SanityCheckItem) -> tuple[bool, str, dict]:
        """检查端口是否可连接。"""
        host, port_str = item.target.split(":")
        port = int(port_str)
        try:
            sock = socket.create_connection(
                (host, port), timeout=item.timeout_seconds
            )
            sock.close()
            return True, f"端口 {item.target} 可达", {"host": host, "port": port}
        except (socket.timeout, ConnectionRefusedError, OSError) as exc:
            return False, f"端口 {item.target} 不可达: {exc}", {"host": host, "port": port}

    def _check_http(self, item: SanityCheckItem) -> tuple[bool, str, dict]:
        """检查 HTTP 服务是否可访问。"""
        adapter = self._adapters.get("http")
        if adapter is None:
            return False, "HttpAdapter 未配置", {}
        try:
            healthy = adapter.is_healthy()
            return (
                healthy,
                f"HTTP {item.target} {'可用' if healthy else '不可用'}",
                {"url": item.target},
            )
        except Exception as exc:
            return False, f"HTTP 检查异常: {exc}", {}

    def _check_adapter(self, item: SanityCheckItem, key: str) -> tuple[bool, str, dict]:
        """通过 ResourceAdapter 检查资源健康。"""
        adapter = self._adapters.get(key)
        if adapter is None:
            return False, f"{key} adapter 未配置", {}
        try:
            healthy = adapter.is_healthy()
            return (
                healthy,
                f"{key} {'可用' if healthy else '不可用'}",
                {"target": item.target},
            )
        except NotImplementedError:
            return True, f"{key} adapter 未实现（跳过检查）", {"skipped": True}
        except Exception as exc:
            return False, f"{key} 检查异常: {exc}", {}

    def _check_env(self, item: SanityCheckItem) -> tuple[bool, str, dict]:
        """检查环境变量是否存在。"""
        import os
        value = os.environ.get(item.target)
        if value is not None:
            return True, f"环境变量 {item.target} 已设置", {"value": value}
        return False, f"环境变量 {item.target} 未设置", {}
