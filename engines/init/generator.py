"""FileGenerator —— 根据 ProjectProfile 和 ToolAdapter 生成所有项目文件。

**现在完全工具无关** —— 所有路径和内容委托给 ToolAdapter。
支持 Claude Code / Codex / Cursor 等任意 AI 工具。
（.claude/skills/ 等由 adapter.install() 在插件安装时写入，init 只生成规则和资产文件）
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from engines.adapters.base import ToolAdapter
    from .models import ProjectProfile, InitReport

logger = logging.getLogger(__name__)


class FileGenerator:
    """根据 ProjectProfile 和 ToolAdapter 生成工具原生文件。

    用法:
        adapter = ClaudeCodeAdapter()
        generator = FileGenerator(profile, project_root=".", adapter=adapter)
        report = generator.generate_all()

    Provider skill 文件的安装由 adapter.install() 执行，
    init 的 FileGenerator 只负责项目规则和资产文件。
    """

    def __init__(
        self,
        profile: ProjectProfile,
        project_root: str | Path = ".",
        adapter: ToolAdapter | None = None,
        providers: list[Any] | None = None,
    ) -> None:
        self.profile = profile
        self._root = Path(project_root)
        self._adapter = adapter
        self._providers = providers or []
        self._created: list[str] = []
        self._skipped: list[str] = []
        self._merged: list[str] = []

    @property
    def adapter(self) -> ToolAdapter:
        """获取工具适配器。未设置时默认使用 ClaudeCodeAdapter。"""
        if self._adapter is None:
            from engines.adapters.claude import ClaudeCodeAdapter
            self._adapter = ClaudeCodeAdapter()
        return self._adapter

    def generate_all(self) -> list[str]:
        """生成所有文件，返回已创建的文件路径列表。"""
        self._created = []
        self._skipped = []
        self._merged = []

        adapter = self.adapter

        self._generate_main_config()
        self._generate_rules()
        self._generate_aicode_files()
        self._generate_ai_assets()

        logger.info(
            "Generated %d files for %s, skipped %d, merged %d",
            len(self._created),
            adapter.display_name,
            len(self._skipped),
            len(self._merged),
        )
        return self._created

    def build_report(self) -> InitReport:
        """构建 InitReport。"""
        from .models import InitReport

        p = self.profile
        report = InitReport(
            success=True,
            profile=p,
            files_created=list(self._created),
            files_skipped=list(self._skipped),
            files_merged=list(self._merged),
            installed_plugins=[pl.name for pl in p.detected_plugins if pl.installed],
            missing_optional=p.missing_recommended,
            next_steps=self._build_next_steps(),
            total_duration_ms=p.scan_duration_ms,
        )
        return report

    # ── 主配置 ──────────────────────────────────────────

    def _generate_main_config(self) -> None:
        """生成工具的主配置文件（CLAUDE.md / .codex/instructions.md 等）。"""
        p = self.profile
        adapter = self.adapter
        target_path = self._root / adapter.main_config_path

        # 检测是否已有来自当前工具或其他工具的配置
        if target_path.exists():
            logger.info("%s exists, skipping (would merge)", adapter.main_config_path)
            self._skipped.append(f"{adapter.main_config_path} (已存在，建议手动合并)")
            self._write_merge_suggestion(target_path)
            return

        content = adapter.render_main_config(p, self._providers)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content, encoding="utf-8")
        self._created.append(adapter.main_config_path)
        logger.info("Generated: %s", adapter.main_config_path)

    def _write_merge_suggestion(self, existing_path: Path) -> None:
        """当主配置文件已存在时，生成合并建议。"""
        adapter = self.adapter
        suggestion_dir = self._root / adapter.aicode_dir
        suggestion_dir.mkdir(parents=True, exist_ok=True)

        suggestion = [
            f"# {adapter.main_config_path} 合并建议",
            "",
            f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"> 目标工具: {adapter.display_name}",
            "",
            f"检测到已有 `{adapter.main_config_path}`，不做覆盖。",
            "",
            "## 建议新增的内容",
            "",
            "以下内容建议添加到现有文件中：",
            "",
            "### AI Coding Loop 集成",
            "",
            f"```markdown",
            f"## AI Coding Loop 命令",
            "",
        ]
        cp = adapter.command_prefix
        for cmd in [
            f"{cp}aicode-full — 完整开发流程",
            f"{cp}aicode-dev — 开发模式",
            f"{cp}aicode-test — 测试模式",
            f"{cp}aicode-spec — 生成 Spec",
            f"{cp}aicode-direct — 快速通道",
            f"{cp}aicode-review — 代码审查",
            f"{cp}aicode-memory — 记忆沉淀",
        ]:
            suggestion.append(f"- `{cmd}`")
        suggestion.append("```")
        suggestion.append("")

        suggestion_path = suggestion_dir / "merge-suggestion.md"
        suggestion_path.write_text("\n".join(suggestion), encoding="utf-8")
        self._created.append(str(suggestion_path.relative_to(self._root)))

    # ── 规则文件 ────────────────────────────────────────

    def _generate_rules(self) -> None:
        """生成规则文件（.claude/rules/ 或 .cursor/rules/ 等）。"""
        adapter = self.adapter
        p = self.profile
        rules_dir = self._root / adapter.rules_dir
        rules_dir.mkdir(parents=True, exist_ok=True)

        rules = adapter.render_rules(p)

        for filename, content in rules.items():
            target = rules_dir / filename
            if target.exists():
                self._skipped.append(str(target.relative_to(self._root)))
                continue
            target.write_text(content, encoding="utf-8")
            self._created.append(str(target.relative_to(self._root)))

    # ── AI Coding Loop 资产 ─────────────────────────────

    def _generate_aicode_files(self) -> None:
        """生成 AI Coding Loop 资产文件（项目地图、风格摘要、工作流）。"""
        adapter = self.adapter
        p = self.profile
        aicode_dir = self._root / adapter.aicode_dir
        aicode_dir.mkdir(parents=True, exist_ok=True)

        files = adapter.render_aicode_files(p)

        for filename, content in files.items():
            target = aicode_dir / filename
            target.write_text(content, encoding="utf-8")
            self._created.append(str(target.relative_to(self._root)))

    # ── .ai/ 跨工具资产 ──────────────────────────────────

    def _generate_ai_assets(self) -> None:
        """Step 11: 初始化 .ai 跨工具资产。"""
        ai_dir = self._root / ".ai"
        ai_dir.mkdir(parents=True, exist_ok=True)

        # .ai/memory.md — 空模板
        memory_file = ai_dir / "memory.md"
        if not memory_file.exists():
            memory_content = self._render_memory_template()
            memory_file.write_text(memory_content, encoding="utf-8")
            self._created.append(".ai/memory.md")

        # .ai/scenarios/
        scenarios_dir = ai_dir / "scenarios"
        scenarios_dir.mkdir(parents=True, exist_ok=True)
        readme = scenarios_dir / "README.md"
        if not readme.exists():
            readme.write_text(
                "# 验证场景\n\n"
                "此目录存放 AI Coding Loop 的验证场景文件。\n\n"
                "场景定义格式见 `.ai/scenarios/example.yaml`。\n"
                "当任务涉及接口行为变更或数据库状态变更时，"
                "需要编写对应的验证场景。\n",
                encoding="utf-8",
            )

        # .ai/fixtures/
        (ai_dir / "fixtures").mkdir(parents=True, exist_ok=True)

        # .ai/runs/
        (ai_dir / "runs").mkdir(parents=True, exist_ok=True)

        # .ai/spec-index.yaml
        spec_index = ai_dir / "spec-index.yaml"
        if not spec_index.exists():
            spec_index.write_text(
                "# AI Coding Loop — Spec Index\n"
                "# 记录所有 Spec 文件的索引和状态\n\n"
                "version: 1\n"
                "providers: []\n"
                "specs: []\n",
                encoding="utf-8",
            )

    def _render_memory_template(self) -> str:
        return "\n".join([
            "# 项目记忆",
            "",
            f"> 初始化: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "> 条目总数: 0",
            "",
            "---",
            "",
            "## 代码风格",
            "<!-- 暂无条目 -->",
            "",
            "## 通用规则",
            "<!-- 暂无条目 -->",
            "",
            "## 禁止事项",
            "<!-- 暂无条目 -->",
            "",
            "## 历史坑",
            "<!-- 暂无条目 -->",
            "",
            "## 失败模式",
            "<!-- 暂无条目 -->",
            "",
            "## 模块边界",
            "<!-- 暂无条目 -->",
            "",
            "## 架构决策",
            "<!-- 暂无条目 -->",
            "",
            "## 测试经验",
            "<!-- 暂无条目 -->",
            "",
            "## 验证模式",
            "<!-- 暂无条目 -->",
            "",
        ])

    # ── 下一步建议 ─────────────────────────────────────────

    def _build_next_steps(self) -> list[str]:
        p = self.profile
        adapter = self.adapter
        steps: list[str] = []

        if p.missing_recommended:
            for m in p.missing_recommended:
                steps.append(f"安装推荐插件: {m}")

        if p.code_style.confidence in ("low",):
            steps.append("运行 `aicode calibrate` 确认代码规范")

        if not p.test_framework:
            steps.append("手动配置测试框架和运行命令")

        if p.resources:
            steps.append(f"为检测到的外部资源配置 MCP Server（{adapter.display_name}）：")
            for r in p.resources:
                steps.append(f"  - {r.name}: `aicode mcp setup {r.type}`")

        cp = adapter.command_prefix
        steps.append(f"运行 `{cp}aicode-spec <需求>` 生成第一个 Spec")
        steps.append(f"或运行 `{cp}aicode-direct <小改动>` 体验快速通道")

        return steps
