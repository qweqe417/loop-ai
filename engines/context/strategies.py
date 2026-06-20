"""阶段加载策略 —— 每个阶段一个策略函数。

策略函数签名:
    (router: ContextRouter, run_state: RunState) → list[ContextPiece]

策略职责:
    1. 决定本阶段加载什么
    2. 决定用 summary 还是 full 模式读文件
    3. 决定调哪些 CodeGraph 查询
    4. 决定 recall 哪些 Memory 条目

策略不负责:
    - 优先级排序（ContextPiece 自带 priority）
    - 预算裁剪（Router 统一处理）
    - 拼装 ContextBundle（Router 统一处理）
"""

from __future__ import annotations

from __future__ import annotations

from typing import TYPE_CHECKING

from engines.state.enums import StageType

from .models import ContextPiece

if TYPE_CHECKING:
    from .router import ContextRouter
    from engines.state.models import RunState


def _estimate(text: str) -> int:
    return max(1, len(text) // 3)


# ── INTAKE ────────────────────────────────────────────────────────

def intake_strategy(router: "ContextRouter", _run_state: "RunState") -> list[ContextPiece]:
    """INTAKE: 项目地图 + CLAUDE.md 核心段 + 已有 AI 配置文件列表。

    目标: 最快的项目理解，不深入代码。
    预算: ~1500 tokens
    """
    pieces: list[ContextPiece] = []

    # 1. 项目地图 (priority=1, 必须)
    pieces.append(router.build_project_map())

    # 2. CLAUDE.md 前 80 行 (priority=1, 必须)
    claude = router.file.read_summary("CLAUDE.md", max_lines=80)
    claude.priority = 1
    claude.metadata["stage_relevance"] = "core project rules"
    pieces.append(claude)

    # 3. 已有 AI 配置文件列表 (priority=1)
    existing = _list_existing_ai_files(router)
    if existing:
        existing.priority = 1
        pieces.append(existing)

    # 4. .claude/rules/ 目录列表 (priority=2)
    rules_dir = router.file.read_summary(".claude/rules/code-style.md", max_lines=30)
    rules_dir.priority = 2
    pieces.append(rules_dir)

    return pieces


# ── SPEC ──────────────────────────────────────────────────────────

def spec_strategy(router: "ContextRouter", run_state: "RunState") -> list[ContextPiece]:
    """SPEC: 项目地图 + 相关模块摘要 + 相关 Memory + 领域术语。

    目标: 为 Spec 生成提供足够但不过量的上下文。
    预算: ~2500 tokens
    """
    pieces: list[ContextPiece] = []

    # 1. 项目地图 (priority=1)
    pieces.append(router.build_project_map())

    # 2. 相关模块摘要 — 用 codegraph_context 查 (priority=2)
    intake_text = ""
    if run_state.task_intake:
        intake_text = f"{run_state.task_intake.input_type} {run_state.task_intake.reason} ({run_state.task_intake.complexity} complexity)"
    task_desc = intake_text or run_state.task_id
    cg = router.codegraph.get_context(task_desc, max_nodes=8)
    if cg.content and "unavailable" not in cg.content:
        cg.priority = 2
        pieces.append(cg)

    # 3. 相关 Memory (priority=2)
    keywords = _extract_keywords(run_state)
    mem = router.memory.load_relevant(keywords, limit=5)
    pieces.append(mem)

    # 4. 影响域分析 — 从 task_intake 取 (priority=2)
    if run_state.task_intake:
        impact = _format_intake_impact(run_state)
        pieces.append(ContextPiece(
            source="run_state",
            path="task_intake",
            content=impact,
            token_estimate=_estimate(impact),
            priority=2,
            metadata={"source": "task_intake_result"},
        ))

    return pieces


# ── PLAN ──────────────────────────────────────────────────────────

def plan_strategy(router: "ContextRouter", run_state: "RunState") -> list[ContextPiece]:
    """PLAN: Spec 摘要 + 相关文件签名 + 代码风格规则 + diff 预算。

    目标: 为 Plan 生成提供执行约束和代码风格约束。
    预算: ~3000 tokens
    """
    pieces: list[ContextPiece] = []

    # 1. 代码风格规则 (priority=1)
    style = router.file.read_summary(".claude/rules/code-style.md", max_lines=60)
    style.priority = 1
    style.metadata["stage_relevance"] = "style contract for plan"
    pieces.append(style)

    # 2. 项目地图 (priority=2)
    pieces.append(router.build_project_map())

    # 3. 相关文件签名 (priority=2) — 用 codegraph 定位
    task_desc = run_state.task_id
    if run_state.task_intake:
        task_desc = run_state.task_intake.reason or run_state.task_id
    cg = router.codegraph.get_context(task_desc, max_nodes=10)
    if cg.content and "unavailable" not in cg.content:
        cg.priority = 2
        pieces.append(cg)

    # 4. 测试规则 (priority=2)
    testing = router.file.read_summary(".claude/rules/testing.md", max_lines=40)
    testing.priority = 2
    pieces.append(testing)

    # 5. 相关 Memory (priority=3)
    keywords = _extract_keywords(run_state)
    mem = router.memory.load_relevant(keywords, limit=3)
    mem.priority = 3
    pieces.append(mem)

    # 6. 影响域 (priority=2)
    if run_state.task_intake:
        impact = _format_intake_impact(run_state)
        pieces.append(ContextPiece(
            source="run_state",
            path="task_intake",
            content=impact,
            token_estimate=_estimate(impact),
            priority=2,
        ))

    return pieces


# ── EXECUTE / DIRECT_EXECUTE ─────────────────────────────────────

def execute_strategy(router: "ContextRouter", run_state: "RunState") -> list[ContextPiece]:
    """EXECUTE: 修改文件全文 + 调用链 + style contract + 禁止文件列表。

    目标: 精确修改所需文件，不越界。
    预算: ~4000 tokens

    和 DIRECT_EXECUTE 的区别：DIRECT 预算更紧 (2500)。
    """
    pieces: list[ContextPiece] = []

    # 1. 风格合约 (priority=1)
    style = router.file.read_summary(".claude/rules/code-style.md", max_lines=50)
    style.priority = 1
    style.metadata["stage_relevance"] = "must follow when writing code"
    pieces.append(style)

    # 2. 安全规则 (priority=1)
    safety = router.file.read_summary(".claude/rules/safety.md", max_lines=30)
    if safety.content.strip():
        safety.priority = 1
        pieces.append(safety)

    # 3. 修改文件 (priority=1) — 从 run_state 中提取 allowed files
    allowed_files = _extract_allowed_files(run_state)
    if allowed_files:
        for f in allowed_files:
            cf = router.file.read_full(f)
            cf.priority = 1
            cf.metadata["stage_relevance"] = "file to modify"
            pieces.append(cf)
    else:
        # 无明确 files 时用 codegraph 定位
        task_desc = run_state.task_id
        cg = router.codegraph.get_context(task_desc, max_nodes=6)
        if cg.content and "unavailable" not in cg.content:
            cg.priority = 1
            pieces.append(cg)

    # 4. 调用链分析 — 对关键符号做 impact 分析 (priority=2)
    key_symbols = _extract_key_symbols(run_state)
    for sym in key_symbols[:3]:
        imp = router.codegraph.get_impact(sym, depth=1)
        if imp.content and "unavailable" not in imp.content:
            pieces.append(imp)

    # 5. 相关 Memory（少一点）(priority=3)
    keywords = _extract_keywords(run_state)
    mem = router.memory.load_relevant(keywords, limit=3)
    mem.priority = 3
    pieces.append(mem)

    # 6. 禁止文件列表 (priority=2)
    forbidden = _extract_forbidden_files(run_state)
    if forbidden:
        pieces.append(ContextPiece(
            source="run_state",
            path="forbidden_files",
            content="**FORBIDDEN files — do NOT modify:**\n" + "\n".join(f"- {f}" for f in forbidden),
            token_estimate=_estimate("\n".join(forbidden)),
            priority=2,
        ))

    return pieces


def direct_execute_strategy(router: "ContextRouter", run_state: "RunState") -> list[ContextPiece]:
    """DIRECT_EXECUTE: EXECUTE 的精简版，预算更紧。

    预算: ~2500 tokens
    """
    pieces = execute_strategy(router, run_state)
    # 标记 3 级片段供 Router 优先裁剪
    for p in pieces:
        if p.priority == 2:
            p.priority = 3  # 降级：在 DIRECT 模式下更激进裁剪
    return pieces


# ── VERIFY ────────────────────────────────────────────────────────

def verify_strategy(router: "ContextRouter", run_state: "RunState") -> list[ContextPiece]:
    """VERIFY: Scenario 定义 + 被修改文件路径 + 验收标准。

    目标: 跑场景验证，不重新理解全项目。
    预算: ~2500 tokens
    """
    pieces: list[ContextPiece] = []

    # 1. 场景定义 (priority=1)
    scenario_ids = _extract_scenario_ids(run_state)
    if scenario_ids:
        for sid in scenario_ids:
            # 查找 .ai/scenarios/ 下的场景文件
            sc_path = f".ai/scenarios/{sid}.yaml"
            sc = router.file.read_full(sc_path)
            sc.priority = 1
            sc.metadata["stage_relevance"] = "scenario to verify"
            pieces.append(sc)
    else:
        # fallback: 列出所有场景
        sc_list = _list_ai_dir(router, "scenarios")
        if sc_list:
            sc_list.priority = 1
            pieces.append(sc_list)

    # 2. 被修改文件列表 (priority=2)
    changed = _extract_changed_files_from_checkpoints(run_state)
    if changed:
        pieces.append(ContextPiece(
            source="run_state",
            path="changed_files",
            content="**Files changed in this task:**\n" + "\n".join(f"- {f}" for f in changed),
            token_estimate=_estimate("\n".join(changed)),
            priority=2,
        ))

    # 3. 验证命令 (priority=1)
    test_cmd = router.file.read_summary(".claude/rules/testing.md", max_lines=30)
    test_cmd.priority = 1
    pieces.append(test_cmd)

    return pieces


# ── REPAIR ────────────────────────────────────────────────────────

def repair_strategy(router: "ContextRouter", run_state: "RunState") -> list[ContextPiece]:
    """REPAIR: 失败上下文 + 出错文件全文 + 调用链 + 相关日志。

    目标: 快速定位根因、最小修复。
    预算: ~3500 tokens
    """
    pieces: list[ContextPiece] = []

    # 1. 失败摘要 (priority=1)
    failures = run_state.failures
    if failures:
        fail_text = "**Recent Failures:**\n"
        for f in failures[-3:]:  # 最近 3 条
            fail_text += f"- [{f.category}] {f.message} (attempt {f.attempt_count})\n"
        pieces.append(ContextPiece(
            source="run_state",
            path="failures",
            content=fail_text,
            token_estimate=_estimate(fail_text),
            priority=1,
        ))

    # 2. 失败相关文件全文 (priority=1)
    changed = _extract_changed_files_from_checkpoints(run_state)
    for f in changed[:3]:
        cf = router.file.read_full(f)
        cf.priority = 1
        cf.metadata["stage_relevance"] = "file related to failure"
        pieces.append(cf)

    # 3. 调用链 — 帮助理解影响范围 (priority=2)
    key_symbols = _extract_key_symbols(run_state)
    for sym in key_symbols[:2]:
        callers = router.codegraph.get_callers(sym)
        if callers.content and "unavailable" not in callers.content:
            pieces.append(callers)
        callees = router.codegraph.get_callees(sym)
        if callees.content and "unavailable" not in callees.content:
            pieces.append(callees)

    # 4. 相关失败记忆 (priority=2)
    mem = router.memory.load_recent_failures(limit=3)
    mem.priority = 2
    pieces.append(mem)

    return pieces


# ── REVIEW ────────────────────────────────────────────────────────

def review_strategy(router: "ContextRouter", run_state: "RunState") -> list[ContextPiece]:
    """REVIEW: diff 摘要 + Plan 合规清单 + 变更文件列表 + Guard 规则。

    目标: 检查是否越界、是否满足 Spec、是否风格合规。
    预算: ~3000 tokens
    """
    pieces: list[ContextPiece] = []

    # 1. 风格规则 (priority=1)
    style = router.file.read_summary(".claude/rules/code-style.md", max_lines=40)
    style.priority = 1
    pieces.append(style)

    # 2. 安全规则 (priority=1)
    safety = router.file.read_summary(".claude/rules/safety.md", max_lines=30)
    if safety.content.strip():
        safety.priority = 1
        pieces.append(safety)

    # 3. 变更文件列表 (priority=1)
    changed = _extract_changed_files_from_checkpoints(run_state)
    if changed:
        pieces.append(ContextPiece(
            source="run_state",
            path="changed_files",
            content="**Files to review:**\n" + "\n".join(f"- {f}" for f in changed),
            token_estimate=_estimate("\n".join(changed)),
            priority=1,
        ))

    # 4. Plan 合规清单 (priority=2)
    if run_state.task_state:
        compliance = run_state.task_state.plan_compliance or "not assessed"
        pieces.append(ContextPiece(
            source="run_state",
            path="plan_compliance",
            content=f"Plan Compliance: {compliance}",
            token_estimate=_estimate(compliance),
            priority=2,
        ))

    return pieces


# ── MEMORY ────────────────────────────────────────────────────────

def memory_strategy(router: "ContextRouter", run_state: "RunState") -> list[ContextPiece]:
    """MEMORY: Session 摘要 + failures + decisions + 候选记忆。

    目标: 从中筛出值得沉淀的经验。
    预算: ~2000 tokens
    """
    pieces: list[ContextPiece] = []

    # 1. 失败记录摘要 (priority=1)
    if run_state.failures:
        fail_text = "**Failures in this session:**\n"
        for f in run_state.failures:
            fail_text += f"- [{f.category}] {f.message}\n"
        pieces.append(ContextPiece(
            source="run_state",
            path="session_failures",
            content=fail_text,
            token_estimate=_estimate(fail_text),
            priority=1,
        ))

    # 2. 检查点摘要 (priority=2)
    if run_state.checkpoints:
        cp_text = "**Checkpoints:**\n"
        for cp in run_state.checkpoints:
            cp_text += f"- {cp.stage}: {cp.reason} ({len(cp.files_changed)} files)\n"
        pieces.append(ContextPiece(
            source="run_state",
            path="checkpoints",
            content=cp_text,
            token_estimate=_estimate(cp_text),
            priority=2,
        ))

    # 3. 当前 memory 状态 (priority=3)
    mem_full = router.memory.load_all()
    if mem_full:
        pieces.append(ContextPiece(
            source="memory",
            path=".ai/memory.md",
            content=f"[existing memory: {len(mem_full)} chars]",
            token_estimate=_estimate(f"[existing memory: {len(mem_full)} chars]"),
            priority=3,
        ))

    return pieces


# ── 策略表 ──────────────────────────────────────────────────────

STAGE_STRATEGIES: dict[StageType, "callable"] = {
    StageType.INTAKE:         intake_strategy,
    StageType.SPEC:           spec_strategy,
    StageType.PLAN:           plan_strategy,
    StageType.EXECUTE:        execute_strategy,
    StageType.DIRECT_EXECUTE: direct_execute_strategy,
    StageType.VERIFY:         verify_strategy,
    StageType.REPAIR:         repair_strategy,
    StageType.REVIEW:         review_strategy,
    StageType.MEMORY:         memory_strategy,
}


# ── 策略辅助函数 ──────────────────────────────────────────────────

def _extract_keywords(run_state: "RunState") -> list[str]:
    """从 run_state 中提取搜索关键词。"""
    kw: list[str] = []
    if run_state.task_intake:
        kw.append(run_state.task_intake.input_type)
        kw.append(run_state.task_intake.flow_mode)
        kw.extend(run_state.task_intake.reason.split())
    kw.append(run_state.task_id)
    kw.append(run_state.project)
    return list(dict.fromkeys(kw))  # 去重保序


def _extract_allowed_files(run_state: "RunState") -> list[str]:
    """从 run_state 中提取 allowed files。"""
    return run_state.metadata.get("allowed_files", [])


def _extract_forbidden_files(run_state: "RunState") -> list[str]:
    """从 run_state 中提取 forbidden files。"""
    return run_state.metadata.get("forbidden_files", [])


def _extract_key_symbols(run_state: "RunState") -> list[str]:
    """从 run_state 中提取关键符号名。"""
    return run_state.metadata.get("key_symbols", [])


def _extract_scenario_ids(run_state: "RunState") -> list[str]:
    """从 run_state 中提取场景 ID 列表。"""
    ids = run_state.metadata.get("scenario_ids", [])
    if not ids:
        ids = [sr.scenario_id for sr in run_state.scenario_results]
    return ids


def _extract_changed_files_from_checkpoints(run_state: "RunState") -> list[str]:
    """从检查点中提取变更文件列表。"""
    files: list[str] = []
    for cp in run_state.checkpoints:
        files.extend(cp.files_changed)
    return list(dict.fromkeys(files))


def _format_intake_impact(run_state: "RunState") -> str:
    """格式化 task_intake 的影响域信息。"""
    ti = run_state.task_intake
    if not ti:
        return ""
    return (
        f"**Task Intake Summary:**\n"
        f"- Input type: {ti.input_type}\n"
        f"- Risk level: {ti.risk_level}\n"
        f"- Complexity: {ti.complexity}\n"
        f"- Flow mode: {ti.flow_mode}\n"
        f"- Needs Spec: {ti.needs_spec}\n"
        f"- Needs Scenario: {ti.verification_required}\n"
        f"- Reason: {ti.reason}"
    )


def _list_existing_ai_files(router: "ContextRouter") -> ContextPiece | None:
    """列出项目中已有的 AI 配置文件。"""
    patterns = ["CLAUDE.md", ".claude/", ".ai/", ".cursor/", ".codex/", "superpowers/"]
    existing: list[str] = []
    for p in patterns:
        if (router.file._root / p).exists():
            existing.append(p)
    if not existing:
        return None
    content = "**Existing AI config files:**\n" + "\n".join(f"- {f}" for f in existing)
    return ContextPiece(
        source="file",
        path="existing_ai_files",
        content=content,
        token_estimate=_estimate(content),
        priority=1,
    )


def _list_ai_dir(router: "ContextRouter", subdir: str) -> ContextPiece | None:
    """列出 .ai/ 子目录中的文件。"""
    d = router.file._root / ".ai" / subdir
    if not d.is_dir():
        return None
    files = [f.name for f in d.iterdir() if f.is_file()]
    if not files:
        return None
    content = f"**Available in .ai/{subdir}/:**\n" + "\n".join(f"- {f}" for f in sorted(files))
    return ContextPiece(
        source="file",
        path=f".ai/{subdir}",
        content=content,
        token_estimate=_estimate(content),
        priority=2,
    )
