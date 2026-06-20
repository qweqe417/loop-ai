"""MemoryExtractor —— 从 RunState 提取可沉淀的记忆。

提取策略:
    - failures → pitfall / failure_pattern
    - decisions → prohibited / rule
    - notes (memory: 开头) → rule
    - session_memory → 直接转发候选

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

    def extract(self, state: RunState) -> list[MemoryEntry]:
        """从 RunState 提取所有候选条目。"""
        candidates: list[MemoryEntry] = []
        candidates.extend(self._extract_failures(state))
        candidates.extend(self._extract_decisions(state))
        candidates.extend(self._extract_notes(state))
        candidates.extend(self._extract_session_memory(state))
        logger.info(
            "Extracted %d memory candidates from task %s",
            len(candidates), state.task_id,
        )
        return candidates

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

    def _next_id(self, category: MemoryCategory) -> str:
        import uuid
        prefix = self.CATEGORY_PREFIX.get(category, "entry")
        return f"{prefix}-{uuid.uuid4().hex[:8]}"
