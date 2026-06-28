"""ToolAdapter 抽象基类 —— 定义 AI 工具适配器的统一接口。

每个 AI 工具（Claude Code / Codex / Cursor）有各自的子类实现。
职责：工具原生文件路径、命令格式、MCP 配置格式、模板变量渲染。
"""

# 启用延迟注解求值，允许前向引用类型
from __future__ import annotations

# 导入 ABC 抽象基类和 abstractmethod 装饰器，用于定义抽象方法
from abc import ABC, abstractmethod
# 导入 dataclass 和 field 用于定义数据类
from dataclasses import dataclass, field
# 导入 Path 用于文件路径操作
from pathlib import Path
# 导入 TYPE_CHECKING 用于类型检查时的条件导入，避免循环导入
from typing import TYPE_CHECKING, Any

# 仅类型检查时导入 ProjectProfile，避免运行时循环导入
if TYPE_CHECKING:
    from engines.init.models import ProjectProfile


# MCP Server 定义数据类：完全工具无关的 MCP 服务器描述
@dataclass
class McpServerDef:
    """MCP Server 定义 —— 完全工具无关。

    ToolAdapter 负责翻译成具体工具的 MCP 配置格式。
    """

    # MCP 服务器名称
    name: str
    # 服务器描述
    description: str = ""
    # 启动命令，默认使用 npx
    command: str = "npx"
    # 命令行参数列表
    args: list[str] = field(default_factory=list)
    # 环境变量字典
    env: dict[str, str] = field(default_factory=dict)
    # 环境变量元数据：key -> {label, default}，供 CLI/UI 引导用户配置
    env_meta: dict[str, dict[str, str]] = field(default_factory=dict)
    # 是否为必需服务器
    required: bool = False


