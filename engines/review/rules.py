"""Review 规则定义。

内置规则（全部默认注册）：
- SecretScanRule:      硬编码凭证扫描（14 条正则），BLOCK
- TestIntegrityRule:   测试文件删除 + "改代码不写测试" 检测，BLOCK + WARN
- ScopeBoundaryRule:   从 Plan Contract 提取 allowed_files，检测越界修改，BLOCK
- SkipDetectionRule:   扫 git diff 新增代码中的 skip/xit/@skip 标记，WARN

Python 职责：确定性检测（有/没有）→ BLOCK 或 WARN
AI 职责：语义判断（对/不对）→ 在 review prompt 中深度审查
"""

from __future__ import annotations

import logging
import re
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from .models import ReviewResult, ReviewSeverity

if TYPE_CHECKING:
    from engines.state.models import RunState

logger = logging.getLogger(__name__)


# ── 抽象基类 ──────────────────────────────────────────────────────

class ReviewRule(ABC):
    """审查规则基类。"""

    name: str
    severity: ReviewSeverity = ReviewSeverity.WARN

    @abstractmethod
    def check(self, state: RunState) -> ReviewResult:
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r} severity={self.severity.value}>"


# ═══════════════════════════════════════════════════════════════════
# 内置规则
# ═══════════════════════════════════════════════════════════════════


class SecretScanRule(ReviewRule):
    """硬编码凭证扫描 —— 14 条正则。 severity=BLOCK。"""

    name = "secret-scan"
    severity = ReviewSeverity.BLOCK

    SECRET_PATTERNS: list[tuple[str, str]] = [
        (r'(?i)api[_-]?key\s*[:=]\s*[\'"][^\'"]{16,}[\'"]', "API Key 硬编码"),
        (r'(?i)secret[_-]?key\s*[:=]\s*[\'"][^\'"]{16,}[\'"]', "Secret Key 硬编码"),
        (r'(?i)access[_-]?token\s*[:=]\s*[\'"][^\'"]{16,}[\'"]', "Access Token 硬编码"),
        (r'AKIA[0-9A-Z]{16}', "AWS Access Key"),
        (r'sk-[A-Za-z0-9]{32,}', "OpenAI API Key"),
        (r'sk-ant-[A-Za-z0-9]{32,}', "Anthropic API Key"),
        (r'gh[pousr]_[A-Za-z0-9_]{36,}', "GitHub Token"),
        (r'(?i)password\s*[:=]\s*[\'"][^\'"]{4,}[\'"]', "密码明文"),
        (r'(?i)passwd\s*[:=]\s*[\'"][^\'"]{4,}[\'"]', "密码明文"),
        (r'eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}', "JWT Token"),
        (r'-----BEGIN (RSA|EC|DSA|OPENSSH) PRIVATE KEY-----', "私钥硬编码"),
        (r'(?i)(mysql|postgres|postgresql|mongodb)://[^:]+:[^@]+@', "数据库连接串含密码"),
        (r'(?i)token\s*[:=]\s*[\'"][A-Za-z0-9+/=]{32,}[\'"]', "Token 硬编码"),
        (r'(?i)api[_-]?secret\s*[:=]\s*[\'"][^\'"]{8,}[\'"]', "API Secret 硬编码"),
    ]

    SCAN_SUFFIXES = (
        '.py', '.ts', '.tsx', '.js', '.jsx', '.go', '.rs', '.java', '.kt',
        '.yaml', '.yml', '.json', '.env', '.toml', '.cfg', '.ini',
        '.sh', '.bash', '.zsh', '.ps1',
    )

    def check(self, state: RunState) -> ReviewResult:
        changed_files = self._get_changed_files(state)
        if not changed_files:
            return ReviewResult.ok(self.name, "无变更文件，跳过密钥扫描")

        project_root = Path(state.project_root) if state.project_root else Path.cwd()
        findings: list[str] = []

        for f in changed_files:
            fpath = project_root / f
            if fpath.suffix not in self.SCAN_SUFFIXES:
                continue
            if not fpath.exists():
                continue
            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
                for pattern, label in self.SECRET_PATTERNS:
                    if re.search(pattern, content):
                        findings.append(f"{f}: {label}")
                        break
            except Exception:
                continue

        if findings:
            return ReviewResult.blocked(
                self.name,
                f"检测到 {len(findings)} 处疑似硬编码凭证",
                findings=findings[:10],
            )
        return ReviewResult.ok(self.name, f"密钥扫描通过 ({len(changed_files)} 个文件)")

    def _get_changed_files(self, state: RunState) -> list[str]:
        files: list[str] = []
        for log in state.task_state.task_logs:
            files.extend(log.changed_files)
        if not files:
            for cp in reversed(state.checkpoints):
                if cp.files_changed:
                    files = cp.files_changed
                    break
        return files


