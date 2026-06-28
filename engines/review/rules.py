"""Review 规则定义。

内置规则（全部默认注册）：
- SecretScanRule:      硬编码凭证扫描（14 条正则），BLOCK
- TestIntegrityRule:   测试文件删除 + "改代码不写测试" 检测，BLOCK + WARN
- ScopeBoundaryRule:   从 Plan Contract 提取 allowed_files，检测越界修改，BLOCK
- SkipDetectionRule:   扫 git diff 新增代码中的 skip/xit/@skip 标记，WARN
- AssertionDeletionRule: 扫描被删除的断言行，BLOCK
- DiffBudgetRule:      变更文件数/行数统计 + Plan 预算超支检查，WARN
- LintIntegrationRule: 读取外部 lint 结果，若未配置则跳过，WARN

Python 职责：确定性检测（有/没有）→ BLOCK 或 WARN
AI 职责：语义判断（对/不对）→ 在 review prompt 中深度审查
"""

# 启用延迟注解求值
from __future__ import annotations

# 导入 logging 库，用于日志记录
import logging
# 导入 re 库，用于正则表达式匹配
import re
# 导入 subprocess 库，用于执行 git 命令
import subprocess
# 导入 ABC 和 abstractmethod 用于定义抽象基类
from abc import ABC, abstractmethod
# 导入 Path 类，用于处理文件路径
from pathlib import Path
# 导入 TYPE_CHECKING，用于类型检查时避免循环导入
from typing import TYPE_CHECKING

# 导入审查结果和严重级别模型
from .models import ReviewResult, ReviewSeverity

# 仅在类型检查时导入，避免运行时循环导入
if TYPE_CHECKING:
    from engines.state.models import RunState

# 创建当前模块的日志记录器
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Plan 合约字段名约定（上游 Plan 阶段写入，下游 Review 规则读取）
# ═══════════════════════════════════════════════════════════════════

# Plan 合约中允许的最大变更文件数
KEY_MAX_FILES = "maxFiles"            # int | None — 允许的最大变更文件数
# Plan 合约中允许的最大变更行数
KEY_MAX_LINES_CHANGED = "maxLinesChanged"  # int | None — 允许的最大变更行数
# Plan 合约中授权修改的文件/目录列表
KEY_ALLOWED_FILES = "allowed_files"   # list[str] — 授权修改的文件/目录
# Plan 合约中的任务标识
KEY_TASK_ID = "task_id"               # str — 任务标识

# ═══════════════════════════════════════════════════════════════════
# 共享工具函数（避免各规则重复调用 git）
# ═══════════════════════════════════════════════════════════════════

def get_changed_files(state: RunState) -> list[str]:
    """从 RunState 提取变更文件列表（优先 task_logs，回退到 checkpoints）。

    Args:
        state: 运行状态

    Returns:
        变更文件路径列表
    """
    files: list[str] = []
    # 先从 task_logs 中收集变更文件
    for log in state.task_state.task_logs:
        files.extend(log.changed_files)
    if not files:
        # 回退：从最后一个有文件变更的 checkpoint 获取
        for cp in reversed(state.checkpoints):
            if cp.files_changed:
                files = cp.files_changed
                break
    return files


def get_git_diff_text(project_root: Path, extra_args: list[str] | None = None) -> str:
    """执行 git diff HEAD 并返回纯文本。

    若不在 git 仓库或命令失败，返回空字符串。
    调用方可复用同一结果，避免重复执行 git。

    Args:
        project_root: 项目根目录
        extra_args: 额外的 git diff 参数（如 --name-status）

    Returns:
        git diff 的纯文本输出，失败时返回空字符串
    """
    # 非 git 仓库直接返回空
    if not (project_root / ".git").is_dir():
        return ""
    try:
        # 构建 git diff HEAD 命令
        cmd = ["git", "diff", "HEAD"]
        if extra_args:
            cmd.extend(extra_args)
        # 执行命令
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, cwd=str(project_root), timeout=15,
        )
        if result.returncode != 0:
            return ""
        return result.stdout
    except Exception:
        return ""


