"""鉴权提供者 —— 从 loop-config.json 读取用户配置的 token。

用法:
    auth = AuthProvider(project_root=".")
    if auth.load_config():
        token = auth.token           # 直接拿，不登录
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class AuthProvider:
    """测试鉴权管理 —— 只读用户配置的 token，不做自动登录。"""

    def __init__(self, project_root: str | Path = ".") -> None:
        self._root = Path(project_root)
        self._token: Optional[str] = None

    def load_config(self) -> bool:
        """从 loop-config.json 读取 auth.token。"""
        config_path = self._root / ".ai" / "loop-config.json"
        if not config_path.exists():
            return False
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False
        auth = config.get("auth", {})
        self._token = auth.get("token")
        if self._token:
            logger.info("Auth: token loaded from loop-config.json")
            return True
        logger.info("Auth: no token configured — requests will not carry auth header")
        return False

    @property
    def token(self) -> Optional[str]:
        return self._token
