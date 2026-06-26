"""Scenario 轻量校验 —— Pydantic 格式检查 + 基本健全性。

不依赖 test_design 模块，直接校验 Scenario YAML。
"""

from __future__ import annotations

import logging
from pathlib import Path

from .models import Scenario

logger = logging.getLogger(__name__)

# ── 合法的 step type ──
VALID_STEP_TYPES = frozenset({
    "http_call", "wait", "setup", "script", "teardown",
    "ui_navigate", "ui_click", "ui_fill", "ui_select", "ui_hover", "ui_wait",
})


def validate_scenario_file(filepath: str | Path) -> dict:
    """校验单个 YAML 文件中的 Scenario。

    Args:
        filepath: YAML 文件路径

    Returns:
        {"valid": bool, "scenario": ..., "errors": [...], "warnings": [...]}
    """
    path = Path(filepath)
    errors: list[str] = []
    warnings: list[str] = []

    # 1. 文件存在
    if not path.exists():
        return {"valid": False, "errors": [f"文件不存在: {filepath}"], "warnings": []}

    # 2. YAML 解析 + Pydantic 校验
    scenario = None
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if data is None:
            errors.append("YAML 文件为空")
            return {"valid": False, "errors": errors, "warnings": warnings}
        scenario = Scenario(**data)
    except ImportError:
        errors.append("PyYAML 未安装")
        return {"valid": False, "errors": errors, "warnings": warnings}
    except Exception as exc:
        errors.append(f"Pydantic 校验失败: {exc}")
        return {"valid": False, "errors": errors, "warnings": warnings}

    # 3. 健全性检查
    _sanity_checks(scenario, errors, warnings)

    return {
        "valid": len(errors) == 0,
        "scenario": scenario,
        "errors": errors,
        "warnings": warnings,
    }


def validate_scenario_dir(dirpath: str | Path) -> list[dict]:
    """校验目录下所有 Scenario YAML 文件（递归），加跨文件 ID 去重。

    返回每个文件的结果列表。
    """
    d = Path(dirpath)
    if not d.is_dir():
        return [{"valid": False, "errors": [f"目录不存在: {dirpath}"], "warnings": []}]

    results = []
    seen_ids: dict[str, str] = {}  # scenario_id → filename

    for yf in sorted(d.rglob("*.yaml")):
        result = validate_scenario_file(yf)

        # 跨文件 ID 去重
        scenario = result.get("scenario")
        if scenario and hasattr(scenario, "id"):
            sid = scenario.id
            if sid in seen_ids:
                result.setdefault("warnings", []).append(
                    f"场景 ID '{sid}' 已在 {seen_ids[sid]} 中定义，此处重复"
                )
            else:
                seen_ids[sid] = yf.name

        results.append(result)
    return results


# ── fixture / step 合法值 ──
VALID_FIXTURE_TYPES = frozenset({"mysql", "redis", "http", "script", "mq"})

# type → 合法 operator
VALID_OPERATORS: dict[str, frozenset[str]] = {
    "http_status": frozenset({"eq", "ne"}),
    "http_body": frozenset({"contains", "not_contains", "matches"}),
    "json_path": frozenset({"eq", "ne", "gt", "lt", "gte", "lte", "contains", "exists", "not_exists"}),
    "header": frozenset({"eq", "ne", "contains", "exists", "not_exists"}),
    "db_query": frozenset({"eq", "ne", "gt", "lt", "gte", "lte", "contains", "exists", "not_exists"}),
    "db_count": frozenset({"eq", "ne", "gt", "lt", "gte", "lte"}),
    "redis_key": frozenset({"exists", "not_exists"}),
    "redis_value": frozenset({"eq", "ne", "contains"}),
    "mq_message": frozenset({"exists", "not_exists", "contains"}),
    "log_contains": frozenset({"contains", "not_contains"}),
    "script": frozenset({"eq", "ne"}),
}


def _sanity_checks(scenario: Scenario, errors: list[str], warnings: list[str]) -> None:
    """基本健全性检查。"""

    # 1. 断言不能为空
    if not scenario.assertions and not scenario.dom_assertions:
        warnings.append(f"[{scenario.id}] 没有任何断言")

    # 2. 步骤类型合法性
    for step in scenario.steps:
        if step.type not in VALID_STEP_TYPES:
            errors.append(f"[{scenario.id}] 步骤 '{step.name}' 类型 '{step.type}' 不合法")

    # 3. fixture 类型合法性
    for f in scenario.fixtures:
        if f.type not in VALID_FIXTURE_TYPES:
            errors.append(f"[{scenario.id}] fixture '{f.name}' 类型 '{f.type}' 不合法")

    # 4. 有数据变更的 fixture 必须有 teardown
    modified_targets = {f.target for f in scenario.fixtures if f.action in ("insert", "update", "upsert")}
    cleaned_targets = {t.target for t in scenario.teardown}
    missing = modified_targets - cleaned_targets
    if missing:
        warnings.append(f"[{scenario.id}] fixtures 修改了 {missing} 但没有对应的 teardown 清理")

    # 5. teardown 里清理的表应该在 fixtures 里出现过
    extra_teardown = cleaned_targets - modified_targets
    if extra_teardown:
        warnings.append(f"[{scenario.id}] teardown 清理了 {extra_teardown} 但 fixtures 未声明，可能是多余的")

    # 6. 声明了资源但没有对应断言
    if "mysql" in scenario.requires:
        has_db = any(a.type.value in ("db_query", "db_count") for a in scenario.assertions)
        if not has_db:
            warnings.append(f"[{scenario.id}] 声明了 mysql 依赖但没有 db_query/db_count 断言")

    # 7. 前端场景检查
    if scenario.scope.value in ("frontend", "fullstack"):
        ui_steps = [s for s in scenario.steps if s.type.startswith("ui_")]
        if ui_steps and not scenario.dom_assertions:
            warnings.append(f"[{scenario.id}] 有 UI 步骤但没有 dom_assertions")

    # 8. assertion operator vs type 匹配
    for a in scenario.assertions:
        allowed = VALID_OPERATORS.get(a.type.value, set())
        if allowed and a.operator.value not in allowed:
            warnings.append(
                f"[{scenario.id}] 断言 '{a.type.value}' 不支持 operator '{a.operator.value}'，"
                f"支持的: {sorted(allowed)}"
            )
