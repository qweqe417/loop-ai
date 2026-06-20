"""AI Coding Loop - 统一 CLI 入口。

所有命令输出 JSON 到 stdout，日志输出到 stderr。
用法:
    bash engines/run.sh init --scan-only --format json
    bash engines/run.sh loop full --task "需求描述"
    bash engines/run.sh verify --scenario order-timeout --format json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ── 工具配置（CLI 多工具兼容）────────────────────────────────

def _load_loop_config(project_root: Path) -> dict | None:
    """读取项目根目录的 .ai/loop-config.json。"""
    config_path = project_root / ".ai" / "loop-config.json"
    if not config_path.exists():
        return None
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _detect_tool(project_root: Path | None = None) -> str:
    """自动检测当前项目的 AI 工具。

    优先级: loop-config.json > 文件探测 > 默认 claude_code
    """
    root = project_root or Path.cwd()
    config = _load_loop_config(root)
    if config:
        return config.get("target_tool", "claude_code")
    if (root / ".codex").exists():
        return "codex"
    if (root / ".cursor").exists():
        return "cursor"
    return "claude_code"


def _get_tool_config(
    project_root: Path | None = None, target_tool: str | None = None
) -> dict:
    """获取工具配置（engines_cmd / plugin_root 等）。

    优先从 loop-config.json 读取，fallback 到硬编码默认值。
    """
    root = project_root or Path.cwd()
    config = _load_loop_config(root) or {}
    tool = target_tool or config.get("target_tool", "claude_code")

    if config.get("target_tool") == tool and "engines_cmd" in config:
        return config

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
logger = logging.getLogger("cli")


def main() -> int:
    parser = argparse.ArgumentParser(prog="aicode-loop")
    sub = parser.add_subparsers(dest="command")

    # ── init ─────────────────────────────────────
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
    p_loop = sub.add_parser("loop", help="运行 Loop")
    p_loop.add_argument("mode", nargs="?", default="full",
                        choices=["full", "dev", "test", "spec", "plan", "plan-only", "verify", "review", "memory", "direct", "continue"])
    p_loop.add_argument("--task", default="")
    p_loop.add_argument("--state-file", default="")
    p_loop.add_argument("--result", default="", help="AI 提交的结果 JSON (仅 continue 模式)")
    p_loop.add_argument("--target", default="", help="目标 AI 工具 (claude_code/codex/cursor)，默认自动检测")
    p_loop.add_argument("--project-root", default="", help="项目根目录，默认当前目录")

    # ── verify ───────────────────────────────────
    p_verify = sub.add_parser("verify", help="场景验证")
    p_verify.add_argument("--scenario", default="")
    p_verify.add_argument("--format", default="json")
    p_verify.add_argument("--target", default="", help="目标 AI 工具，默认自动检测")

    # ── guard ────────────────────────────────────
    p_guard = sub.add_parser("guard", help="Guard 检查")
    p_guard.add_argument("action", nargs="?", default="check", choices=["check", "report"])
    p_guard.add_argument("--diff", default="HEAD")
    p_guard.add_argument("--format", default="json")
    p_guard.add_argument("--target", default="", help="目标 AI 工具，默认自动检测")

    # ── memory ───────────────────────────────────
    p_mem = sub.add_parser("memory", help="记忆管理")
    p_mem.add_argument("action", nargs="?", default="update", choices=["update", "search", "stats"])
    p_mem.add_argument("--keyword", default="")
    p_mem.add_argument("--format", default="json")
    p_mem.add_argument("--target", default="", help="目标 AI 工具，默认自动检测")
    p_mem.add_argument("--project-root", default="", help="项目根目录，默认当前目录")

    # ── context ──────────────────────────────────
    p_ctx = sub.add_parser("context", help="上下文路由")
    p_ctx.add_argument("action", nargs="?", default="route", choices=["route", "project-map"])
    p_ctx.add_argument("--stage", default="intake")
    p_ctx.add_argument("--state-file", default="")
    p_ctx.add_argument("--format", default="json")
    p_ctx.add_argument("--target", default="", help="目标 AI 工具，默认自动检测")
    p_ctx.add_argument("--project-root", default="", help="项目根目录，默认当前目录")

    # ── status ───────────────────────────────────
    sub.add_parser("status", help="检查引擎状态")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    try:
        result = _dispatch(args)
        _output(result, getattr(args, "format", "json"))
        return 0 if result.get("success", True) else 1
    except Exception as e:
        logger.exception("Command failed")
        _output({"success": False, "error": str(e)}, getattr(args, "format", "json"))
        return 1


def _output(data: dict, fmt: str) -> None:
    if fmt == "json":
        json.dump(data, sys.stdout, ensure_ascii=False, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        # text mode
        print(data.get("message", json.dumps(data, ensure_ascii=False, default=str)))


def _dispatch(args: argparse.Namespace) -> dict:
    if args.command == "init":
        return _cmd_init(args)
    elif args.command == "loop":
        return _cmd_loop(args)
    elif args.command == "verify":
        return _cmd_verify(args)
    elif args.command == "guard":
        return _cmd_guard(args)
    elif args.command == "memory":
        return _cmd_memory(args)
    elif args.command == "context":
        return _cmd_context(args)
    elif args.command == "status":
        return _cmd_status()
    return {"success": False, "error": f"Unknown command: {args.command}"}


# ── init ─────────────────────────────────────────

def _cmd_init(args: argparse.Namespace) -> dict:
    from engines.init import InitRunner

    root = Path(args.project_root) if getattr(args, "project_root", "") else Path.cwd()
    target_tool = getattr(args, "target", "claude_code")
    runner = InitRunner(project_root=root, target_tool=target_tool)
    start = time.perf_counter()

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

def _cmd_loop(args: argparse.Namespace) -> dict:
    from engines.runtime import create_sub_loop
    from engines.state.models import RunState, TaskIntakeResult

    mode = args.mode

    # ── continue 模式: 恢复暂停的 loop，注入 AI 结果 ──
    if mode == "continue":
        return _cmd_loop_continue(args)

    # 加载或创建 RunState
    if args.state_file:
        state = RunState.model_validate_json(Path(args.state_file).read_text(encoding="utf-8"))
    else:
        # plan-only / dev 模式建议传入已有 state
        if mode in ("plan-only", "dev"):
            logger.warning(
                "%s mode: 建议通过 --state-file 传入含 Spec/Plan 的状态文件，"
                "否则可能缺少必要的上游产物", mode
            )
        state = RunState(
            task_id=f"cli-{int(time.time())}",
            project=str(PROJECT_ROOT.name),
            project_root=str(PROJECT_ROOT),
            task_intake=TaskIntakeResult(
                input_type="plain_prompt",
                complexity="medium",
                risk_level="L3",
                flow_mode="spec_from_prompt" if mode == "full" else "direct",
                reason=args.task or f"CLI {mode} mode",
            ) if args.task else None,
            metadata={"user_input": args.task, "args_task": args.task},
        )

    runner = create_sub_loop(mode)
    # 保存 sub-loop 模式到 state，供 continue 恢复
    state.metadata["sub_loop_mode"] = mode
    start = time.perf_counter()
    final = runner.run(state)

    # 保存状态文件供后续 continue
    _save_state(final, args)

    result = {
        "success": final.current_stage.value == "completed",
        "final_stage": final.current_stage.value,
        "task_status": final.task_state.status.value if final.task_state else None,
        "failures": len(final.failures),
        "checkpoints": len(final.checkpoints),
        "duration_ms": (time.perf_counter() - start) * 1000,
    }

    # 如果暂停等待 AI，附加 prompt 信息（使用工具特定的命令）
    if final.needs_ai_input:
        project_root = Path(args.project_root) if args.project_root else Path.cwd()
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


def _cmd_loop_continue(args: argparse.Namespace) -> dict:
    """恢复暂停的 loop，注入 AI 提交的结果。"""
    import json as _json
    from engines.runtime import create_sub_loop
    from engines.state.models import RunState

    state_file = args.state_file or "run.json"
    state_path = Path(state_file)

    if not state_path.exists():
        return {"success": False, "error": f"State file not found: {state_file}"}

    state = RunState.model_validate_json(state_path.read_text(encoding="utf-8"))

    # 注入 AI 结果
    if args.result:
        try:
            result_data = _json.loads(args.result)
        except _json.JSONDecodeError:
            return {"success": False, "error": "Invalid JSON in --result"}

        # 根据 pending_action 注入到对应字段
        action = state.pending_action
        if action in ("brainstorm", "generate_spec"):
            state.metadata["spec_result"] = result_data
        elif action == "generate_plan":
            state.metadata["plan_result"] = result_data
        elif action == "execute_task":
            state.metadata["execute_result"] = result_data
        elif action == "repair":
            state.metadata["repair_result"] = result_data
        else:
            state.metadata["ai_result"] = result_data

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

    result = {
        "success": final.current_stage.value == "completed",
        "final_stage": final.current_stage.value,
        "task_status": final.task_state.status.value if final.task_state else None,
        "failures": len(final.failures),
        "duration_ms": (time.perf_counter() - start) * 1000,
    }

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


def _save_state(state, args: argparse.Namespace) -> None:
    """保存 RunState 到文件。"""
    output = args.state_file or "run.json"
    Path(output).write_text(state.model_dump_json(indent=2), encoding="utf-8")
    logger.info("State saved to %s", output)


# ── verify ───────────────────────────────────────

def _cmd_verify(args: argparse.Namespace) -> dict:
    from engines.scenario.runner import ScenarioRunner

    runner = ScenarioRunner()
    runner.sanity_check(port=8080, base_url="http://localhost:8080")

    if args.scenario:
        result = runner.run(args.scenario)
        return result.model_dump()

    return {"success": True, "message": "No scenario specified. Run: aicode verify --scenario <id>"}


# ── guard ────────────────────────────────────────

def _cmd_guard(args: argparse.Namespace) -> dict:
    from engines.guard import create_guard
    from engines.state.models import RunState

    guard = create_guard()
    # Guard.check() 需要 RunState 参数，创建一个最小 state
    state = RunState(
        task_id=f"cli-guard-{int(time.time())}",
        project="guard-check",
    )
    result = guard.check(state)
    return {
        "success": not getattr(result, "block", False),
        "severity": str(getattr(result, "severity", "WARN")),
        "violations": getattr(result, "violations", []),
        "warnings": getattr(result, "warnings", []),
        "reason": getattr(result, "reason", ""),
    }


# ── memory ───────────────────────────────────────

def _cmd_memory(args: argparse.Namespace) -> dict:
    from engines.memory import MemoryStore

    project_root = Path(args.project_root) if getattr(args, "project_root", "") else Path.cwd()
    store = MemoryStore(project_root=project_root)

    if args.action == "search":
        keyword = args.keyword
        if keyword:
            entries = store.find(tags=[keyword]) if keyword else []
        else:
            entries = store.load()
        return {
            "success": True,
            "entries": [e.model_dump() for e in entries],
            "count": len(entries),
        }

    elif args.action == "stats":
        stats = store.stats()
        return {"success": True, "stats": stats.model_dump()}

    elif args.action == "governance":
        gov = store.governance()
        return {"success": True, "governance": gov.model_dump()}

    elif args.action == "recall":
        keywords = args.keywords.split(",") if getattr(args, "keywords", "") else []
        stage = getattr(args, "stage", "") or ""
        limit = getattr(args, "limit", 0) or 5
        entries = store.recall(keywords=keywords, stage=stage, limit=limit)
        return {
            "success": True,
            "entries": [e.model_dump() for e in entries],
            "count": len(entries),
        }

    # update: regenerate projections
    from engines.memory.projection import MemoryProjection
    proj = MemoryProjection(store)
    results = proj.sync_all()
    return {
        "success": True,
        "message": "Projections regenerated",
        "results": results,
    }


# ── context ──────────────────────────────────────

def _cmd_context(args: argparse.Namespace) -> dict:
    from engines.context import ContextRouter
    from engines.state.enums import StageType

    project_root = Path(args.project_root) if getattr(args, "project_root", "") else Path.cwd()
    router = ContextRouter(project_root=project_root)

    if args.action == "project-map":
        piece = router.build_project_map()
        return {"success": True, "project_map": piece.content, "tokens": piece.token_estimate}

    # route
    stage_map = {s.value: s for s in StageType}
    stage = stage_map.get(args.stage, StageType.INTAKE)

    from engines.state.models import RunState
    state = RunState(task_id="cli-context", project=str(PROJECT_ROOT.name))
    if args.state_file:
        state = RunState.model_validate_json(Path(args.state_file).read_text(encoding="utf-8"))

    bundle = router.route(stage, state)
    return {
        "success": True,
        "stage": stage.value,
        "pieces": len(bundle.pieces),
        "total_tokens": bundle.total_tokens,
        "budget_max": bundle.budget_max,
        "budget_used_pct": bundle.budget_used_pct,
        "trimmed": bundle.trimmed,
        "content": bundle.render(),
    }


# ── status ───────────────────────────────────────

def _cmd_status() -> dict:
    from engines.context import CodeGraphSource

    cg = CodeGraphSource(PROJECT_ROOT)
    return {
        "success": True,
        "project_root": str(PROJECT_ROOT),
        "codegraph_available": cg.available,
        "engines_available": True,
    }


if __name__ == "__main__":
    sys.exit(main())
