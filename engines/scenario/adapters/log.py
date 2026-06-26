"""日志适配器 —— 查询应用日志（文件 I/O）。"""

from __future__ import annotations

from typing import Any

from .base import ResourceAdapter


class LogAdapter(ResourceAdapter):
    """日志适配器 —— 搜索 / tail 应用日志文件。"""

    adapter_type = "log"
    adapter_label = "Log"
    supported_assertions = {"log_contains"}

    def __init__(self, log_file: str = "app.log") -> None:
        self._log_file = log_file

    def connect(self) -> bool:
        from pathlib import Path
        return Path(self._log_file).exists()

    def disconnect(self) -> None:
        pass

    def is_healthy(self) -> bool:
        from pathlib import Path
        return Path(self._log_file).exists()

    def execute(self, action: str, target: str, **params: Any) -> Any:
        """执行日志查询。

        Args:
            action: search / tail
            target: 搜索关键词 (search) 或忽略 (tail)
            params: file（日志文件路径）, lines（tail 行数）, max_lines（search 最大行数）

        Returns:
            dict: {"matches": int, "lines": list[str]} 或 {"error": str}
        """
        file_path = params.get("file") or self._log_file

        try:
            with open(file_path, encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
        except FileNotFoundError:
            return {"error": f"日志文件不存在: {file_path}", "lines": []}
        except Exception as exc:
            return {"error": str(exc), "lines": []}

        if action == "search":
            max_lines = int(params.get("max_lines", 500))
            matched = []
            for line in all_lines[:max_lines]:
                if target in line:
                    matched.append(line.rstrip("\n"))
            return {"matches": len(matched), "lines": matched}

        elif action == "tail":
            n = int(params.get("lines", 50))
            return {"lines": [line.rstrip("\n") for line in all_lines[-n:]]}

        else:
            return {"error": f"LogAdapter 不支持 action: {action}"}
