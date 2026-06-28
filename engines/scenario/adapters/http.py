"""HTTP 服务适配器 —— 调用被测服务的 API。"""

from __future__ import annotations

import json as _json
import urllib.error
import urllib.request as _request
from pathlib import Path as _Path
from typing import Any
from urllib.parse import urlparse as _urlparse

from .base import ResourceAdapter


def _read_service_base_url(project_root: str | None = None) -> str | None:
    """从项目目录的 loop-config.json 读取服务 base_url。"""
    if project_root:
        config_path = _Path(project_root) / ".ai" / "loop-config.json"
    else:
        config_path = _Path.cwd() / ".ai" / "loop-config.json"
    if not config_path.exists():
        return None
    try:
        cfg = _json.loads(config_path.read_text(encoding="utf-8"))
        services = cfg.get("services", [])
        if services and services[0].get("health"):
            parsed = _urlparse(services[0]["health"])
            return f"{parsed.scheme}://{parsed.netloc}"
    except Exception:
        pass
    return None


class HttpAdapter(ResourceAdapter):
    """HTTP 服务适配器 —— 调用被测服务的 API。"""

    adapter_type = "http"
    adapter_label = "HTTP"
    supported_assertions = {"http_status", "http_body", "json_path", "header"}

    def __init__(
        self,
        base_url: str = "",
        timeout: int = 30,
        project_root: str | None = None,
    ) -> None:
        if not base_url:
            base_url = _read_service_base_url(project_root=project_root)
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.timeout = timeout
        self._auth_token: str | None = None

    def connect(self) -> bool:
        return True

    def disconnect(self) -> None:
        pass

    def is_healthy(self) -> bool:
        try:
            _request.urlopen(f"{self.base_url}/", timeout=self.timeout)
            return True
        except Exception:
            return False

    def execute(self, action: str, target: str, **params: Any) -> Any:
        """执行 HTTP 请求。

        Args:
            action: GET / POST / PUT / DELETE / PATCH
            target: /api/xxx（接口路径）
            params: body, headers, query

        Returns:
            dict: {"status": int, "body": Any, "headers": dict, "error": str | None}
        """
        url = f"{self.base_url}{target}"
        body_data = params.get("body")
        headers = {k.lower(): v for k, v in (params.get("headers") or {}).items()}

        if self._auth_token and 'authorization' not in headers:
            headers['authorization'] = f'Bearer {self._auth_token}'
        query = params.get("query") or {}

        if query:
            from urllib.parse import urlencode
            url = f"{url}?{urlencode(query)}"

        data_bytes: bytes | None = None
        if body_data is not None:
            if isinstance(body_data, (dict, list)):
                data_bytes = _json.dumps(body_data, ensure_ascii=False).encode("utf-8")
                headers.setdefault("content-type", "application/json")
            elif isinstance(body_data, bytes):
                data_bytes = body_data
            else:
                data_bytes = str(body_data).encode("utf-8")

        method = action.upper()
        req = _request.Request(url, data=data_bytes, method=method)
        for k, v in headers.items():
            req.add_header(k, v)

        try:
            with _request.urlopen(req, timeout=self.timeout) as resp:
                raw_body = resp.read()
                status = resp.status
                resp_headers = dict(resp.headers.items())
        except urllib.error.HTTPError as exc:
            raw_body = exc.read()
            status = exc.code
            resp_headers = dict(exc.headers.items())
        except urllib.error.URLError as exc:
            return {"status": 0, "body": None, "headers": {}, "error": str(exc.reason)}

        content_type = resp_headers.get("content-type", resp_headers.get("Content-Type", ""))
        parsed_body: Any = raw_body.decode("utf-8", errors="replace")
        if "json" in content_type and raw_body:
            try:
                parsed_body = _json.loads(raw_body)
            except _json.JSONDecodeError:
                pass

        return {"status": status, "body": parsed_body, "headers": resp_headers}
