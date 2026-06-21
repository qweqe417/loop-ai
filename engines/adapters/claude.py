"""ClaudeCodeAdapter —— 把 AI Coding Loop 映射到 Claude Code。

生成 CLAUDE.md、.claude/rules/、.claude/aicode/、.claude/commands/、
hooks/hooks.json、.claude/mcp.json。
命令前缀 /，skill 格式为单个 .md 文件。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from engines.adapters.base import McpServerDef, ToolAdapter
from engines.init.models import ProjectProfile

logger = logging.getLogger(__name__)


class ClaudeCodeAdapter(ToolAdapter):
    """Claude Code 适配器。"""

    # ── 元信息 ──

    @property
    def tool_id(self) -> str:
        return "claude_code"

    @property
    def display_name(self) -> str:
        return "Claude Code"

    # ── 路径 ──

    @property
    def main_config_path(self) -> str:
        return "CLAUDE.md"

    @property
    def rules_dir(self) -> str:
        return ".claude/rules"

    @property
    def aicode_dir(self) -> str:
        return ".claude/aicode"

    @property
    def skills_dir(self) -> str:
        return ".claude/skills"

    # ── 命令/钩子 ──

    @property
    def command_prefix(self) -> str:
        return "/"

    @property
    def supports_hooks(self) -> bool:
        return True

    @property
    def hooks_config_path(self) -> str | None:
        return "hooks/hooks.json"

    @property
    def mcp_config_path(self) -> str | None:
        return ".claude/mcp.json"

    @property
    def skill_format(self) -> str:
        return "single_md"

    # ── 模板变量 ──

    @property
    def template_vars(self) -> dict[str, str]:
        return {
            "plugin_root": "${CLAUDE_PLUGIN_ROOT}",
            "engines_cmd": "bash ${CLAUDE_PLUGIN_ROOT}/engines/run.sh",
            "engines_cmd_win": "%CLAUDE_PLUGIN_ROOT%\\engines\\run.bat",
            "cmd_prefix": self.command_prefix,
            "context_var": "${CLAUDE_PLUGIN_ROOT}",
            "aicode_dir": ".claude/aicode",
            "mcp_call": "通过 Claude MCP 工具调用",
            "tool_name": self.display_name,
            "tool_name_lower": self.tool_id,
        }

    # ── 已有文件检测 ──

    def get_existing_file_patterns(self) -> list[str]:
        return [
            "CLAUDE.md",
            ".claude/",
            ".claude/rules/",
        ]

    # ── 内容生成 ──

    def render_main_config(
        self, profile: ProjectProfile, providers: list[Any] | None = None
    ) -> str:
        """生成 CLAUDE.md 自举引导文件 —— Python 只写 prompt，AI 负责生成完整配置。"""
        return self._render_bootstrap_prompt(
            project_name=profile.project_name,
            tool_display_name=self.display_name,
            main_config_path=self.main_config_path,
            rules_dir=self.rules_dir,
            command_prefix=self.command_prefix,
        )

    # ── MCP 配置 ──

    def generate_mcp_config(self, servers: list[McpServerDef]) -> dict[str, Any]:
        """生成 Claude Code 格式的 MCP 配置。

        Claude Code 格式:
          {"mcpServers": {"name": {"command": "npx", "args": [...], "env": {...}}}}
        """
        mcp_servers: dict[str, dict] = {}
        for s in servers:
            entry: dict = {"command": s.command, "args": s.args}
            if s.env:
                entry["env"] = s.env
            if s.description:
                entry["description"] = s.description
            mcp_servers[s.name] = entry
        return {"mcpServers": mcp_servers}

    # ── Hooks ──

    def generate_hooks(self, providers: list[Any]) -> dict[str, Any]:
        """生成 Claude Code hooks 配置（hooks/hooks.json）。

        合并所有 provider 的 hook 声明。
        """
        hooks: dict[str, list] = {}

        for pv in (providers or []):
            pv_hooks = pv.get_hooks()
            for event, handlers in pv_hooks.items():
                if event not in hooks:
                    hooks[event] = []
                for h in handlers:
                    rendered = {}
                    for k, v in h.items():
                        if isinstance(v, str):
                            rendered[k] = self.render_skill(v)
                        else:
                            rendered[k] = v
                    hooks[event].append(rendered)

        # 默认 SessionStart hook
        if "SessionStart" not in hooks:
            hooks["SessionStart"] = []
        hooks["SessionStart"].append({
            "matcher": "startup|clear|compact",
            "hooks": [
                {
                    "type": "command",
                    "command": self.render_skill(
                        "{engines_cmd} context project-map --format json 2>/dev/null"
                    ),
                    "async": False,
                }
            ],
        })

        return {"hooks": hooks}

    # ── 安装 ──

    def install(
        self,
        project_root: Path,
        plugin_root: Path,
        providers: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Claude Code 安装：MCP 配置 / loop-config.json / karpathy.md 规则。"""
        created: list[str] = []
        skipped: list[str] = []
        errors: list[str] = []

        root = Path(project_root)

        # 1. MCP 配置
        all_servers: list[McpServerDef] = []
        for pv in (providers or []):
            all_servers.extend(pv.get_mcp_servers())
        if all_servers:
            mcp_dst = root / self.mcp_config_path  # type: ignore[arg-type]
            mcp_dst.parent.mkdir(parents=True, exist_ok=True)
            mcp_config = self.generate_mcp_config(all_servers)
            mcp_dst.write_text(
                json.dumps(mcp_config, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            created.append(str(mcp_dst.relative_to(root)))

        # 2. loop-config.json（运行时 CLI 读取，知道当前工具和命令格式）
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
                karpathy_dst.write_text(karpathy_src.read_text(encoding="utf-8"), encoding="utf-8")
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


