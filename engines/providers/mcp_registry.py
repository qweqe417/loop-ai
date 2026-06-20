"""MCP Provider 注册表 —— MySQL / Redis / MQ / ES 等资源 Provider。

每个 MCP Provider 声明：
  - 如何检测（扫描配置文件中的关键字）
  - 对 AI 说什么（怎么用、什么禁止）
  - 需要的 MCP Server 定义（由 ToolAdapter 翻译成工具原生格式）
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engines.adapters.base import McpServerDef
from engines.providers.base import ProviderManifest


class _McpResourceProvider(ProviderManifest):
    """MCP 资源 Provider 基类 —— 通过扫描配置文件关键字检测。"""

    # 子类覆写
    _keyword: str = ""          # 配置文件关键字
    _resource_label: str = ""   # 显示名: MySQL / Redis / Kafka
    _resource_type: str = ""    # 资源类型: database / cache / queue
    _mcp_command: str = "npx"
    _mcp_args: list[str] = []
    _mcp_env: dict[str, str] = {}
    _config_files: list[str] = [
        "application.yml", "application.properties", "application.yaml",
        ".env", ".env.example", ".env.local",
        "docker-compose.yml", "docker-compose.yaml",
        "pyproject.toml", "package.json",
    ]

    @property
    def type(self) -> str:
        return "resource_access"

    @property
    def required(self) -> bool:
        return False  # MCP 资源都是可选的

    def detect(self, project_root: Path) -> bool:
        for cf in self._config_files:
            target = project_root / cf
            if target.exists():
                try:
                    content = target.read_text(encoding="utf-8", errors="ignore").lower()
                    if self._keyword.lower() in content:
                        return True
                except Exception:
                    pass
        return False

    def get_skill_templates(self) -> dict[str, str]:
        # MCP 资源不需要额外 skill 文件
        return {}

    def get_mcp_servers(self) -> list[McpServerDef]:
        return [
            McpServerDef(
                name=self._keyword,
                description=f"{self._resource_label} 访问",
                command=self._mcp_command,
                args=self._mcp_args,
                env=self._mcp_env,
                required=False,
            )
        ]

    def get_hooks(self) -> dict[str, Any]:
        return {}


# ── 具体资源 Provider ──

class McpMysqlProvider(_McpResourceProvider):
    name = "mcp-mysql"
    display_name = "MCP MySQL"
    _keyword = "mysql"
    _resource_label = "MySQL"
    _resource_type = "database"
    _mcp_command = "npx"
    _mcp_args = ["-y", "@anthropic/mcp-mysql"]
    _mcp_env = {
        "MYSQL_HOST": "${MYSQL_HOST:localhost}",
        "MYSQL_PORT": "${MYSQL_PORT:3306}",
        "MYSQL_USER": "${MYSQL_USER:root}",
        "MYSQL_DATABASE": "${MYSQL_DATABASE:test}",
    }

    @property
    def capabilities(self) -> list[str]:
        return ["mysql.query", "mysql.schema", "mysql.assertion"]

    def get_ai_instructions(self) -> str:
        return """
### MySQL 数据库访问

本项目检测到 MySQL。AI 可通过 MCP 直接查询：
- 读取 schema 和表结构
- 查询和验证测试数据
- 辅助调试和根因分析

**禁止**：
- 操作生产环境数据库
- 执行 DDL / DROP / TRUNCATE
- dump 大量数据
- 修改连接串指向非测试环境
- 查询结果需要脱敏
"""


class McpRedisProvider(_McpResourceProvider):
    name = "mcp-redis"
    display_name = "MCP Redis"
    _keyword = "redis"
    _resource_label = "Redis"
    _resource_type = "cache"
    _mcp_command = "npx"
    _mcp_args = ["-y", "@anthropic/mcp-redis"]
    _mcp_env = {
        "REDIS_HOST": "${REDIS_HOST:localhost}",
        "REDIS_PORT": "${REDIS_PORT:6379}",
    }

    @property
    def capabilities(self) -> list[str]:
        return ["redis.read", "redis.assertion"]

    def get_ai_instructions(self) -> str:
        return """
### Redis 缓存访问

本项目检测到 Redis。AI 可通过 MCP 读取和验证缓存状态。
主要用于 Scenario 验证中的数据断言。

**禁止**：
- 操作生产环境 Redis
- FLUSHDB / FLUSHALL
- 写入大量数据
"""


class McpKafkaProvider(_McpResourceProvider):
    name = "mcp-kafka"
    display_name = "MCP Kafka"
    _keyword = "kafka"
    _resource_label = "Kafka"
    _resource_type = "queue"
    _mcp_command = "npx"
    _mcp_args = ["-y", "@anthropic/mcp-kafka"]
    _mcp_env = {}

    @property
    def capabilities(self) -> list[str]:
        return ["kafka.consume", "kafka.assertion"]

    def get_ai_instructions(self) -> str:
        return """
### Kafka 消息队列访问

本项目检测到 Kafka。AI 可通过 MCP 消费和验证消息。
主要用于验证消息生产和 outbox 模式。

**禁止**：
- 操作生产环境 Kafka
- 删除 topic
- 大量消费生产消息
"""


class McpElasticsearchProvider(_McpResourceProvider):
    name = "mcp-elasticsearch"
    display_name = "MCP Elasticsearch"
    _keyword = "elasticsearch"
    _resource_label = "Elasticsearch"
    _resource_type = "search"
    _mcp_command = "npx"
    _mcp_args = ["-y", "@anthropic/mcp-elasticsearch"]
    _mcp_env = {}

    @property
    def capabilities(self) -> list[str]:
        return ["es.search", "es.assertion"]

    def get_ai_instructions(self) -> str:
        return """
### Elasticsearch 搜索引擎访问

本项目检测到 Elasticsearch。AI 可通过 MCP 查询和验证搜索数据。

**禁止**：
- 操作生产环境 ES
- 删除索引
"""


# ── Provider 注册表 ──

# 所有可用的 MCP Provider（放在一个列表方便遍历）
ALL_MCP_PROVIDERS: list[type[_McpResourceProvider]] = [
    McpMysqlProvider,
    McpRedisProvider,
    McpKafkaProvider,
    McpElasticsearchProvider,
]


def detect_mcp_providers(project_root: Path) -> list[_McpResourceProvider]:
    """检测所有可用的 MCP Provider。

    Args:
        project_root: 项目根目录。

    Returns:
        检测到的 MCP Provider 实例列表。
    """
    detected: list[_McpResourceProvider] = []
    for cls in ALL_MCP_PROVIDERS:
        instance = cls()
        if instance.detect(project_root):
            detected.append(instance)
    return detected
