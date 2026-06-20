"""Git Worktree 隔离器（架构 §17.3）。

对于高风险 (L4/L5) 或需要隔离执行的任务，在独立 git worktree 中运行，
避免污染主工作区。完成后合并或丢弃。
"""

from __future__ import annotations

import logging
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class WorktreeResult:
    """Worktree 操作结果。"""

    success: bool
    worktree_path: str = ""
    branch_name: str = ""
    message: str = ""


class WorktreeIsolator:
    """Git Worktree 隔离器。

    用法:
        isolator = WorktreeIsolator(project_root=".")
        result = isolator.create()
        try:
            # 在 result.worktree_path 中执行任务
            ...
        finally:
            isolator.cleanup(result)
    """

    WORKTREE_DIR = ".ai/worktrees"

    def __init__(self, project_root: str | Path = ".") -> None:
        self._root = Path(project_root).resolve()
        self._available = (self._root / ".git").is_dir()

    @property
    def available(self) -> bool:
        return self._available

    def create(self, task_id: str = "") -> WorktreeResult:
        """创建隔离 worktree。

        在 .ai/worktrees/ 下创建以 task_id 命名的 worktree。
        """
        if not self._available:
            return WorktreeResult(
                success=False,
                message="非 git 仓库，无法创建 worktree",
            )

        branch = f"loop/{task_id or uuid.uuid4().hex[:8]}"
        wt_path = self._root / self.WORKTREE_DIR / (task_id or uuid.uuid4().hex[:12])

        try:
            # 确保 worktree 目录存在
            wt_path.parent.mkdir(parents=True, exist_ok=True)

            result = subprocess.run(
                ["git", "worktree", "add", str(wt_path), "-b", branch],
                capture_output=True, text=True,
                cwd=str(self._root),
                timeout=30,
            )
            if result.returncode != 0:
                return WorktreeResult(
                    success=False,
                    message=f"Git worktree 创建失败: {result.stderr.strip()}",
                )

            logger.info("Worktree created: %s (branch=%s)", wt_path, branch)
            return WorktreeResult(
                success=True,
                worktree_path=str(wt_path),
                branch_name=branch,
                message="Worktree 创建成功",
            )
        except FileNotFoundError:
            return WorktreeResult(
                success=False,
                message="git 不可用",
            )
        except subprocess.TimeoutExpired:
            return WorktreeResult(
                success=False,
                message="Git worktree 创建超时",
            )
        except Exception as exc:
            logger.warning("Worktree creation error: %s", exc)
            return WorktreeResult(
                success=False,
                message=f"Worktree 创建异常: {exc}",
            )

    def cleanup(self, result: WorktreeResult, discard_changes: bool = True) -> bool:
        """清理 worktree。

        Args:
            result: create() 返回的结果
            discard_changes: True = 丢弃所有变更，False = 先合并再清理
        """
        if not result.success or not result.worktree_path:
            return False

        wt_path = Path(result.worktree_path)
        if not wt_path.exists():
            return False

        try:
            # 先删除 worktree（git 记录层面）
            subprocess.run(
                ["git", "worktree", "remove", str(wt_path),
                 "--force" if discard_changes else ""],
                capture_output=True, text=True,
                cwd=str(self._root),
                timeout=15,
            )

            # 如果分支还在，删除它
            if result.branch_name:
                subprocess.run(
                    ["git", "branch", "-D", result.branch_name],
                    capture_output=True, text=True,
                    cwd=str(self._root),
                    timeout=10,
                )

            logger.info("Worktree cleaned up: %s", result.worktree_path)
            return True
        except Exception as exc:
            logger.warning("Worktree cleanup error: %s", exc)
            return False

    def status(self) -> dict:
        """获取当前 worktree 列表。"""
        if not self._available:
            return {"available": False, "worktrees": []}

        try:
            result = subprocess.run(
                ["git", "worktree", "list", "--porcelain"],
                capture_output=True, text=True,
                cwd=str(self._root),
                timeout=10,
            )
            return {
                "available": True,
                "raw": result.stdout,
            }
        except Exception:
            return {"available": True, "error": "无法获取 worktree 列表"}
