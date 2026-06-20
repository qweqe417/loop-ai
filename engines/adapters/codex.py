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
        return ".codex/skills/aicode-rules"

    @property
    def aicode_dir(self) -> str:
        return ".codex/aicode"

    @property
    def commands_dir(self) -> str | None:
        return None  # Codex 不支持单独的 commands 目录

    @property
    def global_commands_dir(self) -> Path:
        return Path.home() / ".codex" / "commands"

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
        p = profile
        lines = [
            f"# {p.project_name} — Project Instructions",
            "",
            "## Tech Stack",
            f"- Language: {p.language}",
            f"- Framework: {p.framework}",
            f"- Package Manager: {p.package_manager}",
            "",
        ]

        if p.source_dirs:
            lines.append("## Key Directories")
            for d in p.source_dirs:
                lines.append(f"- `{d}/` — source")
            for d in p.test_dirs:
                lines.append(f"- `{d}/` — tests")
            lines.append("")

        lines.append("## AI Coding Loop Commands")
        for cmd in self._get_aicode_commands():
            lines.append(f"- `{cmd}`")
        lines.append("")

        if providers:
            lines.append("## External Integrations")
            for pv in providers:
                instructions = self.render_skill(pv.get_ai_instructions())
                lines.append(instructions)
            lines.append("")

        # 规范文件生成指令
        if providers:
            lines.append("")
        lines.append(self._render_rules_generation_instruction(
            self.display_name, self.rules_dir
        ))
        lines.append("- `.ai/memory.md` — 项目记忆索引")
        lines.append("")

        return "\n".join(lines)

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
        """Codex 安装：拷贝 skills、写 MCP 配置。"""
        created: list[str] = []
        skipped: list[str] = []
        errors: list[str] = []

        root = Path(project_root)
        src = Path(plugin_root)
        skills_src = src / "skills"

        # 1. 拷贝 skill 文件到 .codex/skills/aicode-<name>/SKILL.md（渲染模板变量）
        if skills_src.exists():
            for skill_md in skills_src.glob("*.md"):
                skill_name = skill_md.stem
                skill_dir = root / ".codex" / "skills" / f"aicode-{skill_name}"
                skill_dir.mkdir(parents=True, exist_ok=True)
                dst = skill_dir / "SKILL.md"
                if dst.exists():
                    skipped.append(str(dst.relative_to(root)))
                    continue
                template = skill_md.read_text(encoding="utf-8")
                content = self.render_skill(template)
                dst.write_text(content, encoding="utf-8")
                created.append(str(dst.relative_to(root)))

        # 2. 安装各 provider 的 skill 文件
        # Codex 格式: .codex/skills/aicode-{key}/SKILL.md
        for pv in (providers or []):
            templates = pv.get_skill_templates()
            for key, template in templates.items():
                skill_dir = root / ".codex" / "skills" / f"{pv.name}-{key}"
                skill_dir.mkdir(parents=True, exist_ok=True)
                dst = skill_dir / "SKILL.md"
                if dst.exists():
                    skipped.append(str(dst.relative_to(root)))
                    continue
                content = self.render_skill(template)
                dst.write_text(content, encoding="utf-8")
                created.append(str(dst.relative_to(root)))

        # 3. MCP 配置
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

        # 4. plugin-root.txt
        aicode_dir = root / ".codex" / "aicode"
        aicode_dir.mkdir(parents=True, exist_ok=True)
        plugin_root_file = aicode_dir / "plugin-root.txt"
        plugin_root_file.write_text(str(src.resolve()), encoding="utf-8")
        created.append(str(plugin_root_file.relative_to(root)))

        # 5. 写入 loop-config.json
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
