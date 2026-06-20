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

from .models import ContextBudget, ContextBundle, ContextPiece
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
        3. 按 priority 排序
        4. 累加 token，超预算时从 priority=3 开始裁剪
        5. 组装 ContextBundle
        """
        strategy = STAGE_STRATEGIES.get(stage)
        if strategy is None:
            logger.warning("No strategy for stage %s, returning empty bundle", stage)
            return ContextBundle(stage=stage)

        # 1. 收集
        pieces = strategy(self, run_state)

        # 2. 排序: priority 升序 (1 在前), 同 priority 按 token_estimate 升序
        pieces.sort(key=lambda p: (p.priority, p.token_estimate))

        # 3. 裁剪
        budget = self._budgets.get(stage)
        if budget is None:
            budget = ContextBudget(stage=stage, max_tokens=3000)

        trimmed_pieces, was_trimmed = self._trim(pieces, budget)

        # 4. 计算 token
        total = sum(p.token_estimate for p in trimmed_pieces)

        logger.info(
            "ContextRouter: stage=%s pieces=%d/%d tokens=%d/%d trimmed=%s",
            stage.value,
            len(trimmed_pieces),
            len(pieces),
            total,
            budget.max_tokens,
            was_trimmed,
        )

        return ContextBundle(
            stage=stage,
            pieces=trimmed_pieces,
            total_tokens=total,
            budget_max=budget.max_tokens,
            budget_used_pct=round(total / budget.max_tokens * 100, 1) if budget.max_tokens else 0.0,
            trimmed=was_trimmed,
        )

    # ── 项目地图 ─────────────────────────────────────

    def build_project_map(self) -> ContextPiece:
        """构建项目地图。优先用 CodeGraph，fallback 到文件扫描。"""
        if self.codegraph.available:
            return self.codegraph.get_project_map()
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
    ) -> tuple[list[ContextPiece], bool]:
        """按预算裁剪 pieces，按优先级分层处理。

        规则:
        - priority=1（min_priority_keep）始终保留，超预算时记录警告
        - priority=2 按 token 升序填充剩余预算，超出部分丢弃
        - priority=3 仅在前两层未耗尽预算时加入，超出部分丢弃
        """
        if not pieces:
            return [], False

        total = sum(p.token_estimate for p in pieces)
        if total <= budget.max_tokens:
            return list(pieces), False

        # 按优先级分层
        p1 = [p for p in pieces if p.priority == budget.min_priority_keep]
        p2 = [p for p in pieces if p.priority == budget.min_priority_keep + 1]
        p3 = [p for p in pieces if p.priority > budget.min_priority_keep + 1]

        # Priority 1: 始终保留
        keep: list[ContextPiece] = list(p1)
        running = sum(p.token_estimate for p in p1)

        if running > budget.max_tokens:
            logger.warning(
                "Priority-1 pieces alone exceed budget (%d > %d tokens), keeping all",
                running, budget.max_tokens,
            )

        # Priority 2: 按 token_estimate 升序填充剩余预算
        for p in sorted(p2, key=lambda x: x.token_estimate):
            if running + p.token_estimate > budget.max_tokens:
                continue
            keep.append(p)
            running += p.token_estimate

        # Priority 3: 仅当还有预算时加入
        for p in sorted(p3, key=lambda x: x.token_estimate):
            if running + p.token_estimate > budget.max_tokens:
                continue
            keep.append(p)
            running += p.token_estimate

        was_trimmed = len(keep) < len(pieces)
        return keep, was_trimmed
