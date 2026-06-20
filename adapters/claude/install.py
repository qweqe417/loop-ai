#!/usr/bin/env python3
"""Claude Code adapter installer.

Called by `aicode install claude`. Copies skill files into the target
project so Claude Code discovers them from `.claude/skills/`, and writes
hooks config. Engines and other Python source stay in the plugin install
directory — skills reference them via ${CLAUDE_PLUGIN_ROOT}.

Usage:
    python adapters/claude/install.py [--project-root /path/to/project]
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path


def install(project_root: str | Path = ".") -> dict:
    """Install AI Coding Loop into a Claude Code project.

    Copies skill files and hooks config only. Engines/ source code stays
    in the plugin directory and is referenced via ${CLAUDE_PLUGIN_ROOT}.

    Returns a dict with installation results.
    """
    root = Path(project_root).resolve()
    source_dir = Path(__file__).resolve().parent.parent.parent  # ai-coding-loop root

    results: dict[str, list[str]] = {"created": [], "skipped": [], "errors": []}

    # 1. Copy skill files to .claude/skills/ for auto-discovery
    skills_src = source_dir / "skills"
    skills_dst = root / ".claude" / "skills"
    if skills_src.exists():
        skills_dst.mkdir(parents=True, exist_ok=True)
        for skill_md in skills_src.glob("*.md"):
            dst = skills_dst / skill_md.name
            _copy_file(skill_md, dst, results)

    # 2. Write hooks.json (references engines via ${CLAUDE_PLUGIN_ROOT})
    hooks_src = Path(__file__).resolve().parent / "hooks.json"
    hooks_dst = root / "hooks" / "hooks.json"
    if hooks_src.exists():
        hooks_dst.parent.mkdir(parents=True, exist_ok=True)
        _copy_file(hooks_src, hooks_dst, results)

    # 3. Write plugin root path for fallback when ${CLAUDE_PLUGIN_ROOT} is unset
    aicode_dir = root / ".claude" / "aicode"
    aicode_dir.mkdir(parents=True, exist_ok=True)
    plugin_root_file = aicode_dir / "plugin-root.txt"
    plugin_root_file.write_text(str(source_dir.resolve()), encoding="utf-8")
    results["created"].append(str(plugin_root_file.relative_to(Path.cwd())))

    # 4. Validate: check that engines/ exists in the plugin source
    engines_src = source_dir / "engines"
    if not engines_src.is_dir():
        results["errors"].append("engines/ directory not found in plugin source")
    elif not (engines_src / "run.sh").exists():
        results["errors"].append("engines/run.sh not found in plugin source")

    return {
        "success": len(results["errors"]) == 0,
        "files_created": results["created"],
        "files_skipped": results["skipped"],
        "errors": results["errors"],
    }


def _copy_file(src: Path, dst: Path, results: dict) -> None:
    """Copy a single file with overwrite detection."""
    try:
        if dst.exists():
            results["skipped"].append(str(dst.relative_to(Path.cwd())))
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        results["created"].append(str(dst.relative_to(Path.cwd())))
    except Exception as e:
        results["errors"].append(f"{dst}: {e}")


if __name__ == "__main__":
    project_root = sys.argv[1] if len(sys.argv) > 1 else "."
    result = install(project_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
