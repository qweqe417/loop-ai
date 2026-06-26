"""init 数据模型。

定义项目初始化全流程的数据结构：
ProjectProfile（项目画像）、ScanResult（扫描结果）、InitReport（初始化报告）。

ProjectProfile 现在完全工具无关 —— 不包含 Claude Code 特定字段（如 has_claude_md）。
所有工具特定逻辑由 ToolAdapter 处理。
"""

# 启用延迟注解求值
from __future__ import annotations

# 导入 datetime 用于时间戳字段
from datetime import datetime
# 导入 Any 类型，用于灵活的类型注解
from typing import Any

# 导入 Pydantic 基类和字段描述器，用于定义数据模型
from pydantic import BaseModel, Field


# ── 子结构 ──────────────────────────────────────────────────────

class CodeStyleProfile(BaseModel):
    """推断的代码风格。"""

    # 命名约定：snake_case / camelCase / PascalCase
    naming_convention: str = Field(default="", description="命名约定: snake_case / camelCase / PascalCase")
    # 异常处理方式：try-except / Result<T> / Either
    exception_pattern: str = Field(default="", description="异常处理方式: try-except / Result<T> / Either")
    # 日志框架：logging / loguru / slf4j / winston
    logging_framework: str = Field(default="", description="日志框架: logging / loguru / slf4j / winston")
    # 返回值包装：Response<T> / ApiResult / 裸返回
    return_wrapper: str = Field(default="", description="返回值包装: Response<T> / ApiResult / 裸返回")
    # 测试命名规范：test_* / *Test / *.test
    test_naming: str = Field(default="", description="测试命名: test_* / *Test / *.test")
    # 格式化工具：ruff / prettier / spotless
    formatter: str = Field(default="", description="格式化工具: ruff / prettier / spotless")
    # 推断可信度：low / medium / high
    confidence: str = Field(default="low", description="可信度: low / medium / high")
    # 状态：inferred / confirmed / calibrated
    status: str = Field(default="inferred", description="状态: inferred / confirmed / calibrated")
    # 推断依据说明
    notes: list[str] = Field(default_factory=list, description="推断依据")


class ResourceInfo(BaseModel):
    """检测到的外部资源。"""

    # 资源名：MySQL / Redis / MQ / ES / S3
    name: str = Field(description="资源名: MySQL / Redis / MQ / ES / S3")
    # 类型：database / cache / queue / search / storage
    type: str = Field(default="", description="类型: database / cache / queue / search / storage")
    # 发现来源：application.yml / docker-compose / .env
    evidence: str = Field(default="", description="发现来源: application.yml / docker-compose / .env")
    # 是否已有配置
    configured: bool = Field(default=False, description="是否已有配置")


class PluginInfo(BaseModel):
    """AI Coding Loop 插件信息。"""

    # 插件名：superpowers-provider / scenario-runner
    name: str = Field(description="插件名: superpowers-provider / scenario-runner")
    # 是否已安装
    installed: bool = Field(default=False)
    # 版本号
    version: str = Field(default="")
    # 是否为必需插件
    required: bool = Field(default=False, description="是否为必需插件")
    # 是否可被 CLI 调用
    available: bool = Field(default=False, description="是否可被 CLI 调用")


class ScannedDirectory(BaseModel):
    """关键目录信息。"""

    # 目录路径
    path: str
    # 用途：source / test / config / resource / migration / api
    role: str = Field(default="", description="用途: source / test / config / resource / migration / api")
    # 目录中的编程语言
    language: str = Field(default="")
    # 文件数量
    file_count: int = Field(default=0)


# ── 核心模型 ────────────────────────────────────────────────────

