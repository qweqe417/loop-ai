"""init 模块 —— 项目初始化（aicode init）。

12 步初始化流程：**现在完全工具无关**。
1. 读取项目环境 → 2. 检测 AI 工具 → 3. 检测插件 → 4. 处理缺失
→ 5. 扫描项目结构 → 6. 识别代码规范 → 7. 识别测试方式 → 8. 识别外部资源
→ 9. 检测 Provider → 10. 通过 ToolAdapter 生成工具原生文件 → 11. 初始化 .ai 资产 → 12. 输出报告

目标工具通过 --target 参数选择（claude_code / codex / cursor）。
"""

# 导入项目画像数据模型
from .models import (
    CodeStyleProfile,
    InitReport,
    PluginInfo,
    ProjectProfile,
    ResourceInfo,
    ScanResult,
    ScannedDirectory,
)
# 导入项目扫描器
from .scanner import ProjectScanner
# 导入文件生成器
from .generator import FileGenerator
# 导入初始化流程编排器和工具适配器辅助函数
from .init_runner import InitRunner, get_adapter, get_available_tools

# 公开的 API 列表
__all__ = [
    # 编排器
    "InitRunner",
    # 扫描器
    "ProjectScanner",
    # 生成器
    "FileGenerator",
    # 适配器辅助
    "get_adapter",
    "get_available_tools",
    # 模型
    "ProjectProfile",
    "CodeStyleProfile",
    "ResourceInfo",
    "PluginInfo",
    "ScannedDirectory",
    "ScanResult",
    "InitReport",
]