"""状态序列化工具。

将 RunState / Checkpoint 等核心模型与 JSON 互转，
用于检查点持久化、跨阶段传递和 .ai/ 目录落盘。
"""

# 启用延迟注解求值
from __future__ import annotations

# 导入 datetime 用于类型检查
from datetime import datetime
# 导入 Any 类型
from typing import Any

# 从 models 模块导入需要序列化的核心模型类
from .models import Checkpoint, RunState


# 将 RunState 对象序列化为 JSON 字符串
# 参数 state: 要序列化的 RunState 实例
# 参数 indent: JSON 缩进级别，默认 2 个空格，None 表示紧凑模式
# 返回值: JSON 格式的字符串
def run_state_to_json(state: RunState, *, indent: int | None = 2) -> str:
    """将 RunState 序列化为 JSON 字符串。"""
    # 调用 Pydantic 的 model_dump_json 方法，自动处理日期等复杂类型
    return state.model_dump_json(indent=indent)


# 从 JSON 字符串或字典反序列化为 RunState 对象
# 参数 data: JSON 字符串、字节串或已解析的字典
# 返回值: 反序列化后的 RunState 实例
def run_state_from_json(data: str | bytes | dict[str, Any]) -> RunState:
    """从 JSON 字符串 / 字典反序列化为 RunState。"""
    # 如果已经是字典，直接验证并构建模型
    if isinstance(data, dict):
        return RunState.model_validate(data)
    # 如果是字符串或字节串，先解析 JSON 再验证
    return RunState.model_validate_json(data)


# 将 Checkpoint 对象序列化为 JSON 字符串
# 参数 cp: 要序列化的 Checkpoint 实例
# 参数 indent: JSON 缩进级别，None 表示紧凑模式
# 返回值: JSON 格式的字符串
def checkpoint_to_json(cp: Checkpoint, *, indent: int | None = None) -> str:
    """将单个检查点序列化为 JSON 字符串。"""
    return cp.model_dump_json(indent=indent)


# 从 JSON 字符串或字典反序列化为 Checkpoint 对象
# 参数 data: JSON 字符串、字节串或已解析的字典
# 返回值: 反序列化后的 Checkpoint 实例
def checkpoint_from_json(data: str | bytes | dict[str, Any]) -> Checkpoint:
    """从 JSON 字符串 / 字典反序列化为 Checkpoint。"""
    # 如果已经是字典，直接验证并构建模型
    if isinstance(data, dict):
        return Checkpoint.model_validate(data)
    # 如果是字符串或字节串，先解析 JSON 再验证
    return Checkpoint.model_validate_json(data)