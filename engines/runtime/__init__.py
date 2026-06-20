"""运行时引擎模块。

提供 Loop 核心循环引擎，驱动 RunState 完成从任意入口到退出阶段的循环流程。
支持完整循环和子循环（test-only / dev-only / spec-only 等独立能力）。
"""

from .daemon import LoopDaemon
from .git_sync import GitSyncer, SyncResult
from .loop_runner import (
    LoopRunner,
    SUB_LOOP_PRESETS,
    create_sub_loop,
    list_sub_loops,
)
from .direct_executor import DirectExecutor
from .worktree_isolator import WorktreeIsolator, WorktreeResult
from .stage_handlers import (
    DEFAULT_FLOW,
    DIRECT_STAGES,
    STANDARD_STAGES,
    StageHandler,
    DirectExecuteHandler,
    ExecuteHandler,
    IntakeHandler,
    MemoryHandler,
    PlanHandler,
    RepairHandler,
    ReviewHandler,
    SpecHandler,
    VerifyHandler,
    default_handlers,
    is_terminal,
    next_stage,
)

__all__ = [
    # Git 同步
    "GitSyncer",
    "SyncResult",
    # 隔离与守护
    "WorktreeIsolator",
    "WorktreeResult",
    "LoopDaemon",
    # 引擎
    "LoopRunner",
    "DirectExecutor",
    # 子循环工厂
    "create_sub_loop",
    "list_sub_loops",
    "SUB_LOOP_PRESETS",
    # 阶段处理器
    "StageHandler",
    "IntakeHandler",
    "SpecHandler",
    "PlanHandler",
    "ExecuteHandler",
    "VerifyHandler",
    "RepairHandler",
    "ReviewHandler",
    "MemoryHandler",
    "DirectExecuteHandler",
    "default_handlers",
    # 流转工具
    "DEFAULT_FLOW",
    "STANDARD_STAGES",
    "DIRECT_STAGES",
    "next_stage",
    "is_terminal",
]