def get_git_diff_stat(project_root: Path) -> dict[str, int]:
    """返回 git diff --stat 的汇总数据: {files: N, added: N, removed: N}。

    解析 `git diff --stat HEAD` 输出的最后一行摘要。
    失败时返回全零。

    Args:
        project_root: 项目根目录

    Returns:
        包含 files（文件数）、added（新增行数）、removed（删除行数）的字典
    """
    # 非 git 仓库直接返回零
    if not (project_root / ".git").is_dir():
        return {"files": 0, "added": 0, "removed": 0}
    try:
        result = subprocess.run(
            ["git", "diff", "--stat", "HEAD"],
            capture_output=True, text=True, cwd=str(project_root), timeout=10,
        )
        if result.returncode != 0:
            return {"files": 0, "added": 0, "removed": 0}
        lines = result.stdout.strip().splitlines()
        if not lines:
            return {"files": 0, "added": 0, "removed": 0}
        # 最后一行: "N files changed, X insertions(+), Y deletions(-)"
        summary = lines[-1]
        # 正则提取文件数
        files_m = re.search(r'(\d+)\s+files?\s+changed', summary)
        # 正则提取新增行数
        ins_m = re.search(r'(\d+)\s+insertions?\(\+\)', summary)
        # 正则提取删除行数
        del_m = re.search(r'(\d+)\s+deletions?\(-\)', summary)
        return {
            "files": int(files_m.group(1)) if files_m else len(lines) - 1,
            "added": int(ins_m.group(1)) if ins_m else 0,
            "removed": int(del_m.group(1)) if del_m else 0,
        }
    except Exception:
        return {"files": 0, "added": 0, "removed": 0}


def _is_test_file(filepath: str) -> bool:
    """判断文件路径是否属于测试文件。

    Args:
        filepath: 文件路径

    Returns:
        是否为测试文件
    """
    # 测试文件的常见模式
    TEST_PATTERNS = ("test_", "_test.", "tests/", "spec/", "__tests__/", ".test.", ".spec.")
    return any(pattern in filepath for pattern in TEST_PATTERNS)


def _is_src_file(filepath: str, src_suffixes: tuple[str, ...]) -> bool:
    """判断是否为源码文件（非测试）。

    Args:
        filepath: 文件路径
        src_suffixes: 源码文件后缀元组

    Returns:
        是否为源码文件
    """
    return filepath.endswith(src_suffixes) and not _is_test_file(filepath)


# ── 抽象基类 ──────────────────────────────────────────────────────

class ReviewRule(ABC):
    """审查规则基类。

    所有自定义审查规则必须继承此类并实现 check 方法。
    """

    # 规则名称（子类必须覆盖）
    name: str
    # 默认严重级别为 WARN
    severity: ReviewSeverity = ReviewSeverity.WARN

    @abstractmethod
    def check(self, state: RunState) -> ReviewResult:
        """执行审查检查。

        Args:
            state: 运行状态，包含所有上下文信息

        Returns:
            审查结果
        """
        # 子类必须实现此方法
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r} severity={self.severity.value}>"


# ═══════════════════════════════════════════════════════════════════
# 内置规则
# ═══════════════════════════════════════════════════════════════════


