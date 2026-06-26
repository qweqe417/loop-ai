"""Scenario Runner —— 验证场景执行引擎。

加载场景定义，按序执行步骤 + 断言，输出验证结果。
与 VerifyHandler 集成：VerifyHandler 调 ScenarioRunner，
ScenarioRunner 返回 ScenarioResult 写入 RunState。

修复循环支持：
  - 失败自动分类（TIMING / ENVIRONMENT / ASSERTION / REAL_BUG）
  - ScenarioResult.repair_context() 输出结构化修复信息供 AI REPAIR 阶段使用
  - 调用方（VerifyHandler/Loop 引擎）读取 FailureCategory 决定是否进入 REPAIR
"""

from __future__ import annotations

# 导入日志模块，用于记录执行过程
import logging
# 导入 time 模块，用于计算执行耗时
import time
# 导入 TYPE_CHECKING 常量和 Any 类型
from typing import TYPE_CHECKING, Any

# 从 assertion 模块导入断言引擎和报告
from .assertion import AssertionEngine, AssertionReport
# 从 failure_classifier 模块导入失败分类器和分类枚举
from .failure_classifier import FailureCategory, classify_failure
# 从 models 模块导入数据模型
from .models import (
    Fixture,
    SanityCheckItem,
    Scenario,
    ScenarioStep,
)
# 从 resources 模块导入资源适配器基类和默认适配器工厂
from .resources import ResourceAdapter, default_adapters
# 新适配器路径
from .adapters.base import ResourceAdapter as AdapterBase
# 从 sanity 模块导入健康检查器
from .sanity import SanityChecker

# 仅在类型检查时导入，避免循环导入
if TYPE_CHECKING:
    from engines.state.models import ScenarioResult as StateScenarioResult

# 获取当前模块的日志记录器
logger = logging.getLogger(__name__)


