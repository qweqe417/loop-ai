"""InitRunner —— init 流程编排器。

编排 aicode init 的 12 步完整流程：
扫描 → 检测 → 选择工具适配器 → 生成 → 报告

核心变化：支持 --target 参数选择目标 AI 工具，
所有工具特定逻辑通过 ToolAdapter 处理。
"""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .scanner import ProjectScanner
from .generator import FileGenerator
from .models import InitReport, ProjectProfile, ScanResult

if TYPE_CHECKING:
    from engines.adapters.base import ToolAdapter

logger = logging.getLogger(__name__)


# ── 工具适配器注册表 ──────────────────────────────────────

def _get_adapter_registry() -> dict[str, type[ToolAdapter]]:
    """返回 {tool_id: AdapterClass} 映射。"""
    from engines.adapters.claude import ClaudeCodeAdapter
    from engines.adapters.codex import CodexAdapter
    from engines.adapters.cursor import CursorAdapter

    return {
        "claude_code": ClaudeCodeAdapter,
        "codex": CodexAdapter,
        "cursor": CursorAdapter,
    }


def get_adapter(tool_id: str) -> ToolAdapter:
    """根据 tool_id 获取对应的 ToolAdapter 实例。

    Args:
        tool_id: "claude_code" / "codex" / "cursor"

    Returns:
        ToolAdapter 实例。

    Raises:
        ValueError: 不支持的 tool_id。
    """
    registry = _get_adapter_registry()
    if tool_id not in registry:
        valid = ", ".join(registry.keys())
        raise ValueError(f"不支持的工具 '{tool_id}'，可选: {valid}")
    return registry[tool_id]()


def get_available_tools() -> list[str]:
    """返回所有支持的 tool_id 列表。"""
    return list(_get_adapter_registry().keys())


