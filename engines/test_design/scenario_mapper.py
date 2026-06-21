"""Scenario 映射器 —— 把 TestCase 的 Action Pipeline steps 转成 Scenario。

每个 Step 直接映射为 ScenarioStep，Step.assertions 映射为 Assertion。
同时保留 TestCase.expected 中的最终断言。
"""

from __future__ import annotations

import logging
from typing import Any

from .models import TestCase

logger = logging.getLogger(__name__)

# StepAction → Scenario step type 映射
_ACTION_TYPE_MAP: dict[str, str] = {
    "ui_navigate": "script",
    "ui_click": "script",
    "ui_fill": "script",
    "ui_select": "script",
    "ui_hover": "script",
    "ui_wait": "wait",
    "api_call": "http_call",
    "db_query": "script",
    "redis_get": "script",
    "mq_check": "script",
    "log_check": "script",
    "script": "script",
}


class ScenarioMapper:
    """将 TestCase 的 Action Pipeline 映射为 Scenario 草案。"""

    def map_all(self, test_cases: list[TestCase]) -> list[dict[str, Any]]:
        scenarios = []
        skipped = 0
        for tc in test_cases:
            if not self._should_map(tc):
                skipped += 1
                continue
            try:
                scenarios.append(self.map_one(tc))
            except Exception as e:
                logger.warning("Failed to map %s: %s", tc.id, e)
                skipped += 1
        logger.info("Mapped %d scenarios, skipped %d", len(scenarios), skipped)
        return scenarios

    def map_one(self, tc: TestCase) -> dict[str, Any]:
        return {
            "id": tc.id,
            "name": tc.title,
            "description": f"覆盖 {', '.join(tc.requirement_refs)}",
            "requires": list(tc.dependencies),
            "fixtures": self._map_fixtures(tc),
            "steps": self._map_steps(tc),
            "assertions": self._map_assertions(tc),
            "teardown": self._map_teardown(tc),
            "metadata": {
                "requirement_refs": list(tc.requirement_refs),
                "source_test_case": tc.id,
                "priority": tc.priority.value,
                "risk_level": tc.risk_level.value,
                "scope": tc.scope.value,
            },
        }

    # ── 内部 ────────────────────────────────────────────────────

    def _should_map(self, tc: TestCase) -> bool:
        if not tc.automation:
            return False
        if tc.automation.candidate.value not in ("high", "medium"):
            return False
        if not tc.steps:
            return False
        return True

    def _map_fixtures(self, tc: TestCase) -> list[dict[str, Any]]:
        fixtures = []
        test_data = tc.test_data

        database = test_data.get("database", {})
        for table_name, rows in database.items():
            items = [rows] if isinstance(rows, dict) else rows
            for row in items:
                fixtures.append({
                    "name": f"{table_name}_fixture",
                    "type": "mysql",
                    "action": "insert",
                    "target": table_name,
                    "data": row,
                    "cleanup": tc.cleanup.required,
                })

        users = test_data.get("users", [])
        for user in users:
            fixtures.append({
                "name": f"user_{user.get('ref', 'unknown')}",
                "type": "http",
                "action": "set",
                "target": "auth_token",
                "data": user,
                "cleanup": True,
            })

        return fixtures

    def _map_steps(self, tc: TestCase) -> list[dict[str, Any]]:
        """将 Action Pipeline steps 直接映射为 ScenarioStep 列表。"""
        scenario_steps = []
        for step in tc.steps:
            step_type = _ACTION_TYPE_MAP.get(step.action.value, "script")
            scenario_steps.append({
                "name": step.description or f"{tc.id}: step {step.seq}",
                "type": step_type,
                "config": step.config,
            })
        return scenario_steps

    def _map_assertions(self, tc: TestCase) -> list[dict[str, Any]]:
        """汇总所有断言：steps 中的即时断言 + expected 中的最终断言。"""
        assertions = []

        # 各 step 中的断言
        for step in tc.steps:
            for sa in step.assertions:
                assertions.append({
                    "type": self._map_assertion_type(sa.type),
                    "target": sa.target,
                    "operator": sa.operator,
                    "expected": sa.expected,
                    "message": sa.message or f"{tc.id}: step {step.seq} - {sa.type}",
                })

        # expected.response
        resp = tc.expected.response
        if resp.get("status"):
            assertions.append({
                "type": "http_status",
                "target": "status",
                "operator": "eq",
                "expected": resp["status"],
                "message": f"{tc.id}: HTTP status = {resp['status']}",
            })
        for key, val in resp.get("body", {}).items():
            assertions.append({
                "type": "http_body",
                "target": f"$.{key}",
                "operator": "eq",
                "expected": val,
                "message": f"{tc.id}: body.{key} = {val}",
            })

        # expected.data_assertions
        for da in tc.expected.data_assertions:
            assertions.append({
                "type": self._map_assertion_type(da.type),
                "target": da.target,
                "operator": da.operator,
                "expected": da.expected,
                "message": da.message or f"{tc.id}: {da.type} {da.operator} {da.expected}",
            })

        # expected.dom_assertions
        for da in tc.expected.dom_assertions:
            assertions.append({
                "type": "script",
                "target": da.target,
                "operator": da.operator,
                "expected": da.expected,
                "message": da.message or f"{tc.id}: {da.type}({da.target})",
                "metadata": {"dom_assertion_type": da.type},
            })

        return assertions

    def _map_teardown(self, tc: TestCase) -> list[dict[str, Any]]:
        """根据 cleanup 策略生成清理步骤。"""
        if not tc.cleanup.required:
            return []
        if tc.cleanup.strategy == "not_required":
            return []

        teardown = []
        database = tc.test_data.get("database", {})
        for table_name in database:
            teardown.append({
                "name": f"cleanup_{table_name}",
                "type": "mysql",
                "action": "delete",
                "target": table_name,
                "data": {},
                "cleanup": False,
            })
        return teardown

    def _map_assertion_type(self, t: str) -> str:
        mapping = {
            "mysql": "db_query", "database": "db_query",
            "redis": "redis_value",
            "mq": "mq_message",
            "log": "log_contains",
            "file": "script",
            "external_api": "http_status",
            "http_status": "http_status",
            "http_body": "http_body",
            "dom_visible": "script",
            "dom_hidden": "script",
            "dom_text": "script",
            "dom_value": "script",
            "dom_attribute": "script",
            "dom_count": "script",
        }
        return mapping.get(t, "script")
