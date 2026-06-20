"""ClaudeCodeAdapter —— 把 AI Coding Loop 映射到 Claude Code。

生成 CLAUDE.md、.claude/rules/、.claude/aicode/、.claude/commands/、
hooks/hooks.json、.claude/mcp.json。
命令前缀 /，skill 格式为单个 .md 文件。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from engines.adapters.base import McpServerDef, ToolAdapter
from engines.init.models import ProjectProfile


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
    def commands_dir(self) -> str | None:
        return ".claude/commands"

    @property
    def global_commands_dir(self) -> Path:
        return Path.home() / ".claude" / "commands"

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
            ".claude/aicode/",
            ".claude/skills/",
            "hooks/hooks.json",
        ]

    # ── 内容生成 ──

    def render_main_config(
        self, profile: ProjectProfile, providers: list[Any] | None = None
    ) -> str:
        """生成 CLAUDE.md（60-100 行）。"""
        p = profile
        lines = [
            f"# {p.project_name} — 项目说明",
            "",
            "## 技术栈",
            f"- 语言: {p.language}",
            f"- 框架: {p.framework}",
            f"- 包管理: {p.package_manager}",
        ]

        # 关键目录
        if p.source_dirs or p.test_dirs or p.config_dirs or p.migration_dirs:
            lines.append("")
            lines.append("## 关键目录")
            for d in p.source_dirs:
                lines.append(f"- `{d}/` — 源代码")
            for d in p.test_dirs:
                lines.append(f"- `{d}/` — 测试")
            for d in p.config_dirs:
                lines.append(f"- `{d}/` — 配置")
            for d in p.migration_dirs:
                lines.append(f"- `{d}/` — 数据库迁移")

        # 必须遵守的硬规则
        lines.append("")
        lines.append("## 必须遵守的规则")
        lines.append("")
        self._append_language_rules(lines, p)

        # 禁止行为
        lines.append("")
        lines.append("## 禁止行为")
        lines.append("")
        lines.append("- **禁止** 修改 `.claude/settings.json` 的 allow 列表")
        lines.append("- **禁止** 删除测试断言或 skip 测试来让测试通过")
        lines.append("- **禁止** 修改超出授权范围的文件")
        lines.append("- **禁止** 引入未在 Plan 中声明的新依赖")

        # 命令入口
        lines.append("")
        lines.append("## AI Coding Loop 命令")
        lines.append("")
        lines.append("本项目已集成 AI Coding Loop 插件，可用命令：")
        for cmd in self._get_aicode_commands():
            lines.append(f"- `{cmd}`")

        # Provider 集成说明
        if providers:
            lines.append("")
            lines.append("## 集成的外部能力")
            lines.append("")
            for pv in providers:
                instructions = self.render_skill(pv.get_ai_instructions())
                lines.append(instructions)

        # 细规则索引
        lines.append("")
        lines.append("## 详细规则")
        lines.append("")
        lines.append("详细规则分散在以下文件中，按需读取：")
        lines.append("- `.claude/rules/code-style.md` — 代码风格规范")
        lines.append("- `.claude/rules/testing.md` — 测试规范")
        lines.append("- `.claude/rules/safety.md` — 安全约束")
        if (Path(profile.root_path) / ".claude/rules/database.md").exists():
            lines.append("- `.claude/rules/database.md` — 数据库规范")
        if (Path(profile.root_path) / ".claude/rules/api.md").exists():
            lines.append("- `.claude/rules/api.md` — API 规范")
        lines.append("- `.ai/memory.md` — 项目经验沉淀")

        lines.append("")
        lines.append("<!-- AI_CODING_LOOP_MEMORY_START -->")
        lines.append("<!-- AI_CODING_LOOP_MEMORY_END -->")

        return "\n".join(lines)

    def render_rules(self, profile: ProjectProfile) -> dict[str, str]:
        """生成 .claude/rules/*.md。"""
        p = profile
        return {
            "code-style.md": self._render_code_style_rule(p),
            "testing.md": self._render_testing_rule(p),
            "safety.md": self._render_safety_rule(),
        }

    def render_aicode_files(self, profile: ProjectProfile) -> dict[str, str]:
        """生成 .claude/aicode/*（项目地图、风格摘要、工作流）。"""
        p = profile
        return {
            "project-map.md": self._render_project_map(p),
            "style.md": self._render_style_summary(p),
            "workflow.md": self.render_workflow(p),
        }

    def render_workflow(self, profile: ProjectProfile) -> str:
        """工作流说明 —— 命令格式为 /aicode-xxx。"""
        cp = self.command_prefix
        return "\n".join([
            "# AI Coding Loop — 工作流说明",
            "",
            "## 可用模式",
            "",
            "| 模式 | 命令 | 适用场景 |",
            "|------|------|---------|",
            f"| 完整流程 | `{cp}aicode-full` | L3-L5 大中型需求 |",
            f"| 开发模式 | `{cp}aicode-dev` | 已有 Spec/Plan |",
            f"| 测试模式 | `{cp}aicode-test` | 仅验证+修复 |",
            f"| Direct 模式 | `{cp}aicode-direct` | L1-L2 小改动 |",
            f"| Spec 生成 | `{cp}aicode-spec` | 只生成规格文档 |",
            f"| 代码审查 | `{cp}aicode-review` | PR 审查 |",
            f"| 记忆沉淀 | `{cp}aicode-memory` | 经验持久化 |",
            "",
            "## 流程说明",
            "",
            "完整 Loop 流程: INTAKE → SPEC → PLAN → EXECUTE → VERIFY → REPAIR → REVIEW → MEMORY",
            "",
            "Direct Mode: DIRECT_EXECUTE → VERIFY → REVIEW（跳过 Spec/Plan）",
            "",
            "Test Mode: VERIFY ↔ REPAIR（验证+修复循环）",
            "",
        ])

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
        """Claude Code 安装：拷贝 skills、写 hooks、写 plugin-root.txt。"""
        created: list[str] = []
        skipped: list[str] = []
        errors: list[str] = []

        root = Path(project_root)
        src = Path(plugin_root)

        # 1. 拷贝 skill 文件到 .claude/skills/（渲染模板变量）
        skills_src = src / "skills"
        skills_dst = root / ".claude" / "skills"
        if skills_src.exists():
            skills_dst.mkdir(parents=True, exist_ok=True)
            for skill_md in skills_src.glob("*.md"):
                dst = skills_dst / skill_md.name
                if dst.exists():
                    skipped.append(f"{skill_md.name} (已存在)")
                    continue
                template = skill_md.read_text(encoding="utf-8")
                content = self.render_skill(template)
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(content, encoding="utf-8")
                created.append(str(dst.relative_to(root)))

        # 2. 写入 hooks.json
        hooks_dst = root / "hooks" / "hooks.json"
        hooks_config = self.generate_hooks(providers or [])
        hooks_dst.parent.mkdir(parents=True, exist_ok=True)
        hooks_dst.write_text(
            json.dumps(hooks_config, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        created.append(str(hooks_dst.relative_to(root)))

        # 3. 写入 MCP 配置
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

        # 4. 写入 plugin-root.txt（回退用）
        aicode_dir = root / ".claude" / "aicode"
        aicode_dir.mkdir(parents=True, exist_ok=True)
        plugin_root_file = aicode_dir / "plugin-root.txt"
        plugin_root_file.write_text(str(src.resolve()), encoding="utf-8")
        created.append(str(plugin_root_file.relative_to(root)))

        # 5. 写入 loop-config.json（运行时 CLI 读取，知道当前工具和命令格式）
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

        # 6. 安装各 provider 的文件
        for pv in (providers or []):
            self._install_provider_files(pv, root, created, skipped, errors)

        return {
            "success": len(errors) == 0,
            "files_created": created,
            "files_skipped": skipped,
            "errors": errors,
        }

    def _install_provider_files(
        self,
        provider: Any,
        root: Path,
        created: list[str],
        skipped: list[str],
        errors: list[str],
    ) -> None:
        """安装单个 provider 的 skill 文件到 .claude/skills/。

        Claude Code 格式: .claude/skills/{provider_name}-{key}.md
        """
        templates = provider.get_skill_templates()
        for key, template in templates.items():
            filename = f"{provider.name}-{key}.md"
            dst = root / ".claude" / "skills" / filename
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                skipped.append(str(dst.relative_to(root)))
                continue
            content = self.render_skill(template)
            dst.write_text(content, encoding="utf-8")
            created.append(str(dst.relative_to(root)))

    # ── 私有辅助 ──

    def _get_aicode_commands(self) -> list[str]:
        cp = self.command_prefix
        return [
            f"{cp}aicode-full — 完整开发流程（Spec→Plan→执行→验证→审查→记忆）",
            f"{cp}aicode-dev — 开发模式（已有 Spec/Plan 时用）",
            f"{cp}aicode-test — 测试模式（仅验证+修复）",
            f"{cp}aicode-spec — 生成 Spec（不写代码）",
            f"{cp}aicode-direct — 快速通道（小改动）",
            f"{cp}aicode-review — 代码审查",
            f"{cp}aicode-memory — 记忆沉淀",
        ]