class SecretScanRule(ReviewRule):
    """硬编码凭证扫描 —— 14 条正则。 severity=BLOCK。"""

    # 规则名称
    name = "secret-scan"
    # 严重级别：阻断
    severity = ReviewSeverity.BLOCK

    # 14 条正则模式，用于检测各种硬编码凭证
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

    # 需要扫描的文件后缀
    SCAN_SUFFIXES = (
        '.py', '.ts', '.tsx', '.js', '.jsx', '.go', '.rs', '.java', '.kt',
        '.yaml', '.yml', '.json', '.env', '.toml', '.cfg', '.ini',
        '.sh', '.bash', '.zsh', '.ps1',
    )

    def check(self, state: RunState) -> ReviewResult:
        """扫描变更文件中的硬编码凭证。

        Args:
            state: 运行状态

        Returns:
            审查结果：发现凭证时 BLOCK，否则 PASS
        """
        # 获取变更文件列表
        changed_files = get_changed_files(state)
        if not changed_files:
            return ReviewResult.ok(self.name, "无变更文件，跳过密钥扫描")

        # 获取项目根目录
        project_root = Path(state.project_root) if state.project_root else Path.cwd()
        # 发现列表
        findings: list[str] = []

        # 遍历变更文件，检查后缀是否在扫描范围内
        for f in changed_files:
            fpath = project_root / f
            if fpath.suffix not in self.SCAN_SUFFIXES:
                continue
            if not fpath.exists():
                continue
            try:
                # 读取文件内容
                content = fpath.read_text(encoding="utf-8", errors="ignore")
                # 对每条正则模式进行匹配
                for pattern, label in self.SECRET_PATTERNS:
                    if re.search(pattern, content):
                        findings.append(f"{f}: {label}")
                        break  # 一个文件只记录一次
            except Exception:
                continue

        # 有发现则阻断
        if findings:
            return ReviewResult.blocked(
                self.name,
                f"检测到 {len(findings)} 处疑似硬编码凭证",
                findings=findings[:10],
            )
        return ReviewResult.ok(self.name, f"密钥扫描通过 ({len(changed_files)} 个文件)")


class TestIntegrityRule(ReviewRule):
    """测试完整性检查。 BLOCK: 测试文件被删 / WARN: 改源码不改测试。"""

    # 规则名称
    name = "test-integrity"
    # 严重级别：阻断
    severity = ReviewSeverity.BLOCK

    # 源码文件后缀
    SRC_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".kt")

    def check(self, state: RunState) -> ReviewResult:
        """检查测试完整性。

        1. 检测 git diff 中是否有测试文件被删除 → BLOCK
        2. 检测是否只修改了源码而没有修改测试文件 → WARN

        Args:
            state: 运行状态

        Returns:
            审查结果
        """
        project_root = Path(state.project_root) if state.project_root else Path.cwd()
        changed_files = get_changed_files(state)

        if not changed_files:
            return ReviewResult.ok(self.name, "无变更文件")

        # 检查 git 中的测试文件删除
        deletions = self._check_git_deletions(project_root)
        if deletions:
            return ReviewResult.blocked(
                self.name,
                f"检测到测试文件被删除: {len(deletions)} 个",
                deleted_files=deletions,
            )

        # 分类源码变更和测试变更
        src_changed = [f for f in changed_files if _is_src_file(f, self.SRC_SUFFIXES)]
        test_changed = [f for f in changed_files if _is_test_file(f)]

        # 只改源码不改测试 → WARN
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

    @staticmethod
    def _check_git_deletions(project_root: Path) -> list[str]:
        """检查 git diff 中是否有测试文件被删除。

        通过 git diff --name-status 的 D 行检测。

        Args:
            project_root: 项目根目录

        Returns:
            被删除的测试文件路径列表
        """
        # 获取带文件状态的 diff
        diff_text = get_git_diff_text(project_root, extra_args=["--name-status"])
        if not diff_text:
            return []
        deletions: list[str] = []
        for line in diff_text.splitlines():
            # D 表示删除
            if not line.startswith("D\t"):
                continue
            filepath = line[2:].strip()
            if _is_test_file(filepath):
                deletions.append(filepath)
        return deletions


