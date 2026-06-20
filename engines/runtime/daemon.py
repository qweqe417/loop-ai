"""Daemon 模式骨架（架构 §18）。

以后台守护进程模式运行，持续监听文件变更或新任务，
自动触发 Loop 执行。当前为骨架实现，提供基础框架。
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class LoopDaemon:
    """Loop Daemon —— 后台持续运行，监听任务触发。

    用法:
        daemon = LoopDaemon(project_root=".", engines_cmd="bash engines/run.sh")
        daemon.start(watch_interval=5)

    当前骨架提供:
      - 基础轮询循环
      - .ai/ 目录变更监听
      - RunSh 抽象调用
    未来扩展:
      - inotify/Watchdog 文件系统事件
      - socket/gRPC 服务
      - 多项目并发
    """

    def __init__(
        self,
        project_root: str | Path = ".",
        engines_cmd: str = "bash engines/run.sh",
    ) -> None:
        self._root = Path(project_root).resolve()
        self._engines_cmd = engines_cmd
        self._running = False
        self._task_queue: list[str] = []

    def start(self, watch_interval: float = 5.0) -> None:
        """启动 daemon 循环。

        Args:
            watch_interval: 轮询间隔（秒）
        """
        self._running = True
        logger.info("LoopDaemon started (interval=%.1fs, root=%s)", watch_interval, self._root)

        try:
            while self._running:
                # 1. 检查 .ai/ 目录下是否有新任务文件
                self._poll_for_tasks()

                # 2. 处理任务队列
                while self._task_queue and self._running:
                    task = self._task_queue.pop(0)
                    self._process_task(task)

                # 3. 检查 git 变更（仅在静默期后）
                self._check_git_changes()

                time.sleep(watch_interval)
        except KeyboardInterrupt:
            logger.info("LoopDaemon interrupted, shutting down")
        finally:
            self._running = False

    def stop(self) -> None:
        """停止 daemon。"""
        self._running = False
        logger.info("LoopDaemon stopping")

    # ── 内部方法 ──────────────────────────────────────────

    def _poll_for_tasks(self) -> None:
        """检查触发目录（.ai/tasks/）下是否有未处理的任务。"""
        tasks_dir = self._root / ".ai" / "tasks"
        if not tasks_dir.is_dir():
            return

        for task_file in sorted(tasks_dir.glob("*.json")):
            try:
                task_file.unlink()  # 取走任务
                self._task_queue.append(task_file.name)
                logger.info("Daemon: new task queued: %s", task_file.name)
            except Exception as exc:
                logger.warning("Daemon: failed to queue task %s: %s", task_file.name, exc)

    def _process_task(self, task_name: str) -> None:
        """执行单个任务。"""
        logger.info("Daemon: processing task %s", task_name)
        try:
            result = subprocess.run(
                f"{self._engines_cmd} loop full --task '{task_name}'",
                shell=True,
                capture_output=True, text=True,
                cwd=str(self._root),
                timeout=600,  # 10 分钟超时
            )
            if result.returncode != 0:
                logger.warning("Daemon: task %s failed: %s", task_name, result.stderr[:200])
            else:
                logger.info("Daemon: task %s completed", task_name)
        except subprocess.TimeoutExpired:
            logger.error("Daemon: task %s timed out", task_name)
        except Exception as exc:
            logger.error("Daemon: task %s error: %s", task_name, exc)

    def _check_git_changes(self) -> None:
        """检查 git 是否有新变更（骨架：仅记录）。"""
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True,
                cwd=str(self._root),
                timeout=10,
            )
            if result.stdout.strip():
                logger.debug("Daemon: uncommitted changes detected (%d lines)",
                             len(result.stdout.splitlines()))
        except Exception:
            pass  # 非 git 仓库，忽略
