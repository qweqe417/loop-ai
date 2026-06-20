"""AI 工具适配器 —— 把通用能力翻译成各工具原生格式。

每个 AI 工具一个子类：ClaudeCodeAdapter / CodexAdapter / CursorAdapter。
Provider 只声明语义，ToolAdapter 负责路径、变量、格式。
"""