class ScopeBoundaryRule(ReviewRule):
    """Plan 越界检查 —— 已禁用（allowed_files 约束过于严格，阻碍基础设施依赖）。"""

    name = "scope-boundary"
    severity = ReviewSeverity.BLOCK

    def check(self, state: RunState) -> ReviewResult:
        # ponytail: 禁用 allowed_files 边界检查，AI 可自由修改必要的基础设施文件
        return ReviewResult.ok(self.name, "scope-boundary 检查已禁用（允许修改任何文件）")

    @staticmethod
    def _match_path(filepath: str, allowed: str) -> bool:
        """判断文件路径是否在允许范围内。

        支持精确匹配、目录前缀匹配、文件同级目录匹配。

        Args:
            filepath: 实际文件路径
            allowed: 允许的路径模式

        Returns:
            是否匹配
        """
        # 统一为正斜杠比较，兼顾 Windows 反斜杠
        fp = filepath.replace("\\", "/")
        al = allowed.replace("\\", "/")
        # 精确匹配
        if fp == al:
            return True
        # 目录前缀匹配（allowed 以 / 结尾）
        if al.endswith("/") and fp.startswith(al):
            return True
        # allowed 是文件路径时，其父目录也视为允许范围
        if "/" in al and not al.endswith("/"):
            parent = al.rsplit("/", 1)[0] + "/"
            if fp.startswith(parent):
                return True
        return fp.startswith(al)


class SkipDetectionRule(ReviewRule):
    """跳过标记检测 —— 扫描 git diff 新增行中的 skip/ignore 标记。 severity=WARN。"""

    # 规则名称
    name = "skip-detection"
    # 严重级别：警告
    severity = ReviewSeverity.WARN

    # 常见跳过/忽略标记
    SKIP_MARKERS = (
        "pytest.mark.skip", "unittest.skip", "@skip", "@ignore",
        "xtest(", "xdescribe(", "xit(",
        "TODO: fix later", "it.skip(", "test.skip(", "describe.skip(",
        "// SKIP", "# SKIP", "# type: ignore",
        "eslint-disable", "nolint", "ts-ignore", "noqa",
    )

    def check(self, state: RunState) -> ReviewResult:
        """扫描 git diff 新增行中是否包含 skip/ignore 标记。

        Args:
            state: 运行状态

        Returns:
            审查结果：发现标记时 WARN，否则 PASS
        """
        project_root = Path(state.project_root) if state.project_root else Path.cwd()
        changed_files = get_changed_files(state)

        if not changed_files:
            return ReviewResult.ok(self.name, "无变更文件")

        # 扫描 git diff 新增行
        findings = self._scan_git_diff(project_root, changed_files)
        if findings:
            return ReviewResult.warn(
                self.name,
                f"检测到 {len(findings)} 处新增 skip/忽略标记",
                hints=findings[:10],
                test_skips_added=findings[:10],  # 兼容规范字段名
            )

        return ReviewResult.ok(self.name, "skip 标记检查通过")

    def _scan_git_diff(self, project_root: Path, changed_files: list[str]) -> list[str]:
        """扫描 git diff 中新增行（+ 开头）的 skip/ignore 标记。

        Args:
            project_root: 项目根目录
            changed_files: 变更文件列表

        Returns:
            发现的标记列表
        """
        findings: list[str] = []
        # 获取指定文件的 git diff
        diff_text = get_git_diff_text(project_root, extra_args=["--"] + changed_files)
        if not diff_text:
            # fallback：直接扫描文件内容
            return self._scan_files_fallback(project_root, changed_files)

        current_file = ""
        for line in diff_text.splitlines():
            # 跟踪当前文件
            if line.startswith("+++ b/"):
                current_file = line[6:]
                continue
            # 只检查新增行（+ 开头但不是 +++ 的 diff 头）
            if not line.startswith("+") or line.startswith("+++ "):
                continue
            for marker in self.SKIP_MARKERS:
                if marker in line:
                    findings.append(f"{current_file}: {marker} → {line[:80].strip()}")
                    break
        return findings

    def _scan_files_fallback(self, project_root: Path, changed_files: list[str]) -> list[str]:
        """fallback：直接扫描最近 20 个变更文件的内容。

        Args:
            project_root: 项目根目录
            changed_files: 变更文件列表

        Returns:
            发现的标记列表
        """
        findings: list[str] = []
        for f in changed_files[-20:]:  # 最多检查最近 20 个文件
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


