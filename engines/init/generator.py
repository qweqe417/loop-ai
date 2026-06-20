"""FileGenerator —— 根据 ProjectProfile 和 ToolAdapter 生成项目配置文件。

**完全工具无关** —— 所有路径和内容委托给 ToolAdapter。
支持 Claude Code / Codex / Cursor 等任意 AI 工具。

init 只生成主配置文件（CLAUDE.md 等）和 .ai/ 跨工具资产。
规则文件（code-style.md/testing.md/safety.md）不再硬编码生成，
而是由 AI 在首次处理任务时根据实际代码自行推断并写入 rules_dir。
skills/ 和 MCP 配置由 adapter.install() 在插件安装时写入。
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
        """生成所有文件，返回已创建的文件路径列表。

        注意：不含主配置文件和规则文件 —— 这些由 AI 通过 SKILL.md 直接写入。
        Python 只负责 .ai/ 资产目录。
        """
        self._created = []
        self._skipped = []
        self._merged = []

        self._generate_ai_assets()

        logger.info(
            "Generated %d files for %s, skipped %d, merged %d",
            len(self._created),
            self.adapter.display_name,
            len(self._skipped),
            len(self._merged),
        )
        return self._created

    def generate_ai_assets_only(self) -> list[str]:
        """仅生成 .ai/ 跨工具资产（与 generate_all() 等价）。

        Python 不生成配置内容 —— 所有 CLAUDE.md / rules/*.md 由 AI 写入。
        """
        return self.generate_all()

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

    # ── .ai/ 跨工具资产 ──────────────────────────────────

    def _generate_ai_assets(self) -> None:
        """初始化 .ai/ 目录及所有子资产。"""
        ai_dir = self._root / ".ai"
        ai_dir.mkdir(parents=True, exist_ok=True)

        self._init_memory_structure(ai_dir)
        self._init_scenarios(ai_dir)

        # .ai/config.yaml — 项目公共配置
        config_path = ai_dir / "config.yaml"
        if not config_path.exists():
            self._write_yaml(config_path, {
                "version": 1,
                "project": self.profile.project_name,
                "language": self.profile.language,
                "test_framework": self.profile.test_framework or "",
                "memory": {
                    "max_entries": 200,
                    "draft_stale_days": 30,
                    "projection_targets": ["claude", "codex", "cursor"],
                },
                "loop": {
                    "default_flow": "full",
                    "stages": [
                        "intake", "spec", "plan", "execute",
                        "verify", "repair", "review", "memory",
                    ],
                },
                "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            })
            self._created.append(".ai/config.yaml")

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

    def _init_memory_structure(self, ai_dir: Path) -> None:
        """初始化三层记忆目录结构。"""
        memory_dir = ai_dir / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)

        # 创建子目录
        for subdir in [
            "entries",
            "sessions",
            "archive/deprecated",
            "archive/stale",
            "projections",
        ]:
            d = memory_dir / subdir
            d.mkdir(parents=True, exist_ok=True)
            (d / ".gitkeep").touch(exist_ok=True)

        # .ai/memory.md — 空索引模板
        index_path = ai_dir / "memory.md"
        if not index_path.exists():
            now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            index_path.write_text(
                "# 项目记忆\n"
                "\n"
                f"> 更新: {now} | 总计: 0 | confirmed: 0 | draft: 0 | deprecated: 0\n"
                "\n"
                "> 此文件是权威记忆索引，只放高价值摘要，不放长文。\n"
                "> 详细正文在 .ai/memory/entries/ 下。\n"
                "\n"
                "## 通用规则\n\n<!-- 暂无条目 -->\n\n"
                "## 历史坑\n\n<!-- 暂无条目 -->\n\n"
                "## 验证模式\n\n<!-- 暂无条目 -->\n\n"
                "## 测试经验\n\n<!-- 暂无条目 -->\n\n"
                "## 模块边界\n\n<!-- 暂无条目 -->\n\n"
                "## 架构决策\n\n<!-- 暂无条目 -->\n\n"
                "## 失败模式\n\n<!-- 暂无条目 -->\n\n"
                "## 禁止事项\n\n<!-- 暂无条目 -->\n\n"
                "## 代码风格\n\n<!-- 暂无条目 -->\n",
                encoding="utf-8",
            )
            self._created.append(".ai/memory.md")

        # .ai/memory/stats.json — 运营面板空数据
        stats_path = memory_dir / "stats.json"
        if not stats_path.exists():
            import json
            stats_path.write_text(json.dumps({
                "total_entries": 0,
                "by_category": {},
                "confirmed": 0,
                "draft": 0,
                "deprecated": 0,
                "archived": 0,
                "last_updated": now,
                "last_compression": "",
                "last_archival": "",
                "last_projection": "",
                "hot_tags": [],
                "cold_entries": [],
            }, ensure_ascii=False, indent=2), encoding="utf-8")

    def _init_scenarios(self, ai_dir: Path) -> None:
        """初始化场景目录：config.yaml + example.yaml。"""
        scenarios_dir = ai_dir / "scenarios"
        scenarios_dir.mkdir(parents=True, exist_ok=True)

        # config.yaml — 公共配置
        config_path = scenarios_dir / "config.yaml"
        if not config_path.exists():
            self._write_yaml(config_path, {
                "version": 1,
                "scenarios_dir": ".ai/scenarios",
                "fixtures_dir": ".ai/fixtures",
                "default_sanity_checks": [
                    {"name": "http-local", "resource": "http", "target": "http://localhost:8080"},
                ],
                "execution": {
                    "timeout_seconds": 60,
                    "stop_on_first_failure": False,
                    "cleanup_on_success": True,
                },
            })
            self._created.append(".ai/scenarios/config.yaml")

        # example.yaml — 可工作的场景模板
        example_path = scenarios_dir / "example.yaml"
        if not example_path.exists():
            self._write_yaml(example_path, {
                "id": "example-health-check",
                "name": "服务健康检查示例",
                "description": "验证服务在线并返回正确的 HTTP 状态码",
                "requires": ["http_service"],
                "fixtures": [],
                "steps": [
                    {
                        "name": "GET 首页",
                        "type": "http_call",
                        "config": {
                            "method": "GET",
                            "url": "http://localhost:8080/",
                        },
                    },
                ],
                "assertions": [
                    {
                        "type": "http_status",
                        "target": "",
                        "operator": "eq",
                        "expected": 200,
                        "message": "首页应返回 200 状态码",
                    },
                ],
                "teardown": [],
                "metadata": {
                    "author": "aicode-init",
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                },
            })
            self._created.append(".ai/scenarios/example.yaml")

    @staticmethod
    def _write_yaml(path: Path, data: dict) -> None:
        """写入 YAML 文件，fallback 到 JSON。"""
        try:
            import yaml
            content = yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False)
        except ImportError:
            import json
            content = json.dumps(data, ensure_ascii=False, indent=2)
        path.write_text(content, encoding="utf-8")

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
