"""CursorAdapter —— 把 AI Coding Loop 映射到 Cursor。

生成 .cursor/rules/aicode.md、.cursor/rules/aicode-*.md、.cursor/aicode/。
命令前缀 @，无 hooks，skill 格式为 rule_md（.cursor/rules/）。
Cursor 没有插件变量机制，路径写绝对路径。
"""

# 启用延迟注解求值
from __future__ import annotations

# 导入 json 用于配置序列化
import json
# 导入 logging 用于日志记录
import logging
# 导入 datetime 用于时间戳
from datetime import datetime
# 导入 Path 用于文件路径操作
from pathlib import Path
# 导入 Any 类型
from typing import Any

# 从 base 模块导入基类和 McpServerDef 数据类
from engines.adapters.base import McpServerDef, ToolAdapter
# 从 init.models 导入 ProjectProfile 类型
from engines.init.models import ProjectProfile

# 创建当前模块的日志记录器
logger = logging.getLogger(__name__)


# Cursor 适配器类
class CursorAdapter(ToolAdapter):
    """Cursor 适配器。"""

    # ── 元信息 ──

    # 工具标识
    tool_id: str = "cursor"

    # 工具显示名属性
    @property
    def display_name(self) -> str:
        return "Cursor"

    # ── 路径 ──

    # 主配置文件路径：.cursor/rules/aicode.md
    @property
    def main_config_path(self) -> str:
        return ".cursor/rules/aicode.md"

    # 规则文件目录：.cursor/rules
    @property
    def rules_dir(self) -> str:
        return ".cursor/rules"

    # AI Coding Loop 资产目录：.cursor/aicode
    @property
    def aicode_dir(self) -> str:
        return ".cursor/aicode"

    # Skills 目录：Cursor 规则目录就是 skill 目录
    @property
    def skills_dir(self) -> str:
        return ".cursor/rules"  # Cursor 规则目录就是 skill 目录

    # ── 命令/钩子 ──

    # 命令前缀：@（Cursor 使用 @ 符号）
    @property
    def command_prefix(self) -> str:
        return "@"

    # 是否支持 hooks 机制：否（Cursor 不支持 hooks）
    @property
    def supports_hooks(self) -> bool:
        return False

    # hooks 配置文件路径：无（Cursor 不支持 hooks）
    @property
    def hooks_config_path(self) -> str | None:
        return None

    # MCP 配置文件路径：.cursor/mcp.json
    @property
    def mcp_config_path(self) -> str | None:
        return ".cursor/mcp.json"

    # Skill 文件格式：规则 .md 文件
    @property
    def skill_format(self) -> str:
        return "rule_md"

    # ── 模板变量 ──

    # Cursor 没有插件变量机制，需要知道引擎的绝对路径。
    # 安装时由 install() 更新 _engine_root。
    _engine_root: str = ""

    # 模板变量映射：定义占位符到实际值的映射
    @property
    def template_vars(self) -> dict[str, str]:
        # 导入 sys 获取 Python 解释器路径
        import sys
        # 使用已设置的引擎根目录，或从当前文件路径推算
        engine = self._engine_root or str(Path(__file__).resolve().parent.parent.parent)
        # 获取 Python 可执行文件路径
        python_exe = getattr(sys, 'executable', 'python') or 'python'
        return {
            "plugin_root": engine,
            "engines_cmd": f"{python_exe} {engine}/engines/run.sh",
            "engines_cmd_win": f"{python_exe} {engine}\\engines\\run.sh",
            "cmd_prefix": self.command_prefix,
            "context_var": engine,
            "aicode_dir": ".cursor/aicode",
            "mcp_call": "通过 Cursor MCP 配置调用",
            "tool_name": self.display_name,
            "tool_name_lower": self.tool_id,
        }

    # 设置引擎根目录（Cursor 没有变量机制，需要绝对路径）
    # 参数 path: 引擎根目录的绝对路径
    def set_engine_root(self, path: str) -> None:
        """设置引擎根目录（Cursor 没有变量机制，需要绝对路径）。"""
        self._engine_root = path

    # ── 已有文件检测 ──

    # 需要检测的文件/目录模式列表
    _file_patterns = [".cursor/rules/aicode.md", ".cursor/", ".cursor/rules/"]

    # ── 内容生成 ──

    # 生成 .cursor/rules/aicode.md 自举引导文件
    # 参数 profile: 项目配置信息
    # 参数 providers: Provider 列表（可选）
    # 返回值: 自举引导 prompt 字符串
    def render_main_config(
        self, profile: ProjectProfile, providers: list[Any] | None = None
    ) -> str:
        """生成 .cursor/rules/aicode.md 自举引导文件 —— Python 只写 prompt，AI 负责生成完整配置。"""
        # 调用基类的 _render_bootstrap_prompt 方法生成自举引导内容
        return self._render_bootstrap_prompt(
            project_name=profile.project_name,
            tool_display_name=self.display_name,
            main_config_path=self.main_config_path,
            rules_dir=self.rules_dir,
            command_prefix=self.command_prefix,
        )

    # ── MCP 配置 ──

    # 生成 Cursor 格式的 MCP 配置
    # 参数 servers: MCP Server 定义列表
    # 返回值: Cursor 格式的 MCP 配置字典
    def generate_mcp_config(self, servers: list[McpServerDef]) -> dict[str, Any]:
        """生成 Cursor 格式的 MCP 配置。"""
        mcp_servers: dict[str, dict] = {}
        # 遍历所有 MCP Server 定义
        for s in servers:
            # 构建单个 server 的配置条目
            entry: dict = {"command": s.command, "args": s.args}
            # 如果有环境变量，添加到配置中
            if s.env:
                entry["env"] = s.env
            mcp_servers[s.name] = entry
        return {"mcpServers": mcp_servers}

    # ── Hooks ──

    # 生成 hooks 配置（Cursor 不支持 hooks）
    # 参数 providers: Provider 列表
    # 返回值: 空字典
    def generate_hooks(self, providers: list[Any]) -> dict[str, Any]:
        return {}

    # ── 安装 ──

    # 执行 Cursor 的安装步骤
    # 参数 project_root: 项目根目录
    # 参数 plugin_root: 引擎插件根目录
    # 参数 providers: Provider 列表（可选）
    # 返回值: 安装结果字典
    def install(
        self,
        project_root: Path,
        plugin_root: Path,
        providers: list[Any] | None = None,
        profile: ProjectProfile | None = None,
    ) -> dict[str, Any]:
        """Cursor 安装：MCP 配置 / loop-config.json / karpathy.md 规则。"""
        created: list[str] = []
        skipped: list[str] = []
        errors: list[str] = []

        root = Path(project_root)
        src = Path(plugin_root)
        # Cursor 无变量机制，需要记录引擎的绝对路径
        self._engine_root = str(src.resolve())  # Cursor 无变量机制，需要绝对路径

        # 1. MCP 配置
        # 收集所有 provider 的 MCP Server 定义
        all_servers: list[McpServerDef] = []
        for pv in (providers or []):
            all_servers.extend(pv.get_mcp_servers())
        # 如果有 MCP Server，生成并写入配置文件
        if all_servers:
            mcp_dst = root / ".cursor" / "mcp.json"
            mcp_dst.parent.mkdir(parents=True, exist_ok=True)
            mcp_config = self.generate_mcp_config(all_servers)
            mcp_dst.write_text(
                json.dumps(mcp_config, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            created.append(str(mcp_dst.relative_to(root)))

        # 2. loop-config.json
        loop_config_dst = root / ".ai" / "loop-config.json"
        loop_config_dst.parent.mkdir(parents=True, exist_ok=True)
        existing = {}
        if loop_config_dst.exists():
            try:
                existing = json.loads(loop_config_dst.read_text(encoding="utf-8"))
            except Exception:
                pass
        loop_config = {
            **existing,
            "target_tool": self.tool_id,
            **self.template_vars,
        }
        defaults = self.default_loop_config()
        for key in defaults:
            if key not in loop_config:
                loop_config[key] = defaults[key]

        # ── 自动检测前端项目，填充 test 配置 ─────────────────────
        from engines.adapters.base import _auto_fill_test_config
        _auto_fill_test_config(root, defaults, loop_config)

        loop_config_dst.write_text(
            json.dumps(loop_config, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        action = "updated" if existing else "created"
        created.append(f"{str(loop_config_dst.relative_to(root))} ({action})")

        # 3. Karpathy 行为准则 — 从插件源码原封不动拷贝，不让 AI 发挥
        karpathy_src = Path(plugin_root) / "skills" / "andrej-karpathy" / "karpathy.md"
        karpathy_dst = root / self.rules_dir / "karpathy.md"
        if karpathy_src.exists():
            karpathy_dst.parent.mkdir(parents=True, exist_ok=True)
            # 文件不存在时才拷贝，避免覆盖已有文件
            if not karpathy_dst.exists():
                karpathy_dst.write_text(
                    karpathy_src.read_text(encoding="utf-8"), encoding="utf-8"
                )
                created.append(str(karpathy_dst.relative_to(root)))
            else:
                skipped.append(str(karpathy_dst.relative_to(root)))
                logger.info("karpathy.md already exists, skipping")
        else:
            logger.warning("karpathy karpathy.md not found at %s, skipping", karpathy_src)

        # 返回安装结果
        return {
            "success": len(errors) == 0,
            "files_created": created,
            "files_skipped": skipped,
            "errors": errors,
        }