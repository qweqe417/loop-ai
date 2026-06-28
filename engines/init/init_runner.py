"""InitRunner —— init 流程编排器。

编排 aicode init 的完整流程：
扫描 → 检测 → 选择工具适配器 → 生成 → 安装 → 报告

核心变化：支持 --target 参数选择目标 AI 工具，
所有工具特定逻辑通过 ToolAdapter 处理。
"""

# 启用延迟注解求值
from __future__ import annotations

# 导入 logging 库，用于日志记录
import logging
# 导入 subprocess 库，用于执行 pip 安装命令
import subprocess
# 导入 sys 库，用于获取 Python 可执行文件路径
import sys
# 导入 time 库，用于计算耗时
import time
# 导入 shutil 库，用于复制文件
import shutil
# 导入 Path 类，用于处理文件路径
from pathlib import Path
# 导入 TYPE_CHECKING 和 Any 类型注解
from typing import TYPE_CHECKING, Any

# 导入 init 模块的组件
from .scanner import ProjectScanner
from .generator import FileGenerator
from .models import InitReport, ProjectProfile, ScanResult

# 仅在类型检查时导入，避免运行时循环导入
if TYPE_CHECKING:
    from engines.adapters.base import ToolAdapter

# 创建当前模块的日志记录器
logger = logging.getLogger(__name__)


# ── 工具适配器注册表 ──────────────────────────────────────

def _get_adapter_registry() -> dict[str, type[ToolAdapter]]:
    """返回 {tool_id: AdapterClass} 映射。

    Returns:
        工具 ID 到适配器类的映射字典
    """
    # 导入各个工具的适配器
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
    """返回所有支持的 tool_id 列表。

    Returns:
        支持的 AI 工具 ID 列表
    """
    return list(_get_adapter_registry().keys())


