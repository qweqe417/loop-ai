"""断言引擎。

将 Scenario 中定义的断言逐条执行，判断通过或失败。
支持 HTTP / DB / Redis / MQ / 日志等多种断言类型。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .models import (
    Assertion,
    AssertionOperator,
    AssertionType,
    Fixture,
    Scenario,
)
from .resources import ResourceAdapter

logger = logging.getLogger(__name__)


class AssertionResult:
    """单条断言执行结果。"""

    def __init__(
        self,
        assertion: Assertion,
        passed: bool,
        actual: Any = None,
        message: str = "",
    ) -> None:
        self.assertion = assertion
        self.passed = passed
        self.actual = actual
        self.message = message or assertion.message

    def __repr__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return f"<{status} {self.assertion.type.value}: {self.message}>"


class AssertionReport:
    """断言执行汇总。"""

    def __init__(self) -> None:
        self.results: list[AssertionResult] = []
        self.total: int = 0
        self.passed: int = 0
        self.failed: int = 0

    def add(self, result: AssertionResult) -> None:
        self.results.append(result)
        self.total += 1
        if result.passed:
            self.passed += 1
        else:
            self.failed += 1

    @property
    def all_passed(self) -> bool:
        return self.failed == 0

    @property
    def failed_assertions(self) -> list[AssertionResult]:
        return [r for r in self.results if not r.passed]

    def summary(self) -> str:
        return f"{self.passed}/{self.total} passed, {self.failed} failed"


class AssertionEngine:
    """断言引擎 —— 对实际响应/数据执行断言判断。

    用法:
        engine = AssertionEngine(adapters={"http": HttpAdapter(), ...})
        report = engine.evaluate(scenario, response_data={"status": 200, "body": {...}})
    """

    def __init__(
        self,
        adapters: dict[str, ResourceAdapter] | None = None,
    ) -> None:
        self._adapters = adapters or {}

    def evaluate(
        self,
        scenario: Scenario,
        responses: dict[str, Any] | None = None,
    ) -> AssertionReport:
        """执行 scenario 中的所有断言，返回汇总报告。"""
        report = AssertionReport()

        for assertion in scenario.assertions:
            try:
                result = self._evaluate_one(assertion, responses or {})
            except Exception as exc:
                result = AssertionResult(
                    assertion, passed=False,
                    actual=None,
                    message=f"断言执行异常: {exc}",
                )
            report.add(result)
            if not result.passed:
                logger.warning(
                    "Assertion FAILED [%s]: %s (expected=%s, actual=%s)",
                    assertion.type.value,
                    result.message,
                    assertion.expected,
                    result.actual,
                )
            else:
                logger.debug("Assertion PASSED [%s]: %s", assertion.type.value, result.message)

        return report

    def _evaluate_one(
        self, assertion: Assertion, responses: dict[str, Any]
    ) -> AssertionResult:
        """执行单条断言，路由到对应的处理方法。"""
        atype = assertion.type

        if atype == AssertionType.HTTP_STATUS:
            return self._assert_http_status(assertion, responses)
        elif atype == AssertionType.HTTP_BODY:
            return self._assert_http_body(assertion, responses)
        elif atype == AssertionType.JSON_PATH:
            return self._assert_json_path(assertion, responses)
        elif atype == AssertionType.HEADER:
            return self._assert_header(assertion, responses)
        elif atype in (AssertionType.DB_QUERY, AssertionType.DB_COUNT):
            return self._assert_db(assertion)
        elif atype in (AssertionType.REDIS_KEY, AssertionType.REDIS_VALUE):
            return self._assert_redis(assertion)
        elif atype == AssertionType.MQ_MESSAGE:
            return self._assert_mq(assertion)
        elif atype == AssertionType.LOG_CONTAINS:
            return self._assert_log(assertion)
        elif atype == AssertionType.SCRIPT:
            return self._assert_script(assertion, responses)
        else:
            return AssertionResult(assertion, False, message=f"未知断言类型: {atype.value}")

    # ── HTTP 断言 ────────────────────────────────────────────

    def _assert_http_status(
        self, assertion: Assertion, responses: dict[str, Any]
    ) -> AssertionResult:
        actual = responses.get("status", 0)
        passed = self._compare(actual, assertion.operator, assertion.expected)
        return AssertionResult(
            assertion, passed, actual,
            message=assertion.message or f"HTTP status {actual}",
        )

    def _assert_http_body(
        self, assertion: Assertion, responses: dict[str, Any]
    ) -> AssertionResult:
        body = responses.get("body", "")
        if isinstance(body, dict):
            body = str(body)
        passed = self._compare(body, assertion.operator, assertion.expected)
        return AssertionResult(
            assertion, passed, actual=f"body[size={len(str(body))}]",
            message=assertion.message or "HTTP body check",
        )

    def _assert_json_path(
        self, assertion: Assertion, responses: dict[str, Any]
    ) -> AssertionResult:
        body = responses.get("body", {})
        value = self._resolve_json_path(body, assertion.target)
        passed = self._compare(value, assertion.operator, assertion.expected)
        return AssertionResult(
            assertion, passed, actual=value,
            message=assertion.message or f"$.{assertion.target} = {value}",
        )

    def _assert_header(
        self, assertion: Assertion, responses: dict[str, Any]
    ) -> AssertionResult:
        headers = responses.get("headers", {})
        actual = headers.get(assertion.target, "")
        passed = self._compare(actual, assertion.operator, assertion.expected)
        return AssertionResult(
            assertion, passed, actual=actual,
            message=assertion.message or f"header {assertion.target}",
        )

    # ── 资源断言 (委托给 ResourceAdapter) ─────────────────────

    def _assert_db(self, assertion: Assertion) -> AssertionResult:
        adapter = self._adapters.get("database")
        if adapter is None:
            return AssertionResult(assertion, False, message="DatabaseAdapter 未配置")
        try:
            action = "count" if assertion.type == AssertionType.DB_COUNT else "query"
            actual = adapter.execute(action, assertion.target)
            passed = self._compare(actual, assertion.operator, assertion.expected)
            return AssertionResult(assertion, passed, actual=actual)
        except NotImplementedError:
            return AssertionResult(assertion, passed=False, message="DatabaseAdapter 未实现")
        except Exception as exc:
            return AssertionResult(assertion, False, message=f"DB 断言异常: {exc}")

    def _assert_redis(self, assertion: Assertion) -> AssertionResult:
        adapter = self._adapters.get("redis")
        if adapter is None:
            return AssertionResult(assertion, False, message="RedisAdapter 未配置")
        try:
            action = "get" if assertion.type == AssertionType.REDIS_VALUE else "exists"
            actual = adapter.execute(action, assertion.target)
            passed = self._compare(actual, assertion.operator, assertion.expected)
            return AssertionResult(assertion, passed, actual=actual)
        except NotImplementedError:
            return AssertionResult(assertion, passed=False, message="RedisAdapter 未实现")
        except Exception as exc:
            return AssertionResult(assertion, False, message=f"Redis 断言异常: {exc}")

    def _assert_mq(self, assertion: Assertion) -> AssertionResult:
        adapter = self._adapters.get("mq")
        if adapter is None:
            return AssertionResult(assertion, False, message="MessageQueueAdapter 未配置")
        try:
            actual = adapter.execute("peek", assertion.target)
            passed = self._compare(actual, assertion.operator, assertion.expected)
            return AssertionResult(assertion, passed, actual=actual)
        except NotImplementedError:
            return AssertionResult(assertion, passed=False, message="MessageQueueAdapter 未实现")
        except Exception as exc:
            return AssertionResult(assertion, False, message=f"MQ 断言异常: {exc}")

    def _assert_log(self, assertion: Assertion) -> AssertionResult:
        adapter = self._adapters.get("log")
        if adapter is None:
            return AssertionResult(assertion, False, message="LogAdapter 未配置")
        try:
            actual = adapter.execute("search", assertion.target)
            passed = self._compare(actual, assertion.operator, assertion.expected)
            return AssertionResult(assertion, passed, actual=actual)
        except NotImplementedError:
            return AssertionResult(assertion, passed=False, message="LogAdapter 未实现")
        except Exception as exc:
            return AssertionResult(assertion, False, message=f"日志断言异常: {exc}")

    def _assert_script(
        self, assertion: Assertion, responses: dict[str, Any]
    ) -> AssertionResult:
        """执行自定义 Python 表达式断言。

        assertion.target 是一个 Python 表达式，可访问:
          - responses: 所有步骤的响应数据 dict
          - r: responses 的简写别名

        表达式返回值与 assertion.expected 通过 assertion.operator 比较。
        """
        import json as _json

        namespace: dict[str, Any] = {
            "responses": responses,
            "r": responses,
            "json": _json,
            "__builtins__": {
                "True": True, "False": False, "None": None,
                "int": int, "float": float, "str": str, "bool": bool,
                "list": list, "dict": dict, "tuple": tuple, "set": set,
                "len": len, "max": max, "min": min, "sum": sum,
                "any": any, "all": all, "sorted": sorted, "filter": filter,
                "map": map, "zip": zip, "enumerate": enumerate,
                "isinstance": isinstance, "type": type,
                "range": range, "abs": abs, "round": round,
                "str": str, "int": int, "float": float,
            },
        }
        try:
            actual = eval(assertion.target, namespace)
        except Exception as exc:
            return AssertionResult(
                assertion, passed=False,
                message=f"脚本执行异常: {exc}",
            )

        passed = self._compare(actual, assertion.operator, assertion.expected)
        return AssertionResult(
            assertion, passed, actual=actual,
            message=assertion.message or f"script: {assertion.target[:60]} -> {actual}",
        )

    # ── 工具方法 ─────────────────────────────────────────────

    @staticmethod
    def _compare(actual: Any, operator: AssertionOperator, expected: Any) -> bool:
        """执行比较运算。"""
        if operator == AssertionOperator.EQ:
            return actual == expected
        elif operator == AssertionOperator.NE:
            return actual != expected
        elif operator == AssertionOperator.GT:
            return float(actual) > float(expected)  # type: ignore[arg-type]
        elif operator == AssertionOperator.LT:
            return float(actual) < float(expected)  # type: ignore[arg-type]
        elif operator == AssertionOperator.GTE:
            return float(actual) >= float(expected)  # type: ignore[arg-type]
        elif operator == AssertionOperator.LTE:
            return float(actual) <= float(expected)  # type: ignore[arg-type]
        elif operator == AssertionOperator.CONTAINS:
            return str(expected) in str(actual)
        elif operator == AssertionOperator.NOT_CONTAINS:
            return str(expected) not in str(actual)
        elif operator == AssertionOperator.MATCHES:
            return bool(re.search(str(expected), str(actual)))
        elif operator == AssertionOperator.EXISTS:
            return actual is not None
        elif operator == AssertionOperator.NOT_EXISTS:
            return actual is None
        elif operator == AssertionOperator.EMPTY:
            return not bool(actual)
        elif operator == AssertionOperator.NOT_EMPTY:
            return bool(actual)
        return False

    @staticmethod
    def _resolve_json_path(data: Any, path: str) -> Any:
        """简单的 JSON 路径解析（后续可替换为 jsonpath-ng）。"""
        if not path:
            return data
        parts = path.lstrip("$").lstrip(".").split(".")
        current = data
        for part in parts:
            if part == "":
                continue
            # 处理数组索引: items[0]
            if "[" in part and part.endswith("]"):
                key, idx_str = part.split("[", 1)
                idx = int(idx_str.rstrip("]"))
                if key:
                    current = current.get(key, {})
                if isinstance(current, list) and 0 <= idx < len(current):
                    current = current[idx]
                else:
                    return None
            elif isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current
