"""AI Coding Loop - 统一 CLI 入口。

所有命令输出 JSON 到 stdout，日志输出到 stderr。
用法:
    bash engines/run.sh init --scan-only --format json
    bash engines/run.sh loop full --task "需求描述"
    bash engines/run.sh verify --scenario order-timeout --format json
"""

# 启用延迟注解求值
from __future__ import annotations

# 导入 argparse 用于命令行参数解析
import argparse
# 导入 json 用于 JSON 序列化输出
import json
# 导入 logging 用于日志记录
import logging
# 导入 sys 用于 stdout/stderr 输出和退出码
import sys
# 导入 time 用于计时
import time
# 导入 Path 用于文件路径操作
from pathlib import Path

# ── 强制 UTF-8 编码 ─────────────────────────────────────
# Windows 下 sys.stderr/stdout 默认使用 GBK 编码，中文日志会乱码。
# 通过 reconfigure 强制为 UTF-8 + replace 错误处理，确保所有平台一致。
for _stream_name in ("stdout", "stderr"):
    try:
        getattr(sys, _stream_name).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 计算项目根目录（当前文件所在目录的父目录）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# 将项目根目录添加到 Python 模块搜索路径
sys.path.insert(0, str(PROJECT_ROOT))


# ── 工具配置（CLI 多工具兼容）────────────────────────────────

# 读取项目根目录的 .ai/loop-config.json 配置文件
# 参数 project_root: 项目根目录
# 返回值: 配置字典，文件不存在或读取失败返回 None
def _load_loop_config(project_root: Path) -> dict | None:
    """读取项目根目录的 .ai/loop-config.json。"""
    config_path = project_root / ".ai" / "loop-config.json"
    # 配置文件不存在则返回 None
    if not config_path.exists():
        return None
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return None


# 自动检测当前项目的 AI 工具
# 参数 project_root: 项目根目录，默认为当前工作目录
# 返回值: 工具标识字符串（claude_code / codex / cursor）
def _detect_tool(project_root: Path | None = None) -> str:
    """自动检测当前项目的 AI 工具。

    优先级: loop-config.json > 文件探测 > 默认 claude_code
    """
    root = project_root or Path.cwd()
    # 首先尝试从 loop-config.json 读取
    config = _load_loop_config(root)
    if config:
        return config.get("target_tool", "claude_code")
    # 其次通过探测文件目录判断
    if (root / ".codex").exists():
        return "codex"
    if (root / ".cursor").exists():
        return "cursor"
    # 默认使用 Claude Code
    return "claude_code"


# 获取工具配置（engines_cmd / plugin_root 等）
# 参数 project_root: 项目根目录
# 参数 target_tool: 目标工具标识，不指定则自动检测
# 返回值: 工具配置字典
def _get_tool_config(
    project_root: Path | None = None, target_tool: str | None = None
) -> dict:
    """获取工具配置（engines_cmd / plugin_root 等）。

    优先从 loop-config.json 读取，fallback 到硬编码默认值。
    """
    root = project_root or Path.cwd()
    config = _load_loop_config(root) or {}
    tool = target_tool or config.get("target_tool", "claude_code")

    # 如果 loop-config.json 中已有该工具的配置，直接返回
    if config.get("target_tool") == tool and "engines_cmd" in config:
        return config

    # 各工具的默认配置
    defaults: dict[str, dict] = {
        "claude_code": {
            "target_tool": "claude_code",
            "engines_cmd": "bash ${CLAUDE_PLUGIN_ROOT}/engines/run.sh",
            "plugin_root": "${CLAUDE_PLUGIN_ROOT}",
        },
        "codex": {
            "target_tool": "codex",
            "engines_cmd": "bash ${CODEX_PLUGIN_ROOT}/engines/run.sh",
            "plugin_root": "${CODEX_PLUGIN_ROOT}",
        },
        "cursor": {
            "target_tool": "cursor",
            "engines_cmd": f"python {PROJECT_ROOT}/engines/run.sh",
            "plugin_root": str(PROJECT_ROOT),
        },
    }
    return defaults.get(tool, defaults["claude_code"])


# 日志全部走 stderr，stdout 只走 JSON
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s:%(message)s",
    stream=sys.stderr,
)
# 创建 CLI 模块的日志记录器
logger = logging.getLogger("cli")


