"""资源适配器包 —— 动态注册 + 自动发现。

内置适配器: http / mysql / redis / rabbitmq / log
项目扩展:   .ai/adapters/*.py → 自动发现，覆盖/新增

用法:
    from engines.scenario.adapters import DataSourceRegistry

    registry = DataSourceRegistry.load(project_root)
    if not registry.health_check_all():
        raise RuntimeError("数据源连接失败，请检查 loop-config.json")

    # 传给 ScenarioRunner / AssertionEngine
    runner = ScenarioRunner(adapters=registry.to_adapter_dict())
"""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
from pathlib import Path
from typing import Any

from .base import ResourceAdapter
from .http import HttpAdapter
from .log import LogAdapter
from .mq import MessageQueueAdapter
from .mysql import MysqlAdapter
from .redis_adapter import RedisAdapter

logger = logging.getLogger(__name__)

# ── 内置适配器注册表 ──────────────────────────────────────────
_BUILTIN_ADAPTERS: dict[str, type[ResourceAdapter]] = {
    "mysql": MysqlAdapter,
    "redis": RedisAdapter,
    "rabbitmq": MessageQueueAdapter,
    "log": LogAdapter,
    # http 不在此列，它由 default_adapters() 单独创建（不需要 data_sources 配置）
}

# 断言类型 → 适配器查找缓存
_ASSERTION_MAP: dict[str, str] = {}
for _adapter_cls in _BUILTIN_ADAPTERS.values():
    for _at in _adapter_cls.supported_assertions:
        _ASSERTION_MAP[_at] = _adapter_cls.adapter_type


