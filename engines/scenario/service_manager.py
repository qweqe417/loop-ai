"""服务管理器 —— 自动启停测试服务。

从 .ai/loop-config.json 读取 services 配置，
并行启动所有服务 + 轮询健康检查。
"""

# 启用 Python 3.10+ 的延迟注解求值特性
from __future__ import annotations

# 导入 json 模块，用于解析配置文件
import json
# 导入日志模块，用于记录服务启停过程
import logging
# 导入子进程模块，用于启动和终止服务进程
import subprocess
# 导入 time 模块，用于轮询等待
import time
# 导入 urllib.request 模块，用于健康检查 HTTP 请求
import urllib.request
# 导入 Path 类，用于处理文件系统路径
from pathlib import Path
# 导入 Optional 类型
from typing import Optional

# 获取当前模块的日志记录器
logger = logging.getLogger(__name__)


class ServiceConfig:
    """单个服务的启停配置。"""

    def __init__(self, name: str, start_command: str, health_url: str,
                 startup_timeout: int = 60) -> None:
        # 服务名称
        self.name = name
        # 启动命令
        self.start_command = start_command
        # 健康检查 URL
        self.health_url = health_url
        # 启动超时时间（秒）
        self.startup_timeout = startup_timeout
        # 日志文件路径（启动后写入）
        self.log_file: str = ""