# AI 工具适配器抽象基类
class ToolAdapter(ABC):
    """AI 工具适配器抽象基类。

    子类必须实现：
      - 工具元信息 (tool_id, display_name)
      - 文件路径映射 (main_config_path, rules_dir, aicode_dir, commands_dir)
      - 命令格式 (command_prefix)
      - 模板变量 (template_vars)
      - Hook/MCP 支持声明
      - 内容渲染方法 (render_main_config)

    使用方式:
        adapter = ClaudeCodeAdapter()
        content = adapter.render_main_config(profile, providers)
        adapter.install_provider(superpowers_provider, project_root)
    """

    # ── 子类必须覆写的元信息 ──

    @property
    @abstractmethod
    def tool_id(self) -> str:
        """工具标识: "claude_code" / "codex" / "cursor" """
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """显示名: "Claude Code" / "Codex CLI" / "Cursor" """
        ...

    # ── 子类必须覆写的路径 ──

    @property
    @abstractmethod
    def main_config_path(self) -> str:
        """主配置文件: "CLAUDE.md" / ".codex/instructions.md" """
        ...

    @property
    @abstractmethod
    def rules_dir(self) -> str:
        """规则文件目录: ".claude/rules" / ".cursor/rules" """
        ...

    @property
    @abstractmethod
    def aicode_dir(self) -> str:
        """AI Coding Loop 资产目录: ".claude/aicode" / ".codex/aicode" """
        ...

    # ── 子类必须覆写的命令/钩子 ──

    @property
    @abstractmethod
    def command_prefix(self) -> str:
        """命令前缀: "/" for Claude/Codex, "@" for Cursor"""
        ...

    # ── Hook 支持 ──

    @property
    @abstractmethod
    def supports_hooks(self) -> bool:
        """是否支持 hooks 机制。"""
        ...

    @property
    @abstractmethod
    def hooks_config_path(self) -> str | None:
        """hooks 配置文件路径: "hooks/hooks.json" / None"""
        ...

    @property
    @abstractmethod
    def mcp_config_path(self) -> str | None:
        """MCP 配置文件路径: ".claude/mcp.json" / ".codex/mcp.json" / None"""
        ...

    @property
    @abstractmethod
    def skill_format(self) -> str:
        """Skill 文件格式:
        "single_md"          — .claude/skills/xxx.md（Claude Code）
        "dir_with_skill_md"  — .codex/skills/xxx/karpathy.md（Codex）
        "rule_md"            — .cursor/rules/xxx.md（Cursor）
        """
        ...

    # ── 子类必须覆写的模板变量 ──

    @property
    @abstractmethod
    def template_vars(self) -> dict[str, str]:
        """模板变量映射。

        Provider 的 skill 模板中用 {plugin_root}、{engines_cmd}、{cmd_prefix} 等占位符，
        Adapter 在这里定义每个占位符的具体值。

        必须包含的 key:
          - "plugin_root":   引擎根路径变量
          - "engines_cmd":   调用 engines/run.sh 的完整命令
          - "cmd_prefix":    命令前缀（/ 或 @）
          - "context_var":   Context Router 项目地图的注入方式
        """
        ...

    # ── 模板渲染 ──

    # 把 Provider 模板渲染成当前工具可用的 skill/rule 文件内容
    # 参数 template: 包含占位符 {key} 的模板字符串
    # 返回值: 替换占位符后的渲染结果
    def render_skill(self, template: str) -> str:
        """把 Provider 模板渲染成当前工具可用的 skill/rule 文件内容。

        替换 {key} 为 self.template_vars[key]。
        """
        result = template
        # 遍历所有模板变量，将 {key} 占位符替换为实际值
        for key, val in self.template_vars.items():
            result = result.replace(f"{{{key}}}", val)
        return result

    # ── 内容生成（子类必须实现） ──

    @abstractmethod
    def render_main_config(
        self, profile: ProjectProfile, providers: list[Any] | None = None
    ) -> str:
        """生成工具的主配置/指令文件内容（CLAUDE.md / instructions.md 等）。

        包含：
        - 项目技术栈摘要
        - 关键目录
        - AI 自行生成规范文件的指令
        - 命令入口
        """
        ...

    # ── MCP 配置生成 ──

    @abstractmethod
    def generate_mcp_config(self, servers: list[McpServerDef]) -> dict[str, Any]:
        """把 MCP Server 列表翻译成当前工具的原生 MCP 配置格式。

        Claude Code: {"mcpServers": {"mysql": {"command": "npx", "args": [...]}}}
        Codex:       {"mcpServers": {"mysql": {"type": "stdio", "command": "npx", ...}}}
        Cursor:      {".cursor/mcp.json": {...}}
        """
        ...

    # ── Hooks 生成 ──

    @abstractmethod
    def generate_hooks(self, providers: list[Any]) -> dict[str, Any]:
        """生成 hooks 配置（SessionStart 等）。

        无 hooks 机制的工具返回 {}。
        """
        ...

    # ── 安装 ──

    @staticmethod
    def default_loop_config() -> dict[str, Any]:
        """返回 loop-config.json 的默认值。

        各 adapter 的 install() 调用此方法获取基础配置，
        再叠加 target_tool + template_vars。

        注意：services 不写死启动命令，ServiceManager 会自动检测。
        用户只在自动检测不准确时才需手动配。
        """
        return {
            # ── 鉴权 ──
            "auth": {
                "token": "粘贴你的JWT token到这里",
            },
            # ── 测试目标（决定 verify 阶段走前端 E2E 还是后端场景）──
            # target: "backend"（默认）或 "frontend"
            "test": {
                "target": "backend",
                "test_dir": "tests",
                "dev_server": "http://localhost:3000",
                "dev_command": "npm run dev",
                "browsers": ["chromium"],
                "timeout": 60,
            },
            # ── 服务启停（可选，不配则 ServiceManager 自动检测）──
            # "services": [
            #     {
            #         "name": "app",
            #         "start": "mvn spring-boot:run",
            #         "health": "http://localhost:8080/actuator/health",
            #         "startup_timeout": 90,
            #     },
            # ],
        }

    @abstractmethod
    def install(
        self,
        project_root: Path,
        plugin_root: Path,
        providers: list[Any] | None = None,
        profile: "ProjectProfile | None" = None,
    ) -> dict[str, Any]:
        """执行工具特定的安装步骤。

        Args:
            project_root: 项目根目录
            plugin_root: 插件根目录
            providers: Provider 列表
            profile: 项目画像（可选，用于生成 test 配置等）

        Returns:
            {"created": [...], "skipped": [...], "errors": [...]}
        """
        ...


