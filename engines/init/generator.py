"""FileGenerator —— 根据 ProjectProfile 和 ToolAdapter 生成项目配置文件。

**完全工具无关** —— 所有路径和内容委托给 ToolAdapter。
支持 Claude Code / Codex / Cursor 等任意 AI 工具。

init 只生成主配置文件（CLAUDE.md 等）和 .ai/ 跨工具资产。
规则文件（code-style.md/testing.md/safety.md）不再硬编码生成，
而是由 AI 在首次处理任务时根据实际代码自行推断并写入 rules_dir。
skills/ 和 MCP 配置由 adapter.install() 在插件安装时写入。
"""

# 启用延迟注解求值
from __future__ import annotations

# 导入 logging 库，用于日志记录
import logging
# 导入 datetime 用于生成时间戳
from datetime import datetime
# 导入 Path 类，用于处理文件路径
from pathlib import Path
# 导入 TYPE_CHECKING 和 Any 类型，用于类型注解
from typing import TYPE_CHECKING, Any

# 仅在类型检查时导入，避免运行时循环导入
if TYPE_CHECKING:
    from engines.adapters.base import ToolAdapter
    from .models import ProjectProfile, InitReport

# 创建当前模块的日志记录器
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
        # 项目完整画像
        self.profile = profile
        # 项目根目录
        self._root = Path(project_root)
        # 工具适配器
        self._adapter = adapter
        # Provider 列表
        self._providers = providers or []
        # 已创建的文件列表
        self._created: list[str] = []
        # 已跳过的文件列表
        self._skipped: list[str] = []
        # 已合并的文件列表
        self._merged: list[str] = []

    @property
    def adapter(self) -> ToolAdapter:
        """获取工具适配器。未设置时默认使用 ClaudeCodeAdapter。"""
        if self._adapter is None:
            # 延迟导入 ClaudeCodeAdapter
            from engines.adapters.claude import ClaudeCodeAdapter
            self._adapter = ClaudeCodeAdapter()
        return self._adapter

    def generate_all(self) -> list[str]:
        """生成所有文件，返回已创建的文件路径列表。

        注意：不含主配置文件和规则文件 —— 这些由 AI 通过 karpathy.md 直接写入。
        Python 只负责 .ai/ 资产目录。

        Returns:
            已创建的文件路径列表
        """
        # 重置计数器
        self._created = []
        self._skipped = []
        self._merged = []

        # 生成 .ai/ 跨工具资产
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

        Returns:
            已创建的文件路径列表
        """
        return self.generate_all()

    def build_report(self) -> InitReport:
        """构建 InitReport。

        Returns:
            初始化报告对象
        """
        # 导入 InitReport 模型
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
        """初始化 .ai/ 目录及必要子资产。"""
        ai_dir = self._root / ".ai"
        ai_dir.mkdir(parents=True, exist_ok=True)

        # .ai/fixtures/ — 测试数据目录
        (ai_dir / "fixtures").mkdir(parents=True, exist_ok=True)

        # .ai/scenarios/ — 场景目录 + 示例模板
        self._init_scenarios(ai_dir)

        # .ai/loop-config.json — 服务启停 + 鉴权配置
        self._generate_loop_config(ai_dir)

    def _init_scenarios(self, ai_dir: Path) -> None:
        """初始化场景目录：生成 example.yaml 模板。

        Args:
            ai_dir: .ai/ 目录路径
        """
        scenarios_dir = ai_dir / "scenarios"
        scenarios_dir.mkdir(parents=True, exist_ok=True)

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

    def _generate_loop_config(self, ai_dir: Path) -> None:
        """生成 .ai/loop-config.json，包含 auto-detected 的服务启停 + 鉴权配置。

        单体项目生成 1 条 service，微服务生成多条（用户可按需 enabled=false）。
        已存在则跳过（adapter.install() 后续会合入 template_vars）。
        """
        import json

        config_path = ai_dir / "loop-config.json"
        p = self.profile

        # 构建 services 列表
        services: list[dict] = []
        if p.service_services:
            # 微服务：多条
            services = p.service_services
        elif p.service_start_command:
            # 单体：一条
            svc = {
                "name": "app",
                "start": p.service_start_command,
                "health": p.service_health_url,
                "startup_timeout": 90,
            }
            if p.service_ready_pattern:
                svc["ready_pattern"] = p.service_ready_pattern
            services.append(svc)

        config = {
            "auth": {
                "token": "粘贴你的JWT token到这里",
            },
            # 前端项目配置（Playwright 测试需要）
            # "frontend": {
            #     "dev_server": "http://localhost:3000"
            # },
            "data_sources": {
                # 示例：取消注释并修改为实际连接信息
                # "main_db": {
                #     "type": "mysql",
                #     "host": "localhost",
                #     "port": 3306,
                #     "user": "root",
                #     "password": "",
                #     "database": "test"
                # },
                # "cache": {
                #     "type": "redis",
                #     "host": "localhost",
                #     "port": 6379,
                #     "password": "",
                #     "db": 0
                # }
            },
        }
        if services:
            config["services"] = services

        # 写入（不覆盖已有配置）
        if not config_path.exists():
            config_path.write_text(
                json.dumps(config, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._created.append(".ai/loop-config.json")
        else:
            logger.info(".ai/loop-config.json already exists, skipping")
            self._skipped.append(".ai/loop-config.json")

    @staticmethod
    def _write_yaml(path: Path, data: dict) -> None:
        """写入 YAML 文件，fallback 到 JSON。

        Args:
            path: 目标文件路径
            data: 要写入的数据字典
        """
        try:
            # 尝试使用 yaml 库写入
            import yaml
            content = yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False)
        except ImportError:
            # yaml 库不可用时 fallback 到 JSON
            import json
            content = json.dumps(data, ensure_ascii=False, indent=2)
        path.write_text(content, encoding="utf-8")

    # ── 下一步建议 ─────────────────────────────────────────

    def _build_next_steps(self) -> list[str]:
        """构建下一步操作建议。

        Returns:
            建议步骤列表
        """
        p = self.profile
        adapter = self.adapter
        steps: list[str] = []

        # 如果有缺失的推荐插件，建议安装
        if p.missing_recommended:
            for m in p.missing_recommended:
                steps.append(f"安装推荐插件: {m}")

        # 代码规范可信度低时建议校准
        if p.code_style.confidence in ("low",):
            steps.append("运行 `aicode calibrate` 确认代码规范")

        # 未检测到测试框架时建议手动配置
        if not p.test_framework:
            steps.append("手动配置测试框架和运行命令")

        # 检测到外部资源时建议配置 data_sources
        if p.resources:
            steps.append("检测到外部资源，在 .ai/loop-config.json 的 data_sources 中配置连接信息：")
            for r in p.resources:
                steps.append(f"  - {r.name} (type={r.type}): 配置 host/port/user/password/database")

        # 获取工具的命令前缀
        cp = adapter.command_prefix
        # 建议下一步操作
        steps.append(f"运行 `{cp}aicode-spec <需求>` 生成第一个 Spec")
        steps.append(f"或运行 `{cp}aicode-direct <小改动>` 体验快速通道")

        return steps