"""Provider —— 外部能力声明。

数据源检测: 扫描项目配置文件关键字 → 识别中间件类型。
Scenario Runner: 验证能力 —— HTTP 断言、数据断言、报告生成。

完全工具无关 —— ToolAdapter 负责翻译成具体工具的原生格式。
"""

# 从 base 模块导入 ProviderManifest 抽象基类
from engines.providers.base import ProviderManifest
# 从 mcp_registry 模块导入 MCP 相关类和函数
from engines.providers.mcp_registry import (
    McpResourceProvider,    # 通用 MCP 资源 Provider 类，由 YAML 配置驱动
    detect_mcp_providers,   # 检测项目需要的 MCP Provider 的函数
    load_registry,          # 加载 MCP Server 注册表（内置 + 项目级合并）的函数
)
# 从 scenario_runner 模块导入场景验证 Provider
from engines.providers.scenario_runner import ScenarioRunnerProvider

# 显式声明模块对外暴露的公共 API 列表
__all__ = [
    "ProviderManifest",
    "McpResourceProvider",
    "ScenarioRunnerProvider",
    "detect_mcp_providers",
    "load_registry",
]