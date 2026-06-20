"""增量验证 —— Per-task 快速检查（typecheck / compile / lint）。

在 ExecuteHandler 中每个 Task 完成后自动运行，
提供秒级反馈，不阻塞流程但记录结果。
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class QuickCheckStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"


@dataclass
class QuickCheckResult:
    """单项快速检查结果。"""

    check_name: str
    status: QuickCheckStatus
    message: str = ""
    duration_ms: float = 0
    files_checked: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class QuickCheckReport:
    """快速检查汇总报告。"""

    results: list[QuickCheckResult] = field(default_factory=list)
    total_duration_ms: float = 0
    all_passed: bool = True

    def summary(self) -> str:
        if not self.results:
            return "QuickCheck: 无检查项"
        passed = sum(1 for r in self.results if r.status == QuickCheckStatus.PASSED)
        failed = sum(1 for r in self.results if r.status == QuickCheckStatus.FAILED)
        return (
            f"QuickCheck: {passed}/{len(self.results)} passed, "
            f"{failed} failed ({self.total_duration_ms:.0f}ms)"
        )


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

    def __init__(self, project_root: str | Path = ".", strict: bool = False) -> None:
        self._root = Path(project_root)
        self._strict = strict

    def run_checks(self, changed_files: list[str]) -> QuickCheckReport:
        """对变更文件运行所有适用的快速检查。"""
        start = time.perf_counter()
        results: list[QuickCheckResult] = []

        if not changed_files:
            return QuickCheckReport(results=[], all_passed=True)

        # 按语言分组
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

        total_duration = (time.perf_counter() - start) * 1000
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

    def _group_by_language(self, files: list[str]) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {}
        for f in files:
            lang = self._detect_language(f)
            groups.setdefault(lang, []).append(f)
        return groups

    @staticmethod
    def _detect_language(filepath: str) -> str:
        ext = Path(filepath).suffix.lower()
        if ext in (".py", ".pyx", ".pxd"):
            return "python"
        if ext in (".ts", ".tsx", ".mts"):
            return "typescript"
        if ext in (".js", ".jsx", ".mjs", ".cjs"):
            return "javascript"
        if ext == ".go":
            return "go"
        if ext == ".rs":
            return "rust"
        if ext in (".java", ".kt", ".scala"):
            return "jvm"
        return "other"

    # ── Python 检查 ───────────────────────────────────────

    def _check_py_compile(self, files: list[str]) -> QuickCheckResult:
        """Python 编译检查 (py_compile)。"""
        start = time.perf_counter()
        errors: list[str] = []
        checked: list[str] = []

        for f in files:
            fpath = self._root / f
            if not fpath.exists():
                continue
            try:
                import py_compile
                py_compile.compile(str(fpath), doraise=True)
                checked.append(f)
            except py_compile.PyCompileError as e:
                errors.append(f"{f}: {e}")
            except Exception as e:
                errors.append(f"{f}: {e}")

        duration = (time.perf_counter() - start) * 1000
        if not checked:
            return QuickCheckResult(
                check_name="py_compile",
                status=QuickCheckStatus.SKIPPED,
                message="无可检查的 Python 文件",
                duration_ms=duration,
            )

        if errors:
            return QuickCheckResult(
                check_name="py_compile",
                status=QuickCheckStatus.FAILED,
                message=f"{len(errors)}/{len(files)} 个文件编译失败",
                duration_ms=duration,
                files_checked=checked,
                errors=errors,
            )

        return QuickCheckResult(
            check_name="py_compile",
            status=QuickCheckStatus.PASSED,
            message=f"{len(checked)} 个文件编译通过",
            duration_ms=duration,
            files_checked=checked,
        )

    def _check_ruff(self, files: list[str]) -> QuickCheckResult:
        """Ruff lint 检查（如果可用）。"""
        start = time.perf_counter()
        try:
            result = subprocess.run(
                ["ruff", "check", "--output-format=concise", *files],
                capture_output=True, text=True,
                cwd=str(self._root),
                timeout=self.DEFAULT_TIMEOUT,
            )
            duration = (time.perf_counter() - start) * 1000
            if result.returncode == 0:
                return QuickCheckResult(
                    check_name="ruff",
                    status=QuickCheckStatus.PASSED,
                    message="Ruff 检查通过",
                    duration_ms=duration,
                    files_checked=files,
                )
            errors = [l.strip() for l in result.stdout.splitlines() if l.strip()][:10]
            return QuickCheckResult(
                check_name="ruff",
                status=QuickCheckStatus.FAILED if self._strict else QuickCheckStatus.WARNING,
                message=f"Ruff 发现 {len(errors)} 个问题",
                duration_ms=duration,
                files_checked=files,
                errors=errors,
            )
        except FileNotFoundError:
            return QuickCheckResult(
                check_name="ruff",
                status=QuickCheckStatus.SKIPPED,
                message="ruff 不可用",
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        except subprocess.TimeoutExpired:
            return QuickCheckResult(
                check_name="ruff",
                status=QuickCheckStatus.TIMEOUT,
                message=f"超时 ({self.DEFAULT_TIMEOUT}s)",
                duration_ms=self.DEFAULT_TIMEOUT * 1000,
            )

    # ── TypeScript 检查 ───────────────────────────────────

    def _check_tsc(self, files: list[str]) -> QuickCheckResult:
        """TypeScript 类型检查 --noEmit。"""
        start = time.perf_counter()
        tsconfig = self._root / "tsconfig.json"
        if not tsconfig.exists():
            return QuickCheckResult(
                check_name="tsc",
                status=QuickCheckStatus.SKIPPED,
                message="tsconfig.json 不存在",
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        try:
            result = subprocess.run(
                ["npx", "tsc", "--noEmit", "--pretty", "false"],
                capture_output=True, text=True,
                cwd=str(self._root),
                timeout=self.DEFAULT_TIMEOUT,
            )
            duration = (time.perf_counter() - start) * 1000
            if result.returncode == 0:
                return QuickCheckResult(
                    check_name="tsc",
                    status=QuickCheckStatus.PASSED,
                    message="TypeScript 类型检查通过",
                    duration_ms=duration,
                    files_checked=files,
                )
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

    def _check_eslint(self, files: list[str]) -> QuickCheckResult:
        """ESLint 检查。"""
        start = time.perf_counter()
        try:
            result = subprocess.run(
                ["npx", "eslint", "--format=compact", *files],
                capture_output=True, text=True,
                cwd=str(self._root),
                timeout=self.DEFAULT_TIMEOUT,
            )
            duration = (time.perf_counter() - start) * 1000
            if result.returncode == 0:
                return QuickCheckResult(
                    check_name="eslint",
                    status=QuickCheckStatus.PASSED,
                    message="ESLint 检查通过",
                    duration_ms=duration,
                    files_checked=files,
                )
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
            if result.returncode == 0:
                return QuickCheckResult(
                    check_name="go_vet",
                    status=QuickCheckStatus.PASSED,
                    message="go vet 检查通过",
                    duration_ms=duration,
                    files_checked=files,
                )
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

    def _check_cargo_check(self, files: list[str]) -> QuickCheckResult:
        """Cargo check (快速编译检查)。"""
        start = time.perf_counter()
        try:
            result = subprocess.run(
                ["cargo", "check", "--message-format=short"],
                capture_output=True, text=True,
                cwd=str(self._root),
                timeout=self.DEFAULT_TIMEOUT,
            )
            duration = (time.perf_counter() - start) * 1000
            if result.returncode == 0:
                return QuickCheckResult(
                    check_name="cargo_check",
                    status=QuickCheckStatus.PASSED,
                    message="cargo check 通过",
                    duration_ms=duration,
                    files_checked=files,
                )
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
