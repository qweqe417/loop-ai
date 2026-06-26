"""CompletionGate —— 阶段完成后确定性验证。

每个 AI 阶段完成后，在流转到下一阶段前，检查产物是否真实存在且格式正确。
AI 说"完成了"不算，产物通过门禁才算。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engines.state.models import RunState

logger = logging.getLogger(__name__)


class GateResult:
    def __init__(self, passed: bool, message: str = ""):
        self.passed = passed
        self.message = message

    @classmethod
    def ok(cls):
        return cls(True, "")

    @classmethod
    def fail(cls, msg: str):
        return cls(False, msg)


def check_stage_completion(state: "RunState") -> GateResult:
    """根据当前阶段检查产物完整性。"""
    from engines.state.enums import StageType

    stage = state.current_stage

    if stage == StageType.SPEC:
        return _check_spec(state)
    elif stage == StageType.PLAN:
        return _check_plan(state)
    elif stage == StageType.TEST_DESIGN:
        return _check_test_design(state)
    elif stage == StageType.EXECUTE:
        return _check_execute(state)
    elif stage == StageType.MEMORY:
        return _check_memory(state)

    # SPEC / VERIFY / REPAIR / REVIEW — 不检查或已有自己的 guard
    return GateResult.ok()


# ── SPEC ──

def _check_spec(state: "RunState") -> GateResult:
    root = Path(state.project_root)
    # 优先用 state 里指定的 spec 文件
    spec_file = state.metadata.get("spec_file")
    if spec_file:
        fp = root / spec_file
        if fp.exists() and fp.stat().st_size > 200:
            return GateResult.ok()
        return GateResult.fail(f"指定的 Spec 文件不存在或过小: {spec_file}")

    # 兜底：扫描目录
    for dir_name in ("spec", "superpowers/specs"):
        dir_path = root / "docs" / dir_name
        if dir_path.is_dir():
            for f in dir_path.glob("*.md"):
                if f.stat().st_size > 200:
                    return GateResult.ok()
    return GateResult.fail("SPEC 未完成：无有效 .md 文件")


# ── PLAN ──

def _check_plan(state: "RunState") -> GateResult:
    root = Path(state.project_root)
    # 优先用 state 里指定的 plan 文件
    plan_file = state.metadata.get("plan_file")
    if plan_file:
        fp = root / plan_file
        if fp.exists() and fp.stat().st_size > 200:
            return GateResult.ok()
        return GateResult.fail(f"指定的 Plan 文件不存在或过小: {plan_file}")

    # 兜底：扫描目录
    for dir_name in ("plan", "superpowers/plans"):
        dir_path = root / "docs" / dir_name
        if dir_path.is_dir():
            for f in dir_path.glob("*.md"):
                if f.stat().st_size > 200:
                    return GateResult.ok()
    return GateResult.fail("PLAN 未完成：无有效 .md 文件")

    for f in md_files:
        content = f.read_text(encoding="utf-8")
        if "allowed_files" in content.lower() and f.stat().st_size > 200:
            return GateResult.ok()

    return GateResult.fail("PLAN 完成但文件中未找到 allowed_files 或文件是空壳")


# ── TEST_DESIGN ──

def _check_test_design(state: "RunState") -> GateResult:
    dir_path = Path(state.project_root) / ".ai" / "scenarios"
    if not dir_path.is_dir():
        return GateResult.fail("TEST_DESIGN 完成但 .ai/scenarios/ 目录不存在")

    # 本次运行是否已生成场景（跟 aicode-direct 的 DirectExecuteHandler 入口检查一致）
    if not state.metadata.get("scenarios_generated"):
        return GateResult.fail("TEST_DESIGN: 本次运行尚未生成场景，等待 AI 调用 /aicode-test-design")

    # 优先用 scenario_dir 指定的子目录
    sub_dir = state.metadata.get("scenario_dir", "").strip()
    if sub_dir:
        target = dir_path / sub_dir
        if target.is_dir() and list(target.rglob("*.yaml")):
            return GateResult.ok()
        return GateResult.fail(f"TEST_DESIGN: .ai/scenarios/{sub_dir}/ 下无场景文件")

    # 兜底：有任意 yaml
    if list(dir_path.rglob("*.yaml")):
        return GateResult.ok()
    return GateResult.fail("TEST_DESIGN: .ai/scenarios/ 下无任何场景文件")


# ── EXECUTE ──

def _check_execute(state: "RunState") -> GateResult:
    # 从最近的 checkpoint 提取 changed_files
    changed = []
    for cp in state.checkpoints:
        changed.extend(cp.files_changed)
    changed = list(dict.fromkeys(changed))

    if not changed:
        return GateResult.fail("EXECUTE 完成但没有任何文件被修改 (changed_files 为空)")

    root = Path(state.project_root)
    for f in changed:
        fp = root / f
        if not fp.exists():
            return GateResult.fail(f"EXECUTE 声明的文件 {f} 不存在")

    return GateResult.ok()


# ── MEMORY ──

def _check_memory(state: "RunState") -> GateResult:
    """验证记忆沉淀是否完成。

    检查优先级：
    1. AI 明确标记跳过（无值得沉淀的经验）→ 通过
    2. AI 提交了写入的文件列表 → 逐个验证文件存在
    3. 标记已调用但无文件列表 → 不通过（可能是空提交）
    4. 未调用 → 不通过
    """
    memory_result = state.metadata.get("memory_result") or {}
    if isinstance(memory_result, dict):
        if memory_result.get("skipped"):
            return GateResult.ok()
        files = memory_result.get("files", [])
        if files:
            root = Path(state.project_root)
            missing = [f for f in files if not (root / f).exists()]
            if missing:
                return GateResult.fail(f"记忆文件不存在: {', '.join(missing)}")
            return GateResult.ok()

    # 兼容旧逻辑：memory_ai_called 但没有具体文件信息 → 不通过
    if state.metadata.get("memory_ai_called"):
        return GateResult.fail("memory_ai_called=true 但无文件列表，请重新执行 /memory 并返回 files 字段")

    return GateResult.fail("等待 AI 运行 /memory")