class InitRunner:
    """初始化流程编排器。

    用法:
        runner = InitRunner(project_root="/path/to/project", target_tool="claude_code")
        report = runner.run()                        # 完整流程（bootstrap 模式）
        report = runner.run_assets_only()            # 仅 .ai/ 资产 + install
        report = runner.run(install_missing=True)    # 自动安装
        report = runner.run(auto_confirm=True)       # 跳过确认
    """

    # 前端框架集合 —— 检测到这些框架时自动部署 frontend-design 规则
    FRONTEND_FRAMEWORKS: frozenset[str] = frozenset({
        "React", "Vue", "Next.js", "Angular", "Svelte",
        "Nuxt", "Remix", "SvelteKit",
    })

    def __init__(
        self,
        project_root: str | Path = ".",
        target_tool: str = "claude_code",
    ) -> None:
        # 将项目根目录转为绝对路径
        self._root = Path(project_root).resolve()
        # 目标 AI 工具
        self._target_tool = target_tool
        # 获取适配器实例
        self._adapter = get_adapter(target_tool)
        # 初始化项目扫描器
        self._scanner = ProjectScanner(project_root=self._root, adapter=self._adapter)
        # 文件生成器（延迟初始化）
        self._generator: FileGenerator | None = None
        # Provider 列表
        self._providers: list[Any] = []
        # 各步骤结果
        self._steps: list[ScanResult] = []

    @property
    def adapter(self) -> ToolAdapter:
        """获取当前工具适配器。"""
        return self._adapter

    @property
    def profile(self) -> ProjectProfile:
        """获取当前项目画像。"""
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

        Python 只负责：扫描 + .ai/ 资产 + adapter 安装。
        主配置文件和规则文件（CLAUDE.md / rules/*.md）由 AI 通过
        `/aicode-init` karpathy.md 直接写入 —— Python 不碰配置内容。

        Args:
            install_missing: 是否自动安装缺失插件
            auto_confirm: 是否跳过确认步骤（非交互模式）
            profile: 外部预填充的 ProjectProfile（跳过扫描）

        Returns:
            初始化报告
        """
        self._steps = []
        start = time.perf_counter()

        # 扫描
        if profile is not None:
            # 使用外部提供的 profile，更新目标工具
            profile.target_tool = self._target_tool
        else:
            # 执行完整扫描
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

        # 生成 .ai/ 资产（memory / scenarios / config.yaml 等）
        # 注意：不生成 CLAUDE.md / rules/*.md —— 这些由 AI 写入
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
            message=f"生成了 {len(created)} 个 .ai/ 资产文件（目标: {self._adapter.display_name}）",
            details={
                "files": created,
                "target_tool": self._target_tool,
                "adapter": self._adapter.display_name,
            },
        ))

        # 安装 adapter 文件（MCP 配置 / loop-config.json / plugin-root.txt）
        self._run_install(profile)

        # Step 11: 构建报告
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
        """只执行扫描，不生成文件。

        Returns:
            项目完整画像
        """
        return self._scanner.scan_all()

    def generate(self, profile: ProjectProfile | None = None) -> InitReport:
        """只执行 .ai/ 资产生成（需要先 scan 或提供 profile）。

        Python 不生成 CLAUDE.md / rules/*.md —— 这些由 AI 写入。

        Args:
            profile: 项目画像（可选，不提供则使用扫描结果）

        Returns:
            初始化报告
        """
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

    def run_assets_only(
        self,
        *,
        profile: ProjectProfile | None = None,
    ) -> InitReport:
        """仅生成 .ai/ 资产 + adapter.install()，跳过主配置文件生成。

        用于 /aicode-init karpathy.md 流程：
        AI 已直接写入 CLAUDE.md / rules/*.md 等配置文件，
        Python 只需初始化 .ai/ 目录结构和 adapter skill/hook/MCP 文件。

        Args:
            profile: 项目画像（可选，不提供则执行扫描）

        Returns:
            初始化报告
        """
        start = time.perf_counter()

        p = profile
        if p is None:
            p = self._scanner.scan_all()
        p.target_tool = self._target_tool

        self._providers = self._detect_providers(p)

        self._generator = FileGenerator(
            p,
            project_root=self._root,
            adapter=self._adapter,
            providers=self._providers,
        )
        # 仅生成 .ai/ 资产
        self._generator.generate_ai_assets_only()
        # 安装 adapter 文件
        self._run_install(p)

        report = self._generator.build_report()
        report.total_duration_ms = (time.perf_counter() - start) * 1000
        return report

    # ── 内部方法 ──────────────────────────────────────────

    def _detect_providers(self, profile: ProjectProfile) -> list[Any]:
        """检测可用的 Providers（工具无关）。

        Args:
            profile: 项目画像

        Returns:
            Provider 列表
        """
        # 导入 Provider 类
        from engines.providers.scenario_runner import ScenarioRunnerProvider

        providers: list[Any] = []

        # Scenario Runner（引擎内部，通常始终可用）
        sr = ScenarioRunnerProvider()
        if sr.detect(self._root):
            providers.append(sr)
            logger.info("Detected: Scenario Runner Provider")

        return providers

    def _step(self, name: str, result: ScanResult) -> None:
        """记录一个步骤结果。

        Args:
            name: 步骤名
            result: 步骤结果
        """
        self._steps.append(result)

    def _install_missing(self, profile: ProjectProfile) -> ScanResult:
        """尝试安装缺失的必需插件。

        Args:
            profile: 项目画像

        Returns:
            安装结果
        """
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

        Args:
            name: 插件名

        Returns:
            是否安装成功
        """
        # 已知插件名 → pip 包名映射
        # 只包含确实可通过 pip install 安装的包。
        # superpowers / scenario-runner 等通过插件市场或引擎自带安装，不在此列。
        KNOWN_PLUGIN_MAP: dict[str, str] = {
            "codegraph": "codegraph",
        }

        # 如果不在已知映射中，不支持 pip 安装
        if name not in KNOWN_PLUGIN_MAP:
            logger.warning(
                "Plugin '%s' is not pip-installable. "
                "Install it via the appropriate plugin marketplace or manually.",
                name,
            )
            return False

        package = KNOWN_PLUGIN_MAP[name]
        # 获取 Python 可执行文件路径
        python_exe = getattr(sys, 'executable', 'python') or 'python'

        logger.info("Installing plugin '%s' via pip package '%s'", name, package)
        try:
            # 执行 pip install 命令
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

    def _run_install(self, profile: ProjectProfile) -> None:
        """调用 adapter.install() 安装 MCP 配置 / loop-config / plugin-root。

        Args:
            profile: 项目画像
        """
        try:
            import sys
            # 计算插件根目录（engines/init/init_runner.py 的上三级目录）
            plugin_root = Path(__file__).resolve().parent.parent.parent

            # 部署 bundle 的规则文件（如 frontend-design）
            self._deploy_bundled_rules(plugin_root)

            result = self._adapter.install(
                project_root=self._root,
                plugin_root=plugin_root,
                providers=self._providers,
                profile=profile,
            )
            if result.get("success"):
                created = result.get("files_created", [])
                skipped = result.get("files_skipped", [])
                self._steps.append(ScanResult(
                    step="install",
                    success=True,
                    message=f"安装了 {len(created)} 个 adapter 文件, 跳过 {len(skipped)} 个",
                    details=result,
                ))
            else:
                self._steps.append(ScanResult(
                    step="install",
                    success=False,
                    message="adapter.install() 有错误",
                    warnings=result.get("errors", []),
                ))
        except Exception as exc:
            logger.warning("adapter.install() 异常: %s", exc)

    def _deploy_bundled_rules(self, plugin_root: Path) -> None:
        """部署 Loop bundle 的规则文件到工具规则目录。

        条件部署：
        - frontend-design: 仅当前端框架被识别时部署
          （React / Vue / Next.js / Angular / Svelte 等）。

        后端项目不部署，避免无用文件。

        Args:
            plugin_root: Loop 插件根目录
        """
        p = self._scanner.profile

        # 判断是否为前端项目
        if p.framework not in self.FRONTEND_FRAMEWORKS:
            return

        source = plugin_root / "skills" / "frontend-design" / "SKILL.md"
        if not source.exists():
            logger.warning("frontend-design SKILL.md not found at %s", source)
            return

        target_dir = self._root / self._adapter.rules_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / "frontend-design.md"

        if target.exists():
            logger.info(
                "frontend-design rule already exists at %s, skipping", target)
            return

        shutil.copy2(source, target)
        self._steps.append(ScanResult(
            step="deploy_bundled_rules",
            success=True,
            message=(
                f"已部署 frontend-design 规则到 "
                f"{self._adapter.rules_dir}/frontend-design.md"
            ),
            details={"source": str(source), "target": str(target)},
        ))
        logger.info("Deployed frontend-design rule to %s", target)

        # 推荐 Impeccable: 前端项目生成后打磨 UI 细节
        self._steps.append(ScanResult(
            step="recommend_impeccable",
            success=True,
            message=(
                "检测到前端项目，建议安装 Impeccable 前端打磨工具："
                "npx impeccable install"
                "（20 个打磨命令，适用于 Claude Code / Codex / Cursor）"
            ),
            details={
                "tool": "Impeccable (npx)",
                "install_cmd": "npx impeccable install",
                "note": "安装后在 REVIEW 阶段使用 /audit → /polish → /harden 打磨 UI",
            },
        ))