class ServiceManager:
    """多服务生命周期管理器。

    用法:
        sm = ServiceManager(project_root=".")
        if sm.load_config():
            ok, errors = sm.start_all()
            if not ok:
                print(f"Service startup failed: {errors}")
            # ... 跑测试 ...
            sm.stop_all()
    """

    def __init__(self, project_root: str | Path = ".") -> None:
        # 项目根目录
        self._root = Path(project_root)
        # 已启动的服务进程列表
        self._processes: list[subprocess.Popen] = []
        # 服务配置列表
        self._configs: list[ServiceConfig] = []
        # 日志文件句柄（用于 close）
        self._log_handles: list = []

    def load_config(self) -> bool:
        """从 loop-config.json 加载服务配置。

        支持 enabled 字段：enabled=false 的服务跳过不启动。

        Returns:
            bool: 是否成功加载配置
        """
        config_path = self._root / ".ai" / "loop-config.json"
        if not config_path.exists():
            logger.info("No .ai/loop-config.json, skip service management")
            return False

        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False

        services = config.get("services", [])
        if not services:
            return False

        for svc in services:
            # enabled=false → 跳过（微服务按需启动）
            if svc.get("enabled") is False:
                logger.info("Service [%s] disabled, skipping", svc.get("name", "?"))
                continue
            self._configs.append(ServiceConfig(
                name=svc.get("name", f"service-{len(self._configs)}"),
                start_command=svc["start"],
                health_url=svc["health"],
                startup_timeout=svc.get("startup_timeout", 60),
            ))

        if not self._configs:
            logger.info("ServiceManager: all services disabled or empty, skip")
            return False

        logger.info("ServiceManager: loaded %d service(s)", len(self._configs))
        return True

    def start_all(self) -> tuple[bool, list[str]]:
        """并行启动所有服务，轮询健康检查。

        启动前先清理占用端口的旧进程，避免端口冲突。

        Returns:
            (全部就绪, 错误列表)
        """
        if not self._configs:
            return True, []

        errors: list[str] = []

        # 启动前先杀占用端口的旧进程
        for cfg in self._configs:
            port = self._extract_port(cfg.health_url)
            if port:
                self._kill_port(port)

        # 并行启动所有服务
        # 创建日志目录
        logs_dir = self._root / ".ai" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        for cfg in self._configs:
            try:
                # 二进制模式写入，避免子进程编码与文件编码不匹配导致乱码
                # Windows 下 Maven/Java 默认输出 GBK，UTF-8 文件会乱码
                log_path = logs_dir / f"{cfg.name}.log"
                log_fh = open(str(log_path), "wb")
                self._log_handles.append(log_fh)
                cfg.log_file = str(log_path)

                # 使用 shell 执行启动命令
                # Unix: start_new_session 让 shell+子进程归入独立进程组，便于一键杀
                proc = subprocess.Popen(
                    cfg.start_command,
                    shell=True,
                    cwd=str(self._root),
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                self._processes.append(proc)
                logger.info("Service [%s] started (PID=%d, log=%s)", cfg.name, proc.pid, log_path)
            except Exception as exc:
                errors.append(f"启动失败 [{cfg.name}]: {exc}")

        if errors:
            # 有启动失败，停止所有已启动的服务并返回
            self.stop_all()
            return False, errors

        # 轮询健康检查：等待所有服务就绪
        max_timeout = max(c.startup_timeout for c in self._configs)
        deadline = time.time() + max_timeout
        ready: set[str] = set()  # 已就绪的服务名集合

        while time.time() < deadline:
            for cfg in self._configs:
                if cfg.name in ready:
                    continue  # 已就绪，跳过
                if self._health_check(cfg.health_url):
                    ready.add(cfg.name)
                    logger.info("Service [%s] healthy", cfg.name)

            if len(ready) == len(self._configs):
                # 全部就绪
                return True, []

            time.sleep(3)  # 等待 3 秒后重试

        # 超时：收集未就绪的服务
        for cfg in self._configs:
            if cfg.name not in ready:
                errors.append(
                    f"启动超时 [{cfg.name}]: {cfg.health_url} 不可达 "
                    f"(超时 {cfg.startup_timeout}s)"
                )

        return len(ready) == len(self._configs), errors

    def stop_all(self) -> None:
        """反向顺序关闭所有服务。

        shell + start_new_session 启动的进程树通过以下方式杀：
          - Windows: taskkill /F /T /PID (杀进程树)
          - Unix:    os.killpg(pgid, SIGTERM) + SIGKILL (杀进程组)
        """
        import os as _os
        import signal as _signal
        import platform as _platform
        _win = _platform.system() == "Windows"

        for proc in reversed(self._processes):
            try:
                if _win:
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                        timeout=10,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    # start_new_session=True → 进程组 pgid == proc.pid
                    try:
                        pgid = _os.getpgid(proc.pid)
                        _os.killpg(pgid, _signal.SIGTERM)
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            _os.killpg(pgid, _signal.SIGKILL)
                            proc.wait(timeout=5)
                    except (ProcessLookupError, OSError):
                        pass
            except Exception:
                pass
        self._processes.clear()

        # 兜底：按端口再清一次
        for cfg in self._configs:
            port = self._extract_port(cfg.health_url)
            if port:
                self._kill_port(port)

        # 关闭日志文件句柄
        for fh in self._log_handles:
            try:
                fh.close()
            except Exception:
                pass
        self._log_handles.clear()
        logger.info("ServiceManager: all services stopped")

    # 日志文件最大字节数（~256KB），超出时截断保留尾部
    _MAX_LOG_BYTES = 256 * 1024

    # 错误关键词，用于过滤无关日志行（中英文）
    _ERROR_KEYWORDS = (
        "exception", "error", "fail", "warn", "refused", "timeout",
        "caused by", "traceback", "trace", "at ", "fatal",
        "nullpointer", "npe",
        "失败", "异常", "错误", "超时", "拒绝",
    )

    def get_log_snippet(
        self, service_name: str, max_chars: int = 3000, errors_only: bool = True,
    ) -> str:
        """读取服务日志的关键片段（供 AI 分析用）。

        Args:
            service_name: 服务名
            max_chars: 最大字符数（避免 token 爆炸）
            errors_only: 是否只保留错误相关行

        Returns:
            过滤后的日志片段
        """
        for cfg in self._configs:
            if cfg.name == service_name and cfg.log_file:
                try:
                    log_path = Path(cfg.log_file)
                    if not log_path.exists():
                        return ""
                    # 文件过大时截断
                    self._truncate_log_if_needed(log_path)
                    raw = log_path.read_bytes()
                    content = self._decode_bytes(raw)
                    lines = content.splitlines()

                    if errors_only:
                        lines = [l for l in lines if self._is_error_line(l)]
                    if not lines:
                        # 没有匹配的错误行，回退到最后 30 行
                        lines = content.splitlines()[-30:]

                    # 从尾部累计到 max_chars
                    snippet_lines: list[str] = []
                    total = 0
                    for line in reversed(lines):
                        if total + len(line) > max_chars:
                            snippet_lines.insert(0, f"...(截断，完整日志见 .ai/logs/*.log, {len(lines)} 行匹配)")
                            break
                        snippet_lines.insert(0, line)
                        total += len(line) + 1

                    return "\n".join(snippet_lines)
                except Exception:
                    return ""
        return ""

    @classmethod
    def _is_error_line(cls, line: str) -> bool:
        """判断日志行是否与错误相关。"""
        lower = line.lower()
        return any(kw in lower for kw in cls._ERROR_KEYWORDS)

    @classmethod
    def _truncate_log_if_needed(cls, log_path: Path) -> None:
        """日志文件超过上限时，保留尾部 128KB。"""
        try:
            size = log_path.stat().st_size
            if size <= cls._MAX_LOG_BYTES:
                return
            keep = cls._MAX_LOG_BYTES // 2
            raw = log_path.read_bytes()
            # 从后往前找最近的换行符，避免截断行
            tail = raw[-keep:]
            nl = tail.find(b"\n")
            if nl > 0:
                tail = tail[nl + 1:]
            log_path.write_bytes(tail)
        except Exception:
            pass

    @staticmethod
    def _decode_bytes(raw: bytes) -> str:
        """解码日志字节流，自动处理 Windows GBK 编码。

        策略：
          1. 先尝试 UTF-8（严格模式）
          2. 失败则用 GBK
          3. 都失败用 UTF-8 + replace（至少不崩溃）
        """
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                return raw.decode("gbk")
            except UnicodeDecodeError:
                return raw.decode("utf-8", errors="replace")

    def __enter__(self):
        """上下文管理器入口：加载配置并启动所有服务。"""
        self.load_config()
        ok, errors = self.start_all()
        if not ok:
            raise RuntimeError(f"服务启动失败: {'; '.join(errors)}")
        return self

    def __exit__(self, *args):
        """上下文管理器出口：停止所有服务。"""
        self.stop_all()

    @staticmethod
    def _extract_port(health_url: str) -> int:
        """从 health URL 提取端口号。"""
        from urllib.parse import urlparse
        parsed = urlparse(health_url)
        port = parsed.port
        if port:
            return port
        if parsed.scheme == "https":
            return 443
        return 80

    @staticmethod
    def _kill_port(port: int) -> None:
        """杀掉占用指定端口的进程。

        Windows: PowerShell Get-NetTCPConnection（内置，比 netstat+for/f 可靠）
        Linux/Mac: lsof + xargs kill
        """
        import platform
        try:
            if platform.system() == "Windows":
                subprocess.run(
                    f'powershell -NoProfile -Command '
                    f'"Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue '
                    f'| ForEach-Object {{ Stop-Process -Id $_.OwningProcess -Force }}"',
                    shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
                )
            else:
                subprocess.run(
                    f"lsof -ti:{port} | xargs kill -9",
                    shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
                )
            logger.info("Killed old process on port %d", port)
        except Exception:
            pass  # 没旧进程或没权限，忽略

    @staticmethod
    def _health_check(url: str) -> bool:
        """HEAD 请求健康检查 URL。

        Args:
            url: 健康检查 URL

        Returns:
            bool: 服务是否健康
        """
        try:
            # 先尝试 HEAD 请求
            req = urllib.request.Request(url, method="HEAD")
            urllib.request.urlopen(req, timeout=5)
            return True
        except Exception:
            # HEAD 失败时尝试 GET 作为 fallback（某些服务不支持 HEAD）
            try:
                urllib.request.urlopen(url, timeout=5)
                return True
            except Exception:
                return False