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


def compute_coverage_matrix(scenarios_dir: str | Path, spec_file: str | Path | None = None) -> dict:
    """计算需求覆盖矩阵。

    Args:
        scenarios_dir: .ai/scenarios/<feature>/ 目录
        spec_file: 可选，docs/spec/<feature>.md，传入则解析需求项并匹配

    Returns:
        {
            "total": int,
            "covered": int,
            "uncovered": [{"scenario_id": ..., "requirement_refs": [...]}],
            "matrix": [{"requirement": str, "scenarios": [str], "covered": bool}],
            "uncovered_reqs": [str],
        }
    """
    d = Path(scenarios_dir)
    if not d.is_dir():
        return {"error": f"目录不存在: {scenarios_dir}", "total": 0, "covered": 0, "uncovered": [], "matrix": [], "uncovered_reqs": []}

    # 收集所有 scenario 的 requirement_refs
    all_requirements: dict[str, list[str]] = {}  # req_id → [scenario_id, ...]
    all_scenarios: list[str] = []

    for yf in sorted(d.rglob("*.yaml")):
        try:
            import yaml
            data = yaml.safe_load(yf.read_text(encoding="utf-8")) or {}
            sid = data.get("id", yf.stem)
            all_scenarios.append(sid)
            refs = data.get("metadata", {}).get("requirement_refs", []) if isinstance(data, dict) else []
            for ref in refs:
                all_requirements.setdefault(ref, []).append(sid)
        except Exception:
            pass

    # 解析 spec 文件（如果有）
    spec_requirements: list[dict] = []
    if spec_file:
        spec_path = Path(spec_file)
        if spec_path.exists():
            content = spec_path.read_text(encoding="utf-8")
            # 简单解析 REQ-XXX 格式的需求项
            import re
            for line in content.splitlines():
                m = re.match(r'(REQ-\d+)\s+(.+)', line.strip())
                if m:
                    spec_requirements.append({"id": m.group(1), "name": m.group(2).strip()})

    # 构建矩阵
    matrix: list[dict] = []
    all_reqs = set(all_requirements.keys())
    if spec_requirements:
        for req in spec_requirements:
            rid = req["id"]
            scenarios = all_requirements.get(rid, [])
            matrix.append({
                "requirement": f"{rid} {req['name']}",
                "scenarios": scenarios,
                "covered": rid in all_requirements,
            })
            if rid not in all_requirements:
                all_reqs.discard(rid)  # spec 有但 scenario 没覆盖
    else:
        # 无 spec 时，只列出 scenario 的 requirement_refs
        for req, scens in all_requirements.items():
            matrix.append({
                "requirement": req,
                "scenarios": scens,
                "covered": True,
            })

    uncovered = [{"requirement": r, "scenarios": all_requirements.get(r, [])} for r in sorted(all_reqs) if r not in all_requirements]

    return {
        "total": len(all_reqs),
        "covered": len(all_reqs) - len(uncovered),
        "uncovered": uncovered,
        "matrix": matrix,
        "uncovered_reqs": [u["requirement"] for u in uncovered],
    }


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

    # 9. mysql insert/update fixture 数据完整性检查
    _check_fixture_completeness(scenario, warnings)


# ── 常见 DB 表必须有这些列的启发式规则 ──
_REQUIRED_COLUMN_HINTS: dict[str, list[str]] = {
    # 通用审计列（大部分业务表都有）
    "*": ["id"],  # 主键 —— 如果 fixture data 里没 id 且表无 AUTO_INCREMENT，插入会失败
}

# 已知的表 → 已知必需列（无 DEFAULT 的 NOT NULL 列）
_KNOWN_TABLE_REQUIRED_COLS: dict[str, list[str]] = {}

_FIXTURE_MIN_FIELDS = 3  # insert fixture 少于这个字段数 → 警告


def _check_fixture_completeness(scenario: Scenario, warnings: list[str]) -> None:
    """检查 mysql insert/update fixture 的数据完整性。

    核心思路：fixture data 字段过少（< 3）时发出警告，提示 AI 可能没查表结构。
    这不是精确校验（需要 DB 连接），而是启发式保护。
    """
    for f in scenario.fixtures:
        if f.type != "mysql" or f.action not in ("insert", "update"):
            continue
        data = f.data
        if isinstance(data, list):
            for i, row in enumerate(data):
                if isinstance(row, dict) and len(row) < _FIXTURE_MIN_FIELDS:
                    warnings.append(
                        f"[{scenario.id}] fixture '{f.name}'[{i}] 只有 {len(row)} 个字段（< {_FIXTURE_MIN_FIELDS}），"
                        f"可能遗漏了 NOT NULL 列。请用 data query --source main_db --target \"SHOW COLUMNS FROM {f.target}\" 确认表结构后补全"
                    )
        elif isinstance(data, dict):
            if len(data) < _FIXTURE_MIN_FIELDS:
                warnings.append(
                    f"[{scenario.id}] fixture '{f.name}' 只有 {len(data)} 个字段（< {_FIXTURE_MIN_FIELDS}），"
                    f"可能遗漏了 NOT NULL 列。请用 data query --source main_db --target \"SHOW COLUMNS FROM {f.target}\" 确认表结构后补全"
                )
