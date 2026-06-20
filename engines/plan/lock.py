"""Plan 锁定管理。

控制 Plan 生命周期状态:
  UNLOCKED → LOCKED → (EXECUTE) → REVIEW
                ↓
         CHANGE_REQUESTED → (批准/拒绝) → LOCKED / UNLOCKED
                ↓
            BREACHED → 需要人工介入

Lock 约束:
- LOCKED: 不允许修改 Plan，不允许修改允许文件列表
- CHANGE_REQUESTED: 等待审批，阻塞 EXECUTE
- BREACHED: 人工介入，可以 UNLOCK
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from .models import PlanChangeRequest, PlanContract, PlanLockState

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class PlanLock:
    """Plan 锁 —— 管理单个 Plan 的锁定状态和变更请求。

    用法:
        lock = PlanLock()
        lock.lock()                     # UNLOCKED → LOCKED
        lock.request_change(req)        # LOCKED → CHANGE_REQUESTED
        lock.approve_change()           # CHANGE_REQUESTED → LOCKED
        lock.reject_change()            # CHANGE_REQUESTED → LOCKED (回退)
        lock.breach("违反约束")         # 任意状态 → BREACHED
    """

    def __init__(self) -> None:
        self.state: PlanLockState = PlanLockState.UNLOCKED
        self._contract: PlanContract | None = None
        self._pending_change: PlanChangeRequest | None = None
        self._change_history: list[PlanChangeRequest] = []
        self._locked_at: str = ""
        self._breach_reason: str = ""

    # ── 状态查询 ───────────────────────────────────────────────

    @property
    def is_locked(self) -> bool:
        return self.state == PlanLockState.LOCKED

    @property
    def is_change_pending(self) -> bool:
        return self.state == PlanLockState.CHANGE_REQUESTED

    @property
    def is_breached(self) -> bool:
        return self.state == PlanLockState.BREACHED

    @property
    def pending_change(self) -> PlanChangeRequest | None:
        return self._pending_change

    @property
    def breach_reason(self) -> str:
        return self._breach_reason

    # ── 状态转换 ───────────────────────────────────────────────

    def lock(self, contract: PlanContract) -> None:
        """锁定 Plan → 不可修改。"""
        if self.state not in (PlanLockState.UNLOCKED,):
            logger.warning("PlanLock: 无法从 %s 转为 LOCKED", self.state.value)
            return
        self.state = PlanLockState.LOCKED
        self._contract = contract
        self._locked_at = datetime.now().isoformat()
        logger.info("PlanLock: LOCKED (task=%s)", contract.task_id)

    def request_change(self, request: PlanChangeRequest) -> None:
        """请求变更 Plan → 暂停执行，等待审批。"""
        if self.state != PlanLockState.LOCKED:
            logger.warning("PlanLock: 无法从 %s 请求变更", self.state.value)
            return
        self.state = PlanLockState.CHANGE_REQUESTED
        self._pending_change = request
        logger.info("PlanLock: CHANGE_REQUESTED (task=%s, reason=%s)",
                     request.task_id, request.reason[:60])

    def approve_change(self) -> None:
        """批准变更 → 更新 Plan，回到 LOCKED。"""
        if self.state != PlanLockState.CHANGE_REQUESTED:
            logger.warning("PlanLock: 无待审批变更")
            return
        if self._pending_change:
            self._pending_change.approved = True
            self._change_history.append(self._pending_change)
            # 更新合约预算
            if self._contract:
                self._contract.budget.max_files += self._pending_change.budget_delta
        self.state = PlanLockState.LOCKED
        self._pending_change = None
        logger.info("PlanLock: 变更已批准 → LOCKED")

    def reject_change(self) -> None:
        """拒绝变更 → 回退到 LOCKED，保留原 Plan。"""
        if self.state != PlanLockState.CHANGE_REQUESTED:
            return
        if self._pending_change:
            self._pending_change.approved = False
            self._change_history.append(self._pending_change)
        self.state = PlanLockState.LOCKED
        self._pending_change = None
        logger.info("PlanLock: 变更已拒绝 → LOCKED")

    def breach(self, reason: str) -> None:
        """Plan 违约 → 需要人工介入。"""
        self.state = PlanLockState.BREACHED
        self._breach_reason = reason
        logger.warning("PlanLock: BREACHED — %s", reason[:120])

    def unlock(self) -> None:
        """解锁 Plan → 仅 BREACHED 或 UNLOCKED 时可操作。"""
        if self.state == PlanLockState.LOCKED:
            logger.warning("PlanLock: LOCKED 状态下不可直接 UNLOCK，请先 breach")
            return
        if self.state == PlanLockState.CHANGE_REQUESTED:
            logger.warning("PlanLock: 有待审批变更，请先 approve 或 reject")
            return
        self.state = PlanLockState.UNLOCKED
        self._breach_reason = ""
        logger.info("PlanLock: UNLOCKED")

    # ── 快照 ───────────────────────────────────────────────────

    def snapshot(self) -> dict:
        """返回当前锁状态的快照。"""
        return {
            "state": self.state.value,
            "locked_at": self._locked_at,
            "breach_reason": self._breach_reason,
            "pending_change": (
                self._pending_change.model_dump()
                if self._pending_change else None
            ),
            "change_count": len(self._change_history),
        }
