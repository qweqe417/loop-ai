"""MemoryExtractor —— 从 RunState 提取可沉淀的记忆。

提取策略:
    - failures → pitfall / failure_pattern
    - decisions → prohibited / rule
    - notes (memory: 开头) → rule
    - session_memory → 直接转发候选

质量门禁（第一层：自动格式校验）:
    每条候选记忆必须通过 3 段式格式校验：
    1. trigger_conditions ≥ 20 字符
    2. error_pattern ≥ 20 字符
    3. fix_rule ≥ 20 字符
    不通过 → 标记 draft + 格式问题，不自动确认。

Session 记录保存到 .ai/memory/sessions/{task_id}.json。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .models import Confidence, MemoryCategory, MemoryEntry, SessionMemory

if TYPE_CHECKING:
    from engines.state.models import RunState

logger = logging.getLogger(__name__)


class MemoryExtractor:
    """从 RunState 提取可沉淀的记忆条目。

    用法:
        extractor = MemoryExtractor()
        candidates = extractor.extract(state)   # → list[MemoryEntry]
        session = extractor.build_session_memory(state)  # → SessionMemory
    """

    CATEGORY_PREFIX: dict[MemoryCategory, str] = {
        MemoryCategory.RULE: "rule",
        MemoryCategory.PITFALL: "pitfall",
        MemoryCategory.VERIFICATION: "verify",
        MemoryCategory.TESTING: "testing",
        MemoryCategory.MODULE_BOUNDARY: "boundary",
        MemoryCategory.ARCHITECTURE: "arch",
        MemoryCategory.FAILURE_PATTERN: "failure",
        MemoryCategory.PROHIBITED: "prohibited",
        MemoryCategory.CODE_STYLE: "style",
    }

    # 3 段式最小长度
    MIN_SEGMENT_LENGTH = 20

    def extract(self, state: RunState) -> list[MemoryEntry]:
        """从 RunState 提取所有候选条目，通过格式门禁后返回。"""
        candidates: list[MemoryEntry] = []
        candidates.extend(self._extract_failures(state))
        candidates.extend(self._extract_decisions(state))
        candidates.extend(self._extract_notes(state))
        candidates.extend(self._extract_session_memory(state))

        # 格式门禁：过滤不合格的候选
        valid: list[MemoryEntry] = []
        for c in candidates:
            result = self._validate_3segment(c)
            if result.passed:
                valid.append(c)
            else:
                logger.warning(
                    "Memory format gate REJECTED %s: %s", c.id, result.reason
                )
                # 仍保留为 draft，但标注格式问题
                c.confidence = Confidence.DRAFT
                c.content = f"[FORMAT_ISSUE] {result.reason} | {c.content}"
                valid.append(c)  # 保留但标记

        logger.info(
            "Extracted %d candidates (%d passed format gate) from task %s",
            len(valid), sum(1 for c in valid if "FORMAT_ISSUE" not in c.content), state.task_id,
        )
        return valid

    def build_session_memory(self, state: RunState) -> SessionMemory:
        """从 RunState 构建 SessionMemory。"""
        failures = [
            {
                "category": f.category.value,
                "message": f.message,
                "stage": f.stage.value,
                "attempt": f.attempt_count,
            }
            for f in state.failures
        ]

        decisions: list[dict] = []
        if state.decision:
            decisions.append({
                "action": state.decision.action.value,
                "target_stage": state.decision.target_stage.value if state.decision.target_stage else None,
                "reason": state.decision.reason,
            })
        for cp in state.checkpoints:
            decisions.append({
                "stage": cp.stage.value,
                "reason": cp.reason,
                "files": cp.files_changed,
            })

        candidates = self.extract(state)

        return SessionMemory(
            task_id=state.task_id,
            related_spec=state.metadata.get("spec_id", ""),
            failures=failures,
            decisions=decisions,
            patterns_observed=[],
            candidates=[c.model_dump() for c in candidates],
            notes=list(state.task_state.notes),
        )

    # ── 格式门禁 ──────────────────────────────────────────

    class FormatGateResult:
        def __init__(self, passed: bool, reason: str = ""):
            self.passed = passed
            self.reason = reason

    def _validate_3segment(self, entry: MemoryEntry) -> "MemoryExtractor.FormatGateResult":
        """校验 3 段式格式：每段至少 20 字符，修复规则必须包含动作关键词。"""
        if not entry.trigger_conditions or len(entry.trigger_conditions.strip()) < self.MIN_SEGMENT_LENGTH:
            return self.FormatGateResult(False, "trigger_conditions 不足 20 字符")
        if not entry.error_pattern or len(entry.error_pattern.strip()) < self.MIN_SEGMENT_LENGTH:
            return self.FormatGateResult(False, "error_pattern 不足 20 字符")
        if not entry.fix_rule or len(entry.fix_rule.strip()) < self.MIN_SEGMENT_LENGTH:
            return self.FormatGateResult(False, "fix_rule 不足 20 字符")

        # 修复规则必须包含具体动作
        action_keywords = ["必须", "禁止", "检查", "确保", "避免", "需要", "不要", "MUST", "NEVER", "CHECK", "ENSURE"]
        has_action = any(kw in entry.fix_rule for kw in action_keywords)
        if not has_action:
            return self.FormatGateResult(False, "fix_rule 缺少具体动作关键词（必须/禁止/检查/确保/避免）")

        return self.FormatGateResult(True)

    # ── 提取策略 ──────────────────────────────────────────

    def _extract_failures(self, state: RunState) -> list[MemoryEntry]:
        entries: list[MemoryEntry] = []
        for failure in state.failures:
            cat = failure.category
            if cat.value == "unknown":
                continue
            if cat.value == "code_logic":
                entries.append(MemoryEntry(
                    id=self._next_id(MemoryCategory.PITFALL),
                    category=MemoryCategory.PITFALL,
                    title=f"[{failure.stage.value}] {failure.message[:80]}",
                    content=failure.message,
                    source=state.task_id,
                    confidence=Confidence.DRAFT,
                    tags=[failure.category.value, failure.stage.value],
                    trigger_conditions=f"阶段={failure.stage.value}, 类别=code_logic, 文件={', '.join(self._changed_files(state)[:3])}",
                    error_pattern=failure.message,
                    fix_rule="",  # AI 填充，或人工编辑
                ))
            elif cat.value == "environment":
                entries.append(MemoryEntry(
                    id=self._next_id(MemoryCategory.FAILURE_PATTERN),
                    category=MemoryCategory.FAILURE_PATTERN,
                    title=f"环境故障: {failure.message[:80]}",
                    content=f"在 {failure.stage.value} 阶段遇到环境问题 (第{failure.attempt_count}次尝试): {failure.message}",
                    source=state.task_id,
                    confidence=Confidence.DRAFT,
                    tags=["environment", failure.stage.value],
                    trigger_conditions=f"阶段={failure.stage.value}, 测试环境不可用或配置错误",
                    error_pattern=f"环境故障(第{failure.attempt_count}次尝试): {failure.message}",
                    fix_rule="检查服务是否启动、配置是否正确，确认后重试",
                ))
        return entries

    def _extract_decisions(self, state: RunState) -> list[MemoryEntry]:
        entries: list[MemoryEntry] = []
        decision = state.decision
        if decision is None:
            return entries
        if decision.action.value == "stop_guard":
            entries.append(MemoryEntry(
                id=self._next_id(MemoryCategory.PROHIBITED),
                category=MemoryCategory.PROHIBITED,
                title=f"Guard 拦截: {decision.reason[:80]}",
                content=f"触发 Guard 规则导致任务中止: {decision.reason}",
                source=state.task_id,
                confidence=Confidence.CONFIRMED,
                tags=["guard", "blocked"],
                trigger_conditions=f"触发 Guard 规则: {decision.reason}",
                error_pattern=f"违反安全/质量规则导致任务中止: {decision.reason}",
                fix_rule=f"禁止执行会被 Guard 拦截的操作，必须先修正: {decision.reason}",
            ))
        if decision.action.value == "backtrack":
            entries.append(MemoryEntry(
                id=self._next_id(MemoryCategory.RULE),
                category=MemoryCategory.RULE,
                title=f"回溯经验: {decision.reason[:80]}",
                content=f"在 {state.current_stage.value} 阶段因 '{decision.reason}' 回溯到 {decision.target_stage.value if decision.target_stage else '上一步'}",
                source=state.task_id,
                confidence=Confidence.DRAFT,
                tags=["backtrack"],
                trigger_conditions=f"阶段={state.current_stage.value}, 满足回溯条件: {decision.reason}",
                error_pattern=f"继续执行会导致问题: {decision.reason}",
                fix_rule=f"需要回溯到 {decision.target_stage.value if decision.target_stage else '前一步'}，重新生成后再继续",
            ))
        return entries

    def _extract_notes(self, state: RunState) -> list[MemoryEntry]:
        entries: list[MemoryEntry] = []
        for note in state.task_state.notes:
            if note.lower().startswith("memory:"):
                content = note[7:].strip()
                entries.append(MemoryEntry(
                    id=self._next_id(MemoryCategory.RULE),
                    category=MemoryCategory.RULE,
                    title=content[:80],
                    content=content,
                    source=state.task_id,
                    confidence=Confidence.DRAFT,
                    tags=["manual"],
                    trigger_conditions="用户手动记录",
                    error_pattern=content,
                    fix_rule="",  # 人工补充
                ))
        return entries

    def _extract_session_memory(self, state: RunState) -> list[MemoryEntry]:
        session_data = state.metadata.get("session_memory")
        if session_data is None:
            return []
        if isinstance(session_data, SessionMemory):
            return [MemoryEntry(**c) if isinstance(c, dict) else c for c in session_data.candidates]
        if isinstance(session_data, dict):
            raw = session_data.get("candidates", [])
            return [MemoryEntry(**c) if isinstance(c, dict) else c for c in raw]
        return []

    def _changed_files(self, state: RunState) -> list[str]:
        """提取变更文件列表。"""
        files: list[str] = []
        for cp in state.checkpoints:
            files.extend(cp.files_changed)
        return list(dict.fromkeys(files))

    def _next_id(self, category: MemoryCategory) -> str:
        import uuid
        prefix = self.CATEGORY_PREFIX.get(category, "entry")
        return f"{prefix}-{uuid.uuid4().hex[:8]}"
