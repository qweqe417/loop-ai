"""序列化层 —— 读写测试设计产物文件。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import yaml

from .models import (
    AutomationCandidate,
    CleanupConfig,
    CoverageEntry,
    DataAssertion,
    DOMAssertion,
    ExpectedResult,
    OpenQuestion,
    RequirementItem,
    Step,
    StepAssertion,
    TestCase,
    TestDesignBundle,
)

logger = logging.getLogger(__name__)


# ── 序列化 ──────────────────────────────────────────────────────────

def _bundle_to_dict(bundle: TestDesignBundle) -> dict[str, Any]:
    return {
        "version": bundle.version,
        "feature": bundle.feature,
        "scope": bundle.scope.value,
        "source": bundle.source,
        "requirements": [_req_to_dict(r) for r in bundle.requirements],
        "test_cases": [_tc_to_dict(tc) for tc in bundle.test_cases],
        "coverage": [json.loads(c.model_dump_json()) for c in bundle.coverage],
        "open_questions": [json.loads(q.model_dump_json()) for q in bundle.open_questions],
        "metadata": bundle.metadata,
    }


def _req_to_dict(req: RequirementItem) -> dict[str, Any]:
    return {
        "id": req.id,
        "title": req.title,
        "type": req.type,
        "risk_level": req.risk_level.value,
        "description": req.description,
        "acceptance_criteria": req.acceptance_criteria,
        "source": req.source,
    }


def _tc_to_dict(tc: TestCase) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": tc.id,
        "title": tc.title,
        "scope": tc.scope.value,
        "requirement_refs": tc.requirement_refs,
        "priority": tc.priority.value,
        "risk_level": tc.risk_level.value,
        "test_level": tc.test_level.value,
        "test_types": [t.value for t in tc.test_types],
    }

    if tc.automation:
        result["automation"] = {
            "candidate": tc.automation.candidate.value,
            "target": tc.automation.target,
            "reason": tc.automation.reason,
        }

    result["preconditions"] = tc.preconditions
    result["dependencies"] = tc.dependencies
    result["test_data"] = tc.test_data

    # Action Pipeline steps
    result["steps"] = []
    for s in tc.steps:
        step_dict: dict[str, Any] = {
            "seq": s.seq,
            "action": s.action.value,
            "description": s.description,
            "config": s.config,
        }
        if s.assertions:
            step_dict["assertions"] = [{
                "type": a.type,
                "target": a.target,
                "operator": a.operator,
                "expected": a.expected,
                "message": a.message,
            } for a in s.assertions]
        result["steps"].append(step_dict)

    # expected
    exp: dict[str, Any] = {}
    if tc.expected.response:
        exp["response"] = tc.expected.response
    if tc.expected.data_assertions:
        exp["data_assertions"] = [{
            "type": da.type, "target": da.target,
            "operator": da.operator, "expected": da.expected, "message": da.message,
            "inferred_source": da.inferred_source,
        } for da in tc.expected.data_assertions]
    if tc.expected.dom_assertions:
        exp["dom_assertions"] = [{
            "type": da.type, "target": da.target,
            "operator": da.operator, "expected": da.expected, "message": da.message,
        } for da in tc.expected.dom_assertions]
    result["expected"] = exp

    # cleanup
    result["cleanup"] = {
        "required": tc.cleanup.required,
        "strategy": tc.cleanup.strategy,
        "description": tc.cleanup.description,
    }

    result["notes"] = tc.notes
    result["open_questions"] = tc.open_questions
    return result


# ── 写入 ──────────────────────────────────────────────────────────

def write_test_cases_yaml(bundle: TestDesignBundle, filepath: str | Path) -> Path:
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    data = _bundle_to_dict(bundle)
    with open(filepath, "w", encoding="utf-8") as f:
        yaml.dump(data, f, Dumper=yaml.SafeDumper, allow_unicode=True, default_flow_style=False, sort_keys=False)
    logger.info("test-cases.yaml written (%d cases)", len(bundle.test_cases))
    return filepath


def write_scenario_drafts_yaml(scenarios: list[dict[str, Any]], filepath: str | Path) -> Path:
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        yaml.dump({"scenarios": scenarios}, f, Dumper=yaml.SafeDumper, allow_unicode=True, default_flow_style=False, sort_keys=False)
    logger.info("scenario-drafts.yaml written (%d scenarios)", len(scenarios))
    return filepath


def write_quality_report_md(report: "QualityReport", filepath: str | Path) -> Path:
    from .models import QualityReport as QR
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# 质量报告 — {report.summary.get('feature', '')}",
        "",
        "## 覆盖概览",
        "",
        "| 指标 | 数值 |",
        "|------|------|",
    ]
    for key, val in report.summary.items():
        lines.append(f"| {key} | {val} |")

    lines.append("")
    lines.append("## 门禁结果")
    lines.append("")
    lines.append(f"**{'通过' if report.passed else '未通过'}** {'✅' if report.passed else '❌'}")
    lines.append("")

    if report.errors:
        lines.append("### 硬阻断（必须修复）")
        for e in report.errors:
            lines.append(f"- ❌ {e}")
        lines.append("")
    if report.warnings:
        lines.append("### 软警告（建议修复）")
        for w in report.warnings:
            lines.append(f"- ⚠️ {w}")
        lines.append("")

    if report.blocked_requirements:
        lines.append("## 阻塞项")
        for br in report.blocked_requirements:
            lines.append(f"- {br}")
        lines.append("")

    lines.append(f"*生成时间: {report.generated_at.isoformat()}*")
    filepath.write_text("\n".join(lines), encoding="utf-8")
    return filepath


# ── 反序列化 ──────────────────────────────────────────────────────

def read_test_cases_yaml(filepath: str | Path) -> TestDesignBundle:
    filepath = Path(filepath)
    with open(filepath, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        raise ValueError(f"Empty or invalid YAML: {filepath}")
    return _dict_to_bundle(data)


def _dict_to_bundle(data: dict[str, Any]) -> TestDesignBundle:
    requirements = []
    for r in data.get("requirements", []):
        requirements.append(RequirementItem(
            id=r["id"], title=r["title"],
            type=r.get("type", "functional"),
            risk_level=r.get("risk_level", "medium"),
            description=r.get("description", ""),
            acceptance_criteria=r.get("acceptance_criteria", []),
            source=r.get("source", "spec"),
        ))
    test_cases = [_dict_to_tc(tc) for tc in data.get("test_cases", [])]
    coverage = [CoverageEntry(**c) for c in data.get("coverage", [])]
    open_questions = [OpenQuestion(**q) for q in data.get("open_questions", [])]
    return TestDesignBundle(
        version=data.get("version", 1),
        feature=data.get("feature", ""),
        scope=data.get("scope", "backend"),
        source=data.get("source", {}),
        requirements=requirements,
        test_cases=test_cases,
        coverage=coverage,
        open_questions=open_questions,
        metadata=data.get("metadata", {}),
    )


def _dict_to_tc(d: dict[str, Any]) -> TestCase:
    # automation
    auto = None
    if "automation" in d and d["automation"]:
        auto = AutomationCandidate(
            candidate=d["automation"].get("candidate", "medium"),
            target=d["automation"].get("target", "scenario"),
            reason=d["automation"].get("reason", ""),
        )

    # Action Pipeline steps
    steps = []
    for s in d.get("steps", []):
        step_assertions = []
        for a in s.get("assertions", []):
            step_assertions.append(StepAssertion(
                type=a.get("type", ""),
                target=a.get("target", ""),
                operator=a.get("operator", "eq"),
                expected=a.get("expected"),
                message=a.get("message", ""),
            ))
        steps.append(Step(
            seq=s.get("seq", 1),
            action=s.get("action", "script"),
            description=s.get("description", ""),
            config=s.get("config", {}),
            assertions=step_assertions,
        ))

    # expected
    exp_data = d.get("expected", {})
    data_assertions = []
    for da in exp_data.get("data_assertions", []):
        data_assertions.append(DataAssertion(
            type=da.get("type", "mysql"), target=da.get("target", ""),
            operator=da.get("operator", "eq"), expected=da.get("expected"),
            message=da.get("message", ""),
            inferred_source=da.get("inferred_source", ""),
        ))
    dom_assertions = []
    for da in exp_data.get("dom_assertions", []):
        dom_assertions.append(DOMAssertion(
            type=da.get("type", "dom_visible"), target=da.get("target", ""),
            operator=da.get("operator", "eq"), expected=da.get("expected"),
            message=da.get("message", ""),
        ))
    expected = ExpectedResult(
        response=exp_data.get("response", {}),
        data_assertions=data_assertions,
        dom_assertions=dom_assertions,
    )

    # cleanup
    cl = d.get("cleanup", {})
    cleanup = CleanupConfig(
        required=cl.get("required", True),
        strategy=cl.get("strategy", "by_reference"),
        description=cl.get("description", ""),
    )

    return TestCase(
        id=d["id"], title=d["title"],
        scope=d.get("scope", "backend"),
        requirement_refs=d.get("requirement_refs", []),
        priority=d.get("priority", "P2"),
        risk_level=d.get("risk_level", "medium"),
        test_level=d.get("test_level", "scenario"),
        test_types=[t for t in d.get("test_types", [])],
        automation=auto,
        preconditions=d.get("preconditions", []),
        dependencies=d.get("dependencies", []),
        test_data=d.get("test_data", {}),
        steps=steps,
        expected=expected,
        cleanup=cleanup,
        notes=d.get("notes", []),
        open_questions=d.get("open_questions", []),
    )
