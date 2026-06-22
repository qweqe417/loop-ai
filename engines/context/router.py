"""ContextRouter —— 渐进式上下文路由器。

用法:
    router = ContextRouter(project_root="/path/to/project")
    bundle = router.route(stage=StageType.EXECUTE, run_state=state)
    print(bundle.render())  # 可注入 AI 会话的文本
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from engines.state.enums import StageType

from .models import ContextBudget, ContextBundle, ContextPiece, TrimmedPointer
from .sources import CodeGraphSource, FileSource, MemorySource
from .strategies import STAGE_STRATEGIES

if TYPE_CHECKING:
    from engines.state.models import RunState

logger = logging.getLogger(__name__)


class ContextRouter:
    """渐进式上下文路由器。

    职责:
    1. 按阶段调用对应策略，收集 ContextPiece
    2. 按 priority 排序 (1 → 2 → 3)
    3. 按 token 预算裁剪 (从 priority=3 开始丢)
    4. 组装 ContextBundle

    Source 层只负责"拿数据"，策略层决定"要什么"，
    Router 层决定"最终给多少"。
    """

    def __init__(
        self,
        project_root: str | Path = ".",
        budgets: dict[StageType, ContextBudget] | None = None,
    ) -> None:
        import pathlib
        self._root = pathlib.Path(project_root).resolve()
        self.file = FileSource(project_root)
        self.codegraph = CodeGraphSource(project_root)
        self.memory = MemorySource(project_root)
        self._budgets = budgets or ContextBudget.defaults()

    # ── 主入口 ────────────────────────────────────────

    def route(self, stage: StageType, run_state: "RunState") -> ContextBundle:
        """为指定阶段加载上下文。

        流程:
        1. 查策略表，调用策略函数收集 ContextPiece
        2. 取该阶段 budget
        3. 按优先级分层 + 相关度排序
        4. P0 不限量, P1/P2 共享软预算, P3 始终 pointer
        5. 组装 ContextBundle（含 trimmed_pointers）
        """
        strategy = STAGE_STRATEGIES.get(stage)
        if strategy is None:
            logger.warning("No strategy for stage %s, returning empty bundle", stage)
            return ContextBundle(stage=stage)

        # 1. 收集
        pieces = strategy(self, run_state)

        # 2. 排序: priority 升序 (0=P0 在前), 同 priority 按 metadata.relevance 降序
        pieces.sort(key=lambda p: (p.priority, -(p.metadata.get("relevance", 0) or 0)))

        # 3. 裁剪
        budget = self._budgets.get(stage)
        if budget is None:
            budget = ContextBudget(stage=stage, max_tokens=3000)

        kept_pieces, pointers, was_trimmed = self._trim(pieces, budget)

        # 4. 计算 token
        total = sum(p.token_estimate for p in kept_pieces)

        logger.info(
            "ContextRouter: stage=%s kept=%d/%d pointers=%d tokens=%d/%d trimmed=%s",
            stage.value,
            len(kept_pieces),
            len(pieces),
            len(pointers),
            total,
            budget.max_tokens,
            was_trimmed,
        )

        return ContextBundle(
            stage=stage,
            pieces=kept_pieces,
            trimmed_pointers=pointers,
            total_tokens=total,
            budget_max=budget.max_tokens,
            budget_used_pct=round(total / budget.max_tokens * 100, 1) if budget.max_tokens else 0.0,
            trimmed=was_trimmed,
        )

    # ── 项目地图 ─────────────────────────────────────

    def build_project_map(self) -> ContextPiece:
        """构建项目地图。优先用 CodeGraph，fallback 到文件扫描。"""
        if self.codegraph.available:
            pm = self.codegraph.get_project_map()
            if pm is not None:
                return pm
        return self.file.scan_structure()

    # ── Token 估算 ───────────────────────────────────

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """粗略 token 估算: 字符数 / 3。"""
        return max(1, len(text) // 3)

    # ── 内部 ──────────────────────────────────────────

    def _trim(
        self,
        pieces: list[ContextPiece],
        budget: ContextBudget,
    ) -> tuple[list[ContextPiece], list[TrimmedPointer], bool]:
        """按预算裁剪 pieces，生成指针保留被裁内容。

        优先级体系:
        - P0 (priority=0): 任务定义，永远不裁剪，无上限
        - P1 (priority=1): 核心代码，填充共享软预算，按相关度排序
        - P2 (priority=2): 辅助分析，填充 P1 剩余预算，按相关度排序
        - P3 (priority=3): 补充信息，始终 pointer，不直接注入

        P1+P2 共享 budget.max_tokens 软预算。
        超出部分 → TrimmedPointer，AI 可按需回捞。
        """
        if not pieces:
            return [], [], False

        # 按优先级分层
        p0 = [p for p in pieces if p.priority == 0]
        p1 = [p for p in pieces if p.priority == 1]
        p2 = [p for p in pieces if p.priority == 2]
        p3 = [p for p in pieces if p.priority >= 3]

        # P0: 永远保留，不计数进预算
        keep: list[ContextPiece] = list(p0)
        pointers: list[TrimmedPointer] = []

        # P1: 按相关度降序填充共享预算
        running = sum(p.token_estimate for p in p0)
        for p in p1:
            if running + p.token_estimate <= budget.max_tokens:
                keep.append(p)
                running += p.token_estimate
            else:
                pointers.append(_to_pointer(p, "超出 P1+P2 共享预算"))

        # P2: 按相关度降序填充剩余预算
        for p in p2:
            if running + p.token_estimate <= budget.max_tokens:
                keep.append(p)
                running += p.token_estimate
            else:
                pointers.append(_to_pointer(p, "超出 P1+P2 共享预算"))

        # P3: 始终 pointer，不直接注入
        for p in p3:
            pointers.append(_to_pointer(p, "P3 始终 pointer"))

        was_trimmed = len(pointers) > 0
        return keep, pointers, was_trimmed


# ── 裁剪辅助 ──────────────────────────────────────────

def _to_pointer(piece: ContextPiece, reason: str = "") -> TrimmedPointer:
    """将 ContextPiece 转为 TrimmedPointer。"""
    return TrimmedPointer(
        id=f"{piece.source}:{piece.path}" if piece.path else piece.source,
        type=piece.source,
        summary=piece.content[:120] if piece.content else piece.path,
        why_relevant=reason or piece.metadata.get("stage_relevance", ""),
        estimated_tokens=piece.token_estimate,
        retrieval_hint=_build_retrieval_hint(piece),
    )


def _build_retrieval_hint(piece: ContextPiece) -> str:
    """根据 source 类型生成回捞提示。"""
    source = piece.source
    path = piece.path
    if source == "file":
        return f"Read {path}"
    elif source == "codegraph":
        return f"codegraph_explore '{path}'"
    elif source == "memory":
        return f"Read .ai/memory/entries/{path}.md"
    elif source == "run_state":
        return f"Check run_state.{path}"
    return f"检索 {source}:{path}"
