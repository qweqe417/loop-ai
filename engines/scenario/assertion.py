"""断言引擎 —— 执行 Scenario 断言，返回 detailed diff。

从 Scenario YAML 的 assertions 数组逐条执行，通过 ResourceAdapter
（HTTP/DB/Redis/MQ/Log）获取实际值，与期望值比较，生成详细差异报告。
"""

from __future__ import annotations

import logging
import re           # 正则表达式模块，用于正则匹配断言
from typing import Any

from .models import (
    Assertion,
    AssertionOperator,
    AssertionType,
    Fixture,
    Scenario,
)
from .adapters.base import ResourceAdapter

logger = logging.getLogger(__name__)

# DataSourceRegistry 类型引用（避免循环导入）
_DataSourceRegistry = None


class AssertionResult:
    """单条断言结果。"""

    def __init__(
        self,
        assertion: Assertion,
        passed: bool,
        actual: Any = None,
        message: str = "",
    ) -> None:
        self.assertion = assertion      # 断言定义
        self.passed = passed            # 是否通过
        self.actual = actual            # 实际值
        self.message = message or assertion.message  # 结果消息（优先使用传入的，否则用断言自带的）

    def __repr__(self) -> str:
        """返回结果的字符串表示，用于调试输出。"""
        status = "PASS" if self.passed else "FAIL"
        return f"<{status} {self.assertion.type.value}: {self.message}>"


class AssertionReport:
    """断言汇总报告。"""

    def __init__(self) -> None:
        self.results: list[AssertionResult] = []  # 所有断言结果
        self.total: int = 0                       # 总断言数
        self.passed: int = 0                      # 通过数
        self.failed: int = 0                      # 失败数

    def add(self, result: AssertionResult) -> None:
        """添加一条断言结果，并更新统计。

        Args:
            result: 单条断言结果
        """
        self.results.append(result)
        self.total += 1
        if result.passed:
            self.passed += 1
        else:
            self.failed += 1

    @property
    def all_passed(self) -> bool:
        """是否所有断言都通过。"""
        return self.failed == 0

    @property
    def failed_assertions(self) -> list[AssertionResult]:
        """获取所有失败的断言列表。"""
        return [r for r in self.results if not r.passed]

    def summary(self) -> str:
        """返回断言汇总摘要字符串。"""
        return f"{self.passed}/{self.total} passed, {self.failed} failed"


