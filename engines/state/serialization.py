"""状态序列化工具。

将 RunState / Checkpoint 等核心模型与 JSON 互转，
用于检查点持久化、跨阶段传递和 .ai/ 目录落盘。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .models import Checkpoint, RunState


def run_state_to_json(state: RunState, *, indent: int | None = 2) -> str:
    """将 RunState 序列化为 JSON 字符串。"""
    return state.model_dump_json(indent=indent)


def run_state_from_json(data: str | bytes | dict[str, Any]) -> RunState:
    """从 JSON 字符串 / 字典反序列化为 RunState。"""
    if isinstance(data, dict):
        return RunState.model_validate(data)
    return RunState.model_validate_json(data)


def checkpoint_to_json(cp: Checkpoint, *, indent: int | None = None) -> str:
    """将单个检查点序列化为 JSON 字符串。"""
    return cp.model_dump_json(indent=indent)


def checkpoint_from_json(data: str | bytes | dict[str, Any]) -> Checkpoint:
    """从 JSON 字符串 / 字典反序列化为 Checkpoint。"""
    if isinstance(data, dict):
        return Checkpoint.model_validate(data)
    return Checkpoint.model_validate_json(data)
