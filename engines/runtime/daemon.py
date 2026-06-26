"""Daemon 模式骨架（架构 §18）。

以后台守护进程模式运行，持续监听文件变更或新任务，
自动触发 Loop 执行。当前为骨架实现，提供基础框架。
"""

# 启用 Python 3.10+ 的延迟注解求值特性
from __future__ import annotations

# 导入日志模块，用于记录守护进程运行状态
import logging
# 导入子进程模块，用于执行外部命令（如 engines/run.sh）
import subprocess
# 导入时间模块，用于轮询间隔等待
import time
# 导入 Path 类，用于处理文件系统路径
from pathlib import Path

# 获取当前模块的日志记录器
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
        # 项目根目录，解析为绝对路径
        self._root = Path(project_root).resolve()
        # 执行引擎的命令（如 bash engines/run.sh）
        self._engines_cmd = engines_cmd
        # 守护进程运行状态标志
        self._running = False
        # 任务队列，存储待处理的任务名称
        self._task_queue: list[str] = []

    def start(self, watch_interval: float = 5.0) -> None:
        """启动 daemon 循环。

        Args:
            watch_interval: 轮询间隔（秒）
        """
        # 设置运行标志为 True
        self._running = True
        # 记录启动日志
        logger.info("LoopDaemon started (interval=%.1fs, root=%s)", watch_interval, self._root)

        try:
            # 主循环：持续运行直到 _running 被设为 False
            while self._running:
                # 1. 检查 .ai/ 目录下是否有新任务文件
                self._poll_for_tasks()

                # 2. 处理任务队列中的任务
                while self._task_queue and self._running:
                    # 从队列头部取出一个任务
                    task = self._task_queue.pop(0)
                    # 执行该任务
                    self._process_task(task)

                # 3. 检查 git 变更（仅在静默期后执行）
                self._check_git_changes()

                # 等待指定的轮询间隔
                time.sleep(watch_interval)
        except KeyboardInterrupt:
            # 收到键盘中断信号，优雅关闭
            logger.info("LoopDaemon interrupted, shutting down")
        finally:
            # 确保运行标志被重置
            self._running = False

    def stop(self) -> None:
        """停止 daemon。"""
        # 设置运行标志为 False，主循环将在下次检查时退出
        self._running = False
        logger.info("LoopDaemon stopping")

    # ── 内部方法 ──────────────────────────────────────────

    def _poll_for_tasks(self) -> None:
        """检查触发目录（.ai/tasks/）下是否有未处理的任务。"""
        # 构建任务目录路径
        tasks_dir = self._root / ".ai" / "tasks"
        # 如果任务目录不存在，跳过
        if not tasks_dir.is_dir():
            return

        # 遍历任务目录下的所有 JSON 文件，按文件名排序
        for task_file in sorted(tasks_dir.glob("*.json")):
            try:
                # 删除任务文件（取走任务），防止重复处理
                task_file.unlink()
                # 将任务文件名添加到队列中
                self._task_queue.append(task_file.name)
                logger.info("Daemon: new task queued: %s", task_file.name)
            except Exception as exc:
                # 记录任务入队失败的情况
                logger.warning("Daemon: failed to queue task %s: %s", task_file.name, exc)

    def _process_task(self, task_name: str) -> None:
        """执行单个任务。"""
        logger.info("Daemon: processing task %s", task_name)
        try:
            # 通过子进程执行 engines 命令，传入任务名称参数
            result = subprocess.run(
                f"{self._engines_cmd} loop full --task '{task_name}'",
                shell=True,
                capture_output=True, text=True,
                cwd=str(self._root),
                timeout=600,  # 10 分钟超时，防止任务挂死
            )
            if result.returncode != 0:
                # 任务执行失败，记录错误输出（截取前 200 字符）
                logger.warning("Daemon: task %s failed: %s", task_name, result.stderr[:200])
            else:
                # 任务执行成功
                logger.info("Daemon: task %s completed", task_name)
        except subprocess.TimeoutExpired:
            # 任务执行超时
            logger.error("Daemon: task %s timed out", task_name)
        except Exception as exc:
            # 其他异常
            logger.error("Daemon: task %s error: %s", task_name, exc)

    def _check_git_changes(self) -> None:
        """检查 git 是否有新变更（骨架：仅记录）。"""
        try:
            # 执行 git status --porcelain 获取简洁的变更状态
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True,
                cwd=str(self._root),
                timeout=10,
            )
            if result.stdout.strip():
                # 存在未提交的变更，记录行数
                logger.debug("Daemon: uncommitted changes detected (%d lines)",
                             len(result.stdout.splitlines()))
        except Exception:
            pass  # 非 git 仓库，忽略异常