class DataSourceRegistry:
    """数据源注册表 —— 从 loop-config.json 加载，创建适配器实例。

    启动时自动发现 .ai/adapters/*.py，合并到内置注册表。
    """

    def __init__(self) -> None:
        self._adapters: dict[str, ResourceAdapter] = {}
        self._assertion_map: dict[str, ResourceAdapter] = {}

    # ── 工厂方法 ──

    @classmethod
    def load(cls, project_root: str | Path) -> "DataSourceRegistry":
        """从项目配置加载数据源注册表。

        Args:
            project_root: 项目根目录

        Returns:
            DataSourceRegistry 实例
        """
        root = Path(project_root)
        registry = cls()

        # 1. 自动发现项目级适配器（.ai/adapters/*.py）
        cls._discover_project_adapters(root)

        # 2. 读 loop-config.json
        config = cls._read_config(root)
        data_sources = config.get("data_sources", {})

        if not data_sources:
            logger.info("loop-config.json 中未配置 data_sources，跳过外部数据源")
            # 至少注册 http 和 log（不需要外部连接）
            return registry

        # 3. 按配置实例化适配器
        for name, ds_config in data_sources.items():
            ds_type = ds_config.get("type", "")
            if not ds_type:
                logger.warning("data_sources.%s 缺少 type 字段，跳过", name)
                continue

            adapter = cls._create_adapter(ds_type, ds_config)
            if adapter is None:
                logger.warning("未找到 type=%s 的适配器类，跳过 data_sources.%s", ds_type, name)
                continue

            # 尝试连接
            if not adapter.connect():
                logger.error(
                    "数据源 %s (%s) 连接失败，请检查 loop-config.json data_sources.%s 配置",
                    name, ds_type, name,
                )
                # 仍添加到注册表，让后续操作报明确的错

            registry._adapters[name] = adapter

            # 建立断言类型 → 适配器映射
            for at in adapter.supported_assertions:
                registry._assertion_map[at] = adapter

            logger.info("数据源已注册: %s (%s)", name, ds_type)

        return registry

    # ── 查询 ──

    def get(self, name: str) -> ResourceAdapter | None:
        """按配置 name 获取适配器。"""
        return self._adapters.get(name)

    def find_for_assertion(self, assertion_type: str) -> ResourceAdapter | None:
        """按断言类型查找能处理的适配器。

        Args:
            assertion_type: db_query / redis_key / mq_message / log_contains 等

        Returns:
            匹配的适配器实例，找不到返回 None
        """
        return self._assertion_map.get(assertion_type)

    def health_check_all(self) -> bool:
        """所有适配器健康检查，任一不可用返回 False。"""
        all_ok = True
        for name, adapter in self._adapters.items():
            if not adapter.is_healthy():
                logger.error("数据源 %s (%s) 健康检查失败", name, adapter.adapter_type)
                all_ok = False
        return all_ok

    def to_adapter_dict(self) -> dict[str, ResourceAdapter]:
        """转为 {name: adapter} 字典，给 ScenarioRunner 使用。"""
        result: dict[str, ResourceAdapter] = {}
        # 始终带 http
        result["http"] = HttpAdapter()
        for name, adapter in self._adapters.items():
            # key 用 adapter.adapter_type, 保持和原来 default_adapters() 兼容
            result[adapter.adapter_type] = adapter
        return result

    def reset_all(self) -> None:
        """重置所有适配器状态（每个 Scenario 前）。"""
        for adapter in self._adapters.values():
            adapter.clear()

    # ── 内部 ──

    @staticmethod
    def _read_config(root: Path) -> dict:
        config_path = root / ".ai" / "loop-config.json"
        if not config_path.exists():
            return {}
        try:
            return json.loads(config_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to read loop-config.json: %s", exc)
            return {}

    @classmethod
    def _create_adapter(
        cls, ds_type: str, ds_config: dict
    ) -> ResourceAdapter | None:
        """根据 type 创建适配器实例。"""
        adapter_cls = _BUILTIN_ADAPTERS.get(ds_type)
        if adapter_cls is None:
            # 检查是否被项目级适配器覆盖
            adapter_cls = _PROJECT_ADAPTERS.get(ds_type)

        if adapter_cls is None:
            return None

        # 过滤掉 type 字段，其余作为构造参数
        kwargs = {k: v for k, v in ds_config.items() if k != "type"}
        try:
            return adapter_cls(**kwargs)
        except Exception as exc:
            logger.error("创建 %s 适配器失败: %s", ds_type, exc)
            return None

    # ── 项目级适配器自动发现 ──

    _PROJECT_ADAPTERS: dict[str, type[ResourceAdapter]] = {}

    @classmethod
    def _discover_project_adapters(cls, root: Path) -> None:
        """扫描 .ai/adapters/*.py，动态加载 ResourceAdapter 子类。

        已加载的类缓存在 _PROJECT_ADAPTERS 中，不会重复加载。
        """
        adapters_dir = root / ".ai" / "adapters"
        if not adapters_dir.is_dir():
            return

        # 确保目录在 sys.path 中
        adapters_parent = str(adapters_dir.parent)  # .ai/
        if adapters_parent not in sys.path:
            sys.path.insert(0, adapters_parent)

        for py_file in sorted(adapters_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            cls._load_adapter_module(py_file, root)

    @classmethod
    def _load_adapter_module(cls, py_file: Path, root: Path) -> None:
        """动态加载单个 .py 文件，提取 ResourceAdapter 子类。"""
        module_name = f"_ai_adapter_{py_file.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec is None or spec.loader is None:
                return
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            # 查找模块中的 ResourceAdapter 子类
            for attr_name in dir(module):
                obj = getattr(module, attr_name)
                if (
                    isinstance(obj, type)
                    and issubclass(obj, ResourceAdapter)
                    and obj is not ResourceAdapter
                    and obj.adapter_type
                ):
                    cls._PROJECT_ADAPTERS[obj.adapter_type] = obj
                    # 更新断言映射
                    for at in obj.supported_assertions:
                        _ASSERTION_MAP[at] = obj.adapter_type
                    logger.info(
                        "加载项目适配器: %s (type=%s) from %s",
                        obj.adapter_label, obj.adapter_type, py_file.name,
                    )
        except Exception as exc:
            logger.warning("加载适配器模块 %s 失败: %s", py_file, exc)


# ── 默认适配器工厂（向后兼容）────────────────────────────────

def default_adapters() -> dict[str, ResourceAdapter]:
    """返回默认的资源适配器集合。

    只包含 HttpAdapter — 数据源由 DataSourceRegistry 管理。

    Returns:
        dict[str, ResourceAdapter]: 适配器名称到实例的映射
    """
    return {"http": HttpAdapter()}
