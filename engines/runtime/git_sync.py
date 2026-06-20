"""Git 上游同步工具。

在 EXECUTE 前检查上游是否有新提交，自动 fetch + merge，
检测冲突并报告。
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """Git 同步结果。"""

    success: bool
    fetched: bool = False
    merged: bool = False
    behind_count: int = 0
    ahead_count: int = 0
    conflicts: list[str] = field(default_factory=list)
    upstream_branch: str = ""
    current_branch: str = ""
    message: str = ""
    synced_at: str = ""

    def __post_init__(self) -> None:
        if not self.synced_at:
            self.synced_at = datetime.now().isoformat()


class GitSyncer:
    """Git 上游同步器。

    用法:
        syncer = GitSyncer(project_root=".")
        result = syncer.sync()

        if result.conflicts:
            print(f"冲突文件: {result.conflicts}")
    """

    def __init__(self, project_root: str | Path = ".", remote: str = "origin") -> None:
        self._root = Path(project_root).resolve()
        self._remote = remote

    # ── 公开 API ───────────────────────────────────────────────

    def sync(self, branch: str | None = None, auto_merge: bool = False) -> SyncResult:
        """同步上游变更。

        Args:
            branch: 目标分支（默认当前分支的上游跟踪分支）
            auto_merge: True 时自动执行 merge（无冲突情况下）
        """
        # 1. 获取当前分支和上游信息
        current = self._current_branch()
        upstream = branch or self._upstream_branch(current)

        if not current:
            return SyncResult(success=False, message="无法获取当前分支名")

        # 2. Fetch
        try:
            result = subprocess.run(
                ["git", "-C", str(self._root), "fetch", self._remote, upstream],
                capture_output=True, text=True, timeout=30,
            )
            fetched = result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            return SyncResult(
                success=False,
                current_branch=current,
                upstream_branch=upstream,
                message=f"Fetch 失败: {exc}",
            )

        if not fetched:
            return SyncResult(
                success=False,
                current_branch=current,
                upstream_branch=upstream,
                message=f"Fetch 失败: {result.stderr.strip()[:200]}",
            )

        # 3. 检查 behind/ahead
        behind = self._count_behind(current, f"{self._remote}/{upstream}")
        ahead = self._count_ahead(current, f"{self._remote}/{upstream}")

        if behind == 0:
            return SyncResult(
                success=True,
                fetched=True,
                behind_count=0,
                ahead_count=ahead,
                current_branch=current,
                upstream_branch=upstream,
                message=f"已是最新 (ahead={ahead})",
            )

        # 4. 检查冲突
        conflicts = self._detect_conflicts(current, f"{self._remote}/{upstream}")
        if conflicts:
            return SyncResult(
                success=False,
                fetched=True,
                behind_count=behind,
                ahead_count=ahead,
                conflicts=conflicts,
                current_branch=current,
                upstream_branch=upstream,
                message=f"检测到 {len(conflicts)} 个冲突文件",
            )

        # 5. 自动合并
        if auto_merge and behind > 0 and not conflicts:
            try:
                merge_result = subprocess.run(
                    ["git", "-C", str(self._root), "merge", f"{self._remote}/{upstream}"],
                    capture_output=True, text=True, timeout=30,
                )
                merged = merge_result.returncode == 0
                return SyncResult(
                    success=merged,
                    fetched=True,
                    merged=merged,
                    behind_count=behind,
                    ahead_count=ahead,
                    current_branch=current,
                    upstream_branch=upstream,
                    message="合并成功" if merged else f"合并失败: {merge_result.stderr.strip()[:200]}",
                )
            except (subprocess.TimeoutExpired, OSError) as exc:
                return SyncResult(
                    success=False,
                    fetched=True,
                    behind_count=behind,
                    current_branch=current,
                    upstream_branch=upstream,
                    message=f"合并异常: {exc}",
                )

        return SyncResult(
            success=True,
            fetched=True,
            behind_count=behind,
            ahead_count=ahead,
            current_branch=current,
            upstream_branch=upstream,
            message=f"落后 {behind} 个提交 (需手动合并)",
        )

    def status(self) -> dict[str, object]:
        """获取简要状态。"""
        current = self._current_branch()
        upstream = self._upstream_branch(current) if current else ""
        behind = self._count_behind(current, f"{self._remote}/{upstream}") if current and upstream else -1
        ahead = self._count_ahead(current, f"{self._remote}/{upstream}") if current and upstream else -1
        conflicts = self._detect_conflicts(current, f"{self._remote}/{upstream}") if current and upstream else []
        return {
            "current_branch": current or "unknown",
            "upstream": upstream,
            "behind": behind,
            "ahead": ahead,
            "conflicts": conflicts,
            "clean": len(conflicts) == 0,
        }

    # ── 内部方法 ───────────────────────────────────────────────

    def _current_branch(self) -> str:
        try:
            result = subprocess.run(
                ["git", "-C", str(self._root), "branch", "--show-current"],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return ""

    def _upstream_branch(self, current: str) -> str:
        try:
            result = subprocess.run(
                ["git", "-C", str(self._root), "rev-parse", "--abbrev-ref", f"{current}@{{upstream}}"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                # Returns "origin/main" — extract just "main"
                parts = result.stdout.strip().split("/", 1)
                return parts[1] if len(parts) > 1 else parts[0]
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
        return "main"

    def _count_behind(self, current: str, upstream_ref: str) -> int:
        try:
            result = subprocess.run(
                ["git", "-C", str(self._root), "rev-list", "--count", f"{current}..{upstream_ref}"],
                capture_output=True, text=True, timeout=5,
            )
            return int(result.stdout.strip()) if result.returncode == 0 else -1
        except (ValueError, subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return -1

    def _count_ahead(self, current: str, upstream_ref: str) -> int:
        try:
            result = subprocess.run(
                ["git", "-C", str(self._root), "rev-list", "--count", f"{upstream_ref}..{current}"],
                capture_output=True, text=True, timeout=5,
            )
            return int(result.stdout.strip()) if result.returncode == 0 else -1
        except (ValueError, subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return -1

    def _detect_conflicts(self, current: str, upstream_ref: str) -> list[str]:
        """检测合并冲突文件列表。"""
        try:
            # 尝试 merge-tree 做干跑检测
            result = subprocess.run(
                ["git", "-C", str(self._root), "merge-tree", "--write-tree", current, upstream_ref],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                return []
            # merge-tree 失败 → 解析冲突文件名
            conflicts: list[str] = []
            for line in result.stdout.split("\n"):
                if line.startswith("CONFLICT") or "Merge conflict" in line:
                    conflicts.append(line.strip()[:120])
            return conflicts
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return []