class TestIntegrityRule(ReviewRule):
    """测试完整性检查。 BLOCK: 测试文件被删 / WARN: 改源码不改测试。"""

    name = "test-integrity"
    severity = ReviewSeverity.BLOCK

    TEST_PATTERNS = ("test_", "_test.", "tests/", "spec/", "__tests__/", ".test.", ".spec.")
    SRC_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".kt")

    def check(self, state: RunState) -> ReviewResult:
        project_root = Path(state.project_root) if state.project_root else Path.cwd()
        changed_files = self._get_changed_files(state)

        if not changed_files:
            return ReviewResult.ok(self.name, "无变更文件")

        deletions = self._check_git_deletions(project_root)
        if deletions:
            return ReviewResult.blocked(
                self.name,
                f"检测到测试文件被删除: {len(deletions)} 个",
                deleted_files=deletions,
            )

        src_changed = [f for f in changed_files if self._is_src_file(f)]
        test_changed = [f for f in changed_files if self._is_test_file(f)]

        if src_changed and not test_changed:
            return ReviewResult.warn(
                self.name,
                f"修改了 {len(src_changed)} 个源码文件但未修改测试文件",
                src_files=src_changed[:10],
            )

        return ReviewResult.ok(
            self.name,
            f"测试完整性通过 ({len(src_changed)} src / {len(test_changed)} test)",
        )

    def _get_changed_files(self, state: RunState) -> list[str]:
        files: list[str] = []
        for log in state.task_state.task_logs:
            files.extend(log.changed_files)
        if not files:
            for cp in reversed(state.checkpoints):
                if cp.files_changed:
                    files = cp.files_changed
                    break
        return files

    def _is_src_file(self, filepath: str) -> bool:
        return filepath.endswith(self.SRC_SUFFIXES) and not self._is_test_file(filepath)

    def _is_test_file(self, filepath: str) -> bool:
        return any(pattern in filepath for pattern in self.TEST_PATTERNS)

    @staticmethod
    def _check_git_deletions(project_root: Path) -> list[str]:
        try:
            if not (project_root / ".git").is_dir():
                return []
            result = subprocess.run(
                ["git", "diff", "--name-status", "HEAD"],
                capture_output=True, text=True, cwd=str(project_root), timeout=10,
            )
            if result.returncode != 0:
                return []
            test_patterns = ("test_", "_test.", "tests/", "spec/", "__tests__/", ".test.", ".spec.")
            deletions: list[str] = []
            for line in result.stdout.strip().splitlines():
                if not line.startswith("D\t"):
                    continue
                filepath = line[2:].strip()
                if any(p in filepath for p in test_patterns):
                    deletions.append(filepath)
            return deletions
        except Exception:
            return []


