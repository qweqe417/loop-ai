"""CursorAdapter —— 把 AI Coding Loop 映射到 Cursor。

生成 .cursor/rules/aicode.md、.cursor/rules/aicode-*.md、.cursor/aicode/。
命令前缀 @，无 hooks，skill 格式为 rule_md（.cursor/rules/）。
Cursor 没有插件变量机制，路径写绝对路径。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from engines.adapters.base import McpServerDef, ToolAdapter
from engines.init.models import ProjectProfile

logger = logging.getLogger(__name__)


class CursorAdapter(ToolAdapter):
    """Cursor 适配器。"""

    # ── 元信息 ──

    @property
    def tool_id(self) -> str:
        return "cursor"

    @property
    def display_name(self) -> str:
        return "Cursor"

    # ── 路径 ──

    @property
    def main_config_path(self) -> str:
        return ".cursor/rules/aicode.md"

    @property
    def rules_dir(self) -> str:
        return ".cursor/rules"

    @property
    def aicode_dir(self) -> str:
        return ".cursor/aicode"

    @property
    def skills_dir(self) -> str:
        return ".cursor/rules"  # Cursor 规则目录就是 skill 目录

    # ── 命令/钩子 ──

    @property
    def command_prefix(self) -> str:
        return "@"

    @property
    def supports_hooks(self) -> bool:
        return False

    @property
    def hooks_config_path(self) -> str | None:
        return None

    @property
    def mcp_config_path(self) -> str | None:
        return ".cursor/mcp.json"

    @property
    def skill_format(self) -> str:
        return "rule_md"

    # ── 模板变量 ──

    # Cursor 没有插件变量机制，需要知道引擎的绝对路径。
    # 安装时由 install() 更新 _engine_root。
    _engine_root: str = ""

    @property
    def template_vars(self) -> dict[str, str]:
        import sys
        engine = self._engine_root or str(Path(__file__).resolve().parent.parent.parent)
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

    def set_engine_root(self, path: str) -> None:
        """设置引擎根目录（Cursor 没有变量机制，需要绝对路径）。"""
        self._engine_root = path

    # ── 已有文件检测 ──

    def get_existing_file_patterns(self) -> list[str]:
        return [".cursor/rules/aicode.md", ".cursor/", ".cursor/rules/"]

    # ── 内容生成 ──

    def render_main_config(
        self, profile: ProjectProfile, providers: list[Any] | None = None
    ) -> str:
        """生成 .cursor/rules/aicode.md 自举引导文件 —— Python 只写 prompt，AI 负责生成完整配置。"""
        return self._render_bootstrap_prompt(
            project_name=profile.project_name,
            tool_display_name=self.display_name,
            main_config_path=self.main_config_path,
            rules_dir=self.rules_dir,
            command_prefix=self.command_prefix,
        )

    # ── MCP 配置 ──

    def generate_mcp_config(self, servers: list[McpServerDef]) -> dict[str, Any]:
        """生成 Cursor 格式的 MCP 配置。"""
        mcp_servers: dict[str, dict] = {}
        for s in servers:
            entry: dict = {"command": s.command, "args": s.args}
            if s.env:
                entry["env"] = s.env
            mcp_servers[s.name] = entry
        return {"mcpServers": mcp_servers}

    # ── Hooks ──

    def generate_hooks(self, providers: list[Any]) -> dict[str, Any]:
        return {}

    # ── 安装 ──

    def install(
        self,
        project_root: Path,
        plugin_root: Path,
        providers: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Cursor 安装：MCP 配置 / loop-config.json / karpathy.md 规则。"""
        created: list[str] = []
        skipped: list[str] = []
        errors: list[str] = []

        root = Path(project_root)
        src = Path(plugin_root)
        self._engine_root = str(src.resolve())  # Cursor 无变量机制，需要绝对路径

        # 1. MCP 配置
        all_servers: list[McpServerDef] = []
        for pv in (providers or []):
            all_servers.extend(pv.get_mcp_servers())
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
        loop_config = {
            "target_tool": self.tool_id,
            **self.template_vars,
        }
        loop_config_dst.write_text(
            json.dumps(loop_config, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        created.append(str(loop_config_dst.relative_to(root)))

        # 3. Karpathy 行为准则 — 从插件源码原封不动拷贝，不让 AI 发挥
        karpathy_src = Path(plugin_root) / "skills" / "andrej-karpathy" / "SKILL.md"
        karpathy_dst = root / self.rules_dir / "karpathy.md"
        if karpathy_src.exists():
            karpathy_dst.parent.mkdir(parents=True, exist_ok=True)
            if not karpathy_dst.exists():
                karpathy_dst.write_text(
                    karpathy_src.read_text(encoding="utf-8"), encoding="utf-8"
                )
                created.append(str(karpathy_dst.relative_to(root)))
            else:
                skipped.append(str(karpathy_dst.relative_to(root)))
                logger.info("karpathy.md already exists, skipping")
        else:
            logger.warning("karpathy SKILL.md not found at %s, skipping", karpathy_src)

        return {
            "success": len(errors) == 0,
            "files_created": created,
            "files_skipped": skipped,
            "errors": errors,
        }
