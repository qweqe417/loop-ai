"""MCP Server 注册表 —— 纯数据驱动。

读取 mcp_registry.yaml，扫描项目配置文件关键字，
返回匹配的 McpResourceProvider 列表。
新增中间件只改 YAML，不改代码。
"""

# 启用延迟注解求值
from __future__ import annotations

# 导入 logging 用于日志记录
import logging
# 导入 Path 用于文件路径操作
from pathlib import Path
# 导入 Any 类型
from typing import Any

# 导入 yaml 用于解析 YAML 注册表文件
import yaml

# 从 adapters.base 导入 McpServerDef 数据类
from engines.adapters.base import McpServerDef
# 从 providers.base 导入 ProviderManifest 抽象基类
from engines.providers.base import ProviderManifest

# 创建当前模块的日志记录器
logger = logging.getLogger(__name__)

# 内置 YAML 路径（与 mcp_registry.py 同目录）
_BUILTIN_YAML = Path(__file__).resolve().with_name("mcp_registry.yaml")

# 项目级扩展路径（init 后生成模板）
_PROJECT_YAML_NAME = ".ai/mcp-servers.yaml"

# 扫描的配置文件列表：用于检测项目中使用了哪些中间件
_CONFIG_FILES = [
    "application.yml", "application.properties", "application.yaml",
    ".env", ".env.example", ".env.local",
    "docker-compose.yml", "docker-compose.yaml",
    "pyproject.toml", "package.json", "pom.xml", "build.gradle",
    "build.gradle.kts", "go.mod", "Cargo.toml",
]


# ── Generic MCP Resource Provider ────────────────────────────

# 通用 MCP 资源 Provider 类：由 YAML 配置驱动
class McpResourceProvider(ProviderManifest):
    """通用 MCP 资源 Provider —— 由 YAML 配置驱动。

    每个实例代表一个检测到的外部中间件连接。
    """

    # 构造函数：接收名称和 YAML 配置字典
    # 参数 name: MCP 服务器名称
    # 参数 cfg: YAML 配置字典
    def __init__(self, name: str, cfg: dict) -> None:
        self._name = name
        self._cfg = cfg

    # Provider 名称属性：加 mcp- 前缀
    @property
    def name(self) -> str:
        return f"mcp-{self._name}"

    # 显示名属性：从 YAML 配置中读取 description
    @property
    def display_name(self) -> str:
        return self._cfg.get("description", f"MCP {self._name.title()}")

    # Provider 类型：资源访问
    @property
    def type(self) -> str:
        return "resource_access"

    # 能力声明列表：基于服务名称生成查询和断言能力
    @property
    def capabilities(self) -> list[str]:
        return [f"{self._name}.query", f"{self._name}.assertion"]

    # 是否为必需插件：MCP 资源 Provider 通常为可选
    @property
    def required(self) -> bool:
        return False

    # 检测方法：上层已通过关键字匹配完成检测，此处恒为 True
    # 参数 project_root: 项目根目录
    # 返回值: 始终返回 True
    def detect(self, project_root: Path) -> bool:
        # 检测已在上层完成，这里恒为 True
        return True

    # 获取 skill 模板：MCP 资源 Provider 不需要 skill 模板
    # 返回值: 空字典
    def get_skill_templates(self) -> dict[str, str]:
        return {}

    # 获取 AI 指令：从 YAML 配置中读取 instructions 字段
    # 返回值: AI 指令文本
    def get_ai_instructions(self) -> str:
        return self._cfg.get("instructions", "")

    # 获取 MCP Server 定义列表
    # 返回值: 包含单个 McpServerDef 的列表
    def get_mcp_servers(self) -> list[McpServerDef]:
        # 从 YAML 配置中提取环境变量配置
        env_config = self._cfg.get("env", {})
        # 构建环境变量默认值字典
        env_defaults = {
            k: v.get("default", "") for k, v in env_config.items()
        }
        # 保留 label 元数据，供 CLI/UI 引导用户配置连接信息
        env_meta = {
            k: {"label": v.get("label", k), "default": v.get("default", "")}
            for k, v in env_config.items()
        }
        return [
            McpServerDef(
                name=self._name,
                description=self._cfg.get("description", ""),
                command="npx",
                args=["-y", self._cfg["package"]],
                env=env_defaults,
                env_meta=env_meta,
                required=False,
            )
        ]

    # 获取 hook 定义：MCP 资源 Provider 不需要 hooks
    # 返回值: 空字典
    def get_hooks(self) -> dict[str, Any]:
        return {}

    # 返回 Provider 的字符串表示
    def __repr__(self) -> str:
        return f"<McpResourceProvider name={self.name}>"


# ── YAML 加载与合并 ─────────────────────────────────────────

