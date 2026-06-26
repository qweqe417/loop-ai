"""增量验证 —— Per-task 快速检查（typecheck / compile / lint）。

在 ExecuteHandler 中每个 Task 完成后自动运行，
提供秒级反馈，不阻塞流程但记录结果。
"""

# 启用延迟注解求值
from __future__ import annotations

# 导入 logging 用于日志记录
import logging
# 导入 subprocess 用于执行外部命令（ruff、tsc、eslint 等）
import subprocess
# 导入 time 用于计时
import time
# 导入 dataclass 和 field 用于定义数据类
from dataclasses import dataclass, field
# 导入 Enum 用于定义枚举
from enum import Enum
# 导入 Path 用于文件路径操作
from pathlib import Path

# 创建当前模块的日志记录器
logger = logging.getLogger(__name__)


# 快速检查状态枚举
class QuickCheckStatus(str, Enum):
    PASSED = "passed"     # 通过
    FAILED = "failed"     # 失败
    WARNING = "warning"   # 警告（非严格模式下）
    SKIPPED = "skipped"   # 跳过（工具不可用）
    TIMEOUT = "timeout"   # 超时


# 单项快速检查结果数据类
@dataclass
class QuickCheckResult:
    """单项快速检查结果。"""

    # 检查项名称（如 py_compile、ruff、tsc、eslint 等）
    check_name: str
    # 检查状态
    status: QuickCheckStatus
    # 检查结果消息
    message: str = ""
    # 检查耗时（毫秒）
    duration_ms: float = 0
    # 被检查的文件列表
    files_checked: list[str] = field(default_factory=list)
    # 错误信息列表
    errors: list[str] = field(default_factory=list)


# 快速检查汇总报告数据类
@dataclass
class QuickCheckReport:
    """快速检查汇总报告。"""

    # 各检查项结果列表
    results: list[QuickCheckResult] = field(default_factory=list)
    # 总耗时（毫秒）
    total_duration_ms: float = 0
    # 是否全部通过
    all_passed: bool = True

    # 生成摘要字符串
    # 返回值: 格式化的摘要文本
    def summary(self) -> str:
        # 如果没有检查结果，返回无检查项提示
        if not self.results:
            return "QuickCheck: 无检查项"
        # 统计通过和失败的数量
        passed = sum(1 for r in self.results if r.status == QuickCheckStatus.PASSED)
        failed = sum(1 for r in self.results if r.status == QuickCheckStatus.FAILED)
        return (
            f"QuickCheck: {passed}/{len(self.results)} passed, "
            f"{failed} failed ({self.total_duration_ms:.0f}ms)"
        )