# CLI 主入口函数
# 返回值: 退出码（0 表示成功，1 表示失败）
def main() -> int:
    # 创建顶级参数解析器
    parser = argparse.ArgumentParser(prog="aicode-loop")
    sub = parser.add_subparsers(dest="command")

    # ── init ─────────────────────────────────────
    # init 子命令：项目初始化
    p_init = sub.add_parser("init", help="项目初始化")
    p_init.add_argument("--target", default="claude_code",
                        choices=["claude_code", "codex", "cursor"],
                        help="目标 AI 工具 (默认: claude_code)")
    p_init.add_argument("--project-root", default="",
                        help="项目根目录，默认为当前工作目录")
    p_init.add_argument("--scan-only", action="store_true")
    p_init.add_argument("--generate", action="store_true")
    p_init.add_argument("--auto-confirm", action="store_true")
    p_init.add_argument("--assets-only", action="store_true",
                        help="仅生成 .ai/ 资产 + adapter 安装（AI 已生成配置文件后使用）")
    p_init.add_argument("--format", default="json")

    # ── loop ─────────────────────────────────────
    # loop 子命令：运行 Loop
    p_loop = sub.add_parser("loop", help="运行 Loop")
    p_loop.add_argument("mode", nargs="?", default="full",
                        choices=["full", "dev", "dev-verify", "dev-only", "gate", "verify-loop",
                                 "spec", "plan", "plan-only", "post-sdd", "direct-post-tdd",
                                 "verify", "review", "memory", "direct", "direct-only", "continue"])
    p_loop.add_argument("--task", default="")
    p_loop.add_argument("--state-file", default="")
    p_loop.add_argument("--result", default="", help="AI 提交的结果 JSON (仅 continue 模式)")
    p_loop.add_argument("--only", action="store_true", default=False,
                        help="仅生成代码，不验证/审查（仅 dev/direct 模式有效）")
    p_loop.add_argument("--target", default="", help="目标 AI 工具 (claude_code/codex/cursor)，默认自动检测")
    p_loop.add_argument("--scenario-dir", default="",
                        help="仅加载 .ai/scenarios/<dir> 下的场景（相对于 .ai/scenarios/）")
    p_loop.add_argument("--plan-file", default="",
                        help="指定 Plan 文件路径（相对于项目根目录），如 docs/plan/abc.md")
    p_loop.add_argument("--spec-file", default="",
                        help="指定 Spec 文件路径（相对于项目根目录），如 docs/spec/abc.md")
    p_loop.add_argument("--project-root", default="", help="项目根目录，默认当前目录")

    # ── verify ───────────────────────────────────
    # verify 子命令：场景验证
    p_verify = sub.add_parser("verify", help="场景验证")
    p_verify.add_argument("--scenario", default="")
    p_verify.add_argument("--format", default="json")
    p_verify.add_argument("--target", default="", help="目标 AI 工具，默认自动检测")

    # ── review ────────────────────────────────────
    # review 子命令：审查检查
    p_review = sub.add_parser("review", help="Review 审查检查")
    p_review.add_argument("action", nargs="?", default="check", choices=["check", "report"])
    p_review.add_argument("--diff", default="HEAD")
    p_review.add_argument("--format", default="json")
    p_review.add_argument("--target", default="", help="目标 AI 工具，默认自动检测")

    # ── memory ───────────────────────────────────
    # memory 子命令：记忆管理
    p_mem = sub.add_parser("memory", help="记忆管理")
    p_mem.add_argument("action", nargs="?", default="list",
                      choices=["list", "confirm", "deprecate", "cleanup", "search", "stats", "recall", "update"])
    p_mem.add_argument("--id", default="", help="记忆 ID（confirm/deprecate 时使用）")
    p_mem.add_argument("--keyword", default="")
    p_mem.add_argument("--keywords", default="", help="recall 关键词，逗号分隔")
    p_mem.add_argument("--stage", default="", help="recall 阶段")
    p_mem.add_argument("--limit", type=int, default=5, help="recall 返回上限")
    p_mem.add_argument("--format", default="json")
    p_mem.add_argument("--target", default="", help="目标 AI 工具，默认自动检测")
    p_mem.add_argument("--project-root", default="", help="项目根目录，默认当前目录")

    # ── context ──────────────────────────────────
    # context 子命令：上下文路由
    p_ctx = sub.add_parser("context", help="上下文路由")
    p_ctx.add_argument("action", nargs="?", default="route", choices=["route", "project-map"])
    p_ctx.add_argument("--stage", default="intake")
    p_ctx.add_argument("--state-file", default="")
    p_ctx.add_argument("--format", default="json")
    p_ctx.add_argument("--target", default="", help="目标 AI 工具，默认自动检测")
    p_ctx.add_argument("--project-root", default="", help="项目根目录，默认当前目录")

    # ── scenario ──────────────────────────────────
    p_sc = sub.add_parser("scenario", help="场景校验：验证 Scenario YAML 格式")
    p_sc.add_argument("action", nargs="?", default="validate", choices=["validate"])
    p_sc.add_argument("--file", default="", help="YAML 文件路径")
    p_sc.add_argument("--dir", default="", help=".ai/scenarios/ 目录路径")
    p_sc.add_argument("--coverage", default="", help="docs/spec/<feature>.md 路径，生成需求覆盖矩阵")
    p_sc.add_argument("--project-root", default="", help="项目根目录，默认当前目录")

    # ── status ───────────────────────────────────
    # status 子命令：检查引擎状态
    sub.add_parser("status", help="检查引擎状态")

    # ── data ─────────────────────────────────────
    p_data = sub.add_parser("data", help="数据源操作：通过已配置的适配器查询/写入")
    p_data.add_argument("action", nargs="?", default="query", choices=["query", "execute", "list"])
    p_data.add_argument("--source", default="", help="数据源名（loop-config.json data_sources 的 key）")
    p_data.add_argument("--target", default="", help="操作目标（MySQL=SQL语句, Redis=key, ES=查询JSON, MQ=队列名）")
    p_data.add_argument("--value", default=None, help="写入值（Redis SET/HSET, MQ publish 等场景）")
    p_data.add_argument("--sql", default="", help="SQL 语句（等同于 --target，向后兼容）")
    p_data.add_argument("--project-root", default="", help="项目根目录，默认当前目录")

    # 解析命令行参数
    args = parser.parse_args()

    # 如果没有指定子命令，打印帮助信息
    if args.command is None:
        parser.print_help()
        return 0

    try:
        # 根据子命令分发到对应的处理函数
        result = _dispatch(args)
        # 输出结果到 stdout
        _output(result, getattr(args, "format", "json"))
        # 根据结果中的 success 字段决定退出码
        return 0 if result.get("success", True) else 1
    except Exception as e:
        # 捕获异常，记录日志并输出错误结果
        logger.exception("Command failed")
        _output({"success": False, "error": str(e)}, getattr(args, "format", "json"))
        return 1