class ScopeBoundaryRule(ReviewRule):
    """Plan 越界检查 —— 从 Plan Contract 自动提取 allowed_files。 severity=BLOCK。"""

    name = "scope-boundary"
    severity = ReviewSeverity.BLOCK

    def check(self, state: RunState) -> ReviewResult:
        contracts = state.plan_contracts
        if not contracts:
            return ReviewResult.ok(self.name, "无 Plan Contract，跳过边界检查")

        allowed_by_task: dict[str, list[str]] = {}
        for c in contracts:
            task_id = c.get("task_id", "?")
            allowed_by_task[task_id] = c.get("allowed_files", [])

        changed_files = self._get_changed_files(state)
        if not changed_files:
            return ReviewResult.ok(self.name, "无变更文件，跳过边界检查")

        all_allowed: set[str] = set()
        for paths in allowed_by_task.values():
            all_allowed.update(paths)

        if not all_allowed:
            return ReviewResult.ok(self.name, "Plan Contract 未声明 allowed_files，跳过")

        violations: list[str] = []
        for f in changed_files:
            if not any(self._match_path(f, p) for p in all_allowed):
                violations.append(f)

        if violations:
            return ReviewResult.blocked(
                self.name,
                f"修改超出 Plan 授权范围: {len(violations)} 个文件越界",
                violations=violations,
                allowed_paths=sorted(all_allowed),
            )

        return ReviewResult.ok(self.name, f"所有 {len(changed_files)} 个文件在 Plan 授权范围内")

    def _get_changed_files(self, state: RunState) -> list[str]:
        files: list[str] = []
        for log in state.task_state.task_logs:
            files.extend(log.changed_files)
        if not files:
            for cp in reversed(state.checkpoints):
                if cp.files_changed:
                    files = cp.files_changed
                    break
        return files

    @staticmethod
    def _match_path(filepath: str, allowed: str) -> bool:
        if filepath == allowed:
            return True
        if allowed.endswith("/") and filepath.startswith(allowed):
            return True
        if "/" in allowed and not allowed.endswith("/"):
            parent = allowed.rsplit("/", 1)[0] + "/"
            if filepath.startswith(parent):
                return True
        return filepath.startswith(allowed)


class SkipDetectionRule(ReviewRule):
    """跳过标记检测 —— 扫描 git diff 新增行中的 skip/ignore 标记。 severity=WARN。"""

    name = "skip-detection"
    severity = ReviewSeverity.WARN

    SKIP_MARKERS = (
        "pytest.mark.skip", "unittest.skip", "@skip", "@ignore",
        "xtest(", "xdescribe(", "xit(",
        "TODO: fix later", "it.skip(", "test.skip(", "describe.skip(",
        "// SKIP", "# SKIP", "# type: ignore",
        "eslint-disable", "nolint", "ts-ignore", "noqa",
    )

    def check(self, state: RunState) -> ReviewResult:
        project_root = Path(state.project_root) if state.project_root else Path.cwd()
        changed_files = self._get_changed_files(state)

        if not changed_files:
            return ReviewResult.ok(self.name, "无变更文件")

        findings = self._scan_git_diff(project_root, changed_files)
        if findings:
            return ReviewResult.warn(
                self.name,
                f"检测到 {len(findings)} 处新增 skip/忽略标记",
                hints=findings[:10],
            )

        return ReviewResult.ok(self.name, "skip 标记检查通过")

    def _get_changed_files(self, state: RunState) -> list[str]:
        files: list[str] = []
        for log in state.task_state.task_logs:
            files.extend(log.changed_files)
        if not files:
            for cp in reversed(state.checkpoints):
                if cp.files_changed:
                    files = cp.files_changed
                    break
        return files

    def _scan_git_diff(self, project_root: Path, changed_files: list[str]) -> list[str]:
        findings: list[str] = []
        try:
            if not (project_root / ".git").is_dir():
                return self._scan_files_fallback(project_root, changed_files)

            result = subprocess.run(
                ["git", "diff", "HEAD", "--", *changed_files],
                capture_output=True, text=True, cwd=str(project_root), timeout=10,
            )
            if result.returncode != 0:
                return self._scan_files_fallback(project_root, changed_files)

            current_file = ""
            for line in result.stdout.splitlines():
                if line.startswith("+++ b/"):
                    current_file = line[6:]
                    continue
                if not line.startswith("+") or line.startswith("+++ "):
                    continue
                for marker in self.SKIP_MARKERS:
                    if marker in line:
                        findings.append(f"{current_file}: {marker} → {line[:80].strip()}")
                        break
        except Exception:
            return self._scan_files_fallback(project_root, changed_files)

        return findings

    def _scan_files_fallback(self, project_root: Path, changed_files: list[str]) -> list[str]:
        findings: list[str] = []
        for f in changed_files[-20:]:
            fpath = project_root / f
            if not fpath.exists():
                continue
            try:
                for i, line in enumerate(fpath.read_text(encoding="utf-8", errors="ignore").splitlines()):
                    for marker in self.SKIP_MARKERS:
                        if marker in line:
                            findings.append(f"{f}:{i + 1}: {marker}")
                            break
            except Exception:
                continue
        return findings
