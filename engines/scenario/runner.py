"""Scenario Runner —— 验证场景执行引擎。

加载场景定义，按序执行步骤 + 断言，输出验证结果。
与 VerifyHandler 集成：VerifyHandler 调 ScenarioRunner，
ScenarioRunner 返回 ScenarioResult 写入 RunState。
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from .assertion import AssertionEngine, AssertionReport
from .models import (
    Fixture,
    SanityCheckItem,
    Scenario,
    ScenarioStep,
)
from .resources import ResourceAdapter, default_adapters
from .sanity import SanityChecker

if TYPE_CHECKING:
    from engines.state.models import ScenarioResult as StateScenarioResult

logger = logging.getLogger(__name__)


class ScenarioResult:
    """单个场景的执行结果（scenario 模块内部使用）。

    最终会映射到 src.core.state.models.ScenarioResult。
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

    def to_state_model(self) -> StateScenarioResult:
        """转换为 src.core.state.models.ScenarioResult。"""
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
                **self.metadata,
            },
        )


class ScenarioReport:
    """多场景执行汇总报告。"""

    def __init__(self) -> None:
        self.results: list[ScenarioResult] = []
        self.total: int = 0
        self.passed: int = 0
        self.failed: int = 0
        self.total_duration_ms: float = 0.0

    def add(self, result: ScenarioResult) -> None:
        self.results.append(result)
        self.total += 1
        if result.passed:
            self.passed += 1
        else:
            self.failed += 1
        self.total_duration_ms += result.duration_ms

    @property
    def all_passed(self) -> bool:
        return self.failed == 0

    def summary(self) -> str:
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
    ) -> None:
        self._adapters = adapters or default_adapters()
        self._sanity_checker = SanityChecker(adapters=self._adapters)
        self._assertion_engine = AssertionEngine(adapters=self._adapters)

        # 默认健康检查项（子类/调用方可覆盖）
        self.default_sanity_checks = sanity_checks or []

    # ── 公开 API ───────────────────────────────────────────────

    def run(self, scenario: Scenario) -> ScenarioResult:
        """执行单个场景。"""
        start = time.perf_counter()
        errors: list[str] = []
        step_results: list[dict[str, Any]] = []
        assertion_report: AssertionReport | None = None

        logger.info("Running scenario: %s (%s)", scenario.id, scenario.name)

        # 1. Sanity Check
        if scenario.requires:
            checks = self._build_sanity_checks(scenario.requires)
            sanity = self._sanity_checker.check(checks)
            if not sanity.all_passed and not sanity.actionable:
                return ScenarioResult(
                    scenario_id=scenario.id,
                    name=scenario.name,
                    passed=False,
                    errors=["环境健康检查失败，需要人工介入"] + [
                        f"[{r.check_name}] {r.message}"
                        for r in sanity.results if not r.passed
                    ],
                    duration_ms=(time.perf_counter() - start) * 1000,
                    metadata={"sanity_report": sanity.model_dump()},
                )

        # 2. 执行 Fixtures（前置数据）
        try:
            self._apply_fixtures(scenario.fixtures)
        except Exception as exc:
            errors.append(f"Fixture 执行失败: {exc}")

        # 3. 执行步骤
        if not errors:
            collected_responses: dict[str, Any] = {}
            for step in scenario.steps:
                try:
                    resp = self._execute_step(step, collected_responses)
                    collected_responses[step.name] = resp
                    step_results.append({"step": step.name, "status": "ok", "response": str(resp)[:200]})
                except Exception as exc:
                    step_results.append({"step": step.name, "status": "error", "error": str(exc)})
                    errors.append(f"步骤 [{step.name}] 执行失败: {exc}")
                    break  # 步骤失败 → 后续步骤跳过

        # 4. 执行断言
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
                    errors.append(f"断言失败 [{fr.assertion.type.value}] {fr.message}: expected={fr.assertion.expected}, actual={fr.actual}")

        # 5. 清理 (teardown)
        try:
            self._apply_fixtures(scenario.teardown)
        except Exception as exc:
            errors.append(f"Teardown 失败: {exc}")

        elapsed = (time.perf_counter() - start) * 1000

        return ScenarioResult(
            scenario_id=scenario.id,
            name=scenario.name,
            passed=len(errors) == 0 and (assertion_report is None or assertion_report.all_passed),
            assertions_total=assertion_report.total if assertion_report else 0,
            assertions_passed=assertion_report.passed if assertion_report else 0,
            errors=errors,
            duration_ms=round(elapsed, 1),
            step_results=step_results,
        )

    def run_all(self, scenarios: list[Scenario]) -> ScenarioReport:
        """批量执行场景，返回汇总报告。"""
        report = ScenarioReport()
        for scenario in scenarios:
            result = self.run(scenario)
            report.add(result)
        logger.info("Batch run complete: %s", report.summary())
        return report

    # ── 内部方法 ───────────────────────────────────────────────

    def _build_sanity_checks(
        self, requires: list[str]
    ) -> list[SanityCheckItem]:
        """根据场景的 requires 生成健康检查项。"""
        checks: list[SanityCheckItem] = []
        for req in requires:
            if req == "http_service" and "http" in self._adapters:
                adapter = self._adapters["http"]
                checks.append(
                    SanityCheckItem(
                        name=f"http-{getattr(adapter, 'base_url', 'localhost')}",
                        resource="http",
                        target=getattr(adapter, "base_url", "http://localhost:8080"),
                    )
                )
            elif req == "mysql" and "database" in self._adapters:
                checks.append(
                    SanityCheckItem(
                        name="mysql-connection",
                        resource="mysql",
                        target=getattr(self._adapters.get("database"), "dsn", "localhost:3306"),
                    )
                )
            elif req == "redis" and "redis" in self._adapters:
                checks.append(
                    SanityCheckItem(
                        name="redis-connection",
                        resource="redis",
                        target=getattr(self._adapters.get("redis"), "url", "localhost:6379"),
                    )
                )
            elif req == "mq" and "mq" in self._adapters:
                checks.append(
                    SanityCheckItem(name="mq-connection", resource="mq", target="mq")
                )
        return checks or self.default_sanity_checks

    def _apply_fixtures(self, fixtures: list[Fixture]) -> None:
        """应用前置/后置数据。"""
        for fixture in fixtures:
            adapter = self._adapters.get(fixture.type)
            if adapter is None:
                logger.warning("No adapter for fixture type: %s", fixture.type)
                continue
            adapter.execute(fixture.action, fixture.target, data=fixture.data)

    def _execute_step(self, step: ScenarioStep, collected_responses: dict[str, Any] | None = None) -> Any:
        """执行单个步骤，返回响应数据。"""
        if step.type == "http_call":
            adapter = self._adapters.get("http")
            if adapter is None:
                raise RuntimeError("HttpAdapter 未配置")
            method = step.config.get("method", "GET")
            url = step.config.get("url", "")
            body = step.config.get("body")
            headers = step.config.get("headers", {})
            return adapter.execute(method, url, body=body, headers=headers)

        elif step.type == "wait":
            duration = step.config.get("duration", 1)
            time.sleep(float(duration))
            return {"waited": duration}

        elif step.type == "setup":
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
            code = step.config.get("code", "")
            if not code:
                logger.warning("Script step %s has no code", step.name)
                return {"script": step.name, "status": "no_code"}

            ctx = collected_responses or {}
            namespace: dict[str, Any] = {
                "responses": ctx,
                "r": ctx,
                "result": None,
                "__builtins__": {
                    "True": True, "False": False, "None": None,
                    "int": int, "float": float, "str": str, "bool": bool,
                    "list": list, "dict": dict, "tuple": tuple, "set": set,
                    "len": len, "max": max, "min": min, "sum": sum,
                    "any": any, "all": all, "sorted": sorted, "filter": filter,
                    "map": map, "zip": zip, "enumerate": enumerate,
                    "isinstance": isinstance, "type": type,
                    "range": range, "abs": abs, "round": round,
                    "json": __import__("json"),
                },
            }
            try:
                exec(code, namespace)
            except Exception as exc:
                raise RuntimeError(f"Script step [{step.name}] failed: {exc}") from exc

            return namespace.get("result", {"script": step.name, "status": "ok"})

        else:
            raise ValueError(f"未知步骤类型: {step.type}")