# 输出结果到 stdout
# 参数 data: 要输出的数据字典
# 参数 fmt: 输出格式（json 或 text）
def _output(data: dict, fmt: str) -> None:
    if fmt == "json":
        # JSON 格式输出到 stdout
        json.dump(data, sys.stdout, ensure_ascii=False, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        # 文本模式：打印 message 字段或 JSON 字符串
        print(data.get("message", json.dumps(data, ensure_ascii=False, default=str)))


# 根据子命令分发到对应的处理函数
# 参数 args: 解析后的命令行参数
# 返回值: 处理结果字典
def _dispatch(args: argparse.Namespace) -> dict:
    if args.command == "init":
        return _cmd_init(args)
    elif args.command == "loop":
        return _cmd_loop(args)
    elif args.command == "verify":
        return _cmd_verify(args)
    elif args.command == "review":
        return _cmd_review(args)
    elif args.command == "memory":
        return _cmd_memory(args)
    elif args.command == "context":
        return _cmd_context(args)
    elif args.command == "scenario":
        return _cmd_scenario(args)
    elif args.command == "status":
        return _cmd_status()
    elif args.command == "data":
        return _cmd_data(args)
    return {"success": False, "error": f"Unknown command: {args.command}"}


# ── init ─────────────────────────────────────────

# 确保依赖可用，缺失时自动 pip install
# 参数 package_name: 包名
# 返回值: 是否成功
def _ensure_dependency(package_name: str) -> bool:
    """确保 Python 依赖可用，缺失时自动 pip install。"""
    try:
        __import__(package_name)
        return True
    except ImportError:
        logger.info("Missing dependency: %s, attempting auto-install...", package_name)
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", package_name],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            logger.error("Auto-install failed for %s: %s", package_name, result.stderr.strip())
            return False
        logger.info("Installed %s successfully", package_name)
        return True


# init 命令处理函数
# 参数 args: 解析后的命令行参数
# 返回值: 处理结果字典
def _cmd_init(args: argparse.Namespace) -> dict:
    # 确保 pydantic 依赖可用（init 模块依赖 pydantic）
    if not _ensure_dependency("pydantic"):
        return {
            "success": False,
            "error": "Missing required dependency: pydantic",
            "hint": "Auto-install failed. Please run manually: pip install pydantic",
        }

    # 导入 InitRunner 初始化执行器
    from engines.init import InitRunner

    # 确定项目根目录
    root = Path(args.project_root) if getattr(args, "project_root", "") else Path.cwd()
    # 确定目标工具
    target_tool = getattr(args, "target", "claude_code")
    # 创建初始化执行器
    runner = InitRunner(project_root=root, target_tool=target_tool)
    start = time.perf_counter()

    # --scan-only 模式：仅扫描项目，不生成文件
    if args.scan_only:
        profile = runner.scan()
        return {
            "success": True,
            "action": "scan_only",
            "target_tool": target_tool,
            "adapter": runner.adapter.display_name,
            "profile": profile.model_dump(),
            "duration_ms": (time.perf_counter() - start) * 1000,
        }

    # --assets-only 模式：仅生成 .ai/ 资产和 adapter 安装
    if args.assets_only:
        report = runner.run_assets_only()
        return {
            "success": report.success,
            "action": "assets_only",
            "target_tool": target_tool,
            "adapter": runner.adapter.display_name,
            "files_created": report.files_created,
            "files_skipped": report.files_skipped,
            "total_duration_ms": report.total_duration_ms,
        }

    # 完整初始化模式
    report = runner.run(auto_confirm=args.auto_confirm, install_missing=False)
    return {
        "success": report.success,
        "target_tool": target_tool,
        "adapter": runner.adapter.display_name,
        "profile": report.profile.model_dump(),
        "files_created": report.files_created,
        "files_skipped": report.files_skipped,
        "files_merged": report.files_merged,
        "installed_plugins": report.installed_plugins,
        "missing_optional": report.missing_optional,
        "next_steps": report.next_steps,
        "total_duration_ms": report.total_duration_ms,
    }


# ── loop ─────────────────────────────────────────

# loop 命令处理函数
# 参数 args: 解析后的命令行参数
# 返回值: 处理结果字典
def _cmd_loop(args: argparse.Namespace) -> dict:
    # 导入运行时模块
    from engines.runtime import create_sub_loop
    from engines.state.models import RunState, TaskIntakeResult

    mode = args.mode

    # --only 参数：dev → dev-only, direct → direct-only
    if getattr(args, "only", False):
        if mode == "dev":
            mode = "dev-only"
        elif mode == "direct":
            mode = "direct-only"
        else:
            logger.warning("--only 仅对 dev/direct 模式有效，忽略")

    # ── continue 模式: 恢复暂停的 loop，注入 AI 结果 ──
    if mode == "continue":
        return _cmd_loop_continue(args)

    # 新运行始终从干净状态开始，不加载残留旧状态
    if mode in ("plan-only", "dev"):
        logger.warning(
            "%s mode: 建议通过 --state-file 传入含 Spec/Plan 的状态文件，"
            "否则可能缺少必要的上游产物", mode
        )
    project_root = Path(args.project_root) if getattr(args, "project_root", "") else Path.cwd()

    # ── 处理任务输入：文件路径检测 + 内容读取 ──
    user_input = args.task or ""
    actual_input = user_input
    input_type = "plain_prompt"

    # 检测是否是文件路径（相对路径或绝对路径）
    if user_input:
        input_path = Path(user_input)
        # 尝试相对路径或绝对路径
        resolved_path = input_path if input_path.is_absolute() else project_root / input_path

        if resolved_path.exists() and resolved_path.is_file():
            # 读取文件内容
            try:
                file_content = resolved_path.read_text(encoding="utf-8")
                # 替换 user_input 为文件内容
                actual_input = file_content
                input_type = "file_content"
                logger.info("Read file content from: %s (%d chars)", resolved_path, len(file_content))
            except Exception as e:
                logger.warning("Failed to read file %s: %s, using as plain text", resolved_path, e)

    # ── 自动检测现有 Spec 文件 ──
    # direct 模式跳过 spec 检测（轻量通道，无 spec 约束）
    detected_spec_file = getattr(args, "spec_file", "") or ""
    if not detected_spec_file and mode not in ("direct", "direct-only"):
        for spec_dir in (project_root / "docs" / "spec", project_root / "spec"):
            if spec_dir.is_dir():
                spec_files = sorted(spec_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
                for sf in spec_files:
                    if sf.stat().st_size > 200:
                        detected_spec_file = str(sf.relative_to(project_root))
                        logger.info("Auto-detected spec file: %s", detected_spec_file)
                        break
                if detected_spec_file:
                    break
        # 兜底: .ai/spec.md
        if not detected_spec_file:
            alt_spec = project_root / ".ai" / "spec.md"
            if alt_spec.exists() and alt_spec.stat().st_size > 200:
                detected_spec_file = ".ai/spec.md"
                logger.info("Auto-detected spec file: .ai/spec.md")

    # ── 自动检测现有 Plan 文件 ──
    # 仅在未通过 --plan-file 显式指定时才自动检测
    explicit_plan_file = getattr(args, "plan_file", "") or ""
    if explicit_plan_file:
        detected_plan_file = explicit_plan_file
        logger.info("使用显式指定的 plan file: %s", detected_plan_file)
    else:
        detected_plan_file = ""
        if mode not in ("direct", "direct-only"):
            for plan_dir in (project_root / "docs" / "plan", project_root / "plan"):
                if plan_dir.is_dir():
                    plan_files = sorted(plan_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
                    for pf in plan_files:
                        if pf.stat().st_size > 200:
                            detected_plan_file = str(pf.relative_to(project_root))
                            logger.info("Auto-detected plan file: %s", detected_plan_file)
                            break
                    if detected_plan_file:
                        break

    # 从现有状态文件中恢复 plan_contracts（full 模式 resume 场景）
    existing_contracts: list[dict] = []
    state_file_path = Path(args.state_file) if getattr(args, "state_file", "") else None
    if state_file_path and state_file_path.exists() and mode in ("dev", "full"):
        try:
            existing_state = RunState.model_validate_json(state_file_path.read_text(encoding="utf-8"))
            existing_contracts = existing_state.plan_contracts or []
            if existing_contracts:
                logger.info("从状态文件恢复 %d 个 plan_contracts", len(existing_contracts))
        except Exception as e:
            logger.debug("无法从状态文件恢复 plan_contracts: %s", e)

    # plan_contracts 可以为空（dev 模式只用 plan_file 路径，AI 直接读文件）
    plan_contracts: list[dict] = existing_contracts

    state = RunState(
        task_id=f"cli-{int(time.time())}",
        project=project_root.name,
        project_root=project_root.as_posix(),
        plan_contracts=plan_contracts,
        task_intake=TaskIntakeResult(
            input_type=input_type,
            complexity="medium",
            risk_level="L3",
            flow_mode="spec_from_prompt" if mode == "full" else "direct",
            reason=user_input[:200] if user_input else f"CLI {mode} mode",
        ) if actual_input else None,
        metadata={
            "user_input": user_input,  # 原始输入（可能是文件路径或文本）
            "actual_input": actual_input,  # 处理后的输入（文件内容或原始文本）
            "input_type": input_type,
            "scenario_dir": getattr(args, "scenario_dir", "") or "",
            "plan_file": detected_plan_file,
            "spec_file": detected_spec_file,
        },
    )

    # 创建子循环执行器
    runner = create_sub_loop(mode)
    # 保存 sub-loop 模式到 state，供 continue 恢复
    state.metadata["sub_loop_mode"] = mode
    start = time.perf_counter()
    # 运行循环
    final = runner.run(state)

    # 保存状态文件供后续 continue
    _save_state(final, args)

    # 构建返回结果
    result = {
        "success": final.current_stage.value == "completed",
        "final_stage": final.current_stage.value,
        "task_status": final.task_state.status.value if final.task_state else None,
        "failures": len(final.failures),
        "checkpoints": len(final.checkpoints),
        "duration_ms": (time.perf_counter() - start) * 1000,
    }

    # 如果暂停等待 AI，附加 prompt 信息
    if final.needs_ai_input:
        # 获取 engines_cmd 配置（与 _cmd_loop_continue 保持一致）
        _state_file_path = Path(args.state_file or "run.json")
        _project_root = Path(args.project_root) if args.project_root else _state_file_path.parent.resolve()
        _target = args.target if hasattr(args, "target") and args.target else None
        _tool_config = _get_tool_config(_project_root, _target)
        engines_cmd = _tool_config.get("engines_cmd", "engines/run.sh")

        result["needs_ai_input"] = True
        result["pending_action"] = final.pending_action
        result["pending_prompt"] = final.pending_prompt
        result["hint"] = (
            f"AI: 读取 pending_prompt，完成 {final.pending_action}，"
            f"然后运行: {engines_cmd} loop continue --state-file run.json "
            f"--result '<JSON>'"
        )

    return result


# ── Plan 文件解析辅助函数 ─────────────────────────────────────────

def _extract_contracts_from_plan_file(plan_path: Path) -> list[dict]:
    """从 Plan 文件自动提取 Task Contracts。

    支持解析以下格式的 Plan 文件：
    1. Task 列表（格式: ### Task N: Title 或 ## Task N / ## T[N]）
    2. 每个 Task 包含: goal, allowed_files, forbidden_files, budget

    Args:
        plan_path: Plan 文件路径

    Returns:
        Task contracts 列表，解析失败返回空列表
    """
    import re

    try:
        content = plan_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("无法读取 Plan 文件 %s: %s", plan_path, e)
        return []

    contracts = []

    # 匹配 Task 标题: ### T1: xxx 或 ### Task 1: xxx
    task_pattern = re.compile(r'^###\s+(?:Task\s+)?T?(\d+)\s*[:：]\s*(.+?)(?=\n)', re.MULTILINE)

    # 查找所有 Task
    tasks = list(task_pattern.finditer(content))

    for i, match in enumerate(tasks):
        task_num = match.group(1)
        task_title = match.group(2).strip()

        # 提取该 Task 的内容范围（到下一个 Task 或文件结束）
        start = match.end()
        end = tasks[i + 1].start() if i + 1 < len(tasks) else len(content)
        task_content = content[start:end]

        # 提取 goal: **Goal**: xxx
        goal = task_title
        goal_match = re.search(r'\*\*Goal\*\*:\s*(.+?)(?:\n|$)', task_content, re.MULTILINE)
        if goal_match:
            goal = goal_match.group(1).strip()

        # 提取 allowed_files: **Allowed Files**: 下的 - `xxx` 列表
        allowed_files = []
        files_block_match = re.search(
            r'\*\*Allowed Files\*\*:\s*\n((?:\s*-\s*[^\n]+\n)+)',
            task_content,
            re.MULTILINE
        )
        if files_block_match:
            for line in files_block_match.group(1).split('\n'):
                line = line.strip()
                if line.startswith('-'):
                    # 去掉 "- " 前缀和反引号
                    f = line.lstrip('-').strip().strip('`')
                    if f:
                        allowed_files.append(f)

        # 提取 budget: **Budget**: maxFiles=X, maxLines=Y
        budget = {"max_files": 5, "max_lines_changed": 200}
        budget_match = re.search(r'maxFiles=(\d+),\s*maxLines=(\d+)', task_content)
        if budget_match:
            budget["max_files"] = int(budget_match.group(1))
            budget["max_lines_changed"] = int(budget_match.group(2))

        contract = {
            "task_id": f"T{task_num}",
            "goal": goal,
            "allowed_files": allowed_files if allowed_files else ["src/"],
            "forbidden_files": [],
            "budget": budget,
        }
        contracts.append(contract)
        logger.debug("提取 Task %s: %s (%d files)", task_num, goal[:30], len(allowed_files))

    logger.info("从 %s 解析出 %d 个 Task Contracts", plan_path.name, len(contracts))
    return contracts


# 恢复暂停的 loop，注入 AI 提交的结果
# 参数 args: 解析后的命令行参数
# 返回值: 处理结果字典
def _cmd_loop_continue(args: argparse.Namespace) -> dict:
    """恢复暂停的 loop，注入 AI 提交的结果。"""
    import json as _json
    from engines.runtime import create_sub_loop
    from engines.state.models import RunState

    # 确定状态文件路径
    state_file = args.state_file or "run.json"
    state_path = Path(state_file)

    # 检查状态文件是否存在
    if not state_path.exists():
        return {"success": False, "error": f"State file not found: {state_file}"}

    # 从状态文件加载 RunState
    state = RunState.model_validate_json(state_path.read_text(encoding="utf-8"))

    # 注入 AI 结果
    if args.result:
        try:
            # 解析 AI 提交的 JSON 结果
            result_data = _json.loads(args.result)
        except _json.JSONDecodeError:
            return {"success": False, "error": "Invalid JSON in --result"}

        # 根据 pending_action 注入到对应字段
        action = state.pending_action
        if action in ("brainstorm", "generate_spec"):
            state.metadata["spec_result"] = result_data
        elif action == "generate_plan":
            state.metadata["plan_result"] = result_data
            # 从 plan_result 提取 contracts 写入 plan_contracts，供 EXECUTE 使用
            contracts = result_data.get("contracts", [])
            if contracts:
                state.plan_contracts = contracts
                state.metadata["plan_contract_retries"] = 0  # 重置重试计数
                logger.info("Plan contracts extracted: %d tasks", len(contracts))
            else:
                # 尝试从 result_data.plan_file 提取
                plan_file = result_data.get("plan_file")
                if not plan_file:
                    # Fallback: 从之前保存的 plan_result 中读取 plan_file
                    prev_plan_result = state.metadata.get("plan_result", {})
                    plan_file = prev_plan_result.get("plan_file")
                if plan_file:
                    plan_path = Path(state.project_root) / plan_file
                    if plan_path.exists():
                        contracts = _extract_contracts_from_plan_file(plan_path)
                        if contracts:
                            state.plan_contracts = contracts
                            state.metadata["plan_contract_retries"] = 0
                            logger.info("Plan contracts auto-extracted from %s: %d tasks", plan_file, len(contracts))
                        else:
                            logger.warning("无法从 %s 提取 contracts", plan_file)
                    else:
                        logger.warning("Plan 文件不存在: %s", plan_path)
                if not state.plan_contracts:
                    logger.warning("plan_result 中无 contracts 字段且无 plan_file，plan_contracts 仍为空")
        elif action == "generate_scenarios":
            state.metadata["scenarios_result"] = result_data
        elif action in ("execute_task", "confirm_checklist", "lock_plan",
                        "await_plan_change_approval"):
            state.metadata["execute_result"] = result_data
        elif action == "direct_execute":
            state.metadata["direct_execute_result"] = result_data
        elif action == "repair":
            state.metadata["repair_result"] = result_data
        elif action == "review":
            state.metadata["review_ai_result"] = result_data
        elif action == "review_fix":
            state.metadata["review_fix_result"] = result_data
        elif action == "memory":
            state.metadata["memory_ai_called"] = True
            state.metadata["memory_result"] = result_data
        elif action == "plan_approval":
            # 用户审核 Plan 结果
            approved = result_data.get("plan_approved", False)
            if approved:
                logger.info("用户批准 Plan，准备进入 TEST_DESIGN")
                state.metadata["plan_awaiting_approval"] = False
                state.metadata["plan_approved_by_user"] = True
                # Plan 锁定，准备进入 TEST_DESIGN
                state.plan_lock_state = "locked"
                # 如果 plan_contracts 为空，从 plan_file 自动提取（用户批准前可能未提取）
                if not state.plan_contracts:
                    plan_result = state.metadata.get("plan_result", {})
                    plan_file = result_data.get("plan_file") or plan_result.get("plan_file")
                    if plan_file:
                        plan_path = Path(state.project_root) / plan_file
                        if plan_path.exists():
                            contracts = _extract_contracts_from_plan_file(plan_path)
                            if contracts:
                                state.plan_contracts = contracts
                                logger.info("Plan approval 时补充提取 %d 个 contracts", len(contracts))
                        # 同时保存到 metadata 中（兼容后续 resume）
                    state.metadata["approved_plan_file"] = plan_file
            else:
                # 用户拒绝 Plan，需要修改后重新提交
                logger.info("用户拒绝 Plan，标记为待修改")
                state.metadata["plan_awaiting_approval"] = False
                state.metadata["plan_rejected_by_user"] = True
                # 返回拒绝信息，让用户重新生成 Plan
                state.pending_action = "generate_plan"
                state.needs_ai_input = True
                state.pending_prompt = {
                    "instruction": (
                        "用户拒绝了之前的 Plan，请根据用户反馈重新生成 Plan。\n"
                        "完成后调用: engines/run.sh loop continue --state-file run.json "
                        "--result '{\"plan_file\": \"docs/plan/xxx.md\", \"summary\": \"...\"}'"
                    )
                }
        else:
            state.metadata["ai_result"] = result_data

        # 清除 AI 输入等待标志
        state.needs_ai_input = False
        logger.info("AI result injected for action=%s", action)

    # 恢复执行 — 使用原始 sub_loop_mode，保持与暂停前一致的流程
    sub_loop_mode = state.metadata.get("sub_loop_mode", "full")
    logger.info("Resuming with sub_loop_mode=%s", sub_loop_mode)
    runner = create_sub_loop(sub_loop_mode)
    start = time.perf_counter()
    final = runner.run(state)

    # 保存状态
    _save_state(final, args)

    # 构建返回结果
    result = {
        "success": final.current_stage.value == "completed",
        "final_stage": final.current_stage.value,
        "task_status": final.task_state.status.value if final.task_state else None,
        "failures": len(final.failures),
        "duration_ms": (time.perf_counter() - start) * 1000,
    }

    # 如果继续等待 AI 输入，附加提示信息
    if final.needs_ai_input:
        state_file_path = Path(args.state_file or "run.json")
        project_root = Path(args.project_root) if args.project_root else state_file_path.parent.resolve()
        target = args.target if hasattr(args, "target") and args.target else None
        tool_config = _get_tool_config(project_root, target)
        engines_cmd = tool_config.get("engines_cmd", "engines/run.sh")

        result["needs_ai_input"] = True
        result["pending_action"] = final.pending_action
        result["pending_prompt"] = final.pending_prompt
        result["hint"] = (
            f"AI: 读取 pending_prompt，完成 {final.pending_action}，"
            f"然后运行: {engines_cmd} loop continue --state-file run.json "
            f"--result '<JSON>'"
        )

    return result


# 保存 RunState 到文件
# 参数 state: RunState 实例
# 参数 args: 命令行参数（用于获取输出文件路径）
def _save_state(state, args: argparse.Namespace) -> None:
    """保存 RunState 到文件。"""
    output = args.state_file or "run.json"
    # 序列化为 JSON 并写入文件
    Path(output).write_text(state.model_dump_json(indent=2), encoding="utf-8")
    logger.info("State saved to %s", output)


# ── verify ───────────────────────────────────────

# verify 命令处理函数
# 参数 args: 解析后的命令行参数
# 返回值: 处理结果字典
def _cmd_verify(args: argparse.Namespace) -> dict:
    # 导入 ScenarioRunner 场景运行器
    from engines.scenario.runner import ScenarioRunner
    from engines.scenario.resources import HttpAdapter

    # 从 loop-config.json 读取服务地址
    root = Path(args.project_root) if getattr(args, "project_root", "") else Path.cwd()
    config = _load_loop_config(root)
    if not config:
        return {"success": False, "error": "未找到 .ai/loop-config.json，请先运行 aicode-init"}
    services = config.get("services", [])
    if not services or not services[0].get("health"):
        return {"success": False, "error": "loop-config.json 中未配置 services[0].health"}

    from urllib.parse import urlparse
    parsed = urlparse(services[0]["health"])
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    http_adapter = HttpAdapter(base_url=base_url)
    # 加载 DataSourceRegistry（DB/Redis/MQ 断言需要）
    from engines.scenario.adapters import DataSourceRegistry
    ds_registry = DataSourceRegistry.load(root)
    custom_adapters = {"http": http_adapter}
    for atype, adapter in ds_registry.to_adapter_dict().items():
        if atype != "http":
            custom_adapters[atype] = adapter
    runner = ScenarioRunner(adapters=custom_adapters, registry=ds_registry)

    # 如果指定了场景文件，加载并执行
    if args.scenario:
        result = runner.run(args.scenario)
        return result.model_dump()

    # 未指定场景时的提示
    return {"success": True, "message": "No scenario specified. Run: aicode verify --scenario <id>"}


# ── review ────────────────────────────────────────

# review 命令处理函数
# 参数 args: 解析后的命令行参数
# 返回值: 处理结果字典
def _cmd_review(args: argparse.Namespace) -> dict:
    # 导入审查引擎
    from engines.review import create_review_engine
    from engines.state.models import RunState

    review = create_review_engine()
    # 创建临时 RunState 用于审查
    state = RunState(
        task_id=f"cli-review-{int(time.time())}",
        project="review-check",
    )
    result = review.check(state)

    # 从 details 提取 violations 和 warnings
    results = result.details.get("results", [])
    violations = [r for r in results if not r.get("passed")]
    warnings = [r for r in results if r.get("severity") == "warn"]
    return {
        "success": not result.block,
        "severity": result.severity.value,
        "blocked": result.block,
        "violations": violations,
        "warnings": warnings,
        "reason": result.reason,
        "details": result.details,
    }


# ── memory ───────────────────────────────────────

def _cmd_memory(args: argparse.Namespace) -> dict:
    """直接读取 .claude/rules/loop-memory-*.md，不再依赖 engines.memory。"""
    project_root = Path(args.project_root) if getattr(args, "project_root", "") else Path.cwd()
    rules_dir = project_root / ".claude" / "rules"
    mem_files = sorted(rules_dir.glob("loop-memory-*.md")) if rules_dir.is_dir() else []

    if not mem_files:
        return {"success": True, "files": [], "message": "暂无 loop-memory 文件"}

    if args.action == "list":
        files_info = []
        for f in mem_files:
            content = f.read_text(encoding="utf-8")
            files_info.append({
                "path": str(f.relative_to(project_root)),
                "lines": content.count("\n") + 1,
            })
        return {"success": True, "files": files_info}

    elif args.action == "search":
        keyword = getattr(args, "keyword", "")
        results = []
        for f in mem_files:
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if keyword and keyword.lower() in line.lower():
                    results.append({"file": str(f.relative_to(project_root)), "line": i, "text": line.strip()})
        return {"success": True, "results": results, "count": len(results)}

    elif args.action == "cleanup":
        # 清理旧的 .ai/memory 目录（如果存在，迁移到新方案后可以删）
        old_dir = project_root / ".ai" / "memory"
        cleaned = 0
        if old_dir.is_dir():
            import shutil
            shutil.rmtree(old_dir)
            cleaned = 1
        return {"success": True, "cleaned": cleaned, "message": "旧的 .ai/memory 目录已清理"}

    return {"success": False, "error": f"Unknown action: {args.action}"}


# ── context ──────────────────────────────────────

def _cmd_context(args: argparse.Namespace) -> dict:
    """engines/context 已移除。AI 自行使用 Read / CodeGraph MCP 获取上下文。"""
    return {
        "success": True,
        "message": "ContextRouter 已移除。AI 通过 Read + CodeGraph MCP 自行获取上下文。",
    }


# ── scenario ──────────────────────────────────────

def _cmd_scenario(args: argparse.Namespace) -> dict:
    """校验 Scenario YAML 文件，或生成覆盖矩阵。"""
    from engines.scenario.validator import validate_scenario_file, validate_scenario_dir, compute_coverage_matrix

    if args.file:
        result = validate_scenario_file(args.file)
        return {"success": True, **result}
    elif args.dir:
        results = validate_scenario_dir(args.dir)
        all_valid = all(r["valid"] for r in results)
        resp = {"success": True, "all_valid": all_valid, "results": results}
        # --coverage 存在时附加覆盖矩阵
        if args.coverage:
            cov = compute_coverage_matrix(args.dir, args.coverage)
            resp["coverage"] = cov
        return resp
    return {"success": False, "error": "需要 --file 或 --dir"}


# ── status ───────────────────────────────────────

# status 命令处理函数
# 返回值: 状态检查结果字典
def _cmd_status() -> dict:
    """检查引擎状态。"""
    codegraph_available = (PROJECT_ROOT / ".codegraph").is_dir()
    return {
        "success": True,
        "project_root": str(PROJECT_ROOT),
        "codegraph_available": codegraph_available,
        "engines_available": True,
    }


# ── data ─────────────────────────────────────────

def _cmd_data(args: argparse.Namespace) -> dict:
    """通过已配置的数据源适配器查询 DB/Redis。

    AI 修复时可用此命令验证数据是否存在，避免盲猜。
    """
    root = Path(args.project_root) if getattr(args, "project_root", "") else Path.cwd()

    from engines.scenario.adapters import DataSourceRegistry
    registry = DataSourceRegistry.load(root)

    if not args.source and args.action != "list":
        return {"success": False, "error": "需要 --source 指定数据源名，或用 'list' 列出所有数据源"}

    if args.action == "list":
        sources = {}
        for name, adapter in registry._adapters.items():
            sources[name] = {
                "type": adapter.adapter_type,
                "label": adapter.adapter_label,
                "healthy": adapter.is_healthy(),
            }
        return {"success": True, "sources": sources}

    # query / execute
    adapter = registry.get(args.source)
    if adapter is None:
        return {
            "success": False,
            "error": f"数据源 '{args.source}' 未配置，可用: {list(registry._adapters.keys())}",
        }

    target = args.target or args.sql  # --sql 向后兼容
    if not target:
        return {"success": False, "error": "需要 --target 指定操作目标（MySQL=SQL，Redis=key，...）"}

    extra = {}
    if args.value is not None:
        extra["value"] = args.value

    try:
        result = adapter.execute(args.action, target, **extra)
    except Exception as exc:
        return {"success": False, "error": f"操作失败: {exc}"}

    if isinstance(result, dict) and "error" in result:
        return {"success": False, "error": result["error"]}

    if args.action == "execute":
        return {"success": True, "result": result}

    # query: 结果归一化
    rows = result if isinstance(result, list) else [result]
    return {"success": True, "rows": rows, "count": len(rows)}


# 当脚本直接运行时，执行 main 函数
if __name__ == "__main__":
    sys.exit(main())