# 加载一个 YAML 注册表文件
# 参数 path: YAML 文件路径
# 返回值: 解析后的字典，失败返回 None
def _load_yaml_registry(path: Path) -> dict | None:
    """加载一个 YAML 注册表文件，失败返回 None。"""
    # 文件不存在则返回 None
    if not path.exists():
        return None
    try:
        # 使用 yaml.safe_load 安全解析 YAML 文件
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        # 验证格式：必须包含 "servers" 键
        if isinstance(data, dict) and "servers" in data:
            return data
        logger.warning("Invalid MCP registry format: %s", path)
        return None
    except Exception as exc:
        logger.warning("Failed to load MCP registry %s: %s", path, exc)
        return None


# 合并内置注册表和项目级注册表
# 参数 builtin: 内置注册表数据
# 参数 project: 项目级注册表数据（可选）
# 返回值: 合并后的 server 配置字典
def _merge_registries(builtin: dict, project: dict | None) -> dict[str, dict]:
    """合并内置注册表和项目级注册表。

    项目级覆盖同名 server，新增的追加。
    """
    # 从内置注册表中复制 servers 配置
    merged: dict[str, dict] = dict(builtin.get("servers", {}))
    # 如果有项目级注册表，用其覆盖同名 server
    if project:
        for name, cfg in project.get("servers", {}).items():
            merged[name] = cfg  # 项目覆盖内置
    return merged


# 加载完整的 MCP Server 注册表（内置 + 项目级合并）
# 参数 project_root: 项目根目录（用于查找 .ai/mcp-servers.yaml）
# 返回值: {server_name: server_config} 字典
def load_registry(project_root: Path | None = None) -> dict[str, dict]:
    """加载完整的 MCP Server 注册表（内置 + 项目级合并）。

    Args:
        project_root: 项目根目录（查找 .ai/mcp-servers.yaml）。

    Returns:
        {server_name: server_config} 字典。
    """
    # 加载内置注册表
    builtin = _load_yaml_registry(_BUILTIN_YAML)
    if not builtin:
        logger.error("Built-in MCP registry not found at %s", _BUILTIN_YAML)
        return {}

    # 加载项目级注册表（如果 project_root 已指定）
    project = None
    if project_root:
        project_yaml = Path(project_root) / _PROJECT_YAML_NAME
        project = _load_yaml_registry(project_yaml)
        if project:
            logger.info("Loaded project MCP registry: %s", project_yaml)

    # 合并并返回
    return _merge_registries(builtin, project)


# ── 检测 ─────────────────────────────────────────────────────

# 读取所有配置文件内容，统一小写用于关键字匹配
# 参数 project_root: 项目根目录
# 返回值: 所有配置文件内容拼接后的字符串（小写）
def _scan_config_content(project_root: Path) -> str:
    """读取所有配置文件内容，统一小写用于关键字匹配。"""
    parts: list[str] = []
    # 遍历所有需要扫描的配置文件
    for cf in _CONFIG_FILES:
        target = project_root / cf
        # 如果文件存在，读取其内容
        if target.exists():
            try:
                parts.append(target.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                pass
    # 拼接所有内容并转为小写
    return "\n".join(parts).lower()


# 检测项目需要的 MCP Provider
# 参数 project_root: 项目根目录
# 返回值: 检测到的 McpResourceProvider 实例列表
def detect_mcp_providers(project_root: Path) -> list[McpResourceProvider]:
    """检测项目需要的 MCP Provider。

    扫描项目配置文件，匹配 YAML 注册表中各 server 的 keywords，
    返回匹配的 McpResourceProvider 列表。

    用户只需改生成出来的 .claude/mcp.json / .codex/mcp.json
    里的 IP/端口/账号/密码即可。

    Args:
        project_root: 项目根目录。

    Returns:
        检测到的 MCP Provider 实例列表。
    """
    # 加载完整注册表
    registry = load_registry(project_root)
    if not registry:
        return []

    # 扫描项目配置文件内容
    content = _scan_config_content(project_root)
    if not content:
        logger.debug("No config files found for MCP detection")
        return []

    detected: list[McpResourceProvider] = []
    # 遍历注册表中的每个 server
    for name, cfg in registry.items():
        # 获取该 server 的关键字列表
        keywords = cfg.get("keywords", [])
        if not keywords:
            continue
        # 检查项目配置内容中是否包含任一关键字
        if any(kw.lower() in content for kw in keywords):
            # 创建 McpResourceProvider 实例
            provider = McpResourceProvider(name, cfg)
            detected.append(provider)
            logger.info(
                "Detected MCP provider: %s (keywords: %s)",
                provider.display_name,
                [kw for kw in keywords if kw.lower() in content],
            )

    return detected