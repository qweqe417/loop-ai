"""ClaudeCodeAdapter —— 把 AI Coding Loop 映射到 Claude Code。

生成 CLAUDE.md、.claude/rules/、.claude/aicode/、.claude/commands/、
hooks/hooks.json、.claude/mcp.json。
命令前缀 /，skill 格式为单个 .md 文件。
"""

# 启用延迟注解求值
from __future__ import annotations

# 导入 json 用于 MCP 和 hooks 配置的序列化
import json
# 导入 logging 用于日志记录
import logging
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


# Claude Code 适配器类
class ClaudeCodeAdapter(ToolAdapter):
    """Claude Code 适配器。"""

    # ── 元信息 ──

    # 工具标识
    tool_id: str = "claude_code"

    # 工具显示名属性
    @property
    def display_name(self) -> str:
        return "Claude Code"

    # ── 路径 ──

    # 主配置文件路径：CLAUDE.md
    @property
    def main_config_path(self) -> str:
        return "CLAUDE.md"

    # 规则文件目录：.claude/rules
    @property
    def rules_dir(self) -> str:
        return ".claude/rules"

    # AI Coding Loop 资产目录：.claude/aicode
    @property
    def aicode_dir(self) -> str:
        return ".claude/aicode"

    # Skills 目录：.claude/skills
    @property
    def skills_dir(self) -> str:
        return ".claude/skills"

    # ── 命令/钩子 ──

    # 命令前缀：/
    @property
    def command_prefix(self) -> str:
        return "/"

    # 是否支持 hooks 机制：是
    @property
    def supports_hooks(self) -> bool:
        return True

    # hooks 配置文件路径：hooks/hooks.json
    @property
    def hooks_config_path(self) -> str | None:
        return "hooks/hooks.json"

    # MCP 配置文件路径：.claude/mcp.json
    @property
    def mcp_config_path(self) -> str | None:
        return ".claude/mcp.json"

    # Skill 文件格式：单个 .md 文件
    @property
    def skill_format(self) -> str:
        return "single_md"

    # ── 模板变量 ──

    # 模板变量映射：定义占位符到实际值的映射
    @property
    def template_vars(self) -> dict[str, str]:
        return {
            "plugin_root": "${CLAUDE_PLUGIN_ROOT}",
            "engines_cmd": "bash ${CLAUDE_PLUGIN_ROOT}/engines/run.sh",
            "engines_cmd_win": "%CLAUDE_PLUGIN_ROOT%\\engines\\run.bat",
            "cmd_prefix": self.command_prefix,
            "context_var": "${CLAUDE_PLUGIN_ROOT}",
            "aicode_dir": ".claude/aicode",
            "mcp_call": "通过 Claude MCP 工具调用",
            "tool_name": self.display_name,
            "tool_name_lower": self.tool_id,
        }

    # ── 已有文件检测 ──

    # 需要检测的文件/目录模式列表
    _file_patterns = ["CLAUDE.md", ".claude/", ".claude/rules/"]

    # ── 内容生成 ──

    # 生成 CLAUDE.md 自举引导文件
    # 参数 profile: 项目配置信息
    # 参数 providers: Provider 列表（可选）
    # 返回值: 自举引导 prompt 字符串
    def render_main_config(
        self, profile: ProjectProfile, providers: list[Any] | None = None
    ) -> str:
        """生成 CLAUDE.md 自举引导文件 —— Python 只写 prompt，AI 负责生成完整配置。"""
        # 调用基类的 _render_bootstrap_prompt 方法生成自举引导内容
        return self._render_bootstrap_prompt(
            project_name=profile.project_name,
            tool_display_name=self.display_name,
            main_config_path=self.main_config_path,
            rules_dir=self.rules_dir,
            command_prefix=self.command_prefix,
        )

    # ── MCP 配置 ──

    # 生成 Claude Code 格式的 MCP 配置
    # 参数 servers: MCP Server 定义列表
    # 返回值: Claude Code 格式的 MCP 配置字典
    def generate_mcp_config(self, servers: list[McpServerDef]) -> dict[str, Any]:
        """生成 Claude Code 格式的 MCP 配置。

        Claude Code 格式:
          {"mcpServers": {"name": {"command": "npx", "args": [...], "env": {...}}}}
        """
        mcp_servers: dict[str, dict] = {}
        # 遍历所有 MCP Server 定义，构造配置字典
        for s in servers:
            # 构建单个 server 的配置条目
            entry: dict = {"command": s.command, "args": s.args}
            # 如果有环境变量，添加到配置中
            if s.env:
                entry["env"] = s.env
            # 如果有描述，添加到配置中
            if s.description:
                entry["description"] = s.description
            mcp_servers[s.name] = entry
        return {"mcpServers": mcp_servers}

    # ── Hooks ──

    # 生成 Claude Code hooks 配置
    # 参数 providers: Provider 列表
    # 返回值: hooks 配置字典
    def generate_hooks(self, providers: list[Any]) -> dict[str, Any]:
        """生成 Claude Code hooks 配置（hooks/hooks.json）。

        合并所有 provider 的 hook 声明。
        自动剥离 `_` 前缀的内部元数据字段（如 _throttle_seconds）。
        """
        hooks: dict[str, list] = {}

        # 遍历所有 provider，收集其 hook 声明
        for pv in (providers or []):
            pv_hooks = pv.get_hooks()
            # 遍历每个事件及其 handler 列表
            for event, handlers in pv_hooks.items():
                if event not in hooks:
                    hooks[event] = []
                for h in handlers:
                    rendered = {}
                    # 遍历 handler 的每个键值对
                    for k, v in h.items():
                        # 剥离内部元数据字段（_ 前缀不写入 hooks JSON）
                        if k.startswith("_"):
                            continue
                        # 如果是字符串，进行模板渲染
                        if isinstance(v, str):
                            rendered[k] = self.render_skill(v)
                        else:
                            rendered[k] = v
                    # 跳过被完全剥离的空 handler
                    if rendered:  # 跳过被完全剥离的空 handler
                        hooks[event].append(rendered)

        # 添加默认的 SessionStart hook
        if "SessionStart" not in hooks:
            hooks["SessionStart"] = []
        # 在 SessionStart 时自动加载项目地图
        hooks["SessionStart"].append({
            "matcher": "startup|clear|compact",
            "hooks": [
                {
                    "type": "command",
                    "command": self.render_skill(
                        "{engines_cmd} context project-map --format json 2>/dev/null"
                    ),
                    "async": False,
                }
            ],
        })

        return {"hooks": hooks}

    # ── 安装 ──

    # 执行 Claude Code 的安装步骤
    # 参数 project_root: 项目根目录
    # 参数 plugin_root: 引擎插件根目录
    # 参数 providers: Provider 列表（可选）
    # 返回值: 安装结果字典 {"success": bool, "files_created": [...], "files_skipped": [...], "errors": [...]}
    def install(
        self,
        project_root: Path,
        plugin_root: Path,
        providers: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Claude Code 安装：MCP 配置 / loop-config.json / karpathy.md 规则。"""
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
            mcp_dst = root / self.mcp_config_path  # type: ignore[arg-type]
            mcp_dst.parent.mkdir(parents=True, exist_ok=True)
            mcp_config = self.generate_mcp_config(all_servers)
            mcp_dst.write_text(
                json.dumps(mcp_config, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            created.append(str(mcp_dst.relative_to(root)))

        # 2. loop-config.json（运行时 CLI 读取，知道当前工具和命令格式）
        loop_config_dst = root / ".ai" / "loop-config.json"
        loop_config_dst.parent.mkdir(parents=True, exist_ok=True)
        # 合并已有配置 + 新默认值，不覆盖用户手动修改的内容
        existing = {}
        if loop_config_dst.exists():
            try:
                existing = json.loads(loop_config_dst.read_text(encoding="utf-8"))
            except Exception:
                pass
        loop_config = {
            **existing,  # 已有值优先
            "target_tool": self.tool_id,
            **self.template_vars,
        }
        # 确保 auth 等默认值存在（如果用户没配）
        defaults = self.default_loop_config()
        for key in defaults:
            if key not in loop_config:
                loop_config[key] = defaults[key]
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
                karpathy_dst.write_text(karpathy_src.read_text(encoding="utf-8"), encoding="utf-8")
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