# Per-task 快速检查执行器类
class QuickCheckRunner:
    """Per-task 快速检查执行器。

    用法:
        runner = QuickCheckRunner(project_root=".")
        report = runner.run_checks(changed_files=["src/main.py", "src/utils.py"])
        if not report.all_passed:
            print(report.summary())
    """

    # 超时设置 (秒)
    DEFAULT_TIMEOUT = 10

    # 构造函数
    # 参数 project_root: 项目根目录
    # 参数 strict: 是否严格模式（严格模式下 lint 警告也算失败）
    def __init__(self, project_root: str | Path = ".", strict: bool = False) -> None:
        self._root = Path(project_root)
        self._strict = strict

    # 对变更文件运行所有适用的快速检查
    # 参数 changed_files: 变更的文件路径列表
    # 返回值: QuickCheckReport 汇总报告
    def run_checks(self, changed_files: list[str]) -> QuickCheckReport:
        """对变更文件运行所有适用的快速检查。"""
        start = time.perf_counter()
        results: list[QuickCheckResult] = []

        # 如果没有变更文件，直接返回空报告
        if not changed_files:
            return QuickCheckReport(results=[], all_passed=True)

        # 按语言分组文件
        file_groups = self._group_by_language(changed_files)

        # Python 文件 → py_compile + ruff
        if file_groups.get("python"):
            results.append(self._check_py_compile(file_groups["python"]))
            results.append(self._check_ruff(file_groups["python"]))

        # TypeScript/JavaScript → tsc --noEmit
        if file_groups.get("typescript"):
            results.append(self._check_tsc(file_groups["typescript"]))
        if file_groups.get("javascript"):
            results.append(self._check_eslint(file_groups["javascript"]))

        # Go → go vet
        if file_groups.get("go"):
            results.append(self._check_go_vet(file_groups["go"]))

        # Rust → cargo check
        if file_groups.get("rust"):
            results.append(self._check_cargo_check(file_groups["rust"]))

        # 通用: 语法检查（已由 py_compile 等覆盖，此处跳过）

        # 计算总耗时（毫秒）
        total_duration = (time.perf_counter() - start) * 1000
        # 判断是否全部通过（没有任何 FAILED 状态）
        all_passed = all(
            r.status != QuickCheckStatus.FAILED for r in results
        )

        report = QuickCheckReport(
            results=results,
            total_duration_ms=total_duration,
            all_passed=all_passed,
        )
        logger.info("QuickCheck: %s", report.summary())
        return report

    # ── 语言检测 ──────────────────────────────────────────

    # 按语言分组文件
    # 参数 files: 文件路径列表
    # 返回值: {语言: [文件路径列表]} 字典
    def _group_by_language(self, files: list[str]) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {}
        for f in files:
            # 检测文件语言
            lang = self._detect_language(f)
            # 添加到对应语言分组
            groups.setdefault(lang, []).append(f)
        return groups

    # 检测单个文件的语言类型
    # 参数 filepath: 文件路径
    # 返回值: 语言类型字符串
    @staticmethod
    def _detect_language(filepath: str) -> str:
        # 获取文件扩展名（小写）
        ext = Path(filepath).suffix.lower()
        # Python 文件
        if ext in (".py", ".pyx", ".pxd"):
            return "python"
        # TypeScript 文件
        if ext in (".ts", ".tsx", ".mts"):
            return "typescript"
        # JavaScript 文件
        if ext in (".js", ".jsx", ".mjs", ".cjs"):
            return "javascript"
        # Go 文件
        if ext == ".go":
            return "go"
        # Rust 文件
        if ext == ".rs":
            return "rust"
        # JVM 语言文件
        if ext in (".java", ".kt", ".scala"):
            return "jvm"
        # 其他语言
        return "other"

    # ── Python 检查 ───────────────────────────────────────

    # Python 编译检查（py_compile）
    # 参数 files: Python 文件路径列表
    # 返回值: QuickCheckResult 检查结果
    def _check_py_compile(self, files: list[str]) -> QuickCheckResult:
        """Python 编译检查 (py_compile)。"""
        start = time.perf_counter()
        errors: list[str] = []
        checked: list[str] = []

        # 逐个文件进行编译检查
        for f in files:
            fpath = self._root / f
            # 文件不存在则跳过
            if not fpath.exists():
                continue
            try:
                import py_compile
                # 调用 py_compile 编译文件，doraise=True 表示编译错误时抛出异常
                py_compile.compile(str(fpath), doraise=True)
                checked.append(f)
            except py_compile.PyCompileError as e:
                errors.append(f"{f}: {e}")
            except Exception as e:
                errors.append(f"{f}: {e}")

        # 计算耗时
        duration = (time.perf_counter() - start) * 1000
        # 如果没有可检查的文件，返回 SKIPPED 状态
        if not checked:
            return QuickCheckResult(
                check_name="py_compile",
                status=QuickCheckStatus.SKIPPED,
                message="无可检查的 Python 文件",
                duration_ms=duration,
            )

        # 如果有编译错误，返回 FAILED 状态
        if errors:
            return QuickCheckResult(
                check_name="py_compile",
                status=QuickCheckStatus.FAILED,
                message=f"{len(errors)}/{len(files)} 个文件编译失败",
                duration_ms=duration,
                files_checked=checked,
                errors=errors,
            )

        # 全部通过
        return QuickCheckResult(
            check_name="py_compile",
            status=QuickCheckStatus.PASSED,
            message=f"{len(checked)} 个文件编译通过",
            duration_ms=duration,
            files_checked=checked,
        )

    # Ruff lint 检查（如果可用）
    # 参数 files: Python 文件路径列表
    # 返回值: QuickCheckResult 检查结果
    def _check_ruff(self, files: list[str]) -> QuickCheckResult:
        """Ruff lint 检查（如果可用）。"""
        start = time.perf_counter()
        try:
            # 执行 ruff check 命令
            result = subprocess.run(
                ["ruff", "check", "--output-format=concise", *files],
                capture_output=True, text=True,
                cwd=str(self._root),
                timeout=self.DEFAULT_TIMEOUT,
            )
            duration = (time.perf_counter() - start) * 1000
            # 返回码为 0 表示通过
            if result.returncode == 0:
                return QuickCheckResult(
                    check_name="ruff",
                    status=QuickCheckStatus.PASSED,
                    message="Ruff 检查通过",
                    duration_ms=duration,
                    files_checked=files,
                )
            # 提取前 10 条错误信息
            errors = [l.strip() for l in result.stdout.splitlines() if l.strip()][:10]
            return QuickCheckResult(
                check_name="ruff",
                # 严格模式下 lint 问题算失败，否则算警告
                status=QuickCheckStatus.FAILED if self._strict else QuickCheckStatus.WARNING,
                message=f"Ruff 发现 {len(errors)} 个问题",
                duration_ms=duration,
                files_checked=files,
                errors=errors,
            )
        except FileNotFoundError:
            # ruff 命令不可用
            return QuickCheckResult(
                check_name="ruff",
                status=QuickCheckStatus.SKIPPED,
                message="ruff 不可用",
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        except subprocess.TimeoutExpired:
            # 检查超时
            return QuickCheckResult(
                check_name="ruff",
                status=QuickCheckStatus.TIMEOUT,
                message=f"超时 ({self.DEFAULT_TIMEOUT}s)",
                duration_ms=self.DEFAULT_TIMEOUT * 1000,
            )

    # ── TypeScript 检查 ───────────────────────────────────

    # TypeScript 类型检查 --noEmit
    # 参数 files: TypeScript 文件路径列表
    # 返回值: QuickCheckResult 检查结果
    def _check_tsc(self, files: list[str]) -> QuickCheckResult:
        """TypeScript 类型检查 --noEmit。"""
        start = time.perf_counter()
        # 检查 tsconfig.json 是否存在
        tsconfig = self._root / "tsconfig.json"
        if not tsconfig.exists():
            return QuickCheckResult(
                check_name="tsc",
                status=QuickCheckStatus.SKIPPED,
                message="tsconfig.json 不存在",
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        try:
            # 执行 tsc --noEmit 进行类型检查
            result = subprocess.run(
                ["npx", "tsc", "--noEmit", "--pretty", "false"],
                capture_output=True, text=True,
                cwd=str(self._root),
                timeout=self.DEFAULT_TIMEOUT,
            )
            duration = (time.perf_counter() - start) * 1000
            # 返回码为 0 表示通过
            if result.returncode == 0:
                return QuickCheckResult(
                    check_name="tsc",
                    status=QuickCheckStatus.PASSED,
                    message="TypeScript 类型检查通过",
                    duration_ms=duration,
                    files_checked=files,
                )
            # 提取前 10 条错误
            errors = result.stdout.splitlines()[:10]
            return QuickCheckResult(
                check_name="tsc",
                status=QuickCheckStatus.FAILED if self._strict else QuickCheckStatus.WARNING,
                message=f"TypeScript 类型错误: {len(errors)} 个",
                duration_ms=duration,
                errors=errors,
            )
        except FileNotFoundError:
            return QuickCheckResult(
                check_name="tsc",
                status=QuickCheckStatus.SKIPPED,
                message="tsc 不可用",
            )
        except subprocess.TimeoutExpired:
            return QuickCheckResult(
                check_name="tsc",
                status=QuickCheckStatus.TIMEOUT,
                message=f"超时 ({self.DEFAULT_TIMEOUT}s)",
            )

    # ── JavaScript 检查 ───────────────────────────────────

    # ESLint 检查
    # 参数 files: JavaScript 文件路径列表
    # 返回值: QuickCheckResult 检查结果
    def _check_eslint(self, files: list[str]) -> QuickCheckResult:
        """ESLint 检查。"""
        start = time.perf_counter()
        try:
            # 执行 eslint 命令
            result = subprocess.run(
                ["npx", "eslint", "--format=compact", *files],
                capture_output=True, text=True,
                cwd=str(self._root),
                timeout=self.DEFAULT_TIMEOUT,
            )
            duration = (time.perf_counter() - start) * 1000
            # 返回码为 0 表示通过
            if result.returncode == 0:
                return QuickCheckResult(
                    check_name="eslint",
                    status=QuickCheckStatus.PASSED,
                    message="ESLint 检查通过",
                    duration_ms=duration,
                    files_checked=files,
                )
            # 提取前 10 条错误
            errors = [l.strip() for l in result.stdout.splitlines() if l.strip()][:10]
            return QuickCheckResult(
                check_name="eslint",
                status=QuickCheckStatus.FAILED if self._strict else QuickCheckStatus.WARNING,
                message=f"ESLint 发现 {len(errors)} 个问题",
                duration_ms=duration,
                files_checked=files,
                errors=errors,
            )
        except FileNotFoundError:
            return QuickCheckResult(
                check_name="eslint",
                status=QuickCheckStatus.SKIPPED,
                message="eslint 不可用",
            )
        except subprocess.TimeoutExpired:
            return QuickCheckResult(
                check_name="eslint",
                status=QuickCheckStatus.TIMEOUT,
                message=f"超时 ({self.DEFAULT_TIMEOUT}s)",
            )

    # ── Go 检查 ───────────────────────────────────────────

    # Go vet 检查
    # 参数 files: Go 文件路径列表
    # 返回值: QuickCheckResult 检查结果
    def _check_go_vet(self, files: list[str]) -> QuickCheckResult:
        """Go vet 检查。"""
        start = time.perf_counter()
        try:
            # go vet 需要包路径，而非文件
            result = subprocess.run(
                ["go", "vet", "./..."],
                capture_output=True, text=True,
                cwd=str(self._root),
                timeout=self.DEFAULT_TIMEOUT,
            )
            duration = (time.perf_counter() - start) * 1000
            # 返回码为 0 表示通过
            if result.returncode == 0:
                return QuickCheckResult(
                    check_name="go_vet",
                    status=QuickCheckStatus.PASSED,
                    message="go vet 检查通过",
                    duration_ms=duration,
                    files_checked=files,
                )
            # 从 stderr 或 stdout 提取错误
            errors = result.stderr.splitlines()[:10] or result.stdout.splitlines()[:10]
            return QuickCheckResult(
                check_name="go_vet",
                status=QuickCheckStatus.FAILED if self._strict else QuickCheckStatus.WARNING,
                message=f"go vet 发现 {len(errors)} 个问题",
                duration_ms=duration,
                errors=errors,
            )
        except FileNotFoundError:
            return QuickCheckResult(
                check_name="go_vet",
                status=QuickCheckStatus.SKIPPED,
                message="go 不可用",
            )
        except subprocess.TimeoutExpired:
            return QuickCheckResult(
                check_name="go_vet",
                status=QuickCheckStatus.TIMEOUT,
                message=f"超时 ({self.DEFAULT_TIMEOUT}s)",
            )

    # ── Rust 检查 ─────────────────────────────────────────

    # Cargo check（快速编译检查）
    # 参数 files: Rust 文件路径列表
    # 返回值: QuickCheckResult 检查结果
    def _check_cargo_check(self, files: list[str]) -> QuickCheckResult:
        """Cargo check (快速编译检查)。"""
        start = time.perf_counter()
        try:
            # 执行 cargo check 命令
            result = subprocess.run(
                ["cargo", "check", "--message-format=short"],
                capture_output=True, text=True,
                cwd=str(self._root),
                timeout=self.DEFAULT_TIMEOUT,
            )
            duration = (time.perf_counter() - start) * 1000
            # 返回码为 0 表示通过
            if result.returncode == 0:
                return QuickCheckResult(
                    check_name="cargo_check",
                    status=QuickCheckStatus.PASSED,
                    message="cargo check 通过",
                    duration_ms=duration,
                    files_checked=files,
                )
            # 从 stderr 提取错误
            errors = result.stderr.splitlines()[:10]
            return QuickCheckResult(
                check_name="cargo_check",
                status=QuickCheckStatus.FAILED if self._strict else QuickCheckStatus.WARNING,
                message=f"cargo check 发现 {len(errors)} 个问题",
                duration_ms=duration,
                errors=errors,
            )
        except FileNotFoundError:
            return QuickCheckResult(
                check_name="cargo_check",
                status=QuickCheckStatus.SKIPPED,
                message="cargo 不可用",
            )
        except subprocess.TimeoutExpired:
            return QuickCheckResult(
                check_name="cargo_check",
                status=QuickCheckStatus.TIMEOUT,
                message=f"超时 ({self.DEFAULT_TIMEOUT}s)",
            )