class ProjectProfile(BaseModel):
    """项目完整画像 —— init 扫描的最终产物。**完全工具无关。**

    所有生成步骤通过 ToolAdapter 完成，不再直接写 .claude/ 特定路径。
    """

    # 基础信息
    # 项目名称（从目录名推断）
    project_name: str = Field(default="", description="项目名称（从目录名推断）")
    # 项目根目录绝对路径
    root_path: str = Field(default="", description="项目根目录绝对路径")
    # 目标 AI 工具：claude_code / codex / cursor
    target_tool: str = Field(default="claude_code", description="目标 AI 工具: claude_code / codex / cursor")
    # 是否为 Git 仓库
    is_git_repo: bool = Field(default=False)
    # Git 工作区是否干净
    git_clean: bool = Field(default=False)
    # 当前 Git 分支名
    git_branch: str = Field(default="")

    # 技术栈
    # 主要语言：python / java / typescript / go / rust
    language: str = Field(default="", description="主要语言: python / java / typescript / go / rust")
    # 框架：FastAPI / Spring Boot / Next.js / Gin
    framework: str = Field(default="", description="框架: FastAPI / Spring Boot / Next.js / Gin")
    # 包管理器：pip / maven / npm / go mod
    package_manager: str = Field(default="", description="包管理器: pip / maven / npm / go mod")
    # 构建工具：setuptools / gradle / webpack / cargo
    build_tool: str = Field(default="", description="构建工具: setuptools / gradle / webpack / cargo")

    # 目录结构
    # 源代码目录列表
    source_dirs: list[str] = Field(default_factory=list)
    # 测试目录列表
    test_dirs: list[str] = Field(default_factory=list)
    # 配置文件目录列表
    config_dirs: list[str] = Field(default_factory=list)
    # 数据库迁移目录列表
    migration_dirs: list[str] = Field(default_factory=list)
    # 关键目录详情
    key_directories: list[ScannedDirectory] = Field(default_factory=list)
    # 入口文件：main.py / App.java / index.ts
    entry_files: list[str] = Field(default_factory=list, description="入口文件: main.py / App.java / index.ts")

    # 代码规范
    # 推断的代码风格
    code_style: CodeStyleProfile = Field(default_factory=CodeStyleProfile)
    # 检测到的 lint 配置文件列表
    linter_configs: list[str] = Field(default_factory=list, description="检测到的 lint 配置文件")

    # 测试
    # 测试框架：pytest / JUnit / Jest / go test
    test_framework: str = Field(default="", description="测试框架: pytest / JUnit / Jest / go test")
    # 测试运行命令：pytest / npm test / mvn test
    test_runner_command: str = Field(default="", description="测试运行命令: pytest / npm test / mvn test")
    # 是否有单元测试
    has_unit_tests: bool = Field(default=False)
    # 是否有集成测试
    has_integration_tests: bool = Field(default=False)
    # 是否有端到端测试
    has_e2e_tests: bool = Field(default=False)
    # 是否有 Docker Compose 配置
    has_docker_compose: bool = Field(default=False)
    # 是否有测试数据库配置
    has_test_db_config: bool = Field(default=False)

    # 服务启停（init 自动检测，写入 loop-config.json）
    service_start_command: str = Field(default="", description="自动检测的服务启动命令")
    service_health_url: str = Field(default="", description="服务健康检查 URL")
    service_ready_pattern: str = Field(default="", description="启动完成日志特征")
    service_port: int = Field(default=0, description="服务端口号")
    is_monolith: bool = Field(default=True, description="是否为单体应用")
    service_services: list[dict] = Field(default_factory=list, description="多服务列表（微服务用）")

    # 外部资源
    # 检测到的外部资源列表
    resources: list[ResourceInfo] = Field(default_factory=list)

    # 工具环境（通用）
    # 检测到的 AI 工具：claude_code / codex / cursor
    detected_tools: list[str] = Field(default_factory=list, description="检测到的 AI 工具: claude_code / codex / cursor")
    # 检测到的外部插件
    detected_plugins: list[PluginInfo] = Field(default_factory=list, description="检测到的外部插件")
    # 引擎内部模块可用性
    internal_modules: dict[str, bool] = Field(default_factory=dict, description="引擎内部模块可用性")
    # 缺失的必需插件
    missing_required: list[str] = Field(default_factory=list, description="缺失的必需插件")
    # 缺失的推荐插件
    missing_recommended: list[str] = Field(default_factory=list, description="缺失的推荐插件")

    # 已有文件（工具无关 —— 使用 adapter 的 get_existing_file_patterns() 检测）
    # 是否存在 .ai/ 目录
    has_ai_dir: bool = Field(default=False)
    # 是否存在 superpowers 目录
    has_superpowers_dir: bool = Field(default=False)
    # 检测到的所有已有工具相关文件（合并）
    existing_files: list[str] = Field(default_factory=list, description="检测到的所有已有工具相关文件（合并）")
    # 按工具分组的已存在文件/目录检测结果
    existing_tool_files: dict[str, list[str]] = Field(
        default_factory=dict,
        description="按工具分组的已存在文件/目录检测结果: "
                    "{'claude_code': ['CLAUDE.md', '.claude/'], 'codex': []}"
    )

    # 元数据
    # 扫描时间
    scanned_at: datetime = Field(default_factory=datetime.now)
    # 扫描耗时（毫秒）
    scan_duration_ms: float = Field(default=0.0)


class ScanResult(BaseModel):
    """单步扫描结果。"""

    # 步骤名
    step: str = Field(description="步骤名")
    # 是否成功
    success: bool = Field(default=True)
    # 结果消息
    message: str = Field(default="")
    # 详细数据
    details: dict[str, Any] = Field(default_factory=dict)
    # 警告信息
    warnings: list[str] = Field(default_factory=list)


class InitReport(BaseModel):
    """初始化完成报告 —— aicode init 的输出。"""

    # 整体是否成功
    success: bool = Field(default=False)
    # 项目完整画像
    profile: ProjectProfile = Field(default_factory=ProjectProfile)
    # 各步骤结果
    steps: list[ScanResult] = Field(default_factory=list)

    # 生成的文件
    # 已创建的文件列表
    files_created: list[str] = Field(default_factory=list)
    # 已跳过的文件列表
    files_skipped: list[str] = Field(default_factory=list)
    # 与已有文件合并的文件列表
    files_merged: list[str] = Field(default_factory=list, description="与已有文件合并的")

    # 摘要
    # 已安装的插件列表
    installed_plugins: list[str] = Field(default_factory=list)
    # 缺失的可选组件
    missing_optional: list[str] = Field(default_factory=list)
    # 需要用户确认的规则
    needs_confirmation: list[str] = Field(default_factory=list, description="需要用户确认的规则")
    # 下一步建议
    next_steps: list[str] = Field(default_factory=list, description="下一步建议")

    # 元数据
    # 报告创建时间
    created_at: datetime = Field(default_factory=datetime.now)
    # 总耗时（毫秒）
    total_duration_ms: float = Field(default=0.0)

    def summary_text(self) -> str:
        """生成人类可读的摘要。

        Returns:
            格式化的多行摘要文本
        """
        # 构建摘要文本行
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
        # 如果存在缺失的可选组件，列出
        if self.missing_optional:
            lines.append("Missing optional capabilities:")
            for m in self.missing_optional:
                lines.append(f"  - {m}")
            lines.append("")
        # 如果有下一步建议，列出
        if self.next_steps:
            lines.append("Next steps:")
            for s in self.next_steps:
                lines.append(f"  - {s}")
            lines.append("")
        # 添加总耗时
        lines.append(f"Duration: {self.total_duration_ms:.0f}ms")
        return "\n".join(lines)