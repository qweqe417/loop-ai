"""init 数据模型。

定义项目初始化全流程的数据结构：
ProjectProfile（项目画像）、ScanResult（扫描结果）、InitReport（初始化报告）。

ProjectProfile 现在完全工具无关 —— 不包含 Claude Code 特定字段（如 has_claude_md）。
所有工具特定逻辑由 ToolAdapter 处理。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ── 子结构 ──────────────────────────────────────────────────────

class CodeStyleProfile(BaseModel):
    """推断的代码风格。"""

    naming_convention: str = Field(default="", description="命名约定: snake_case / camelCase / PascalCase")
    exception_pattern: str = Field(default="", description="异常处理方式: try-except / Result<T> / Either")
    logging_framework: str = Field(default="", description="日志框架: logging / loguru / slf4j / winston")
    return_wrapper: str = Field(default="", description="返回值包装: Response<T> / ApiResult / 裸返回")
    test_naming: str = Field(default="", description="测试命名: test_* / *Test / *.test")
    formatter: str = Field(default="", description="格式化工具: ruff / prettier / spotless")
    confidence: str = Field(default="low", description="可信度: low / medium / high")
    status: str = Field(default="inferred", description="状态: inferred / confirmed / calibrated")
    notes: list[str] = Field(default_factory=list, description="推断依据")


class ResourceInfo(BaseModel):
    """检测到的外部资源。"""

    name: str = Field(description="资源名: MySQL / Redis / MQ / ES / S3")
    type: str = Field(default="", description="类型: database / cache / queue / search / storage")
    evidence: str = Field(default="", description="发现来源: application.yml / docker-compose / .env")
    configured: bool = Field(default=False, description="是否已有配置")
    mcp_available: bool = Field(default=False, description="是否有 MCP Server 可用")


class PluginInfo(BaseModel):
    """AI Coding Loop 插件信息。"""

    name: str = Field(description="插件名: superpowers-provider / scenario-runner")
    installed: bool = Field(default=False)
    version: str = Field(default="")
    required: bool = Field(default=False, description="是否为必需插件")
    available: bool = Field(default=False, description="是否可被 CLI 调用")


class ScannedDirectory(BaseModel):
    """关键目录信息。"""

    path: str
    role: str = Field(default="", description="用途: source / test / config / resource / migration / api")
    language: str = Field(default="")
    file_count: int = Field(default=0)


# ── 核心模型 ────────────────────────────────────────────────────

class ProjectProfile(BaseModel):
    """项目完整画像 —— init 扫描的最终产物。**完全工具无关。**

    所有生成步骤通过 ToolAdapter 完成，不再直接写 .claude/ 特定路径。
    """

    # 基础信息
    project_name: str = Field(default="", description="项目名称（从目录名推断）")
    root_path: str = Field(default="", description="项目根目录绝对路径")
    target_tool: str = Field(default="claude_code", description="目标 AI 工具: claude_code / codex / cursor")
    is_git_repo: bool = Field(default=False)
    git_clean: bool = Field(default=False)
    git_branch: str = Field(default="")

    # 技术栈
    language: str = Field(default="", description="主要语言: python / java / typescript / go / rust")
    framework: str = Field(default="", description="框架: FastAPI / Spring Boot / Next.js / Gin")
    package_manager: str = Field(default="", description="包管理器: pip / maven / npm / go mod")
    build_tool: str = Field(default="", description="构建工具: setuptools / gradle / webpack / cargo")

    # 目录结构
    source_dirs: list[str] = Field(default_factory=list)
    test_dirs: list[str] = Field(default_factory=list)
    config_dirs: list[str] = Field(default_factory=list)
    migration_dirs: list[str] = Field(default_factory=list)
    key_directories: list[ScannedDirectory] = Field(default_factory=list)
    entry_files: list[str] = Field(default_factory=list, description="入口文件: main.py / App.java / index.ts")

    # 代码规范
    code_style: CodeStyleProfile = Field(default_factory=CodeStyleProfile)
    linter_configs: list[str] = Field(default_factory=list, description="检测到的 lint 配置文件")

    # 测试
    test_framework: str = Field(default="", description="测试框架: pytest / JUnit / Jest / go test")
    test_runner_command: str = Field(default="", description="测试运行命令: pytest / npm test / mvn test")
    has_unit_tests: bool = Field(default=False)
    has_integration_tests: bool = Field(default=False)
    has_e2e_tests: bool = Field(default=False)
    has_docker_compose: bool = Field(default=False)
    has_test_db_config: bool = Field(default=False)

    # 外部资源
    resources: list[ResourceInfo] = Field(default_factory=list)

    # 工具环境（通用）
    detected_tools: list[str] = Field(default_factory=list, description="检测到的 AI 工具: claude_code / codex / cursor")
    detected_plugins: list[PluginInfo] = Field(default_factory=list, description="检测到的外部插件")
    internal_modules: dict[str, bool] = Field(default_factory=dict, description="引擎内部模块可用性")
    missing_required: list[str] = Field(default_factory=list, description="缺失的必需插件")
    missing_recommended: list[str] = Field(default_factory=list, description="缺失的推荐插件")

    # 已有文件（工具无关 —— 使用 adapter 的 get_existing_file_patterns() 检测）
    has_ai_dir: bool = Field(default=False)
    has_superpowers_dir: bool = Field(default=False)
    existing_files: list[str] = Field(default_factory=list, description="检测到的所有已有工具相关文件（合并）")
    existing_tool_files: dict[str, list[str]] = Field(
        default_factory=dict,
        description="按工具分组的已存在文件/目录检测结果: "
                    "{'claude_code': ['CLAUDE.md', '.claude/'], 'codex': []}"
    )

    # 元数据
    scanned_at: datetime = Field(default_factory=datetime.now)
    scan_duration_ms: float = Field(default=0.0)


class ScanResult(BaseModel):
    """单步扫描结果。"""

    step: str = Field(description="步骤名")
    success: bool = Field(default=True)
    message: str = Field(default="")
    details: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class InitReport(BaseModel):
    """初始化完成报告 —— aicode init 的输出。"""

    success: bool = Field(default=False)
    profile: ProjectProfile = Field(default_factory=ProjectProfile)
    steps: list[ScanResult] = Field(default_factory=list)

    # 生成的文件
    files_created: list[str] = Field(default_factory=list)
    files_skipped: list[str] = Field(default_factory=list)
    files_merged: list[str] = Field(default_factory=list, description="与已有文件合并的")

    # 摘要
    installed_plugins: list[str] = Field(default_factory=list)
    missing_optional: list[str] = Field(default_factory=list)
    needs_confirmation: list[str] = Field(default_factory=list, description="需要用户确认的规则")
    next_steps: list[str] = Field(default_factory=list, description="下一步建议")

    # 元数据
    created_at: datetime = Field(default_factory=datetime.now)
    total_duration_ms: float = Field(default=0.0)

    def summary_text(self) -> str:
        """生成人类可读的摘要。"""
        lines = [
            "=" * 50,
            "AI Coding Loop — Init Report",
            "=" * 50,
            "",
            f"Project: {self.profile.project_name}",
            f"Language: {self.profile.language} ({self.profile.framework})",
            f"Git: {'clean' if self.profile.git_clean else 'dirty'}",
            "",
            f"Files created: {len(self.files_created)}",
            f"Files skipped: {len(self.files_skipped)}",
            f"Files merged: {len(self.files_merged)}",
            "",
        ]
        if self.missing_optional:
            lines.append("Missing optional capabilities:")
            for m in self.missing_optional:
                lines.append(f"  - {m}")
            lines.append("")
        if self.next_steps:
            lines.append("Next steps:")
            for s in self.next_steps:
                lines.append(f"  - {s}")
            lines.append("")
        lines.append(f"Duration: {self.total_duration_ms:.0f}ms")
        return "\n".join(lines)