class ScenarioResult:
    """单个场景的执行结果（scenario 模块内部使用）。

    最终会映射到 engines.state.models.ScenarioResult。
    提供 repair_context() 方法供 AI REPAIR 阶段使用。
    """

    def __init__(
        self,
        scenario_id: str,
        name: str = "",
        passed: bool = False,
        assertions_total: int = 0,
        assertions_passed: int = 0,
        errors: list[str] | None = None,
        duration_ms: float = 0.0,
        step_results: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        failure_category: str | None = None,
        failed_assertions: list[dict[str, Any]] | None = None,
    ) -> None:
        self.scenario_id = scenario_id
        self.name = name
        self.passed = passed
        self.assertions_total = assertions_total
        self.assertions_passed = assertions_passed
        self.errors = errors or []
        self.duration_ms = duration_ms
        self.step_results = step_results or []
        self.metadata = metadata or {}
        self.failure_category = failure_category
        self.failed_assertions = failed_assertions or []

    def to_state_model(self) -> StateScenarioResult:
        """转换为 engines.state.models.ScenarioResult。"""
        from engines.state.models import ScenarioResult as StateSR

        return StateSR(
            scenario_id=self.scenario_id,
            name=self.name,
            passed=self.passed,
            assertions_total=self.assertions_total,
            assertions_passed=self.assertions_passed,
            errors=self.errors,
            metadata={
                "duration_ms": self.duration_ms,
                "step_count": len(self.step_results),
                "failure_category": self.failure_category,
                "failed_assertions": self.failed_assertions,
                **self.metadata,
            },
        )

    def repair_context(self) -> dict[str, Any]:
        """生成结构化修复上下文，供 AI REPAIR 阶段使用。

        上层（VerifyHandler / Loop 引擎）读取此字典组装修复 Prompt。
        包含：失败分类、需关注的文件、期望 vs 实际差异、日志摘要。

        Returns:
            {
                "scenario_id": str,
                "failure_category": "REAL_BUG" | "ASSERTION" | "TIMING" | "ENVIRONMENT",
                "repair_hints": [
                    {
                        "assertion_type": str,
                        "target": str,
                        "expected": ...,
                        "actual": ...,
                        "message": str,
                        "category": str,
                        "hint": str,   # 人类可读的修复方向
                    },
                    ...
                ],
                "step_errors": [...],
                "summary": str,
                "auto_fixable": bool,
            }
        """
        repair_hints: list[dict[str, Any]] = []

        for fa in self.failed_assertions:
            hint_text = self._build_repair_hint(fa)
            repair_hints.append({
                "assertion_type": fa.get("type", ""),
                "target": fa.get("target", ""),
                "expected": fa.get("expected"),
                "actual": fa.get("actual"),
                "message": fa.get("message", ""),
                "category": fa.get("failure_category", "UNKNOWN"),
                "hint": hint_text,
            })

        # 合并步骤错误中未被断言覆盖的
        for sr in self.step_results:
            if sr.get("status") == "error" and "error" in sr:
                # 避免重复
                already_covered = any(
                    sr.get("error", "") in fa.get("message", "")
                    for fa in self.failed_assertions
                )
                if not already_covered:
                    repair_hints.append({
                        "assertion_type": "step_error",
                        "target": sr.get("step", ""),
                        "expected": "success",
                        "actual": sr.get("error", ""),
                        "message": sr.get("error", ""),
                        "category": FailureCategory.ENVIRONMENT.value
                            if any(kw in str(sr.get("error", "")).lower()
                                   for kw in ("connection", "timeout", "refused"))
                            else FailureCategory.REAL_BUG.value,
                        "hint": f"步骤执行失败，检查: {sr.get('error', '')}",
                    })

        auto_fixable = self.failure_category not in (
            FailureCategory.ENVIRONMENT.value,
        ) if self.failure_category else True

        return {
            "scenario_id": self.scenario_id,
            "failure_category": self.failure_category,
            "repair_hints": repair_hints,
            "step_errors": [
                sr for sr in self.step_results if sr.get("status") == "error"
            ],
            "summary": (
                f"Scenario '{self.name}' ({self.scenario_id}): "
                f"{self.assertions_passed}/{self.assertions_total} assertions passed. "
                f"Category: {self.failure_category}. "
                f"{len(repair_hints)} hints."
            ),
            "auto_fixable": auto_fixable,
        }

    @staticmethod
    def _build_repair_hint(failed_assertion: dict[str, Any]) -> str:
        """根据失败特征生成人类可读的修复方向提示。"""
        atype = failed_assertion.get("type", "")
        expected = failed_assertion.get("expected")
        actual = failed_assertion.get("actual")
        category = failed_assertion.get("failure_category", "")

        if category == FailureCategory.TIMING.value:
            return "可能为异步未完成，建议在相关步骤后增加 wait 步骤或增加超时时间"
        elif category == FailureCategory.ENVIRONMENT.value:
            return "服务或中间件不可达，检查目标资源是否启动、网络是否可达"
        elif category == FailureCategory.ASSERTION.value:
            return f"期望值({expected})与实际值({actual})接近，可能是断言期望值写错或容忍度不够"
        elif category == FailureCategory.REAL_BUG.value:
            if atype in ("http_status", "HTTP_STATUS"):
                return f"HTTP 状态码不匹配(期望{expected}, 实际{actual})，检查路由和鉴权"
            elif atype in ("json_path", "JSON_PATH"):
                target = failed_assertion.get("target", "")
                return f"JSON 路径 $.{target} 的值不匹配(期望{expected}, 实际{actual})，检查数据处理逻辑"
            elif atype in ("db_count", "DB_COUNT", "db_query", "DB_QUERY"):
                return f"数据库查询结果不匹配(期望{expected}, 实际{actual})，检查数据写入逻辑和事务"
            elif atype in ("redis_key", "redis_value", "REDIS_KEY", "REDIS_VALUE"):
                return f"Redis 缓存值不匹配(期望{expected}, 实际{actual})，检查缓存写入/过期逻辑"
            elif atype in ("dom_visible", "dom_text", "dom_count", "dom_value"):
                return f"前端 DOM 断言失败(期望{expected}, 实际{actual})，检查渲染逻辑和状态管理"
            return f"代码逻辑错误: 期望{expected}, 实际{actual}"
        return "未知失败类型，请检查日志和 diff 定位问题"


class ScenarioReport:
    """多场景执行汇总报告。"""

    def __init__(self) -> None:
        self.results: list[ScenarioResult] = []   # 所有场景结果列表
        self.total: int = 0                       # 场景总数
        self.passed: int = 0                      # 通过数
        self.failed: int = 0                      # 失败数
        self.total_duration_ms: float = 0.0       # 总耗时（毫秒）

    def add(self, result: ScenarioResult) -> None:
        """添加单个场景结果，更新统计。

        Args:
            result: 场景执行结果
        """
        self.results.append(result)
        self.total += 1
        if result.passed:
            self.passed += 1
        else:
            self.failed += 1
        self.total_duration_ms += result.duration_ms

    @property
    def all_passed(self) -> bool:
        """是否所有场景都通过。"""
        return self.failed == 0

    def summary(self) -> str:
        """返回场景执行摘要字符串。"""
        return (
            f"Scenarios: {self.passed}/{self.total} passed, {self.failed} failed "
            f"({self.total_duration_ms:.0f}ms)"
        )


