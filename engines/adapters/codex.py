"""CodexAdapter —— 把 AI Coding Loop 映射到 Codex CLI。

生成 .codex/instructions.md、.codex/skills/aicode-xxx/karpathy.md、.codex/aicode/、
.codex/mcp.json。
命令前缀 /，skill 格式为目录+karpathy.md。
"""

# 启用延迟注解求值
from __future__ import annotations

# 导入 json 用于配置序列化
import json
# 导入 logging 用于日志记录
import logging
# 导入 datetime 用于时间戳
from datetime import datetime
# 导入 Path 用于文件路径操作
from pathlib import Path
# 导入 Any 类型
from typing import Any

# 从 base 模块导入基类和 McpServerDef 数据类
from engines.adapters.base import McpServerDef, ToolAdapter
# 从 init.models 导入 ProjectProfile 类型
from engines.init.models import ProjectProfile

# 创建当前模块的日志记录器
logger = logging.getLogger(__name__)


# Codex CLI 适配器类
class CodexAdapter(ToolAdapter):
    """Codex CLI 适配器。"""

    # ── 元信息 ──

    # 工具标识
    tool_id: str = "codex"

    # 工具显示名属性
    @property
    def display_name(self) -> str:
        return "Codex CLI"

    # ── 路径 ──

    # 主配置文件路径：.codex/instructions.md
    @property
    def main_config_path(self) -> str:
        return ".codex/instructions.md"

    # 规则文件目录：.codex/rules
    @property
    def rules_dir(self) -> str:
        return ".codex/rules"

    # AI Coding Loop 资产目录：.codex/aicode
    @property
    def aicode_dir(self) -> str:
        return ".codex/aicode"

    # Skills 目录：.codex/skills
    @property
    def skills_dir(self) -> str:
        return ".codex/skills"

    # ── 命令/钩子 ──

    # 命令前缀：/
    @property
    def command_prefix(self) -> str:
        return "/"

    # 是否支持 hooks 机制：是
    @property
    def supports_hooks(self) -> bool:
        return True

    # hooks 配置文件路径：hooks/hooks-codex.json
    @property
    def hooks_config_path(self) -> str | None:
        return "hooks/hooks-codex.json"

    # MCP 配置文件路径：.codex/mcp.json
    @property
    def mcp_config_path(self) -> str | None:
        return ".codex/mcp.json"

    # Skill 文件格式：目录 + skill.md 文件
    @property
    def skill_format(self) -> str:
        return "dir_with_skill_md"

    # ── 模板变量 ──

    # 模板变量映射：定义占位符到实际值的映射
    @property
    def template_vars(self) -> dict[str, str]:
        return {
            "plugin_root": "${PLUGIN_ROOT}",
            "engines_cmd": "bash ${PLUGIN_ROOT}/engines/run.sh",
            "engines_cmd_win": "%PLUGIN_ROOT%\\engines\\run.bat",
            "cmd_prefix": self.command_prefix,
            "context_var": "${PLUGIN_ROOT}",
            "aicode_dir": ".codex/aicode",
            "mcp_call": "通过 Codex MCP 工具调用",
            "tool_name": self.display_name,
            "tool_name_lower": self.tool_id,
        }

    # ── 已有文件检测 ──

    # 需要检测的文件/目录模式列表
    _file_patterns = [".codex/instructions.md", ".codex/", ".codex/rules/"]

    # ── 内容生成 ──

    # 生成 .codex/instructions.md 自举引导文件
    # 参数 profile: 项目配置信息
    # 参数 providers: Provider 列表（可选）
    # 返回值: 自举引导 prompt 字符串
    def render_main_config(
        self, profile: ProjectProfile, providers: list[Any] | None = None
    ) -> str:
        """生成 .codex/instructions.md 自举引导文件 —— Python 只写 prompt，AI 负责生成完整配置。"""
        # 调用基类的 _render_bootstrap_prompt 方法生成自举引导内容
        return self._render_bootstrap_prompt(
            project_name=profile.project_name,
            tool_display_name=self.display_name,
            main_config_path=self.main_config_path,
            rules_dir=self.rules_dir,
            command_prefix=self.command_prefix,
        )

    # ── MCP 配置 ──

    # 生成 Codex 格式的 MCP 配置
    # 参数 servers: MCP Server 定义列表
    # 返回值: Codex 格式的 MCP 配置字典
    def generate_mcp_config(self, servers: list[McpServerDef]) -> dict[str, Any]:
        """生成 Codex 格式的 MCP 配置。

        Codex 格式与 Claude 类似，但多一个 type 字段。
          {"mcpServers": {"name": {"type": "stdio", "command": "npx", "args": [...]}}}
        """
        mcp_servers: dict[str, dict] = {}
        # 遍历所有 MCP Server 定义
        for s in servers:
            # Codex 格式需要 type: "stdio" 字段
            entry: dict = {"type": "stdio", "command": s.command, "args": s.args}
            # 如果有环境变量，添加到配置中
            if s.env:
                entry["env"] = s.env
            mcp_servers[s.name] = entry
        return {"mcpServers": mcp_servers}

    # ── Hooks ──

    # 生成 hooks 配置（Codex 暂无 hook 机制）
    # 参数 providers: Provider 列表
    # 返回值: 空字典
    def generate_hooks(self, providers: list[Any]) -> dict[str, Any]:
        """Codex 暂无 hook 机制。"""
        return {}

    # ── 安装 ──

    # 执行 Codex 的安装步骤
    # 参数 project_root: 项目根目录
    # 参数 plugin_root: 引擎插件根目录
    # 参数 providers: Provider 列表（可选）
    # 返回值: 安装结果字典
    def install(
        self,
        project_root: Path,
        plugin_root: Path,
        providers: list[Any] | None = None,
        profile: ProjectProfile | None = None,
    ) -> dict[str, Any]:
        """Codex 安装：MCP 配置 / loop-config.json / karpathy.md 规则。"""
        created: list[str] = []
        skipped: list[str] = []
        errors: list[str] = []

        root = Path(project_root)

        # 1. MCP 配置
        # 收集所有 provider 的 MCP Server 定义
        all_servers: list[McpServerDef] = []
        for pv in (providers or []):
            all_servers.extend(pv.get_mcp_servers())
        # 如果有 MCP Server，生成并写入配置文件
        if all_servers:
            mcp_dst = root / ".codex/mcp.json"
            mcp_dst.parent.mkdir(parents=True, exist_ok=True)
            mcp_config = self.generate_mcp_config(all_servers)
            mcp_dst.write_text(
                json.dumps(mcp_config, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            created.append(str(mcp_dst.relative_to(root)))

        # 2. loop-config.json
        loop_config_dst = root / ".ai" / "loop-config.json"
        loop_config_dst.parent.mkdir(parents=True, exist_ok=True)
        existing = {}
        if loop_config_dst.exists():
            try:
                existing = json.loads(loop_config_dst.read_text(encoding="utf-8"))
            except Exception:
                pass
        loop_config = {
            **existing,
            "target_tool": self.tool_id,
            **self.template_vars,
        }
        defaults = self.default_loop_config()
        for key in defaults:
            if key not in loop_config:
                loop_config[key] = defaults[key]

        # ── 自动检测前端项目，填充 test 配置 ─────────────────────
        from engines.adapters.base import _auto_fill_test_config
        _auto_fill_test_config(root, defaults, loop_config)

        loop_config_dst.write_text(
            json.dumps(loop_config, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        action = "updated" if existing else "created"
        created.append(f"{str(loop_config_dst.relative_to(root))} ({action})")

        # 3. Karpathy 行为准则 — 从插件源码原封不动拷贝，不让 AI 发挥
        karpathy_src = Path(plugin_root) / "skills" / "andrej-karpathy" / "karpathy.md"
        karpathy_dst = root / self.rules_dir / "karpathy.md"
        if karpathy_src.exists():
            karpathy_dst.parent.mkdir(parents=True, exist_ok=True)
            # 文件不存在时才拷贝，避免覆盖已有文件
            if not karpathy_dst.exists():
                karpathy_dst.write_text(
                    karpathy_src.read_text(encoding="utf-8"), encoding="utf-8"
                )
                created.append(str(karpathy_dst.relative_to(root)))
            else:
                skipped.append(str(karpathy_dst.relative_to(root)))
                logger.info("karpathy.md already exists, skipping")
        else:
            logger.warning("karpathy karpathy.md not found at %s, skipping", karpathy_src)

        # 返回安装结果
        return {
            "success": len(errors) == 0,
            "files_created": created,
            "files_skipped": skipped,
            "errors": errors,
        }