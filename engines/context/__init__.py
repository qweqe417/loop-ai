"""context 模块 —— 渐进式上下文路由器（Context Router）。

按 Loop Engineering 的 8 个阶段，渐进式注入上下文，防止 Token 爆炸。
优先使用 CodeGraph MCP 工具作为代码索引引擎，fallback 到文件扫描。

用法:
    from engines.context import ContextRouter
    from engines.state import StageType

    router = ContextRouter(project_root="/path/to/project")
    bundle = router.route(stage=StageType.EXECUTE, run_state=state)

    # 注入 AI 会话
    print(bundle.render())
"""

from .models import ContextBudget, ContextBundle, ContextPiece
from .sources import CodeGraphSource, FileSource, MemorySource
from .strategies import STAGE_STRATEGIES
from .router import ContextRouter

__all__ = [
    # 路由器
    "ContextRouter",
    # 数据模型
    "ContextPiece",
    "ContextBundle",
    "ContextBudget",
    # 数据来源
    "FileSource",
    "CodeGraphSource",
    "MemorySource",
    # 策略表
    "STAGE_STRATEGIES",
]