class InitRunner:
    """初始化流程编排器。

    用法:
        runner = InitRunner(project_root="/path/to/project", target_tool="claude_code")
        report = runner.run()                        # 默认交互模式
        report = runner.run(install_missing=True)    # 自动安装
        report = runner.run(auto_confirm=True)       # 跳过确认
    """

    def __init__(
        self,
        project_root: str | Path = ".",
        target_tool: str = "claude_code",
    ) -> None:
        self._root = Path(project_root).resolve()
        self._target_tool = target_tool
        self._adapter = get_adapter(target_tool)
        self._scanner = ProjectScanner(project_root=self._root, adapter=self._adapter)
        self._generator: FileGenerator | None = None
        self._providers: list[Any] = []
        self._steps: list[ScanResult] = []

    @property
    def adapter(self) -> ToolAdapter:
        return self._adapter

    @property
    def profile(self) -> ProjectProfile:
        return self._scanner.profile

    # ── 主流程 ────────────────────────────────────────────

    def run(
        self,
        *,
        install_missing: bool = False,
        auto_confirm: bool = False,
        profile: ProjectProfile | None = None,
    ) -> InitReport:
        """执行完整 init 流程。

        Args:
            install_missing: 是否自动安装缺失插件
            auto_confirm: 是否跳过确认步骤（非交互模式）
            profile: 外部预填充的 ProjectProfile（跳过扫描）
        """
        self._steps = []
        start = time.perf_counter()

        # Step 1-8: 扫描
        if profile is not None:
            profile.target_tool = self._target_tool
        else:
            profile = self._scanner.scan_all()
            profile.target_tool = self._target_tool

        # 检测 Providers
        self._providers = self._detect_providers(profile)

        # 处理缺失必需插件
        if profile.missing_required:
            if install_missing:
                self._step("install_missing", self._install_missing(profile))
            else:
                self._steps.append(ScanResult(
                    step="install_missing",
                    success=False,
                    message=f"缺失必需插件: {profile.missing_required}",
                    warnings=profile.missing_required,
                ))

        # Step 10-11: 生成文件（通过 adapter）
        self._generator = FileGenerator(
            profile,
            project_root=self._root,
            adapter=self._adapter,
            providers=self._providers,
        )

        created = self._generator.generate_all()

        self._steps.append(ScanResult(
            step="generate_files",
            success=True,
            message=f"生成了 {len(created)} 个文件（目标: {self._adapter.display_name}）",
            details={
                "files": created,
                "target_tool": self._target_tool,
                "adapter": self._adapter.display_name,
            },
        ))

        # Step 12: 报告
        report = self._generator.build_report()
        report.steps = self._steps
        report.total_duration_ms = (time.perf_counter() - start) * 1000

        logger.info(
            "Init complete for %s: %d files created, %d skipped, %.0fms",
            self._adapter.display_name,
            len(report.files_created),
            len(report.files_skipped),
            report.total_duration_ms,
        )
        return report

    # ── 分布执行 (用于 CLI 交互) ──────────────────────────

    def scan(self) -> ProjectProfile:
        """只执行扫描，不生成文件。"""
        return self._scanner.scan_all()

    def generate(self, profile: ProjectProfile | None = None) -> InitReport:
        """只执行文件生成（需要先 scan 或提供 profile）。"""
        p = profile or self._scanner.profile
        p.target_tool = self._target_tool
        self._providers = self._detect_providers(p)
        self._generator = FileGenerator(
            p,
            project_root=self._root,
            adapter=self._adapter,
            providers=self._providers,
        )
        self._generator.generate_all()
        return self._generator.build_report()

    # ── 内部方法 ──────────────────────────────────────────

    def _detect_providers(self, profile: ProjectProfile) -> list[Any]:
        """检测可用的 Providers（工具无关）。"""
        from engines.providers.superpowers import SuperpowersProvider
        from engines.providers.scenario_runner import ScenarioRunnerProvider
        from engines.providers.mcp_registry import detect_mcp_providers

        providers: list[Any] = []

        # Superpowers
        sp = SuperpowersProvider()
        if sp.detect(self._root):
            providers.append(sp)
            logger.info("Detected: Superpowers Provider")

        # Scenario Runner（引擎内部，通常始终可用）
        sr = ScenarioRunnerProvider()
        if sr.detect(self._root):
            providers.append(sr)
            logger.info("Detected: Scenario Runner Provider")

        # MCP 资源
        mcp_providers = detect_mcp_providers(self._root)
        providers.extend(mcp_providers)
        if mcp_providers:
            logger.info("Detected MCP providers: %s",
                        [p.display_name for p in mcp_providers])

        return providers

    def _step(self, name: str, result: ScanResult) -> None:
        self._steps.append(result)

    def _install_missing(self, profile: ProjectProfile) -> ScanResult:
        """尝试安装缺失的必需插件。"""
        installed: list[str] = []
        failed: list[str] = []
        for plugin_name in profile.missing_required:
            try:
                if self._install_plugin(plugin_name):
                    installed.append(plugin_name)
                else:
                    failed.append(plugin_name)
            except Exception as exc:
                failed.append(f"{plugin_name} ({exc})")

        return ScanResult(
            step="install_missing",
            success=len(failed) == 0,
            message=f"安装了 {len(installed)} 个插件: {installed}",
            details={"installed": installed, "failed": failed},
            warnings=failed,
        )

    def _install_plugin(self, name: str) -> bool:
        """安装单个插件。

        支持策略（按顺序尝试）：
        1. 已知映射：plugin name → pip package
        2. 通用 pip install（与 plugin name 同名）
        3. 返回 False 并提供手动安装指导
        """
        # 已知插件名 → pip 包名映射
        KNOWN_PLUGIN_MAP: dict[str, str] = {
            "codegraph": "codegraph",
            "superpowers": "claude-code-superpowers",
            "scenario-runner": "aicode-scenario-runner",
        }

        package = KNOWN_PLUGIN_MAP.get(name, name)
        python_exe = getattr(sys, 'executable', 'python') or 'python'

        logger.info("Installing plugin '%s' via pip package '%s'", name, package)
        try:
            result = subprocess.run(
                [python_exe, "-m", "pip", "install", package],
                capture_output=True, text=True,
                timeout=120,
            )
            if result.returncode == 0:
                logger.info("Plugin '%s' installed successfully", name)
                return True
            else:
                stderr_tail = result.stderr.strip().splitlines()[-3:] if result.stderr else []
                logger.warning(
                    "Plugin '%s' install failed (rc=%d): %s",
                    name, result.returncode, stderr_tail,
                )
                return False
        except FileNotFoundError:
            logger.warning("pip not found, cannot install plugin '%s'", name)
            return False
        except subprocess.TimeoutExpired:
            logger.warning("Plugin '%s' install timed out", name)
            return False
        except Exception as exc:
            logger.warning("Plugin '%s' install error: %s", name, exc)
            return False
