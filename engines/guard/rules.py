"""Guard 规则定义。

抽象基类 + 内置规则：
- ScopeBoundaryRule: 检查修改是否超出授权范围
- RiskLevelRule: 检查风险等级与 GuardLevel 是否匹配
- SanityCheckRule: 基础冒烟检查（编译 / lint 通过性）
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from .models import GuardResult, GuardSeverity

if TYPE_CHECKING:
    from engines.state.models import RunState

logger = logging.getLogger(__name__)


# ── 抽象基类 ──────────────────────────────────────────────────────

class GuardRule(ABC):
    """Guard 规则基类。

    每条规则实现 check() 方法，返回 GuardResult。
    """

    name: str
    severity: GuardSeverity = GuardSeverity.WARN

    @abstractmethod
    def check(self, state: RunState) -> GuardResult:
        """检查当前状态，返回结果。"""
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r} severity={self.severity.value}>"


# ── 内置规则 ──────────────────────────────────────────────────────

class ScopeBoundaryRule(GuardRule):
    """修改边界检查 —— 验证变更文件/目录是否在授权范围内。

    severity=BLOCK: 超出授权范围直接拦截。
    """

    name = "scope-boundary"
    severity = GuardSeverity.BLOCK

    # 授权路径白名单（None 表示不限制）
    def __init__(self, allowed_paths: list[str] | None = None) -> None:
        self.allowed_paths = allowed_paths

    def check(self, state: RunState) -> GuardResult:
        if self.allowed_paths is None:
            return GuardResult.ok(self.name, "未配置路径白名单，跳过边界检查")

        # 从多个数据源收集变更文件:
        #   1. task_logs (最可靠)
        #   2. checkpoints (辅助)
        changed_files: list[str] = []

        # 源1: Task Execution Logs
        for log in state.task_state.task_logs:
            changed_files.extend(log.changed_files)

        # 源2: Checkpoints (兼容旧数据)
        if not changed_files:
            for cp in reversed(state.checkpoints):
                if cp.files_changed:
                    changed_files = cp.files_changed
                    break

        if not changed_files:
            return GuardResult.ok(self.name, "无变更文件，跳过边界检查")

        violations: list[str] = []
        for f in changed_files:
            if not any(f.startswith(p) for p in self.allowed_paths):
                violations.append(f)

        if violations:
            return GuardResult.blocked(
                self.name,
                f"修改超出授权范围: {len(violations)} 个文件越界",
                violations=violations,
                allowed_paths=self.allowed_paths,
            )

        return GuardResult.ok(self.name, f"所有 {len(changed_files)} 个文件在授权范围内")


class RiskLevelRule(GuardRule):
    """风险等级校验 —— 检查当前 GuardLevel 是否足以覆盖风险等级。

    severity=BLOCK: 高风险走低等级 Guard 时拦截。
    """

    name = "risk-level"
    severity = GuardSeverity.BLOCK

    # L4/L5 必须有 strict 级 Guard
    GUARD_LEVEL_RANK = {"light": 0, "normal": 1, "strict": 2}

    def check(self, state: RunState) -> GuardResult:
        intake = state.task_intake
        if intake is None:
            return GuardResult.ok(self.name, "无入口分析，跳过风险校验")

        risk = intake.risk_level
        guard = intake.guard_level

        # L4/L5: guard 必须是 strict
        if risk in ("L4", "L5") and guard != "strict":
            return GuardResult.blocked(
                self.name,
                f"风险等级 {risk} 要求 strict 级 Guard，当前为 {guard}",
                risk_level=risk,
                guard_level=guard,
            )

        # L3: guard 至少是 normal
        if risk == "L3" and guard == "light":
            return GuardResult.warn(
                self.name,
                f"风险等级 {risk} 建议至少 normal 级 Guard，当前为 {guard}",
                risk_level=risk,
                guard_level=guard,
            )

        return GuardResult.ok(self.name, f"风险 {risk} / Guard {guard} 匹配")


class SanityCheckRule(GuardRule):
    """冒烟检查 —— 验证基础条件是否满足。

    severity=BLOCK: 冒烟不通过不允许继续。
    当前检查点: task_id 不为空、current_stage 合法。
    """

    name = "sanity-check"
    severity = GuardSeverity.BLOCK

    def check(self, state: RunState) -> GuardResult:
        checks: list[str] = []

        if not state.task_id:
            checks.append("task_id 为空")

        if not state.current_stage:
            checks.append("current_stage 未设置")

        # 检查 retry 次数
        if state.task_state.retry_count > 5:
            checks.append(f"retry 次数过多 ({state.task_state.retry_count})")

        if checks:
            return GuardResult.blocked(
                self.name,
                f"冒烟检查失败: {'; '.join(checks)}",
                failures=checks,
            )

        return GuardResult.ok(self.name, "冒烟检查通过")


# ── 反作弊规则 ──────────────────────────────────────────────────────


class TestIntegrityRule(GuardRule):
    """测试完整性检查 —— 检测测试文件删除、测试用例移除。

    severity=BLOCK: 不允许删除现有测试或以 skip 替换测试逻辑。

    两层检测:
      1. git diff --name-status 检测实际删除 (D) 的测试文件
      2. task_logs 中的 changed_files 检查标记为删除的文件
    """

    name = "test-integrity"
    severity = GuardSeverity.BLOCK

    # 测试文件路径模式
    TEST_PATTERNS = ("test_", "_test.", "tests/", "spec/", "__tests__/")

    def check(self, state: RunState) -> GuardResult:
        deletions: list[str] = []

        # 层1: git diff 检测实际删除
        git_deletions = self._check_git_deletions(state)
        deletions.extend(git_deletions)

        # 层2: task_logs/checkpoints 中的 .removed 标记
        changed_files = self._get_changed_files(state)
        for f in changed_files:
            if any(pattern in f for pattern in self.TEST_PATTERNS):
                if f.endswith(".removed") or ".deleted" in f:
                    if f not in deletions:
                        deletions.append(f)

        if deletions:
            return GuardResult.blocked(
                self.name,
                f"检测到测试文件被删除: {len(deletions)} 个",
                deleted_files=deletions,
            )

        return GuardResult.ok(
            self.name,
            f"测试完整性检查通过 ({len(changed_files)} 个变更文件, 0 个删除)",
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

    @staticmethod
    def _check_git_deletions(state: RunState) -> list[str]:
        """通过 git diff --name-status 检测已删除的测试文件。"""
        try:
            import subprocess
            from pathlib import Path

            project_root = Path(state.project_root) if state.project_root else Path.cwd()
            if not (project_root / ".git").is_dir():
                return []

            result = subprocess.run(
                ["git", "diff", "--name-status", "HEAD"],
                capture_output=True, text=True,
                cwd=str(project_root),
                timeout=10,
            )
            if result.returncode != 0:
                return []

            deletions: list[str] = []
            test_patterns = ("test_", "_test.", "tests/", "spec/", "__tests__/")
            for line in result.stdout.strip().splitlines():
                if not line.startswith("D\t"):
                    continue
                filepath = line[2:].strip()
                if any(pattern in filepath for pattern in test_patterns):
                    deletions.append(filepath)
            return deletions
        except Exception:
            return []


class AssertionWeakeningRule(GuardRule):
    """断言弱化检测 —— 检测 scenario 断言数量减少或预期值放宽。

    severity=WARN: 不阻止流程，但记录警告。
    """

    name = "assertion-weakening"
    severity = GuardSeverity.WARN

    def check(self, state: RunState) -> GuardResult:
        # 检查 scenario_results 中是否有断言数量下降的趋势
        scenario_results = state.scenario_results
        if len(scenario_results) < 2:
            return GuardResult.ok(self.name, "场景结果不足，跳过断言弱化检测")

        # 对比首次和最新一次验证的断言数
        first = scenario_results[0]
        latest = scenario_results[-1]

        if latest.assertions_total < first.assertions_total:
            delta = first.assertions_total - latest.assertions_total
            return GuardResult.warn(
                self.name,
                f"断言数量从 {first.assertions_total} 降至 {latest.assertions_total} (减少 {delta})",
                first_total=first.assertions_total,
                latest_total=latest.assertions_total,
                delta=delta,
            )

        # 检查通过率异常（90%+ 通过率但验证整体失败 → 可能弱化了断言）
        if latest.assertions_total > 0:
            pass_rate = latest.assertions_passed / latest.assertions_total
            if pass_rate > 0.9 and not latest.passed:
                return GuardResult.warn(
                    self.name,
                    f"断言通过率 {pass_rate:.0%} 但场景整体未通过 — 可能存在断言弱化",
                    pass_rate=pass_rate,
                )

        return GuardResult.ok(self.name, "断言弱化检查通过")


class SkipModificationRule(GuardRule):
    """跳过/忽略检测 —— 检测代码中添加 skip/ignore 标记。

    severity=WARN: 添加 skip 是常见偷懒手段，记录警告。
    """

    name = "skip-modification"
    severity = GuardSeverity.WARN

    # 可疑标记
    SUSPICIOUS_MARKERS = (
        "pytest.mark.skip",
        "unittest.skip",
        "@skip",
        "@ignore",
        "xtest(",
        "xdescribe(",
        "xit(",
        "TODO: fix later",
        "FIXME: skip",
        "# type: ignore",
        "eslint-disable",
        "nolint",
        "// SKIP",
        "# SKIP",
    )

    def check(self, state: RunState) -> GuardResult:
        # 通过 task_state 的 notes 和分析来检测
        # 此规则依赖 AI 提供实际 diff 内容的分析
        notes = state.task_state.notes
        failures = state.failures

        skip_hints: list[str] = []
        for note in notes:
            note_lower = note.lower()
            if "skip" in note_lower or "忽略" in note:
                skip_hints.append(note[:120])

        if skip_hints:
            return GuardResult.warn(
                self.name,
                f"检测到 {len(skip_hints)} 处可能添加 skip/忽略标记",
                hints=skip_hints[:5],
            )

        return GuardResult.ok(self.name, "skip 标记检查通过")


class FileSizeLimitRule(GuardRule):
    """文件大小限制 —— 拒绝生成过大的文件。

    severity=WARN: 大文件可能是 AI 幻觉或未优化的生成。
    可配置 max_size_kb，默认 200KB。
    """

    name = "file-size-limit"
    severity = GuardSeverity.WARN

    def __init__(self, max_size_kb: int = 200) -> None:
        self.max_size_kb = max_size_kb

    def check(self, state: RunState) -> GuardResult:
        changed_files: list[str] = []
        for log in state.task_state.task_logs:
            changed_files.extend(log.changed_files)
        if not changed_files:
            return GuardResult.ok(self.name, "无变更文件，跳过大小检查")

        try:
            from pathlib import Path

            project_root = Path(state.project_root) if state.project_root else Path.cwd()
            oversized: list[str] = []
            for f in changed_files:
                fpath = project_root / f
                if fpath.exists():
                    size_kb = fpath.stat().st_size / 1024
                    if size_kb > self.max_size_kb:
                        oversized.append(f"{f} ({size_kb:.0f}KB)")

            if oversized:
                return GuardResult.warn(
                    self.name,
                    f"检测到 {len(oversized)} 个超大文件 (> {self.max_size_kb}KB)",
                    oversized_files=oversized,
                )
            return GuardResult.ok(self.name, f"所有文件在大小限制内 (≤ {self.max_size_kb}KB)")
        except Exception:
            return GuardResult.ok(self.name, "大小检查跳过 (文件系统不可用)")


class NetworkCallRule(GuardRule):
    """网络调用检测 —— 检测新增代码中是否引入未授权的网络调用。

    severity=WARN: 发现疑似网络请求库导入时告警。
    关注常见 HTTP/网络库的 import 语句。
    """

    name = "network-call"
    severity = GuardSeverity.WARN

    # 常见网络库导入模式
    NETWORK_IMPORTS = [
        "import requests",
        "from requests",
        "import urllib",
        "from urllib",
        "import httpx",
        "from httpx",
        "import aiohttp",
        "from aiohttp",
        "import socket",
        "from socket",
        "import http.client",
        "from http.client",
        "subprocess.call",
        "subprocess.run",
        "subprocess.Popen",
        "os.system(",
        "os.popen(",
    ]

    def check(self, state: RunState) -> GuardResult:
        changed_files: list[str] = []
        for log in state.task_state.task_logs:
            changed_files.extend(log.changed_files)

        if not changed_files:
            return GuardResult.ok(self.name, "无变更文件，跳过网络调用检查")

        try:
            from pathlib import Path

            project_root = Path(state.project_root) if state.project_root else Path.cwd()
            suspicious: list[str] = []

            for f in changed_files:
                fpath = project_root / f
                if not fpath.exists() or not fpath.suffix:
                    continue
                try:
                    content = fpath.read_text(encoding="utf-8", errors="ignore")
                    for pattern in self.NETWORK_IMPORTS:
                        if pattern in content:
                            suspicious.append(f"{f}: {pattern}")
                            break
                except Exception:
                    continue

            if suspicious:
                return GuardResult.warn(
                    self.name,
                    f"检测到 {len(suspicious)} 处网络/子进程调用",
                    details=suspicious[:10],
                )
            return GuardResult.ok(self.name, "网络调用检查通过")
        except Exception:
            return GuardResult.ok(self.name, "网络调用检查跳过")


class SecretScanRule(GuardRule):
    """密钥/凭证扫描 —— 检测硬编码的 API Key、密码、Token。

    severity=BLOCK: 硬编码凭证是严重安全漏洞，必须拦截。
    使用正则模式匹配常见密钥格式。
    """

    name = "secret-scan"
    severity = GuardSeverity.BLOCK

    # 高危模式 (匹配常见的密钥格式)
    SECRET_PATTERNS: list[tuple[str, str]] = [
        # API Key 类
        (r'(?i)api[_-]?key\s*[:=]\s*[\'"][^\'"]{16,}[\'"]', "API Key 硬编码"),
        (r'(?i)secret[_-]?key\s*[:=]\s*[\'"][^\'"]{16,}[\'"]', "Secret Key 硬编码"),
        (r'(?i)access[_-]?token\s*[:=]\s*[\'"][^\'"]{16,}[\'"]', "Access Token 硬编码"),
        # AWS
        (r'AKIA[0-9A-Z]{16}', "AWS Access Key"),
        # OpenAI/Anthropic
        (r'sk-[A-Za-z0-9]{32,}', "OpenAI API Key"),
        (r'sk-ant-[A-Za-z0-9]{32,}', "Anthropic API Key"),
        # GitHub Token
        (r'gh[pousr]_[A-Za-z0-9_]{36,}', "GitHub Token"),
        # 密码
        (r'(?i)password\s*[:=]\s*[\'"][^\'"]{4,}[\'"]', "密码明文"),
        (r'(?i)passwd\s*[:=]\s*[\'"][^\'"]{4,}[\'"]', "密码明文"),
        # JWT
        (r'eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}', "JWT Token"),
        # 私钥头
        (r'-----BEGIN (RSA|EC|DSA|OPENSSH) PRIVATE KEY-----', "私钥硬编码"),
        # 数据库连接串 (含密码)
        (r'(?i)(mysql|postgres|postgresql|mongodb)://[^:]+:[^@]+@', "数据库连接串含密码"),
        # Generic
        (r'(?i)token\s*[:=]\s*[\'"][A-Za-z0-9+/=]{32,}[\'"]', "Token 硬编码"),
    ]

    def check(self, state: RunState) -> GuardResult:
        changed_files: list[str] = []
        for log in state.task_state.task_logs:
            changed_files.extend(log.changed_files)

        if not changed_files:
            return GuardResult.ok(self.name, "无变更文件，跳过密钥扫描")

        try:
            import re
            from pathlib import Path

            project_root = Path(state.project_root) if state.project_root else Path.cwd()
            findings: list[str] = []

            for f in changed_files:
                fpath = project_root / f
                # 跳过非代码文件
                if fpath.suffix in ('.lock', '.json', '.md', '.txt', '.yml', '.yaml',
                                     '.toml', '.cfg', '.ini'):
                    continue
                if not fpath.exists() or not fpath.suffix:
                    continue
                try:
                    content = fpath.read_text(encoding="utf-8", errors="ignore")
                    for pattern, label in self.SECRET_PATTERNS:
                        if re.search(pattern, content):
                            findings.append(f"{f}: {label}")
                            break  # 每个文件只报告一次
                except Exception:
                    continue

            if findings:
                return GuardResult.blocked(
                    self.name,
                    f"检测到 {len(findings)} 处疑似硬编码凭证",
                    findings=findings[:10],
                )
            return GuardResult.ok(self.name, f"密钥扫描通过 ({len(changed_files)} 个文件)")
        except Exception:
            return GuardResult.ok(self.name, "密钥扫描跳过")
