"""Spec 质量门禁模块。

提供:
- SpecQualityGate: 模糊词检测 + 完整性检查 + 质量评分
- SpecEntry: Spec 数据模型（gate 输入）
- SpecQualityReport: 质量报告
- SpecContextPacket: Spec 生成上下文包（架构 §8.5.3）
- BrainstormResult: Brainstorm 输出结构（架构 §8.5.2）
- ImpactDomain: 影响域判断
"""

from engines.spec.models import (
    BrainstormResult,
    FuzzyWord,
    ImpactDomain,
    SpecContextPacket,
    SpecEntry,
    SpecQualityReport,
    SpecSection,
)
from engines.spec.quality_gate import SpecQualityGate

__all__ = [
    "SpecQualityGate",
    "SpecEntry",
    "SpecQualityReport",
    "SpecSection",
    "FuzzyWord",
    "SpecContextPacket",
    "BrainstormResult",
    "ImpactDomain",
]
