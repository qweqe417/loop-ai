"""CursorAdapter —— 把 AI Coding Loop 映射到 Cursor。

生成 .cursor/rules/aicode.md、.cursor/rules/aicode-*.md、.cursor/aicode/。
命令前缀 @，无 hooks，skill 格式为 rule_md（.cursor/rules/）。
Cursor 没有插件变量机制，路径写绝对路径。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from engines.adapters.base import McpServerDef, ToolAdapter
from engines.init.models import ProjectProfile


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
    def commands_dir(self) -> str | None:
        return None

    @property
    def global_commands_dir(self) -> Path:
        return Path.home() / ".cursor" / "rules"

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
        p = profile
        engine = self._engine_root or str(Path(__file__).resolve().parent.parent.parent)

        lines = [
            f"# {p.project_name} — AI Coding 规则",
            "",
            f"> 语言: {p.language} | 框架: {p.framework}",
            f"> AI Coding Loop 引擎: `{engine}`",
            "",
            "## 关键目录",
        ]
        for d in p.source_dirs:
            lines.append(f"- `{d}/` — 源码")
        for d in p.test_dirs:
            lines.append(f"- `{d}/` — 测试")
        lines.append("")

        lines.append("## 必须遵守的规则")
        self._append_language_rules(lines, p)
        lines.append("")

        lines.append("## 禁止行为")
        lines.append("- **禁止** 删除测试断言或 skip 测试来让测试通过")
        lines.append("- **禁止** 修改超出授权范围的文件")
        lines.append("- **禁止** 引入未在 Plan 中声明的新依赖")
        lines.append("")

        lines.append("## AI Coding Loop")
        lines.append("")
        lines.append("AI Coding Loop 已集成。使用以下规则引用：")
        for rule_name in self._get_aicode_rules():
            lines.append(f"- `{rule_name}`")

        if providers:
            lines.append("")
            lines.append("## 集成的外部能力")
            for pv in providers:
                instructions = self.render_skill(pv.get_ai_instructions())
                lines.append(instructions)

        lines.append("")
        lines.append("## 详细规则")
        lines.append(f"- `{self.rules_dir}/aicode-code-style.md` — 代码风格")
        lines.append(f"- `{self.rules_dir}/aicode-testing.md` — 测试规范")
        lines.append(f"- `{self.rules_dir}/aicode-safety.md` — 安全约束")
        lines.append("- `.ai/memory.md` — 项目经验")
        lines.append("")

        return "\n".join(lines)

    def render_rules(self, profile: ProjectProfile) -> dict[str, str]:
        """Cursor 规则文件加 aicode- 前缀避免与用户已有规则冲突。"""
        p = profile
        raw_rules = {
            "code-style.md": self._render_code_style_rule(p),
            "testing.md": self._render_testing_rule(p),
            "safety.md": self._render_safety_rule(),
        }
        return {f"aicode-{k}": v for k, v in raw_rules.items()}

    def render_aicode_files(self, profile: ProjectProfile) -> dict[str, str]:
        p = profile
        return {
            "project-map.md": self._render_project_map(p),
            "style.md": self._render_style_summary(p),
            "workflow.md": self.render_workflow(p),
        }

    def render_workflow(self, profile: ProjectProfile) -> str:
        cp = self.command_prefix
        return "\n".join([
            "# AI Coding Loop — 工作流",
            "",
            "## 可用规则引用",
            "",
            "| 模式 | 规则引用 | 场景 |",
            "|------|---------|------|",
            f"| 完整流程 | `{cp}aicode-full` | L3-L5 大中型需求 |",
            f"| 开发模式 | `{cp}aicode-dev` | 已有 Spec/Plan |",
            f"| 测试模式 | `{cp}aicode-test` | 仅验证+修复 |",
            f"| Direct | `{cp}aicode-direct` | L1-L2 小改动 |",
            f"| Spec | `{cp}aicode-spec` | 仅生成规格 |",
            f"| Review | `{cp}aicode-review` | 代码审查 |",
            f"| Memory | `{cp}aicode-memory` | 经验沉淀 |",
            "",
            "## 流程",
            "INTAKE → SPEC → PLAN → EXECUTE → VERIFY → REPAIR → REVIEW → MEMORY",
            "",
        ])

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
        """Cursor 安装：写规则文件到 .cursor/rules/。"""
        created: list[str] = []
        skipped: list[str] = []
        errors: list[str] = []

        root = Path(project_root)
        src = Path(plugin_root)
        self._engine_root = str(src.resolve())

        rules_dir = root / ".cursor" / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)

        # 1. 安装 loop skill 文件为 .cursor/rules/aicode-{name}.md（渲染模板变量）
        skills_src = src / "skills"
        if skills_src.exists():
            for skill_md in skills_src.glob("*.md"):
                skill_name = skill_md.stem
                dst = rules_dir / f"aicode-{skill_name}.md"
                if dst.exists():
                    skipped.append(str(dst.relative_to(root)))
                    continue
                template = skill_md.read_text(encoding="utf-8")
                content = self.render_skill(template)
                dst.write_text(content, encoding="utf-8")
                created.append(str(dst.relative_to(root)))

        # 2. 安装各 provider 的 rule 文件
        for pv in (providers or []):
            templates = pv.get_skill_templates()
            for key, template in templates.items():
                filename = f"aicode-{pv.name}-{key}.md"
                dst = rules_dir / filename
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
            mcp_dst = root / ".cursor" / "mcp.json"
            mcp_dst.parent.mkdir(parents=True, exist_ok=True)
            mcp_config = self.generate_mcp_config(all_servers)
            mcp_dst.write_text(
                json.dumps(mcp_config, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            created.append(str(mcp_dst.relative_to(root)))

        # 4. 写入 loop-config.json
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

    def _get_aicode_rules(self) -> list[str]:
        return [
            "@aicode-full — 完整开发流程",
            "@aicode-dev — 开发模式",
            "@aicode-spec — 生成 Spec",
            "@aicode-direct — 快速通道",
            "@aicode-review — 代码审查",
            "@aicode-memory — 记忆沉淀",
        ]
