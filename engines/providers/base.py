"""ProviderManifest 抽象基类 —— 声明外部能力的接口。

每个 Provider（Superpowers / MCP-MySQL / ScenarioRunner）有各自的子类实现。
职责：声明能力、提供 skill 模板（语义）、声明 MCP/Hook 需求。
完全不感知自己在哪个 AI 工具中运行。
"""

# 启用延迟注解求值
from __future__ import annotations

# 导入 ABC 抽象基类和 abstractmethod 装饰器
from abc import ABC, abstractmethod
# 导入 dataclass 和 field 用于定义数据类
from dataclasses import dataclass, field
# 导入 Path 用于文件路径操作
from pathlib import Path

# 从 adapters.base 导入 McpServerDef 数据类（Provider 声明 MCP 需求时使用）
from engines.adapters.base import McpServerDef


# Provider 抽象基类：外部能力声明，完全工具无关
class ProviderManifest(ABC):
    """Provider 抽象基类 —— 外部能力声明，完全工具无关。

    子类必须实现：
      - 元信息 (name, display_name, type, capabilities)
      - detect(): 检测是否已安装
      - get_skill_templates(): 返回带占位符的模板
      - get_ai_instructions(): 在主配置中注入的段落
      - get_mcp_servers(): 需要的 MCP Server 列表
      - get_hooks(): 需要的 hook 定义
    """

    # ── 子类必须覆写 ──

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider 标识: "superpowers" / "mcp-mysql" / "scenario-runner" """
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """显示名: "Superpowers" / "MCP MySQL" """
        ...

    @property
    @abstractmethod
    def type(self) -> str:
        """类型: "spec_provider" / "resource_access" / "verification" / "guard" """
        ...

    @property
    @abstractmethod
    def capabilities(self) -> list[str]:
        """能力声明: ["spec.generate", "plan.generate", "task.breakdown"]"""
        ...

    @property
    @abstractmethod
    def required(self) -> bool:
        """是否为必需插件。必需插件缺失时 init 会报错。"""
        ...

    # ── 检测 ──

    # 检测此 Provider 是否已安装/可用
    # 参数 project_root: 项目根目录
    # 返回值: True 表示已安装或配置已就绪
    @abstractmethod
    def detect(self, project_root: Path) -> bool:
        """检测此 Provider 是否已安装/可用。

        Args:
            project_root: 项目根目录。

        Returns:
            True 表示已安装或配置已就绪。
        """
        ...

    # ── Skill 模板（内容由 ToolAdapter 渲染） ──

    # 返回 skill/rule 模板字典
    # 返回值: {逻辑名: 模板内容} 字典
    @abstractmethod
    def get_skill_templates(self) -> dict[str, str]:
        """返回 {逻辑名: 模板内容} 的 skill/rule 模板。

        模板中使用 {plugin_root}、{engines_cmd}、{cmd_prefix}、{mcp_call} 等占位符。
        ToolAdapter.render_skill() 替换这些占位符为具体值。

        Example:
            {
                "init": "## Step 1\\n```bash\\n{engines_cmd} init --scan-only\\n```\\n",
                "spec": "...",
            }
        """
        ...

    # ── 主配置注入 ──

    # 返回在主配置文件中注入的段落
    # 返回值: 告诉 AI 这个 Provider 是什么、怎么调用的说明文本
    @abstractmethod
    def get_ai_instructions(self) -> str:
        """在主配置文件（CLAUDE.md 等）中注入的段落。

        告诉 AI 这个 Provider 是什么、怎么调用。
        也可以用 {engines_cmd} / {cmd_prefix} 等占位符。
        """
        ...

    # ── MCP 需求 ──

    # 返回此 Provider 需要的 MCP Server 列表
    # 返回值: McpServerDef 实例列表
    @abstractmethod
    def get_mcp_servers(self) -> list[McpServerDef]:
        """此 Provider 需要的 MCP Server 列表。

        Provider 只声明需求，不关心具体 MCP JSON 格式。
        ToolAdapter.generate_mcp_config() 负责翻译。
        """
        ...

    # ── Hook 需求 ──

    # 返回此 Provider 需要的 hook 定义
    # 返回值: hook 定义字典
    @abstractmethod
    def get_hooks(self) -> dict[str, Any]:
        """此 Provider 需要的 hook 定义。

        返回格式（工具无关）:
            {
                "SessionStart": [
                    {"command": "{engines_cmd} context project-map --format json", "async": False}
                ]
            }

        ToolAdapter 负责翻译成具体 hooks 格式或决定是否支持。
        """
        ...

    # ── 工具方法 ──

    # 返回 Provider 的字符串表示
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name}>"