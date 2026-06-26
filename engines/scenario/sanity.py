"""环境健康检查（Sanity Check）。

在 Scenario 执行前检查所需资源是否可用。
如果环境不可用，不进入代码修复 Loop，暂停并提示人工处理。
"""

# 启用 Python 3.10+ 的延迟注解求值特性
from __future__ import annotations

# 导入日志模块，用于记录检查过程和结果
import logging
# 导入 socket 模块，用于端口连通性检查
import socket
# 导入 time 模块，用于计算检查耗时
import time
# 导入 Any 类型，用于灵活的类型注解
from typing import Any

# 从 models 模块导入健康检查相关的数据模型
from .models import SanityCheckItem, SanityCheckResult, SanityReport
# 从 resources 模块导入 ResourceAdapter 基类
from .resources import ResourceAdapter

# 获取当前模块的日志记录器
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
        # 资源适配器字典，用于通过适配器检查资源健康状态
        self._adapters = adapters or {}

    def check(self, items: list[SanityCheckItem]) -> SanityReport:
        """逐条执行健康检查，返回汇总报告。

        Args:
            items: 健康检查项列表

        Returns:
            SanityReport: 汇总报告，包含通过/失败统计和可修复性判断
        """
        # 存储每条检查的结果
        results: list[SanityCheckResult] = []
        passed_count = 0
        failed_count = 0
        # 是否可自动修复（有 required 检查失败则不可自动修复）
        actionable = True

        for item in items:
            # 记录检查开始时间
            start = time.perf_counter()
            try:
                # 执行单条检查
                passed, message, details = self._check_one(item)
            except Exception as exc:
                # 检查过程异常，视为失败
                passed = False
                message = f"检查异常: {exc}"
                details = {"exception": str(exc)}
            # 计算检查耗时（毫秒）
            elapsed = (time.perf_counter() - start) * 1000

            # 构建单条检查结果
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

        # 返回汇总报告
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
        """执行单条检查，根据资源类型路由到对应的检查方法。

        Args:
            item: 单条健康检查项

        Returns:
            (是否通过, 结果消息, 详情字典)
        """
        resource_type = item.resource

        if resource_type == "port":
            # 端口连通性检查
            return self._check_port(item)
        elif resource_type == "http":
            # HTTP 服务可用性检查
            return self._check_http(item)
        elif resource_type == "mysql":
            # 数据库连通性检查（委托给 adapter）
            return self._check_adapter(item, "database")
        elif resource_type == "redis":
            # Redis 连通性检查（委托给 adapter）
            return self._check_adapter(item, "redis")
        elif resource_type == "mq":
            # 消息队列可用性检查（委托给 adapter）
            return self._check_adapter(item, "mq")
        elif resource_type == "env":
            # 环境变量存在性检查
            return self._check_env(item)
        else:
            # 未知资源类型
            return False, f"未知资源类型: {resource_type}", {}

    def _check_port(self, item: SanityCheckItem) -> tuple[bool, str, dict]:
        """检查端口是否可连接。

        Args:
            item: 端口检查项（target 格式为 "host:port"）

        Returns:
            (是否可达, 消息, 详情字典)
        """
        # 解析 host:port 格式
        host, port_str = item.target.split(":")
        port = int(port_str)
        try:
            # 创建 TCP 连接测试端口可达性
            sock = socket.create_connection(
                (host, port), timeout=item.timeout_seconds
            )
            sock.close()
            return True, f"端口 {item.target} 可达", {"host": host, "port": port}
        except (socket.timeout, ConnectionRefusedError, OSError) as exc:
            return False, f"端口 {item.target} 不可达: {exc}", {"host": host, "port": port}

    def _check_http(self, item: SanityCheckItem) -> tuple[bool, str, dict]:
        """检查 HTTP 服务是否可访问（通过 HttpAdapter 的 is_healthy）。

        Args:
            item: HTTP 检查项

        Returns:
            (是否可用, 消息, 详情字典)
        """
        adapter = self._adapters.get("http")
        if adapter is None:
            return False, "HttpAdapter 未配置", {}
        try:
            # 通过适配器检查 HTTP 服务健康状态
            healthy = adapter.is_healthy()
            return (
                healthy,
                f"HTTP {item.target} {'可用' if healthy else '不可用'}",
                {"url": item.target},
            )
        except Exception as exc:
            return False, f"HTTP 检查异常: {exc}", {}

    def _check_adapter(self, item: SanityCheckItem, key: str) -> tuple[bool, str, dict]:
        """通过 ResourceAdapter 检查资源健康。

        Args:
            item: 检查项
            key: 适配器 key（如 "database", "redis", "mq"）

        Returns:
            (是否健康, 消息, 详情字典)
        """
        adapter = self._adapters.get(key)
        if adapter is None:
            return False, f"{key} adapter 未配置", {}
        try:
            # 通过适配器检查资源健康状态
            healthy = adapter.is_healthy()
            return (
                healthy,
                f"{key} {'可用' if healthy else '不可用'}",
                {"target": item.target},
            )
        except NotImplementedError:
            # 适配器未实现健康检查，跳过
            return True, f"{key} adapter 未实现（跳过检查）", {"skipped": True}
        except Exception as exc:
            return False, f"{key} 检查异常: {exc}", {}

    def _check_env(self, item: SanityCheckItem) -> tuple[bool, str, dict]:
        """检查环境变量是否存在。

        Args:
            item: 环境变量检查项（target 为环境变量名）

        Returns:
            (是否已设置, 消息, 详情字典)
        """
        import os
        value = os.environ.get(item.target)
        if value is not None:
            return True, f"环境变量 {item.target} 已设置", {"value": value}
        return False, f"环境变量 {item.target} 未设置", {}