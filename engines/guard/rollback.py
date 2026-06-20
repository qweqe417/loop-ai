"""回滚计划生成器。

从 RunState.checkpoints 和 git diff 生成可执行回滚方案。
输出 .ai/reports/rollback.md。
"""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engines.state.models import Checkpoint, RunState

logger = logging.getLogger(__name__)


class RollbackPlan:
    """单条回滚操作。"""

    def __init__(
        self,
        step: int,
        action: str,
        target: str,
        command: str = "",
        reversible: bool = True,
        risk: str = "low",
    ) -> None:
        self.step = step
        self.action = action
        self.target = target
        self.command = command
        self.reversible = reversible
        self.risk = risk


class RollbackPlanner:
    """回滚计划生成器。

    用法:
        planner = RollbackPlanner(project_root=".")
        plan = planner.generate(state)
        planner.write(plan)
    """

    def __init__(self, project_root: str | Path = ".") -> None:
        self._root = Path(project_root)

    def generate(self, state: RunState) -> list[RollbackPlan]:
        """从 RunState 生成回滚计划。"""
        plans: list[RollbackPlan] = []
        step = 0

        # 1. Git 回滚（最优先，最安全）
        git_plan = self._git_revert_plan(state.checkpoints)
        if git_plan:
            plans.extend(git_plan)
            step = len(plans)

        # 2. 文件级回滚（从 checkpoints 的 diff_snapshot）
        step += 1
        for cp in reversed(state.checkpoints):
            if cp.files_changed:
                for f in cp.files_changed:
                    step += 1
                    plans.append(RollbackPlan(
                        step=step,
                        action="git_checkout",
                        target=f,
                        command=f"git checkout HEAD -- {f}",
                        reversible=True,
                        risk="low",
                    ))

        # 3. 数据库回滚（如果有 fixture 操作）
        step += 1
        plans.append(RollbackPlan(
            step=step,
            action="fixture_cleanup",
            target="database/redis/mq",
            command="# 运行 .ai/fixtures/ 下的 cleanup 脚本",
            reversible=True,
            risk="medium",
        ))

        # 4. 环境变量回滚
        step += 1
        plans.append(RollbackPlan(
            step=step,
            action="env_restore",
            target="environment",
            command="# 检查 .env 备份: cp .env.bak .env",
            reversible=True,
            risk="low",
        ))

        return plans

    def _git_revert_plan(self, checkpoints: list[Checkpoint]) -> list[RollbackPlan]:
        """生成 git revert 方案。"""
        plans: list[RollbackPlan] = []

        # 尝试获取最近的 git commits
        try:
            result = subprocess.run(
                ["git", "-C", str(self._root), "log", "--oneline", "-5"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                commits = result.stdout.strip().split("\n")
                for i, commit in enumerate(commits):
                    commit_hash = commit.split()[0]
                    plans.append(RollbackPlan(
                        step=i + 1,
                        action="git_revert",
                        target=commit_hash,
                        command=f"git revert --no-commit {commit_hash}",
                        reversible=True,
                        risk="low" if i < 3 else "medium",
                    ))
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            logger.debug("Git not available for rollback plan")

        return plans

    def write(self, plans: list[RollbackPlan], output_dir: str | Path | None = None) -> Path:
        """将回滚计划写入 .ai/reports/rollback.md。"""
        out_dir = Path(output_dir) if output_dir else self._root / ".ai" / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "rollback.md"

        lines: list[str] = [
            "# Rollback Plan",
            "",
            f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"> 操作总数: {len(plans)}",
            "",
            "| Step | Action | Target | Risk | Reversible | Command |",
            "|------|--------|--------|------|------------|---------|",
        ]

        for p in plans:
            reversible = "yes" if p.reversible else "no"
            lines.append(
                f"| {p.step} | {p.action} | {p.target} | {p.risk} | {reversible} | `{p.command}` |"
            )

        lines.extend([
            "",
            "## 执行步骤",
            "",
            "1. 确认当前分支和未提交更改: `git status`",
            "2. 按 Step 顺序从后往前执行回滚",
            "3. 每步执行后验证: 运行 `/aicode-verify`",
            "4. 全部完成后创建回滚 commit",
            "",
            "## 安全规则",
            "",
            "- 不回滚数据库 schema 变更（DDL）",
            "- 不回滚第三方服务状态",
            "- 回滚后必须运行完整场景验证",
        ])

        out_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Rollback plan written to %s", out_path)
        return out_path

    @staticmethod
    def generate_summary(plans: list[RollbackPlan]) -> str:
        """生成回滚计划摘要。"""
        if not plans:
            return "无回滚操作"
        actions = {}
        for p in plans:
            actions[p.action] = actions.get(p.action, 0) + 1
        parts = [f"{v}x {k}" for k, v in actions.items()]
        return f"回滚计划: {', '.join(parts)} ({len(plans)} 步)"