class AssertionEngine:
    """断言引擎 —— 执行断言并生成 diff 报告。

    用法:
        engine = AssertionEngine(adapters={"http": HttpAdapter(), ...})
        report = engine.evaluate(scenario, responses)
    """

    # DOM 断言 operator 字符串 → AssertionOperator 映射（类常量，避免每次调用重建）
    _DOM_OP_MAP: dict[str, AssertionOperator] = {
        "eq": AssertionOperator.EQ,
        "ne": AssertionOperator.NE,
        "gt": AssertionOperator.GT,
        "gte": AssertionOperator.GTE,
        "lt": AssertionOperator.LT,
        "lte": AssertionOperator.LTE,
        "contains": AssertionOperator.CONTAINS,
        "exists": AssertionOperator.EXISTS,
        "not_exists": AssertionOperator.NOT_EXISTS,
    }

    def __init__(
        self,
        adapters: dict[str, ResourceAdapter] | None = None,
        registry: Any = None,  # DataSourceRegistry | None
    ) -> None:
        self._adapters = adapters or {}  # 资源适配器字典
        self._registry = registry       # 数据源注册表（可选）

    def evaluate(
        self,
        scenario: Scenario,
        responses: dict[str, Any] | None = None,
    ) -> AssertionReport:
        """执行 scenario 中的所有断言，返回汇总报告。

        Args:
            scenario: 场景定义对象
            responses: 步骤响应数据字典

        Returns:
            AssertionReport: 断言汇总报告
        """
        report = AssertionReport()

        for assertion in scenario.assertions:
            try:
                # 逐条执行断言
                result = self._evaluate_one(assertion, responses or {})
            except Exception as exc:
                # 断言执行过程异常，记录失败
                result = AssertionResult(
                    assertion, passed=False,
                    actual=None,
                    message=f"断言执行异常: {exc}",
                )
            report.add(result)
            if not result.passed:
                # 记录失败详情
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
        """执行单条断言，根据断言类型路由到对应的处理方法。

        Args:
            assertion: 断言定义
            responses: 步骤响应数据

        Returns:
            AssertionResult: 单条断言结果
        """
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
        """HTTP 状态码断言。失败时附上响应体，供 AI 分析。"""
        actual = responses.get("status", 0)
        passed = self._compare(actual, assertion.operator, assertion.expected)
        msg = assertion.message or f"HTTP status {actual}"
        if not passed:
            body = responses.get("body")
            if body is not None:
                body_str = str(body)
                if len(body_str) > 500:
                    body_str = body_str[:500] + "..."
                msg = f"HTTP status {actual} (expected {assertion.expected}), body: {body_str}"
        return AssertionResult(assertion, passed, actual, message=msg)

    def _assert_http_body(
        self, assertion: Assertion, responses: dict[str, Any]
    ) -> AssertionResult:
        """HTTP 响应体包含断言。失败时截断长 body。"""
        body = responses.get("body", "")
        if isinstance(body, dict):
            body = str(body)
        passed = self._compare(body, assertion.operator, assertion.expected)
        actual_str = f"body[size={len(str(body))}]"
        msg = assertion.message or "HTTP body check"
        if not passed and len(str(body)) > 500:
            msg = f"{msg} (body truncated): {str(body)[:500]}..."
        return AssertionResult(assertion, passed, actual=actual_str, message=msg)

    def _assert_json_path(
        self, assertion: Assertion, responses: dict[str, Any]
    ) -> AssertionResult:
        """JSON 路径取值断言。"""
        body = responses.get("body", {})
        value = self._resolve_json_path(body, assertion.target)  # 解析 JSON 路径
        passed = self._compare(value, assertion.operator, assertion.expected)
        return AssertionResult(
            assertion, passed, actual=value,
            message=assertion.message or f"$.{assertion.target} = {value}",
        )

    def _assert_header(
        self, assertion: Assertion, responses: dict[str, Any]
    ) -> AssertionResult:
        """HTTP 响应头断言。"""
        headers = responses.get("headers", {})
        actual = headers.get(assertion.target, "")
        passed = self._compare(actual, assertion.operator, assertion.expected)
        return AssertionResult(
            assertion, passed, actual=actual,
            message=assertion.message or f"header {assertion.target}",
        )

    # ── 资源断言 (通过 DataSourceRegistry / Adapter 执行) ──────

    def _assert_db(self, assertion: Assertion) -> AssertionResult:
        """数据库查询/计数断言 —— 通过 DataSourceRegistry 查找适配器执行。"""
        adapter = self._find_adapter_for("db_query")
        if adapter is None:
            return AssertionResult(assertion, passed=False,
                message=(
                    f"数据库适配器未配置。请在 .ai/loop-config.json 的 data_sources 中"
                    f"添加 MySQL/PostgreSQL 连接配置，并确保对应 Python 驱动已安装。"
                ))
        # db_query → action="query", db_count → action="count"
        action = "count" if assertion.type.value == "db_count" else "query"
        result = adapter.execute(action, assertion.target)
        if isinstance(result, dict) and "error" in result:
            return AssertionResult(assertion, passed=False,
                message=f"数据库查询失败: {result['error']}")
        # 提取标量值：单行单列结果 [{'cnt': 1}] → 1，便于与数字期望值比较
        compare_value = self._extract_db_scalar(result)
        passed = self._compare(compare_value, assertion.operator, assertion.expected)
        return AssertionResult(
            assertion, passed, actual=result,
            message=assertion.message or f"db query: {assertion.target[:60]}",
        )

    @staticmethod
    def _extract_db_scalar(result: Any) -> Any:
        """从 db 查询结果中提取标量值用于比较。

        单行单列 → 提取唯一的值，如 [{'cnt': 1}] → 1
        空结果   → 0
        其他     → 原样返回
        """
        if isinstance(result, list):
            if len(result) == 0:
                return 0
            if len(result) == 1 and isinstance(result[0], dict):
                values = list(result[0].values())
                if len(values) == 1:
                    return values[0]
        return result

    def _assert_redis(self, assertion: Assertion) -> AssertionResult:
        """Redis 断言 —— 通过 DataSourceRegistry 查找适配器执行。"""
        adapter = self._find_adapter_for("redis_key")
        if adapter is None:
            return AssertionResult(assertion, passed=False,
                message=(
                    f"Redis 适配器未配置。请在 .ai/loop-config.json 的 data_sources 中"
                    f"添加 Redis 连接配置，并确保 redis-py 已安装。"
                ))
        # redis_key → action="exists", redis_value → action="get"
        action = "exists" if assertion.type.value == "redis_key" else "get"
        actual = adapter.execute(action, assertion.target)
        passed = self._compare(actual, assertion.operator, assertion.expected)
        return AssertionResult(
            assertion, passed, actual=actual,
            message=assertion.message or f"redis {action}: {assertion.target}",
        )

    def _assert_mq(self, assertion: Assertion) -> AssertionResult:
        """消息队列断言 —— 通过 DataSourceRegistry 查找适配器执行。"""
        adapter = self._find_adapter_for("mq_message")
        if adapter is None:
            return AssertionResult(assertion, passed=False,
                message=(
                    f"消息队列适配器未配置。请在 .ai/loop-config.json 的 data_sources 中"
                    f"添加 RabbitMQ 连接配置，并确保 pika 已安装。"
                ))
        actual = adapter.execute("peek", assertion.target)
        passed = self._compare(actual, assertion.operator, assertion.expected)
        return AssertionResult(
            assertion, passed, actual=actual,
            message=assertion.message or f"mq peek: {assertion.target}",
        )

    def _assert_log(self, assertion: Assertion) -> AssertionResult:
        """日志断言 —— 通过 LogAdapter 执行。"""
        adapter = self._find_adapter_for("log_contains")
        if adapter is None:
            # fallback: 创建默认 LogAdapter（不需要外部连接配置）
            from .adapters.log import LogAdapter
            adapter = LogAdapter()
        result = adapter.execute("search", assertion.target)
        if isinstance(result, dict) and "error" in result:
            return AssertionResult(assertion, passed=False,
                message=f"日志查询失败: {result['error']}")
        matches = result.get("matches", 0) if isinstance(result, dict) else 0
        passed = self._compare(matches, assertion.operator, assertion.expected)
        return AssertionResult(
            assertion, passed, actual=matches,
            message=assertion.message or f"log search '{assertion.target}': {matches} matches",
        )

    def _find_adapter_for(self, assertion_type: str) -> ResourceAdapter | None:
        """按断言类型查找适配器。

        优先从 DataSourceRegistry 查找，fallback 到 _adapters 字典（匹配 supported_assertions）。
        """
        if self._registry:
            adapter = self._registry.find_for_assertion(assertion_type)
            if adapter:
                return adapter
        # fallback: 遍历 _adapters，匹配 supported_assertions
        for adapter in self._adapters.values():
            if assertion_type in getattr(adapter, 'supported_assertions', set()):
                return adapter
        return None

    def _assert_script(
        self, assertion: Assertion, responses: dict[str, Any]
    ) -> AssertionResult:
        """执行自定义 Python 表达式断言（安全沙箱）。

        assertion.target 是一个 Python 表达式，可访问:
          - responses: 所有步骤的响应数据 dict（_SafeDict 代理，禁止 __dunder__）
          - r: responses 的简写别名

        表达式返回值与 assertion.expected 通过 assertion.operator 比较。

        安全说明：Scenario YAML 文件应被视为项目受信配置。
        本方法使用 safe_eval 提供纵深防御级别的沙箱保护。
        """
        from .safe_eval import safe_eval

        try:
            actual = safe_eval(assertion.target, responses=responses)
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

    # ── DOM 断言（前端）─────────────────────────────────────

    def evaluate_dom(
        self,
        dom_snapshot: dict,
        dom_assertions: list,  # list[DomAssertion]
    ) -> AssertionReport:
        """对 Playwright 返回的 accessibility tree 执行 DOM 断言。"""
        report = AssertionReport()
        for assertion in dom_assertions:
            try:
                result = self._evaluate_dom_one(assertion, dom_snapshot)
            except Exception as exc:
                result = AssertionResult(
                    assertion, False,
                    message=f"DOM 断言异常: {exc}",
                )
            report.add(result)
        return report

    def _evaluate_dom_one(self, assertion, dom_snapshot: dict) -> AssertionResult:
        atype = getattr(assertion, "type", "")
        target = getattr(assertion, "target", "")
        operator_str = getattr(assertion, "operator", "eq")
        expected = getattr(assertion, "expected", None)
        message = getattr(assertion, "message", "")

        operator = self._DOM_OP_MAP.get(operator_str, AssertionOperator.EQ)

        if atype == "dom_visible":
            found = self._find_in_snapshot(dom_snapshot, target)
            passed = found is not None
            return AssertionResult(assertion, passed, actual=found, message=message or f"{target} visible={passed}")

        elif atype == "dom_text":
            found = self._find_in_snapshot(dom_snapshot, target)
            text = found.get("name", "") if found else ""
            passed = self._compare(text, operator, expected)
            return AssertionResult(assertion, passed, actual=text, message=message or f"{target} text='{text}'")

        elif atype == "dom_count":
            count = self._count_in_snapshot(dom_snapshot, target)
            passed = self._compare(count, operator, expected)
            return AssertionResult(assertion, passed, actual=count, message=message or f"{target} count={count}")

        elif atype == "dom_value":
            found = self._find_in_snapshot(dom_snapshot, target)
            value = found.get("value", "") if found else ""
            passed = self._compare(value, operator, expected)
            return AssertionResult(assertion, passed, actual=value, message=message or f"{target} value='{value}'")

        elif atype == "dom_hidden":
            found = self._find_in_snapshot(dom_snapshot, target)
            passed = found is None
            return AssertionResult(assertion, passed, actual=found, message=message or f"{target} hidden={passed}")

        return AssertionResult(assertion, False, message=f"未知 DOM 断言类型: {atype}")

    def _find_in_snapshot(self, node: dict, selector: str) -> dict | None:
        """在 accessibility tree 中递归查找匹配元素。

        支持两种选择器格式：
          1. 简单子串匹配: "Submit" → 匹配 name/role 包含 "Submit" 的节点
          2. 结构化匹配: "role=button name=Submit" → role 包含 "button" 且 name 包含 "Submit"
             支持: role=, name=, value= (空格分隔，AND 逻辑)
        """
        if not isinstance(node, dict):
            return None

        if self._match_snapshot_node(node, selector):
            return node

        for child in node.get("children", []):
            found = self._find_in_snapshot(child, selector)
            if found:
                return found
        return None

    def _count_in_snapshot(self, node: dict, selector: str) -> int:
        """统计 accessibility tree 中匹配元素数量。"""
        if not isinstance(node, dict):
            return 0
        count = 0
        if self._match_snapshot_node(node, selector):
            count += 1
        for child in node.get("children", []):
            count += self._count_in_snapshot(child, selector)
        return count

    @staticmethod
    def _match_snapshot_node(node: dict, selector: str) -> bool:
        """判断单个 accessibility node 是否匹配选择器。

        自动检测选择器格式：
          - 包含 '=' → 结构化匹配（如 "role=button name=Submit"）
          - 否则 → 简单子串匹配（在 name 或 role 中查找）
        """
        if not isinstance(node, dict):
            return False

        name = node.get("name", "")
        role = node.get("role", "")
        value = node.get("value", "")

        # 检测结构化选择器: key=value 格式
        if "=" in selector and any(
            prefix in selector for prefix in ("role=", "name=", "value=")
        ):
            conditions = selector.split()
            for cond in conditions:
                if "=" not in cond:
                    continue
                key, _, val = cond.partition("=")
                if key == "role" and val not in str(role):
                    return False
                elif key == "name" and val not in str(name):
                    return False
                elif key == "value" and val not in str(value):
                    return False
            return True
        else:
            # 简单子串匹配
            return selector in str(name) or selector in str(role)

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
