#!/usr/bin/env python3
"""SessionStart hook — inject project context at session start.

Called by Claude Code hooks system when a new session starts.
Outputs a minimal project map to stderr so it becomes part of the AI's context.

Usage:
    python hooks/session-start.py [--project-root /path/to/project]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> dict:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()

    # Try engines import
    engines_path = root / "engines"
    if str(engines_path) not in sys.path:
        sys.path.insert(0, str(root))
        sys.path.insert(0, str(engines_path))

    result = {
        "project": root.name,
        "codegraph_available": (root / ".codegraph").is_dir(),
        "claude_md_exists": (root / "CLAUDE.md").exists(),
        "ai_memory_exists": (root / ".ai" / "memory.md").exists(),
    }

    # Try to load project map via ContextRouter
    try:
        from engines.context import FileSource, CodeGraphSource

        cg = CodeGraphSource(root)
        if cg.available:
            piece = cg.get_project_map()
            result["project_map_source"] = "codegraph"
            result["project_map_tokens"] = piece.token_estimate
        else:
            fs = FileSource(root)
            piece = fs.scan_structure()
            result["project_map_source"] = "file_scan"
            result["project_map_tokens"] = piece.token_estimate

        # Print project map to stdout for hook injection
        print(piece.content[:3000], file=sys.stderr)  # Cap at 3000 chars

    except Exception as e:
        result["project_map_error"] = str(e)

    return result


if __name__ == "__main__":
    result = main()
    # Also output JSON result
    print(json.dumps(result, ensure_ascii=False, default=str))