class ScenarioRunner:
    """场景执行引擎 —— 加载、运行、验证 Scenario。

    用法:
        adapter = HttpAdapter(base_url="http://localhost:3000")
        runner = ScenarioRunner(adapters={"http": adapter})

        scenario = Scenario(id="test-1", name="创建订单", steps=[...], assertions=[...])
        result = runner.run(scenario)

        # 批量执行
        report = runner.run_all([scenario1, scenario2])
    """

    def __init__(
        self,
        adapters: dict[str, ResourceAdapter] | None = None,
        sanity_checks: list[SanityCheckItem] | None = None,
        playwright_timeout: int = 30,
        registry: Any = None,  # DataSourceRegistry | None
    ) -> None:
        self._adapters = adapters or default_adapters()          # 资源适配器字典
        self._sanity_checker = SanityChecker(adapters=self._adapters)  # 健康检查器
        self._assertion_engine = AssertionEngine(
            adapters=self._adapters, registry=registry,
        )  # 断言引擎（注入 registry 用于 DB/Redis/MQ 断言）
        self._playwright_timeout = playwright_timeout               # Playwright 超时（秒）

        # 默认健康检查项（子类/调用方可覆盖）
        self.default_sanity_checks = sanity_checks or []

    # ── 公开 API ───────────────────────────────────────────────

    def run(self, scenario: Scenario) -> ScenarioResult:
        """执行单个场景。

        流程: 重置适配器 → 健康检查 → Fixture → 步骤 → 断言 → 分类 → Teardown

        Args:
            scenario: 场景定义对象

        Returns:
            ScenarioResult: 场景执行结果
        """
        start = time.perf_counter()  # 记录开始时间
        errors: list[str] = []
        step_results: list[dict[str, Any]] = []
        assertion_report: AssertionReport | None = None
        failed_assertions: list[dict[str, Any]] = []

        logger.info("Running scenario: %s (%s)", scenario.id, scenario.name)

        # 0. 注册/登录场景不需要全局 token（场景自己生成）
        saved_token = None
        http_adapter = self._adapters.get("http")
        if not getattr(scenario, 'auth_required', True):
            if http_adapter and hasattr(http_adapter, '_auth_token'):
                saved_token = http_adapter._auth_token
                http_adapter._auth_token = None

        # 0. 重置资源适配器状态（避免跨场景数据污染）
        self._reset_adapters()

        # 1. Sanity Check
        if scenario.requires:
            checks = self._build_sanity_checks(scenario.requires)
            sanity = self._sanity_checker.check(checks)
            if not sanity.all_passed and not sanity.actionable:
                if saved_token is not None:
                    http_adapter._auth_token = saved_token  # type: ignore[union-attr]
                return ScenarioResult(
                    scenario_id=scenario.id,
                    name=scenario.name,
                    passed=False,
                    failure_category=FailureCategory.ENVIRONMENT.value,
                    errors=["环境健康检查失败，需要人工介入"] + [
                        f"[{r.check_name}] {r.message}"
                        for r in sanity.results if not r.passed
                    ],
                    duration_ms=(time.perf_counter() - start) * 1000,
                    metadata={"sanity_report": sanity.model_dump()},
                )

        # 2. 执行 Fixtures（前置数据）
        try:
            fixture_errors = self._apply_fixtures(scenario.fixtures)
            if fixture_errors:
                errors.extend(fixture_errors)
        except Exception as exc:
            errors.append(f"Fixture 执行失败: {exc}")

        # 3. 执行步骤
        if not errors:
            collected_responses: dict[str, Any] = {}

            # 前端场景：批量 Playwright 执行
            ui_steps = [s for s in scenario.steps if s.type.startswith("ui_")]
            if ui_steps:
                try:
                    from .playwright_executor import PlaywrightExecutor

                    device = self._resolve_device(scenario)

                    executor = PlaywrightExecutor(
                        headless=True, timeout=self._playwright_timeout,
                    )
                    if executor.available:
                        pw_result = executor.execute_scenario(
                            [{"action": s.type, "config": s.config} for s in ui_steps],
                            device=str(device),
                        )
                        collected_responses["playwright"] = pw_result
                        for s in ui_steps:
                            step_results.append({
                                "step": s.name, "status": "ok" if "error" not in pw_result else "error",
                                "response": str(pw_result)[:200],
                            })
                        logger.info(
                            "Playwright executor: %s",
                            "OK" if "error" not in pw_result else pw_result.get("error", "FAIL"),
                        )
                    else:
                        errors.append("Playwright Skill not installed — cannot run frontend scenario")
                except Exception as exc:
                    errors.append(f"Playwright execution failed: {exc}")

            # 后端步骤：逐个执行
            for step in scenario.steps:
                if step.type.startswith("ui_"):
                    continue  # 已批量执行
                try:
                    resp = self._execute_step(step, collected_responses)
                    collected_responses[step.name] = resp
                    step_results.append({"step": step.name, "status": "ok", "response": str(resp)[:200]})
                except Exception as exc:
                    step_results.append({"step": step.name, "status": "error", "error": str(exc)})
                    errors.append(f"步骤 [{step.name}] 执行失败: {exc}")
                    break  # 步骤失败 → 后续步骤跳过

        # 4. 执行断言 + 失败分类
        assertion_report: AssertionReport | None = None
        dom_assertions_total = 0
        dom_assertions_passed = 0

        if not errors or scenario.assertions:
            # 合并顶层 HTTP 响应字段，使 HTTP_STATUS/HTTP_BODY/JSON_PATH/HEADER
            # 断言能从 responses 顶层直接读到（兼容简单场景）
            eval_responses = dict(collected_responses)
            for step_name, step_resp in collected_responses.items():
                if isinstance(step_resp, dict):
                    for key in ("status", "body", "headers"):
                        if key in step_resp and key not in eval_responses:
                            eval_responses[key] = step_resp[key]
            assertion_report = self._assertion_engine.evaluate(
                scenario, responses=eval_responses
            )
            if not assertion_report.all_passed:
                for fr in assertion_report.failed_assertions:
                    # 对每条失败断言进行分类
                    category = classify_failure(
                        expected=fr.assertion.expected,
                        actual=fr.actual,
                        error_message=fr.message,
                    )
                    type_label = getattr(fr.assertion.type, 'value', str(fr.assertion.type))
                    error_msg = (
                        f"断言失败 [{type_label}] {fr.message}: "
                        f"expected={fr.assertion.expected}, actual={fr.actual}"
                    )
                    errors.append(error_msg)
                    failed_assertions.append({
                        "type": type_label,
                        "target": fr.assertion.target,
                        "expected": fr.assertion.expected,
                        "actual": fr.actual,
                        "message": fr.message,
                        "failure_category": category.value,
                    })

            # 4b. DOM 断言（前端）—— 从增强 Scenario 的 dom_assertions 字段消费
            dom_assertions = getattr(scenario, "dom_assertions", None)
            if dom_assertions:
                pw_result = collected_responses.get("playwright", {})
                dom_snapshot = pw_result.get("dom_snapshot") if isinstance(pw_result, dict) else None
                if dom_snapshot:
                    dom_report = self._assertion_engine.evaluate_dom(dom_snapshot, dom_assertions)
                    dom_assertions_total = dom_report.total
                    dom_assertions_passed = dom_report.passed
                    if not dom_report.all_passed:
                        for fr in dom_report.failed_assertions:
                            category = classify_failure(
                                expected=getattr(fr.assertion, 'expected', None),
                                actual=fr.actual,
                                error_message=fr.message,
                            )
                            type_label = getattr(fr.assertion.type, 'value', str(fr.assertion.type))
                            error_msg = (
                                f"DOM 断言失败 [{type_label}] {fr.message}: "
                                f"expected={getattr(fr.assertion, 'expected', None)}, actual={fr.actual}"
                            )
                            errors.append(error_msg)
                            failed_assertions.append({
                                "type": type_label,
                                "target": getattr(fr.assertion, 'target', ''),
                                "expected": getattr(fr.assertion, 'expected', None),
                                "actual": fr.actual,
                                "message": fr.message,
                                "failure_category": category.value,
                            })
                else:
                    logger.warning(
                        "Scenario %s has %d dom_assertions but no dom_snapshot from Playwright",
                        scenario.id, len(dom_assertions),
                    )

        # 5. 自动清理 Fixtures — 逆序删除 insert 的种子数据
        #    步骤中通过 API 创建的数据不在此列，不会被自动删除
        try:
            ac_errors = self._auto_cleanup_fixtures(scenario.fixtures)
            for ac_err in ac_errors:
                logger.warning("Auto-cleanup: %s", ac_err)
        except Exception as exc:
            logger.warning("Auto-cleanup 异常: %s", exc)

        # 6. 显式清理 (teardown) — best-effort，失败不影响场景结果
        #    仅用于特殊场景（如恢复被修改的全局状态），不用于清理种子数据
        try:
            td_errors = self._apply_fixtures(scenario.teardown)
            for td_err in td_errors:
                logger.warning("Teardown: %s", td_err)
        except Exception as exc:
            logger.warning("Teardown 异常: %s", exc)

        elapsed = (time.perf_counter() - start) * 1000

        # 计算整体失败分类（取最严重的）
        overall_category = self._compute_overall_category(errors, failed_assertions)

        if saved_token is not None:
            http_adapter._auth_token = saved_token  # type: ignore[union-attr]

        result = ScenarioResult(
            scenario_id=scenario.id,
            name=scenario.name,
            passed=len(errors) == 0 and (assertion_report is None or assertion_report.all_passed),
            assertions_total=(assertion_report.total if assertion_report else 0) + dom_assertions_total,
            assertions_passed=(assertion_report.passed if assertion_report else 0) + dom_assertions_passed,
            errors=errors,
            duration_ms=round(elapsed, 1),
            step_results=step_results,
            failure_category=overall_category,
            failed_assertions=failed_assertions,
        )
        return result

    def run_all(self, scenarios: list[Scenario]) -> ScenarioReport:
        """批量执行场景，返回汇总报告。

        Args:
            scenarios: 场景定义列表

        Returns:
            ScenarioReport: 多场景执行汇总报告
        """
        report = ScenarioReport()
        for scenario in scenarios:
            result = self.run(scenario)
            report.add(result)
        logger.info("Batch run complete: %s", report.summary())
        return report

    # ── 内部方法 ───────────────────────────────────────────────

    @staticmethod
    def _resolve_device(scenario: Scenario) -> str:
        """从 Scenario 中解析 Playwright 设备名称。

        优先级: scenario.device.value > "pc"
        """
        device = getattr(scenario, "device", None)
        if device is not None:
            # DeviceType 枚举 → 取其 .value
            value = getattr(device, "value", None)
            if value is not None:
                return str(value)
            return str(device)
        return "pc"

    def _reset_adapters(self) -> None:
        """重置所有资源适配器的会话级状态，避免跨场景数据污染。

        对支持 clear() 的适配器（RedisAdapter、MessageQueueAdapter 等）
        调用 clear() 清空类级别共享存储。
        """
        for adapter in self._adapters.values():
            clearer = getattr(adapter, "clear", None)
            if callable(clearer):
                try:
                    clearer()
                except Exception as exc:
                    logger.warning(
                        "Failed to clear adapter %s: %s",
                        getattr(adapter, "name", type(adapter).__name__), exc,
                    )

    @staticmethod
    def _compute_overall_category(
        errors: list[str],
        failed_assertions: list[dict[str, Any]],
    ) -> str | None:
        """计算整体失败分类，取最严重的类别。

        优先级: ENVIRONMENT > REAL_BUG > ASSERTION > TIMING
        """
        if not errors and not failed_assertions:
            return None

        categories: set[str] = set()

        # 从失败断言中收集分类
        for fa in failed_assertions:
            cat = fa.get("failure_category", "")
            if cat:
                categories.add(cat)

        # 从错误消息中推断分类（未归入断言的步骤错误等）
        for err in errors:
            lower = err.lower()
            if any(kw in lower for kw in (
                "connection refused", "timed out", "timeout",
                "unreachable", "name resolution", "no route to host",
                "connection reset", "环境健康检查失败",
            )):
                categories.add(FailureCategory.ENVIRONMENT.value)

        # 按优先级选取最严重的
        priority = [
            FailureCategory.ENVIRONMENT.value,
            FailureCategory.REAL_BUG.value,
            FailureCategory.ASSERTION.value,
            FailureCategory.TIMING.value,
        ]
        for cat in priority:
            if cat in categories:
                return cat
        return FailureCategory.REAL_BUG.value

    def _build_sanity_checks(
        self, requires: list[str]
    ) -> list[SanityCheckItem]:
        """根据场景的 requires 生成健康检查项。

        Args:
            requires: 场景声明的资源需求列表

        Returns:
            list[SanityCheckItem]: 健康检查项列表
        """
        # HTTP 由 ServiceManager 负责，DB/Redis/MQ 由 DataSourceRegistry 适配器直接验证
        # 这里的 sanity check 只做外部中间件端口探测（已在 VerifyHandler 完成）
        # 场景级别的 requires 不再生成额外检查
        return self.default_sanity_checks

    def _apply_fixtures(self, fixtures: list[Fixture]) -> list[str]:
        """应用前置/后置数据。

        返回值是错误消息列表（空列表 = 全部成功）。
        调用方自行决定 setup 失败是否阻断场景执行。

        Args:
            fixtures: Fixture 列表

        Returns:
            list[str]: 错误消息列表
        """
        errors: list[str] = []
        for fixture in fixtures:
            adapter = self._adapters.get(fixture.type)  # 查找对应类型的适配器
            if adapter is None:
                msg = f"Fixture '{fixture.name}': 未找到 type={fixture.type} 的适配器"
                logger.warning(msg)
                errors.append(msg)
                continue
            result = adapter.execute(fixture.action, fixture.target, data=fixture.data)
            # 检查返回值：dict 含 "error" 键表示执行失败
            if isinstance(result, dict) and "error" in result:
                msg = f"Fixture '{fixture.name}' 执行失败: {result['error']}"
                logger.error(msg)
                errors.append(msg)
        return errors

    def _auto_cleanup_fixtures(self, fixtures: list[Fixture]) -> list[str]:
        """自动清理 Fixture 插入的种子数据（逆序删除，尊重外键依赖）。

        只清理 action=insert 的 fixture，通过 API 步骤创建的数据不受影响。
        这样 YAML teardown 无需手写种子数据清理，只需处理特殊恢复逻辑。

        Args:
            fixtures: 与 scenario.fixtures 相同的 Fixture 列表

        Returns:
            list[str]: 错误消息列表
        """
        errors: list[str] = []
        for fixture in reversed(fixtures):
            if fixture.action != "insert":
                continue
            adapter = self._adapters.get(fixture.type)
            if adapter is None:
                continue
            rows = fixture.data if isinstance(fixture.data, list) else [fixture.data]
            for record in rows:
                if not isinstance(record, dict):
                    continue
                result = adapter.execute("delete", fixture.target, data=record)
                if isinstance(result, dict) and "error" in result:
                    errors.append(
                        f"Auto-cleanup '{fixture.name}' failed: {result['error']}"
                    )
        return errors

    def _execute_step(self, step: ScenarioStep, collected_responses: dict[str, Any] | None = None) -> Any:
        """执行单个步骤，根据步骤类型路由到对应的执行逻辑。

        Args:
            step: 场景步骤定义
            collected_responses: 已收集的步骤响应数据（供 script 步骤引用）

        Returns:
            步骤执行结果（响应数据）

        Raises:
            RuntimeError: 适配器未配置或脚本执行失败
            ValueError: 未知步骤类型
        """
        if step.type == "http_call":
            # HTTP 调用步骤
            adapter = self._adapters.get("http")
            if adapter is None:
                raise RuntimeError("HttpAdapter 未配置")
            method = step.config.get("method", "GET")
            url = step.config.get("url", "")
            body = step.config.get("body")
            headers = step.config.get("headers", {})
            return adapter.execute(method, url, body=body, headers=headers)

        elif step.type == "wait":
            # 等待步骤
            duration = step.config.get("duration", 1)
            time.sleep(float(duration))
            return {"waited": duration}

        elif step.type == "setup":
            # 前置设置步骤
            fixture = Fixture(
                name=step.name,
                type=step.config.get("resource", "http"),
                action=step.config.get("action", "insert"),
                target=step.config.get("target", ""),
                data=step.config.get("data"),
            )
            self._apply_fixtures([fixture])
            return {"setup": step.name}

        elif step.type == "script":
            # 自定义脚本步骤
            code = step.config.get("code", "")
            if not code:
                logger.warning("Script step %s has no code", step.name)
                return {"script": step.name, "status": "no_code"}

            from .safe_eval import safe_exec

            try:
                namespace = safe_exec(code, responses=collected_responses or {})
            except Exception as exc:
                raise RuntimeError(f"Script step [{step.name}] failed: {exc}") from exc

            return namespace.get("result", {"script": step.name, "status": "ok"})

        else:
            raise ValueError(f"未知步骤类型: {step.type}")
