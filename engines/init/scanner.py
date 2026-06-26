"""ProjectScanner —— 项目扫描器。

扫描项目目录，识别技术栈、代码规范、测试方式、外部资源，
填充 ProjectProfile。**完全工具无关** —— 所有工具特定检测委托给 ToolAdapter。
"""

# 启用延迟注解求值
from __future__ import annotations

# 导入 logging 库，用于日志记录
import logging
# 导入 subprocess 库，用于执行 Git 命令
import subprocess
# 导入 time 库，用于计算扫描耗时
import time
# 导入 Path 类，用于处理文件路径
from pathlib import Path
# 导入 TYPE_CHECKING，用于类型检查时避免循环导入
from typing import TYPE_CHECKING

# 导入 init 模块的数据模型
from .models import (
    CodeStyleProfile,
    PluginInfo,
    ProjectProfile,
    ResourceInfo,
    ScanResult,
)

# 仅在类型检查时导入，避免运行时循环导入
if TYPE_CHECKING:
    from engines.adapters.base import ToolAdapter

# 创建当前模块的日志记录器
logger = logging.getLogger(__name__)


class ProjectScanner:
    """项目扫描器 —— 12 步 init 流程的 Step 1-8。**完全工具无关。**

    用法:
        scanner = ProjectScanner(project_root="/path/to/project", adapter=claude_adapter)
        profile = scanner.scan_all()
    """

    def __init__(
        self,
        project_root: str | Path = ".",
        adapter: ToolAdapter | None = None,
    ) -> None:
        # 将项目根目录转为绝对路径
        self._root = Path(project_root).resolve()
        # 工具适配器（用于检测工具特定文件）
        self._adapter = adapter
        # 初始化空的 ProjectProfile
        self._profile = ProjectProfile(root_path=str(self._root))

    @property
    def profile(self) -> ProjectProfile:
        """获取当前扫描的项目画像。"""
        return self._profile

    def set_adapter(self, adapter: ToolAdapter) -> None:
        """设置目标工具适配器（扫描后、生成前设置）。

        Args:
            adapter: 目标 AI 工具的适配器实例
        """
        self._adapter = adapter
        self._profile.target_tool = adapter.tool_id

    # ── 全量扫描 ──────────────────────────────────────────

    def scan_all(self) -> ProjectProfile:
        """执行全部扫描步骤，返回完整 ProjectProfile。

        Returns:
            填充完全的 ProjectProfile 对象
        """
        # 记录扫描开始时间
        start = time.perf_counter()

        # 按顺序执行各扫描步骤
        self.scan_environment()
        self.detect_tools()
        self.detect_plugins()
        self.scan_structure()
        self.infer_code_style()
        self.detect_testing()
        self.detect_resources()
        self._detect_services()

        # 计算扫描总耗时
        self._profile.scan_duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "Scan complete: %s (%s/%s) in %.0fms",
            self._profile.project_name,
            self._profile.language,
            self._profile.framework,
            self._profile.scan_duration_ms,
        )
        return self._profile

    # ── Step 1: 读取项目环境 ───────────────────────────────

    def scan_environment(self) -> ScanResult:
        """Step 1: 读取项目环境。**工具无关。**

        通过 adapter.get_existing_file_patterns() 检测工具特定文件。

        Returns:
            环境扫描结果
        """
        p = self._profile
        # 项目名称取自根目录名
        p.project_name = self._root.name

        # Git 状态检测
        git_dir = self._root / ".git"
        p.is_git_repo = git_dir.exists() and git_dir.is_dir()

        if p.is_git_repo:
            try:
                # 检查 Git 工作区是否干净
                result = subprocess.run(
                    ["git", "status", "--porcelain"],
                    capture_output=True, text=True, cwd=str(self._root), timeout=10,
                )
                p.git_clean = not bool(result.stdout.strip())
                # 获取当前分支名
                branch = subprocess.run(
                    ["git", "branch", "--show-current"],
                    capture_output=True, text=True, cwd=str(self._root), timeout=5,
                )
                p.git_branch = branch.stdout.strip()
            except Exception:
                # Git 命令失败时静默跳过
                pass

        # .ai/ 目录检测（跨工具）
        p.has_ai_dir = (self._root / ".ai").is_dir()

        # Superpowers 检测（跨工具）
        p.has_superpowers_dir = (
            (self._root / "superpowers").is_dir() or
            (self._root / ".superpowers").is_dir()
        )

        # 工具特定文件检测 —— 通过 adapter
        p.existing_tool_files = {}
        if self._adapter:
            # 获取当前目标工具的已有文件模式
            patterns = self._adapter.get_existing_file_patterns()
            found: list[str] = []
            for pattern in patterns:
                target = self._root / pattern.rstrip("/")
                if target.exists():
                    found.append(pattern)
            p.existing_tool_files[self._adapter.tool_id] = found

        # 同时检测所有已知工具的已有文件（用于报告）
        # 使用类方法，无需实例化 Adapter
        from engines.adapters.claude import ClaudeCodeAdapter
        from engines.adapters.codex import CodexAdapter
        from engines.adapters.cursor import CursorAdapter

        # 遍历所有已知的适配器类，检测其工具文件
        for adp_cls in [ClaudeCodeAdapter, CodexAdapter, CursorAdapter]:
            if adp_cls.tool_id not in p.existing_tool_files:  # type: ignore[union-attr]
                found = []
                for pattern in adp_cls.get_existing_file_patterns():
                    target = self._root / pattern.rstrip("/")
                    if target.exists():
                        found.append(pattern)
                p.existing_tool_files[adp_cls.tool_id] = found

        # 合并所有工具的已存在文件列表
        p.existing_files = []
        for files in p.existing_tool_files.values():
            p.existing_files.extend(files)

        return ScanResult(
            step="environment",
            success=True,
            message=f"项目: {p.project_name}, Git: {p.is_git_repo}",
            details={
                "project_name": p.project_name,
                "is_git_repo": p.is_git_repo,
                "git_clean": p.git_clean,
                "existing_tool_files": p.existing_tool_files,
            },
        )

    # ── Step 2: 检测 AI 编程工具 ─────────────────────────────

    def detect_tools(self) -> ScanResult:
        """Step 2: 检测 AI 编程工具。

        Returns:
            工具检测结果
        """
        p = self._profile

        # 通过已检测到的文件判断已安装的工具
        for tool_id, files in p.existing_tool_files.items():
            if files:
                p.detected_tools.append(tool_id)

        # 兜底检测：直接检查标志性文件/目录
        if "claude_code" not in p.detected_tools:
            if (self._root / "CLAUDE.md").exists() or (self._root / ".claude").is_dir():
                p.detected_tools.append("claude_code")
        if "codex" not in p.detected_tools:
            if (self._root / ".codex").exists():
                p.detected_tools.append("codex")
        if "cursor" not in p.detected_tools:
            if (self._root / ".cursor").exists():
                p.detected_tools.append("cursor")

        return ScanResult(
            step="detect_tools",
            success=True,
            message=f"检测到工具: {', '.join(p.detected_tools) or '无'}",
            details={"tools": p.detected_tools},
        )

    # ── Step 3-4: 检测插件与内部模块 ───────────────────────────

    def detect_plugins(self) -> ScanResult:
        """Step 3-4: 检测外部插件和内部模块。

        外部插件 — 通过全局插件缓存检测（~/.claude/plugins/cache/）。
        内部模块 — 引擎自带能力，检测是否可 import。

        Returns:
            插件检测结果
        """
        p = self._profile

        # ── 外部插件（全局安装，非项目级） ──
        # 全局插件缓存目录
        plugins_cache = Path.home() / ".claude" / "plugins" / "cache"

        # 定义外部插件列表
        external_plugins = {
            "superpowers": {
                "path": "claude-plugins-official/superpowers",
                "required": False,
                "label": "Superpowers 技能库",
            },
            "andrej-karpathy-skills": {
                "path": "karpathy-skills/andrej-karpathy-skills",
                "required": False,
                "label": "Andrej Karpathy 行为规范",
            },
            "codegraph": {
                "path": None,  # MCP-based，单独检测
                "required": False,
                "label": "CodeGraph 代码知识图谱",
            },
        }

        # 检测每个外部插件
        for plugin_id, cfg in external_plugins.items():
            installed = self._check_external_plugin(plugin_id, cfg.get("path"), plugins_cache)
            info = PluginInfo(
                name=plugin_id,
                installed=installed,
                required=cfg["required"],
                available=installed,
            )
            p.detected_plugins.append(info)
            if not installed:
                p.missing_recommended.append(f"{plugin_id} ({cfg['label']})")

        # ── 内部模块（引擎自带，不算插件） ──
        # 定义内部模块列表
        internal_modules = {
            "scenario-runner": ("engines.scenario", "ScenarioRunner"),
            "review-engine": ("engines.review", "ReviewEngine"),
        }
        p.internal_modules = {}
        for mod_name, (module_path, class_name) in internal_modules.items():
            # 检测模块是否可导入且包含指定类
            p.internal_modules[mod_name] = self._check_module(module_path, class_name)

        installed_count = len([pl for pl in p.detected_plugins if pl.installed])
        return ScanResult(
            step="detect_plugins",
            success=True,
            message=f"外部插件: {installed_count}/{len(external_plugins)} 已安装, "
                    f"内部模块: {sum(p.internal_modules.values())}/{len(internal_modules)} 可用",
            details={
                "external_plugins": {
                    pl.name: "已安装" if pl.installed else "未安装"
                    for pl in p.detected_plugins
                },
                "internal_modules": p.internal_modules,
                "missing_recommended": p.missing_recommended,
            },
        )

    def _check_external_plugin(
        self, plugin_id: str, rel_path: str | None, cache_root: Path
    ) -> bool:
        """检测外部插件是否已安装。

        - 有 rel_path 的：检查全局插件缓存目录
        - codegraph：检查 MCP 配置 + 插件缓存

        Args:
            plugin_id: 插件标识符
            rel_path: 插件在缓存中的相对路径
            cache_root: 插件缓存根目录

        Returns:
            插件是否已安装
        """
        if rel_path:
            # 检查版本目录（cache/<marketplace>/<plugin>/<version>/）
            plugin_dir = cache_root / rel_path
            if plugin_dir.is_dir():
                # 检查是否有版本子目录
                for entry in plugin_dir.iterdir():
                    if entry.is_dir() and (entry / "skills").is_dir():
                        return True
                # 直接就是技能目录（无版本层级）
                if (plugin_dir / "skills").is_dir():
                    return True
            return False

        # codegraph: 检查 MCP 配置或插件目录
        if plugin_id == "codegraph":
            return self._check_codegraph()

        return False

    def _check_codegraph(self) -> bool:
        """检测 codegraph 是否可用（MCP Server 或插件）。

        Returns:
            codegraph 是否可用
        """
        # 1. 检查全局 MCP 配置
        global_mcp = Path.home() / ".claude" / "mcp.json"
        if global_mcp.exists():
            try:
                import json
                config = json.loads(global_mcp.read_text(encoding="utf-8"))
                if "codegraph" in config.get("mcpServers", {}):
                    return True
            except Exception:
                pass

        # 2. 检查项目级 MCP 配置
        project_mcp = self._root / ".claude" / "mcp.json"
        if project_mcp.exists():
            try:
                import json
                config = json.loads(project_mcp.read_text(encoding="utf-8"))
                if "codegraph" in config.get("mcpServers", {}):
                    return True
            except Exception:
                pass

        # 3. 检查是否有 .codegraph/ 索引目录
        if (self._root / ".codegraph").is_dir():
            return True

        return False

    def _check_module(self, module_path: str, class_name: str) -> bool:
        """检测内部 Python 模块是否可用。

        Args:
            module_path: 模块路径，如 "engines.scenario"
            class_name: 类名，如 "ScenarioRunner"

        Returns:
            模块是否可导入且包含指定类
        """
        try:
            import importlib
            # 动态导入模块
            mod = importlib.import_module(module_path)
            # 检查模块中是否存在指定类
            return hasattr(mod, class_name)
        except ImportError:
            return False

    # ── Step 5: 扫描项目结构 ───────────────────────────────

    def scan_structure(self) -> ScanResult:
        """Step 5: 扫描项目结构，识别语言/框架/目录。

        Returns:
            结构扫描结果
        """
        p = self._profile
        # 检测编程语言和框架
        self._detect_language()
        # 分类目录
        self._categorize_directories()
        # 查找入口文件
        self._find_entry_files()

        return ScanResult(
            step="scan_structure",
            success=True,
            message=f"技术栈: {p.language}/{p.framework}, 源目录: {len(p.source_dirs)}, 测试目录: {len(p.test_dirs)}",
            details={
                "language": p.language,
                "framework": p.framework,
                "package_manager": p.package_manager,
                "source_dirs": p.source_dirs,
                "test_dirs": p.test_dirs,
                "config_dirs": p.config_dirs,
                "migration_dirs": p.migration_dirs,
            },
        )

    def _detect_language(self) -> None:
        """检测项目语言和框架。"""
        p = self._profile
        root = self._root

        # Python 项目检测
        if (root / "pyproject.toml").exists() or (root / "setup.py").exists() or (root / "requirements.txt").exists():
            p.language = "python"
            p.package_manager = "pip"
            p.build_tool = "setuptools" if (root / "pyproject.toml").exists() else "pip"
            # 检测框架
            if self._find_in_file(root / "pyproject.toml", "fastapi"):
                p.framework = "FastAPI"
            elif self._find_in_file(root / "pyproject.toml", "django"):
                p.framework = "Django"
            elif self._find_in_file(root / "pyproject.toml", "flask"):
                p.framework = "Flask"
            else:
                p.framework = "Python (未知框架)"

        # Java / Kotlin 项目检测
        elif (root / "pom.xml").exists() or (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
            p.language = "java"
            p.package_manager = "maven" if (root / "pom.xml").exists() else "gradle"
            p.build_tool = p.package_manager
            if (root / "pom.xml").exists() and self._find_in_file(root / "pom.xml", "spring-boot"):
                p.framework = "Spring Boot"
            p.source_dirs = ["src/main/java", "src/main/kotlin"]
            p.test_dirs = ["src/test/java", "src/test/kotlin"]

        # TypeScript / JavaScript 项目检测
        elif (root / "package.json").exists():
            p.package_manager = "npm"
            has_ts = (root / "tsconfig.json").exists()
            p.language = "typescript" if has_ts else "javascript"
            p.build_tool = "webpack"
            # 检测框架
            if self._find_in_file(root / "package.json", "next"):
                p.framework = "Next.js"
            elif self._find_in_file(root / "package.json", "react"):
                p.framework = "React"
            elif self._find_in_file(root / "package.json", "vue"):
                p.framework = "Vue"
            elif self._find_in_file(root / "package.json", "express"):
                p.framework = "Express"
            p.source_dirs = ["src", "app", "pages", "components"]
            p.test_dirs = ["__tests__", "tests", "test", "spec"]

        # Go 项目检测
        elif (root / "go.mod").exists():
            p.language = "go"
            p.package_manager = "go mod"
            p.build_tool = "go build"
            p.framework = "Go (标准库)" if not (root / "gin").exists() else "Gin"
            p.source_dirs = ["cmd", "internal", "pkg"]

        # Rust 项目检测
        elif (root / "Cargo.toml").exists():
            p.language = "rust"
            p.package_manager = "cargo"
            p.build_tool = "cargo"
            p.framework = "Rust"
            p.source_dirs = ["src"]
            p.test_dirs = ["tests"]

        # 无法识别语言时的默认值
        if not p.language:
            p.language = "unknown"

    def _detect_services(self) -> None:
        """根据项目类型自动推断服务启动命令和健康检查 URL。

        检测逻辑与 _detect_language 一致：看项目根目录的标志文件。
        结果写入 ProjectProfile，供 generator 生成 loop-config.json。
        """
        p = self._profile
        root = self._root

        # ── docker-compose 优先 ──
        for fname in ("docker-compose.yml", "docker-compose.yaml"):
            if (root / fname).exists():
                p.service_start_command = "docker-compose up -d"
                p.service_health_url = "http://localhost:8080/"
                p.service_port = 8080
                return

        # ── Java ──
        if (root / "pom.xml").exists():
            mvnw = "./mvnw" if (root / "mvnw").exists() else "mvn"
            if self._find_in_file(root / "pom.xml", "spring-boot"):
                # 检查是否为多模块
                modules = self._find_maven_modules()
                if modules:
                    p.is_monolith = False
                    # 多模块 → 生成 services 列表，每个 module 一条
                    p.service_services = [
                        {
                            "name": m,
                            "start": f"{mvnw} install -DskipTests && {mvnw} -pl {m} spring-boot:run",
                            "health": f"http://localhost:8080/actuator/health",
                            "enabled": True,
                        }
                        for m in modules
                    ]
                    return
                # 单体
                p.service_start_command = f"{mvnw} install -DskipTests && {mvnw} spring-boot:run"
                p.service_health_url = "http://localhost:8080/actuator/health"
                p.service_ready_pattern = "Started"
                p.service_port = 8080
                return
            # 非 Spring Boot 的 Java 项目
            p.service_start_command = f"{mvnw} exec:java"
            p.service_health_url = "http://localhost:8080/"
            p.service_port = 8080
            return

        if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
            gradlew = "./gradlew" if (root / "gradlew").exists() else "gradle"
            gradle_file = root / "build.gradle" if (root / "build.gradle").exists() else root / "build.gradle.kts"
            p.service_start_command = (
                f"{gradlew} bootRun" if self._find_in_file(gradle_file, "spring-boot")
                else f"{gradlew} run"
            )
            p.service_health_url = "http://localhost:8080/actuator/health"
            p.service_port = 8080
            return

        # ── Python ──
        if (root / "pyproject.toml").exists():
            if self._find_in_file(root / "pyproject.toml", "fastapi"):
                p.service_start_command = "uvicorn main:app --reload --host 0.0.0.0 --port 8080"
                p.service_health_url = "http://localhost:8080/"
            elif self._find_in_file(root / "pyproject.toml", "flask"):
                p.service_start_command = "flask run --host 0.0.0.0 --port 8080"
                p.service_health_url = "http://localhost:8080/"
            elif self._find_in_file(root / "pyproject.toml", "django"):
                p.service_start_command = "python manage.py runserver 0.0.0.0:8080"
                p.service_health_url = "http://localhost:8080/"
            p.service_port = 8080
            return

        # ── Node.js ──
        if (root / "package.json").exists():
            try:
                pkg = json.loads((root / "package.json").read_text(encoding="utf-8"))
                scripts = pkg.get("scripts", {})
                # 优先 dev，其次 start
                for key in ("dev", "start", "serve"):
                    if key in scripts:
                        p.service_start_command = f"npm run {key}"
                        break
                p.service_health_url = "http://localhost:3000/"
                p.service_port = 3000
            except Exception:
                pass
            return

        # ── Go ──
        if (root / "go.mod").exists():
            p.service_start_command = "go run ."
            p.service_health_url = "http://localhost:8080/"
            p.service_port = 8080
            return

        # ── Rust ──
        if (root / "Cargo.toml").exists():
            p.service_start_command = "cargo run"
            p.service_health_url = "http://localhost:8080/"
            p.service_port = 8080

    def _find_maven_modules(self) -> list[str]:
        """检测 Maven 多模块项目，返回 Spring Boot 模块列表。"""
        root = self._root
        # 简单检测：pom.xml 里 <modules> 标签
        pom = root / "pom.xml"
        if not pom.exists():
            return []
        try:
            content = pom.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return []
        # 简单的正则提取 <module>xxx</module>
        import re
        module_names = re.findall(r'<module>([^<]+)</module>', content)
        if not module_names:
            return []
        # 检查子模块是否含 spring-boot
        boot_modules = []
        for m in module_names:
            m_pom = root / m / "pom.xml"
            if m_pom.exists() and self._find_in_file(m_pom, "spring-boot"):
                boot_modules.append(m)
        return boot_modules

    def _categorize_directories(self) -> None:
        """分类目录为 source / test / config / resource / migration。"""
        p = self._profile
        # 已知的配置目录名
        known_config = {"config", "conf", "configuration", "settings"}
        # 已知的迁移目录名
        known_migration = {"migrations", "migration", "db", "alembic", "flyway", "liquibase"}

        # 遍历项目根目录下的子目录
        for entry in self._root.iterdir():
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            name = entry.name.lower()
            if name in known_config:
                p.config_dirs.append(entry.name)
            elif name in known_migration:
                p.migration_dirs.append(entry.name)

    def _find_entry_files(self) -> None:
        """查找入口文件。"""
        p = self._profile
        # 常见的入口文件名
        candidates = ["main.py", "app.py", "run.py", "__main__.py",
                       "index.ts", "index.js", "server.ts", "server.js",
                       "main.go", "cmd/main.go",
                       "App.java", "Application.java", "Main.java"]
        for candidate in candidates:
            target = self._root / candidate
            if target.exists():
                p.entry_files.append(candidate)

    # ── Step 6: 识别代码规范 ──────────────────────────────

    def infer_code_style(self) -> ScanResult:
        """Step 6: 推断代码规范。

        Returns:
            代码规范推断结果
        """
        p = self._profile
        style = p.code_style

        # 检测 lint 配置文件
        for config in ["pyproject.toml", "ruff.toml", ".prettierrc", ".prettierrc.json",
                        ".eslintrc.js", "checkstyle.xml", ".editorconfig"]:
            if (self._root / config).exists():
                p.linter_configs.append(config)

        # 推断格式化工具
        if any(c in p.linter_configs for c in ["pyproject.toml", "ruff.toml"]):
            style.formatter = "ruff"
        elif any(".prettierrc" in c for c in p.linter_configs):
            style.formatter = "prettier"

        # 根据语言推断代码规范
        if p.language == "python":
            style.naming_convention = "snake_case (Python 惯例)"
            style.test_naming = "test_*.py"
            style.logging_framework = "logging / loguru"
            style.exception_pattern = "try-except (Python 惯例)"
            conf = "medium"
        elif p.language == "java":
            style.naming_convention = "camelCase / PascalCase"
            style.test_naming = "*Test.java"
            style.logging_framework = "SLF4J / Logback"
            style.exception_pattern = "try-catch / @ExceptionHandler"
            conf = "medium"
        elif p.language in ("typescript", "javascript"):
            style.naming_convention = "camelCase / PascalCase"
            style.test_naming = "*.test.ts / *.spec.ts"
            style.logging_framework = "winston / console"
            style.exception_pattern = "try-catch / Promise.catch"
            conf = "medium"
        else:
            conf = "low"

        style.confidence = conf

        return ScanResult(
            step="code_style",
            success=True,
            message=f"代码规范: 命名={style.naming_convention}, 格式化={style.formatter}, 可信度={style.confidence}",
            details={"code_style": style.model_dump()},
        )

    # ── Step 7: 识别测试方式 ───────────────────────────────

    def detect_testing(self) -> ScanResult:
        """Step 7: 识别测试和验证方式。

        Returns:
            测试方式检测结果
        """
        p = self._profile

        # Python 项目的测试框架检测
        if p.language == "python":
            for cfg in ["pytest.ini", "tox.ini", "pyproject.toml"]:
                if (self._root / cfg).exists():
                    if self._find_in_file(self._root / cfg, "pytest"):
                        p.test_framework = "pytest"
                        p.test_runner_command = "pytest"
                        break
            if not p.test_framework:
                p.test_framework = "pytest (推测)"
                p.test_runner_command = "pytest"

        # Java 项目的测试框架
        elif p.language == "java":
            p.test_framework = "JUnit"
            p.test_runner_command = f"./{'mvnw' if (self._root / 'mvnw').exists() else 'mvn'} test"

        # TypeScript/JavaScript 项目的测试框架检测
        elif p.language in ("typescript", "javascript"):
            if (self._root / "jest.config.js").exists() or (self._root / "jest.config.ts").exists():
                p.test_framework = "Jest"
            elif self._find_in_file(self._root / "package.json", "vitest"):
                p.test_framework = "Vitest"
            elif self._find_in_file(self._root / "package.json", "mocha"):
                p.test_framework = "Mocha"
            else:
                p.test_framework = "Jest (推测)"
            p.test_runner_command = "npm test"

        # Go 项目的测试框架
        elif p.language == "go":
            p.test_framework = "go test"
            p.test_runner_command = "go test ./..."

        # Rust 项目的测试框架
        elif p.language == "rust":
            p.test_framework = "cargo test"
            p.test_runner_command = "cargo test"

        # Docker Compose 检测
        for f in ["docker-compose.yml", "docker-compose.yaml", "compose.yaml"]:
            if (self._root / f).exists():
                p.has_docker_compose = True
                break

        # 测试目录检测
        test_root = None
        for d in p.test_dirs:
            if (self._root / d).is_dir():
                test_root = self._root / d
                break
        if test_root:
            # 递归搜索测试文件
            test_files = list(test_root.rglob("test_*.py")) + list(test_root.rglob("*Test.java")) + list(test_root.rglob("*.test.*"))
            p.has_unit_tests = len(test_files) > 0
            p.has_integration_tests = len(test_files) > 3

        # 测试数据库配置检测
        p.has_test_db_config = any(
            (self._root / f).exists()
            for f in ["application-test.yml", "application-test.properties", ".env.test"]
        )

        return ScanResult(
            step="detect_testing",
            success=True,
            message=f"测试: {p.test_framework}, 单测: {p.has_unit_tests}, 集成测试: {p.has_integration_tests}, Docker: {p.has_docker_compose}",
            details={
                "test_framework": p.test_framework,
                "test_runner": p.test_runner_command,
                "has_unit_tests": p.has_unit_tests,
                "has_integration_tests": p.has_integration_tests,
                "has_docker_compose": p.has_docker_compose,
            },
        )

    # ── Step 8: 识别外部资源 ──────────────────────────────

    # 资源名 → 类型的简单映射（用于 ResourceInfo.type）
    _RESOURCE_TYPE_MAP: dict[str, str] = {
        "mysql": "database",
        "postgres": "database",
        "mongodb": "database",
        "redis": "cache",
        "kafka": "queue",
        "rabbitmq": "queue",
        "elasticsearch": "search",
    }

    def detect_resources(self) -> ScanResult:
        """Step 8: 识别外部资源 —— 扫描项目配置文件关键字。

        检测到的资源建议用户在 loop-config.json 的 data_sources 中配置连接信息。

        Returns:
            资源检测结果
        """
        p = self._profile

        # 扫描配置文件关键字
        try:
            from engines.providers.mcp_registry import load_registry, _scan_config_content
            registry = load_registry(self._root)
            content = _scan_config_content(self._root) if registry else ""
        except Exception:
            logger.warning("Resource detection failed", exc_info=True)
            registry = {}
            content = ""

        # 关键字匹配 → ResourceInfo
        for name, cfg in registry.items():
            keywords = cfg.get("keywords", [])
            if not keywords:
                continue
            if any(kw.lower() in content for kw in keywords):
                rtype = self._RESOURCE_TYPE_MAP.get(name, "")
                p.resources.append(ResourceInfo(
                    name=cfg.get("description", name),
                    type=rtype,
                    evidence=f"配置文件关键字匹配: {[kw for kw in keywords if kw.lower() in content]}",
                    configured=False,
                ))

        return ScanResult(
            step="detect_resources",
            success=True,
            message=f"检测到 {len(p.resources)} 个外部资源: {[r.name for r in p.resources]}",
            details={"resources": [r.model_dump() for r in p.resources]},
        )

    # ── 工具方法 ──────────────────────────────────────────

    @staticmethod
    def _find_in_file(filepath: Path, keyword: str) -> bool:
        """在文件中查找关键词（不区分大小写）。

        Args:
            filepath: 文件路径
            keyword: 搜索关键词

        Returns:
            是否找到关键词
        """
        if not filepath.exists():
            return False
        try:
            # 读取文件内容并转为小写进行匹配
            content = filepath.read_text(encoding="utf-8", errors="ignore").lower()
            return keyword.lower() in content
        except Exception:
            return False