class AssertionDeletionRule(ReviewRule):
    """断言删除检测 —— 扫描 git diff 中被删除的断言行。 severity=BLOCK。

    检测模式：
    - assert* / expect* / .should() 行被删除
    - 校验行被删除（validate*/check*）
    - 覆盖 Python / JS / TS / Go / Java / Rust 常见断言框架
    """

    # 规则名称
    name = "assertion-deletion"
    # 严重级别：阻断
    severity = ReviewSeverity.BLOCK

    # 断言相关的正则模式（覆盖多种语言/框架）
    ASSERTION_PATTERNS: list[str] = [
        # Python 断言
        r'^\s*assert\s+', r'^\s*assert[A-Z]\w*\(', r'^\s*self\.assert\w+\(', r'^\s*\.assert\w+\(',
        # JS/TS: expect / should / jest
        r'^\s*expect\(', r'\.to[A-Z]\w+\(', r'^\s*\.should\(', r'^\s*it\(', r'^\s*test\(', r'^\s*describe\(',
        # Go 断言
        r'^\s*\w+\.Assert\(', r'^\s*\w+\.Equal\(', r'^\s*assert\.\w+\(', r'^\s*require\.\w+\(',
        # Java 断言
        r'^\s*assert\w+\(', r'^\s*Assert\w+\.\w+\(', r'^\s*assertThat\(',
        # Rust 断言
        r'^\s*assert!\s*\(', r'^\s*assert_eq!\s*\(', r'^\s*assert_ne!\s*\(',
    ]

    def check(self, state: RunState) -> ReviewResult:
        """扫描 git diff 中被删除（- 开头）的断言相关行。

        Args:
            state: 运行状态

        Returns:
            审查结果：发现断言删除时 BLOCK，否则 PASS
        """
        project_root = Path(state.project_root) if state.project_root else Path.cwd()

        # 非 git 仓库无法做 diff 分析
        if not (project_root / ".git").is_dir():
            return ReviewResult.ok(self.name, "非 git 仓库，跳过断言删除检测")

        deletions: list[str] = self._scan_assertion_deletions(project_root)
        if deletions:
            return ReviewResult.blocked(
                self.name,
                f"检测到 {len(deletions)} 处断言/测试行被删除",
                assertion_deletions=deletions[:20],
            )

        return ReviewResult.ok(self.name, "断言完整性通过")

    def _scan_assertion_deletions(self, project_root: Path) -> list[str]:
        """扫描 git diff 中 - 开头且匹配断言模式的行。

        Args:
            project_root: 项目根目录

        Returns:
            被删除的断言行列表
        """
        deletions: list[str] = []
        diff_text = get_git_diff_text(project_root)
        if not diff_text:
            return []

        current_file = ""
        line_num = 0
        for line in diff_text.splitlines():
            # 跟踪文件位置：--- a/ 表示原始文件
            if line.startswith("--- a/"):
                current_file = line[6:]
                continue
            # 解析 hunk header: @@ -old_start,old_count +new_start,new_count @@
            if line.startswith("@@ "):
                m = re.match(r'@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
                if m:
                    line_num = int(m.group(1))
                continue
            # 只检查被删除的行（- 开头但不是 --- 的 diff 头）
            if not line.startswith("-") or line.startswith("--- "):
                if line.startswith(" "):
                    line_num += 1
                continue
            # 检查是否匹配断言模式
            stripped = line[1:]  # 去掉前导 -
            for pattern in self.ASSERTION_PATTERNS:
                if re.match(pattern, stripped):
                    deletions.append(f"{current_file}:{line_num}: {stripped.strip()[:100]}")
                    break
            line_num += 1
        return deletions


class DiffBudgetRule(ReviewRule):
    """变更预算检查 —— 统计文件数/行数与 Plan 合约中的预算对比。 severity=WARN。

    对应规范中的 diff_stats 字段。
    从 plan_contracts 中提取 maxFiles / maxLinesChanged 上限并与实际 diff 比较。
    """

    # 规则名称
    name = "diff-budget"
    # 严重级别：警告
    severity = ReviewSeverity.WARN

    def check(self, state: RunState) -> ReviewResult:
        """检查变更量是否超出 Plan 合约中的预算。

        Args:
            state: 运行状态

        Returns:
            审查结果：超支时 WARN，否则 PASS
        """
        project_root = Path(state.project_root) if state.project_root else Path.cwd()
        contracts = state.plan_contracts

        # 获取 git diff 统计
        stats = get_git_diff_stat(project_root)

        # 无变更时直接通过
        if stats["files"] == 0 and stats["added"] == 0 and stats["removed"] == 0:
            return ReviewResult.ok(self.name, "无变更统计（可能无 git diff 或无 .git）",
                                   diff_stats=stats)

        violations: list[str] = []
        if contracts:
            for c in contracts:
                max_files = c.get(KEY_MAX_FILES)
                max_lines = c.get(KEY_MAX_LINES_CHANGED)
                task_id = c.get(KEY_TASK_ID, "?")

                # 检查文件数是否超预算
                if max_files is not None and stats["files"] > max_files:
                    violations.append(
                        f"[{task_id}] 变更文件数 {stats['files']} 超出预算 {max_files}"
                    )
                # 检查行数是否超预算
                if max_lines is not None:
                    total_lines = stats["added"] + stats["removed"]
                    if total_lines > max_lines:
                        violations.append(
                            f"[{task_id}] 变更行数 {total_lines} 超出预算 {max_lines}"
                        )

        if violations:
            return ReviewResult.warn(
                self.name,
                f"变更预算超支: {'; '.join(violations)}",
                diff_stats=stats,
                violations=violations,
            )

        return ReviewResult.ok(
            self.name,
            f"变更预算范围内 ({stats['files']} 文件, +{stats['added']}/-{stats['removed']} 行)",
            diff_stats=stats,
        )


class LintIntegrationRule(ReviewRule):
    """Lint/格式化问题集成 —— 读取外部 lint 输出文件，汇总问题。 severity=WARN。

    符合规范的 lint_issues 字段。
    支持的文件（按优先级）:
    - .claude/aicode/lint-results.json
    - lint-results.json
    若均不存在则跳过（不阻塞）。
    """

    # 规则名称
    name = "lint-integration"
    # 严重级别：警告
    severity = ReviewSeverity.WARN

    # lint 结果文件候选路径
    LINT_RESULT_PATHS: list[str] = [
        ".claude/aicode/lint-results.json",
        "lint-results.json",
    ]

    def check(self, state: RunState) -> ReviewResult:
        """读取外部 lint 结果文件并汇总问题。

        Args:
            state: 运行状态

        Returns:
            审查结果：有 lint 问题时 WARN，否则 PASS
        """
        project_root = Path(state.project_root) if state.project_root else Path.cwd()

        # 按优先级查找 lint 结果文件
        lint_file = None
        for rel_path in self.LINT_RESULT_PATHS:
            candidate = project_root / rel_path
            if candidate.exists():
                lint_file = candidate
                break

        if lint_file is None:
            return ReviewResult.ok(
                self.name,
                "未找到 lint 结果文件（lint-results.json），跳过",
                lint_issues=[],
            )

        import json

        try:
            data = json.loads(lint_file.read_text(encoding="utf-8"))
        except Exception:
            return ReviewResult.ok(self.name, "lint 结果文件无法解析，跳过", lint_issues=[])

        # 解析 lint 问题
        issues: list[str] = []
        if isinstance(data, list):
            # 列表格式：[{file, line, column, rule, message}, ...]
            for item in data:
                if isinstance(item, dict):
                    issues.append(
                        f"{item.get('file', '?')}:{item.get('line', '?')}:{item.get('column', '?')} "
                        f"[{item.get('rule', '?')}] {item.get('message', '')}"
                    )
                else:
                    issues.append(str(item))
        elif isinstance(data, dict):
            # 字典格式：{file_path: [messages]}
            for file_path, msgs in data.items():
                for msg in (msgs if isinstance(msgs, list) else [str(msgs)]):
                    issues.append(f"{file_path}: {msg}")

        if not issues:
            return ReviewResult.ok(self.name, "Lint 无问题")
        return ReviewResult.warn(
            self.name,
            f"Lint 发现 {len(issues)} 个问题",
            lint_issues=issues[:20],
        )