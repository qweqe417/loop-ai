"""ToolAdapter 抽象基类 —— 定义 AI 工具适配器的统一接口。

每个 AI 工具（Claude Code / Codex / Cursor）有各自的子类实现。
职责：工具原生文件路径、命令格式、MCP 配置格式、模板变量渲染。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from engines.init.models import ProjectProfile


@dataclass
class McpServerDef:
    """MCP Server 定义 —— 完全工具无关。

    ToolAdapter 负责翻译成具体工具的 MCP 配置格式。
    """

    name: str
    description: str = ""
    command: str = "npx"
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    required: bool = False


class ToolAdapter(ABC):
    """AI 工具适配器抽象基类。

    子类必须实现：
      - 工具元信息 (tool_id, display_name)
      - 文件路径映射 (main_config_path, rules_dir, aicode_dir, commands_dir)
      - 命令格式 (command_prefix)
      - 模板变量 (template_vars)
      - Hook/MCP 支持声明
      - 内容渲染方法 (render_main_config, render_rules, render_aicode_files, render_workflow)

    使用方式:
        adapter = ClaudeCodeAdapter()
        content = adapter.render_main_config(profile, providers)
        adapter.install_provider(superpowers_provider, project_root)
    """

    # ── 子类必须覆写的元信息 ──

    @property
    @abstractmethod
    def tool_id(self) -> str:
        """工具标识: "claude_code" / "codex" / "cursor" """
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """显示名: "Claude Code" / "Codex CLI" / "Cursor" """
        ...

    # ── 子类必须覆写的路径 ──

    @property
    @abstractmethod
    def main_config_path(self) -> str:
        """主配置文件: "CLAUDE.md" / ".codex/instructions.md" """
        ...

    @property
    @abstractmethod
    def rules_dir(self) -> str:
        """规则文件目录: ".claude/rules" / ".cursor/rules" """
        ...

    @property
    @abstractmethod
    def aicode_dir(self) -> str:
        """AI Coding Loop 资产目录: ".claude/aicode" / ".codex/aicode" """
        ...

    @property
    @abstractmethod
    def commands_dir(self) -> str | None:
        """命令入口目录: ".claude/commands" / None（不支持时）"""
        ...

    # ── 子类必须覆写的命令/钩子 ──

    @property
    @abstractmethod
    def command_prefix(self) -> str:
        """命令前缀: "/" for Claude/Codex, "@" for Cursor"""
        ...

    @property
    @abstractmethod
    def supports_hooks(self) -> bool:
        """是否支持 hooks 机制。"""
        ...

    @property
    @abstractmethod
    def hooks_config_path(self) -> str | None:
        """hooks 配置文件路径: "hooks/hooks.json" / None"""
        ...

    @property
    @abstractmethod
    def mcp_config_path(self) -> str | None:
        """MCP 配置文件路径: ".claude/mcp.json" / ".codex/mcp.json" / None"""
        ...

    @property
    @abstractmethod
    def skill_format(self) -> str:
        """Skill 文件格式:
        "single_md"          — .claude/skills/xxx.md（Claude Code）
        "dir_with_skill_md"  — .codex/skills/xxx/SKILL.md（Codex）
        "rule_md"            — .cursor/rules/xxx.md（Cursor）
        """
        ...

    # ── 子类必须覆写的模板变量 ──

    @property
    @abstractmethod
    def template_vars(self) -> dict[str, str]:
        """模板变量映射。

        Provider 的 skill 模板中用 {plugin_root}、{engines_cmd}、{cmd_prefix} 等占位符，
        Adapter 在这里定义每个占位符的具体值。

        必须包含的 key:
          - "plugin_root":   引擎根路径变量
          - "engines_cmd":   调用 engines/run.sh 的完整命令
          - "cmd_prefix":    命令前缀（/ 或 @）
          - "context_var":   Context Router 项目地图的注入方式
        """
        ...

    # ── 模板渲染 ──

    def render_skill(self, template: str) -> str:
        """把 Provider 模板渲染成当前工具可用的 skill/rule 文件内容。

        替换 {key} 为 self.template_vars[key]。
        """
        result = template
        for key, val in self.template_vars.items():
            result = result.replace(f"{{{key}}}", val)
        return result

    # ── 内容生成（子类必须实现） ──

    @abstractmethod
    def render_main_config(
        self, profile: ProjectProfile, providers: list[Any] | None = None
    ) -> str:
        """生成工具的主配置/指令文件内容（CLAUDE.md / instructions.md 等）。"""
        ...

    @abstractmethod
    def render_rules(self, profile: ProjectProfile) -> dict[str, str]:
        """返回 {文件名: 内容} 的规则文件映射。"""
        ...

    @abstractmethod
    def render_aicode_files(self, profile: ProjectProfile) -> dict[str, str]:
        """返回 {文件名: 内容} 的项目地图/风格摘要/工作流等。"""
        ...

    @abstractmethod
    def render_workflow(self, profile: ProjectProfile) -> str:
        """生成工作流说明（命令格式跟随当前工具）。"""
        ...

    # ── MCP 配置生成 ──

    @abstractmethod
    def generate_mcp_config(self, servers: list[McpServerDef]) -> dict[str, Any]:
        """把 MCP Server 列表翻译成当前工具的原生 MCP 配置格式。

        Claude Code: {"mcpServers": {"mysql": {"command": "npx", "args": [...]}}}
        Codex:       {"mcpServers": {"mysql": {"type": "stdio", "command": "npx", ...}}}
        Cursor:      {".cursor/mcp.json": {...}}
        """
        ...

    # ── Hooks 生成 ──

    @abstractmethod
    def generate_hooks(self, providers: list[Any]) -> dict[str, Any]:
        """生成 hooks 配置（SessionStart 等）。

        无 hooks 机制的工具返回 {}。
        """
        ...

    # ── 安装 ──

    @abstractmethod
    def install(
        self,
        project_root: Path,
        plugin_root: Path,
        providers: list[Any] | None = None,
    ) -> dict[str, Any]:
        """执行工具特定的安装步骤。

        返回 {"created": [...], "skipped": [...], "errors": [...]}
        """
        ...

    # ── 已有文件检测 ──

    def get_existing_file_patterns(self) -> list[str]:
        """返回需要检测是否已存在的文件/目录模式列表。

        用于 init 阶段的冲突检测。
        """
        patterns = [self.main_config_path, self.rules_dir, self.aicode_dir]
        if self.commands_dir:
            patterns.append(self.commands_dir)
        return [p for p in patterns if p]

    # ── 共享工具方法 ──

    @staticmethod
    def _append_language_rules(lines: list[str], profile: Any) -> None:
        """向 lines 列表追加语言特定的规则（工具无关）。"""
        lang = getattr(profile, "language", "")
        if lang == "python":
            lines.append("- 使用 pydantic v2 风格（model_validate 而非 dict()）")
            lines.append("- 异常使用项目统一异常类，不裸 raise")
            lines.append("- 遵循现有项目分层，不引入新的依赖模式")
        elif lang == "java":
            lines.append("- 遵循现有 Controller/Service/Repository 分层")
            lines.append("- 异常使用 @ExceptionHandler 或项目统一异常处理")
            lines.append("- 测试使用 JUnit，不引入新的测试框架")
        elif lang in ("typescript", "javascript"):
            lines.append("- 遵循现有组件结构和命名约定")
            lines.append("- 使用项目的 ESLint/Prettier 配置")
            lines.append("- 测试使用项目已有测试框架")

    @staticmethod
    def _copy_file(src: Path, dst: Path) -> bool:
        """复制文件，目标已存在时返回 False。"""
        import shutil
        try:
            if dst.exists():
                return False
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            return True
        except Exception:
            return False

    # ── 共享渲染方法 ──────────────────────────────────────

    @staticmethod
    def _render_code_style_rule(p: Any) -> str:
        """生成代码风格规则（工具无关）。"""
        from datetime import datetime
        style = p.code_style
        lines = [
            "# 代码风格规范",
            "",
            f"> 初始状态: {style.status}",
            f"> 可信度: {style.confidence}",
            f"> 基于项目扫描自动生成，可通过 `aicode calibrate` 校准",
            "",
            "## 命名约定",
            f"- {style.naming_convention or '遵循语言惯例'}",
            "",
            "## 测试命名",
            f"- {style.test_naming or '遵循框架惯例'}",
            "",
            "## 异常处理",
            f"- {style.exception_pattern or '遵循语言惯例'}",
            "",
            "## 日志",
            f"- {style.logging_framework or '遵循语言惯例'}",
            "",
        ]
        if p.linter_configs:
            lines.append("## 格式化")
            for cfg in p.linter_configs:
                lines.append(f"- 配置: `{cfg}`")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _render_testing_rule(p: Any) -> str:
        """生成测试规范（工具无关）。"""
        lines = [
            "# 测试规范",
            "",
            "## 测试框架",
            f"- {p.test_framework}",
            f"- 运行命令: `{p.test_runner_command}`",
            "",
            "## 测试目录",
        ]
        for d in p.test_dirs:
            lines.append(f"- `{d}/`")
        lines.append("")
        lines.append("## 测试类型")
        lines.append(f"- 单元测试: {'已检测' if p.has_unit_tests else '未检测到'}")
        lines.append(f"- 集成测试: {'已检测' if p.has_integration_tests else '未检测到'}")
        lines.append(f"- E2E: {'已检测' if p.has_e2e_tests else '未检测到'}")
        lines.append("")
        if p.has_docker_compose:
            lines.append("## Docker Compose")
            lines.append("- 检测到 docker-compose，可能用于测试环境")
            lines.append("")
        lines.append("## 验证原则")
        lines.append("- 测试应可独立运行，不依赖特定顺序")
        lines.append("- 不删除或弱化已有测试断言")
        lines.append("- 新增功能应有对应测试")
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _render_safety_rule() -> str:
        """生成安全约束（工具无关）。"""
        return "\n".join([
            "# 安全约束",
            "",
            "## 禁止事项",
            "",
            "- **禁止** 修改 `.claude/settings.json` 的 allow 列表",
            "- **禁止** 删除测试断言或 skip 测试来让测试通过",
            "- **禁止** 修改超出授权范围的文件",
            "- **禁止** 引入未在 Plan 中声明的新依赖",
            "- **禁止** 操作生产环境数据库",
            "- **禁止** 执行 DDL / DROP / TRUNCATE",
            "- **禁止** 硬编码密钥或敏感信息",
            "",
            "## 修改边界",
            "",
            "AI 修改代码前必须声明：",
            "- 计划修改哪些文件",
            "- 不修改哪些文件",
            "- 修改理由",
            "- 验证方式",
            "",
            "## Guard 规则",
            "",
            "每次修改前后自动运行 Guard 检查：",
            "- 修改范围是否越界",
            "- 风险等级是否匹配",
            "- 基础冒烟检查是否通过",
            "",
        ])

    @staticmethod
    def _render_project_map(p: Any) -> str:
        """生成项目地图（工具无关）。"""
        from datetime import datetime
        lines = [
            f"# {p.project_name} — 项目地图",
            "",
            f"> 自动生成于: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"> 语言: {p.language} | 框架: {p.framework}",
            "",
            "## 目录结构",
            "",
        ]
        for d in p.source_dirs:
            lines.append(f"- `{d}/` — **源代码**")
        for d in p.test_dirs:
            lines.append(f"- `{d}/` — **测试**")
        for d in p.config_dirs:
            lines.append(f"- `{d}/` — **配置**")
        for d in p.migration_dirs:
            lines.append(f"- `{d}/` — **数据库迁移**")

        lines.append("")
        lines.append("## 入口文件")
        for f in p.entry_files:
            lines.append(f"- `{f}`")
        if not p.entry_files:
            lines.append("- 未自动识别")

        lines.append("")
        lines.append("## 外部资源")
        if p.resources:
            for r in p.resources:
                lines.append(f"- **{r.name}** ({r.type}) — 来源: {r.evidence}")
        else:
            lines.append("- 未检测到外部资源")

        return "\n".join(lines)

    @staticmethod
    def _render_style_summary(p: Any) -> str:
        """生成代码风格摘要（工具无关）。"""
        style = p.code_style
        return "\n".join([
            f"# {p.project_name} — 代码风格摘要",
            "",
            f"> 初始状态: {style.status} | 可信度: {style.confidence}",
            f"> 使用 `aicode calibrate` 确认或修正规则",
            "",
            "## 命名",
            f"- {style.naming_convention or '未识别'}",
            "",
            "## 异常处理",
            f"- {style.exception_pattern or '未识别'}",
            "",
            "## 日志",
            f"- {style.logging_framework or '未识别'}",
            "",
            "## 格式化",
            f"- {style.formatter or '未识别'}",
            *(f"- 配置文件: `{c}`" for c in p.linter_configs),
            "",
        ])
