"""CodexAdapter —— 把 AI Coding Loop 映射到 Codex CLI。

生成 .codex/instructions.md、.codex/skills/aicode-xxx/SKILL.md、.codex/aicode/、
.codex/mcp.json。
命令前缀 /，skill 格式为目录+SKILL.md。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from engines.adapters.base import McpServerDef, ToolAdapter
from engines.init.models import ProjectProfile


class CodexAdapter(ToolAdapter):
    """Codex CLI 适配器。"""

    # ── 元信息 ──

    @property
    def tool_id(self) -> str:
        return "codex"

    @property
    def display_name(self) -> str:
        return "Codex CLI"

    # ── 路径 ──

    @property
    def main_config_path(self) -> str:
        return ".codex/instructions.md"

    @property
    def rules_dir(self) -> str:
        return ".codex/rules"

    @property
    def aicode_dir(self) -> str:
        return ".codex/aicode"

    @property
    def skills_dir(self) -> str:
        return ".codex/skills"

    # ── 命令/钩子 ──

    @property
    def command_prefix(self) -> str:
        return "/"

    @property
    def supports_hooks(self) -> bool:
        return True

    @property
    def hooks_config_path(self) -> str | None:
        return "hooks/hooks-codex.json"

    @property
    def mcp_config_path(self) -> str | None:
        return ".codex/mcp.json"

    @property
    def skill_format(self) -> str:
        return "dir_with_skill_md"

    # ── 模板变量 ──

    @property
    def template_vars(self) -> dict[str, str]:
        return {
            "plugin_root": "${PLUGIN_ROOT}",
            "engines_cmd": "bash ${PLUGIN_ROOT}/engines/run.sh",
            "engines_cmd_win": "%PLUGIN_ROOT%\\engines\\run.bat",
            "cmd_prefix": self.command_prefix,
            "context_var": "${PLUGIN_ROOT}",
            "aicode_dir": ".codex/aicode",
            "mcp_call": "通过 Codex MCP 工具调用",
            "tool_name": self.display_name,
            "tool_name_lower": self.tool_id,
        }

    # ── 已有文件检测 ──

    def get_existing_file_patterns(self) -> list[str]:
        return [".codex/instructions.md", ".codex/", ".codex/skills/"]

    # ── 内容生成 ──

    def render_main_config(
        self, profile: ProjectProfile, providers: list[Any] | None = None
    ) -> str:
        """生成 .codex/instructions.md 自举引导文件 —— Python 只写 prompt，AI 负责生成完整配置。"""
        return self._render_bootstrap_prompt(
            project_name=profile.project_name,
            tool_display_name=self.display_name,
            main_config_path=self.main_config_path,
            rules_dir=self.rules_dir,
            command_prefix=self.command_prefix,
        )

    # ── MCP 配置 ──

    def generate_mcp_config(self, servers: list[McpServerDef]) -> dict[str, Any]:
        """生成 Codex 格式的 MCP 配置。

        Codex 格式与 Claude 类似，但多一个 type 字段。
          {"mcpServers": {"name": {"type": "stdio", "command": "npx", "args": [...]}}}
        """
        mcp_servers: dict[str, dict] = {}
        for s in servers:
            entry: dict = {"type": "stdio", "command": s.command, "args": s.args}
            if s.env:
                entry["env"] = s.env
            mcp_servers[s.name] = entry
        return {"mcpServers": mcp_servers}

    # ── Hooks ──

    def generate_hooks(self, providers: list[Any]) -> dict[str, Any]:
        """Codex 暂无 hook 机制。"""
        return {}

    # ── 安装 ──

    def install(
        self,
        project_root: Path,
        plugin_root: Path,
        providers: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Codex 安装：MCP 配置 / loop-config.json。"""
        created: list[str] = []
        skipped: list[str] = []
        errors: list[str] = []

        root = Path(project_root)

        # 1. MCP 配置
        all_servers: list[McpServerDef] = []
        for pv in (providers or []):
            all_servers.extend(pv.get_mcp_servers())
        if all_servers:
            mcp_dst = root / ".codex/mcp.json"
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

        return {
            "success": len(errors) == 0,
            "files_created": created,
            "files_skipped": skipped,
            "errors": errors,
        }

    def _get_aicode_commands(self) -> list[str]:
        cp = self.command_prefix
        return [
            f"{cp}aicode-init — project init",
            f"{cp}aicode-calibrate — calibrate rules",
            f"{cp}aicode-spec — generate spec",
            f"{cp}aicode-plan — generate plan",
            f"{cp}aicode-full — full 8-stage loop",
            f"{cp}aicode-dev — dev mode",
            f"{cp}aicode-test — test mode",
            f"{cp}aicode-direct — quick path",
            f"{cp}aicode-verify — scenario verification",
            f"{cp}aicode-review — code review",
            f"{cp}aicode-memory — persist learnings",
        ]
