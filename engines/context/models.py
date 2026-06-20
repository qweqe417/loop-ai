"""Context 数据模型。

Context Piece 是最小上下文单元；ContextBundle 是单个阶段的完整上下文包；
ContextBudget 控制每个阶段的 token 上限，防止上下文爆炸。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from engines.state.enums import StageType


# ── 上下文片段 ───────────────────────────────────────────────────

class ContextPiece(BaseModel):
    """单条上下文片段 —— 一个文件 / 一个 codegraph 结果 / 一条 memory。

    所有 Source 都返回 ContextPiece 列表，由 Router 按优先级拼装。
    """

    source: str = Field(description="来源: file / codegraph / memory / run_state / project_map")
    path: str = Field(default="", description="文件路径 / 符号名 / memory ID")
    content: str = Field(default="", description="实际内容（可能是摘要，不一定是全文）")
    token_estimate: int = Field(default=0, description="粗略 token 数")
    priority: int = Field(default=2, description="1=必须保底, 2=重要增强, 3=补充（超预算时优先裁剪）")
    metadata: dict = Field(default_factory=dict, description="额外信息 {lines, stage_relevance, snippet_type, ...}")


# ── Token 预算 ────────────────────────────────────────────────────

class ContextBudget(BaseModel):
    """单阶段 Token 预算 —— 每个阶段都有自己的上限。

    超过上限时，Router 从 priority=3 开始裁剪，直到回到预算内。
    """

    stage: StageType = Field(description="适用阶段")
    max_tokens: int = Field(default=3000, description="该阶段最大 token 数")
    min_priority_keep: int = Field(default=2, description="最少保留到哪个优先级（1=只留必须, 3=全留）")

    @classmethod
    def defaults(cls) -> dict[StageType, "ContextBudget"]:
        """返回所有阶段的默认预算。"""
        return {
            StageType.INTAKE:         cls(stage=StageType.INTAKE,         max_tokens=1500, min_priority_keep=1),
            StageType.SPEC:           cls(stage=StageType.SPEC,           max_tokens=2500, min_priority_keep=1),
            StageType.PLAN:           cls(stage=StageType.PLAN,           max_tokens=3000, min_priority_keep=1),
            StageType.EXECUTE:        cls(stage=StageType.EXECUTE,        max_tokens=4000, min_priority_keep=1),
            StageType.DIRECT_EXECUTE: cls(stage=StageType.DIRECT_EXECUTE, max_tokens=2500, min_priority_keep=1),
            StageType.VERIFY:         cls(stage=StageType.VERIFY,         max_tokens=2500, min_priority_keep=1),
            StageType.REPAIR:         cls(stage=StageType.REPAIR,         max_tokens=3500, min_priority_keep=1),
            StageType.REVIEW:         cls(stage=StageType.REVIEW,         max_tokens=3000, min_priority_keep=1),
            StageType.MEMORY:         cls(stage=StageType.MEMORY,         max_tokens=2000, min_priority_keep=1),
        }


# ── 上下文包 ──────────────────────────────────────────────────────

class ContextBundle(BaseModel):
    """单个阶段的完整上下文包 —— Router.route() 的返回值。

    pieces 已按优先级排序、已按预算裁剪，可直接注入 AI 会话。
    """

    stage: StageType = Field(description="目标阶段")
    pieces: list[ContextPiece] = Field(default_factory=list, description="上下文片段列表（已排序、已裁剪）")
    total_tokens: int = Field(default=0, description="总估算 token 数")
    budget_max: int = Field(default=0, description="该阶段预算上限")
    budget_used_pct: float = Field(default=0.0, description="预算使用率 (0-100)")
    trimmed: bool = Field(default=False, description="是否因超预算做过裁剪")

    def render(self) -> str:
        """把上下文包渲染为一段可注入 AI 会话的文本。"""
        parts: list[str] = []
        for piece in self.pieces:
            parts.append(f"<!-- source={piece.source} path={piece.path} -->\n{piece.content}")
        return "\n\n".join(parts)