def _auto_fill_test_config(root: Path, defaults: dict, loop_config: dict) -> None:
    """自动检测前端项目并填充 test 配置。三个 adapter 共用此逻辑。"""
    has_playwright = (root / "playwright.config.ts").exists()
    has_vite_config = (root / "vite.config.ts").exists()
    has_package_json = (root / "package.json").exists()
    is_frontend = has_playwright and has_vite_config and has_package_json

    if is_frontend and "test" in defaults:
        import json as _json
        test_defaults = defaults["test"].copy()
        # 尝试从 package.json 读取 dev 命令和包管理器
        try:
            pkg = _json.loads((root / "package.json").read_text(encoding="utf-8"))
            scripts = pkg.get("scripts", {})
            dev_cmd = scripts.get("dev", "")
            if dev_cmd:
                test_defaults["dev_command"] = dev_cmd
            # 从 packageManager 字段读取（pnpm/yarn/bun）
            pkg_manager = pkg.get("packageManager", "")
            if pkg_manager:
                # "pnpm@9" -> "pnpm"
                pm = pkg_manager.split("@")[0]
                test_defaults["package_manager"] = pm
        except Exception:
            pass
        # 合并到 loop_config（已有值优先）
        if "test" not in loop_config:
            loop_config["test"] = test_defaults
        else:
            for k, v in test_defaults.items():
                if k not in loop_config["test"]:
                    loop_config["test"][k] = v
        import logging
        logging.getLogger(__name__).info("Frontend project detected, test config auto-filled")


    # ── 已有文件检测 ──

    # 子类覆写：无需实例化的文件模式列表（类级别常量）
    _file_patterns: list[str] = []

    # 类方法：返回需要检测是否已存在的文件/目录模式列表
    # 用于 init 阶段的冲突检测
    @classmethod
    def get_existing_file_patterns(cls) -> list[str]:
        """返回需要检测是否已存在的文件/目录模式列表。

        用于 init 阶段的冲突检测。优先使用 _file_patterns 类属性。
        """
        # 如果子类定义了 _file_patterns，直接返回
        if cls._file_patterns:
            return cls._file_patterns
        # 否则抛出未实现错误
        raise NotImplementedError(f"{cls.__name__} must define _file_patterns")

    # ── 共享工具方法 ──

    # 静态方法：向 lines 列表追加语言特定的规则（工具无关）
    # 参数 lines: 要追加到的行列表
    # 参数 profile: 项目配置信息，需包含 language 属性
    @staticmethod
    def _append_language_rules(lines: list[str], profile: Any) -> None:
        """向 lines 列表追加语言特定的规则（工具无关）。"""
        # 获取项目语言类型
        lang = getattr(profile, "language", "")
        # Python 项目的特定规则
        if lang == "python":
            lines.append("- 使用 pydantic v2 风格（model_validate 而非 dict()）")
            lines.append("- 异常使用项目统一异常类，不裸 raise")
            lines.append("- 遵循现有项目分层，不引入新的依赖模式")
        # Java 项目的特定规则
        elif lang == "java":
            lines.append("- 遵循现有 Controller/Service/Repository 分层")
            lines.append("- 异常使用 @ExceptionHandler 或项目统一异常处理")
            lines.append("- 测试使用 JUnit，不引入新的测试框架")
        # TypeScript/JavaScript 项目的特定规则
        elif lang in ("typescript", "javascript"):
            lines.append("- 遵循现有组件结构和命名约定")
            lines.append("- 使用项目的 ESLint/Prettier 配置")
            lines.append("- 测试使用项目已有测试框架")

    # 静态方法：复制文件，目标已存在时返回 False
    # 参数 src: 源文件路径
    # 参数 dst: 目标文件路径
    # 返回值: True 表示复制成功，False 表示目标已存在或复制失败
    @staticmethod
    def _copy_file(src: Path, dst: Path) -> bool:
        """复制文件，目标已存在时返回 False。"""
        import shutil
        try:
            # 目标已存在则跳过
            if dst.exists():
                return False
            # 确保目标目录存在
            dst.parent.mkdir(parents=True, exist_ok=True)
            # 复制文件（保留元数据）
            shutil.copy2(src, dst)
            return True
        except Exception:
            return False

    # ── 共享渲染方法 ──────────────────────────────────────

    # 静态方法：生成规则文件的引导 prompt
    # 参数 rules_dir: 规则文件目录路径
    # 返回值: 引导 AI 提取规则的 prompt 字符串
    @staticmethod
    def _render_rules_prompt(rules_dir: str) -> str:
        """生成规则文件的引导 prompt —— 引导 AI 从实际代码提取规则。"""
        return "\n".join([
            f"### `{rules_dir}/code-style.md`  ≤60 行",
            "从实际源码提取（翻 5-10 个文件找规律），每条规则附真实代码例子：",
            "- 命名约定：类/函数/变量/常量的实际命名模式，给 3+ 个实例",
            "- 文件组织：每个包/模块的职责和依赖方向",
            "- 异常处理：代码中实际用的异常类、何时用哪个、如何传播",
            "- 日志：实际使用的日志库和调用模式（不是 copy 配置）",
            "",
            f"### `{rules_dir}/testing.md`  ≤40 行",
            "从实际测试代码提取：",
            "- 测试框架和断言库（从依赖文件确认版本）",
            "- 测试文件命名约定和目录结构（与源码的对应关系）",
            "- Mock/Stub/Fixture 的实际使用模式（从现有测试找例子）",
            "- 测试运行命令（从 package.json/Makefile/tox.ini 等读取，确保可直接运行）",
            "",
            f"### `{rules_dir}/safety.md`  ≤30 行",
            "从项目配置提取：",
            "- 不应修改的文件/目录（配置、构建脚本、CI/CD、生成的代码）",
            "- 项目特有的禁止操作（对照 .gitignore 确认边界）",
            "- 修改边界：哪些模块可以改、哪些是外部接口不能动",
        ])

    # 静态方法：生成自举引导文件 —— Python 只写这个 prompt，AI 负责生成所有配置
    # 参数 project_name: 项目名称
    # 参数 tool_display_name: 工具显示名
    # 参数 main_config_path: 主配置文件路径
    # 参数 rules_dir: 规则文件目录
    # 参数 command_prefix: 命令前缀
    # 返回值: 自举引导 prompt 字符串
    @staticmethod
    def _render_bootstrap_prompt(
        project_name: str,
        tool_display_name: str,
        main_config_path: str,
        rules_dir: str,
        command_prefix: str,
    ) -> str:
        """生成自举引导文件 —— Python 只写这个 prompt，AI 负责生成所有配置。

        这是 AI Coding Loop 的"种子"文件。后续所有代码都按这些配置执行，
        所以 prompt 必须引导 AI 从实际代码中提取信息，写出精准、可操作、
        项目特有的配置。
        """
        # 生成规则文件 prompt 部分
        rules_section = ToolAdapter._render_rules_prompt(rules_dir)
        return "\n".join([
            f"# {project_name}",
            "",
            "> 本文件是 AI Coding Loop 的初始化引导文件。",
            f"> **你必须在首次处理任务时重写本文件**，并生成下列规则文件。",
            f"> 完成后本引导内容可删除。",
            "",
            "---",
            "",
            "## 初始化任务",
            "",
            f"在开始任何代码工作前，你需要完成 {tool_display_name} 的项目配置初始化。",
            "**每一步都必须基于实际项目代码，不得编造。**",
            "",
            "### 第 1 步：扫描项目，逐项记录",
            "",
            "| 检查项 | 从哪里看 |",
            "|--------|----------|",
            "| 语言/框架 | package.json / pyproject.toml / pom.xml / go.mod |",
            "| 包管理器 | 依赖文件 + lockfile |",
            "| 目录结构 | 列出顶层目录，确认源码/测试/资源/配置的实际位置 |",
            "| 构建命令 | Makefile / package.json scripts / setup.py |",
            "| 测试命令 | 从配置中读取实际命令，确保可复制粘贴直接运行 |",
            "| Lint/Format | .eslintrc / .ruff.toml / .prettierrc / checkstyle 等 |",
            "| 命名约定 | 翻 5-10 个源文件，提取实际的类名/函数名/变量名模式 |",
            "| 异常处理 | 搜索 raise/throw/catch，提取实际异常类和传播方式 |",
            "| 日志 | 搜索 log/logger，提取实际日志库和调用模式 |",
            "",
            "### 第 2 步：重写本文件",
            "",
            f"删除以上引导内容，将本文件重写为完整的 `{main_config_path}`。",
            "",
            "**写作要求（来自 Claude Code/Codex/Cursor 业界最佳实践）：**",
            "- 只写项目特有的东西，禁止通用建议（如\"遵循最佳实践\"\"编写清晰的代码\"）",
            "- 只写 AI 容易猜错、代码里读不出来的约定",
            "- 不抄 linter 配置里已有的规则",
            "- 每条命令可直接复制粘贴到终端运行",
            "- 每条规则必须能从项目代码中找到依据",
            "- 正面引导优先：\"使用 const\" 而非 \"不要用 var\"",
            "- 总长度控制在 80 行以内",
            "",
            "**必须包含的节：**",
            "",
            "1. **技术栈** — 语言 / 框架 / 包管理器（1 行）",
            "2. **关键目录** — 源码/测试/资源各 1 行",
            "3. **常用命令** — 构建、测试、lint，每行一条可运行命令",
            "4. **代码风格** — 命名约定（附真实例子）+ 文件组织 + 异常/日志约定",
            "5. **测试** — 框架名 + 运行命令 + 测试文件位置",
            "6. **架构约束** — 分层规则、模块依赖方向",
            "7. **禁止行为** — 项目特有的红线，从 .gitignore 和现有代码推断",
            "",
            "### 第 3 步：生成规则文件",
            "",
            "创建以下文件，严格按长度限制：",
            "",
            rules_section,
            "",
            "**规则文件写作原则（来自 golden-CLAUDE.md 等最佳实践）：**",
            "- 每条规则 3 部分：做什么 + 不这样做会怎样 + 为什么",
            "- 正面引导：\"使用 logger 模块\"而非\"不要用 console.log\"",
            "- 不写 README 式的长篇说明，只写 AI 需要知道的约束",
            "",
            "---",
            "",
            "## 质量检查",
            "",
            "生成完毕后，逐条确认（这些是 AI 配置文件的业界标准）：",
            "",
            "- [ ] 每条命令粘贴到终端能直接运行，不需要手动替换参数",
            "- [ ] 每条命名约定能从项目代码中找到 3 个以上实例",
            "- [ ] 没有\"建议\"\"推荐\"\"遵循最佳实践\"等模糊表述",
            "- [ ] 没有\"详见 xxx 文档\"——AI 看不到外部链接",
            "- [ ] 没有和本项目无关的通用规则",
            "- [ ] 没有 linter 配置里已有的规则",
            f"- [ ] `{rules_dir}/code-style.md` ≤ 60 行",
            f"- [ ] `{rules_dir}/testing.md` ≤ 40 行",
            f"- [ ] `{rules_dir}/safety.md` ≤ 30 行",
            f"- [ ] `{main_config_path}` ≤ 80 行",
            "",
            "> 初始化完成后本引导内容可删除。",
        ])

    # ── 共享工具方法 ──────────────────────────────────────────

    # 静态方法：深度合并 hooks 配置：同事件追加 handler，不删除已有的
    # 参数 existing: 已有的 hooks 配置字典
    # 参数 new: 新的 hooks 配置字典
    # 返回值: 合并后的 hooks 配置字典
    @staticmethod
    def _deep_merge_hooks(existing: dict, new: dict) -> dict:
        """深度合并 hooks 配置：同事件追加 handler，不删已有。"""
        # 如果没有已有配置，直接返回新配置的副本
        if not existing:
            return dict(new)
        # 如果没有新配置，直接返回已有配置的副本
        if not new:
            return dict(existing)
        # 复制已有配置作为基础
        merged = dict(existing)
        # 遍历新配置中的每个事件
        for event, handlers in new.items():
            # 如果事件不存在，初始化为空列表
            if event not in merged:
                merged[event] = []
            # 追加不重复的 handler
            for h in handlers:
                if h not in merged[event]:
                    merged[event].append(h)
        return merged