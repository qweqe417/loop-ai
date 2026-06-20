"""MemoryProjection —— 将权威记忆投影到工具文件。

投影方向:
    .ai/memory.md + entries/ (权威源)
        → .ai/memory/projections/claude-memory.md  (Claude Code 投影)
        → .ai/memory/projections/codex-memory.md   (Codex 投影)
        → .ai/memory/projections/cursor-memory.md  (Cursor 投影)
        → CLAUDE.md (标记段注入)
        → .claude/rules/safety.md (禁止事项)
        → .claude/rules/testing.md (测试经验)

原则:
    - 投影内容只取 confirmed
    - 投影文件可删了重建
    - 权威源永远是 .ai/memory.md + entries/
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from .models import Confidence, MemoryCategory, MemoryEntry
from .store import MemoryStore

logger = logging.getLogger(__name__)

# 投影输出文件（相对于项目根目录）
PROJECTION_OUTPUTS: dict[str, list[str]] = {
    "claude": [
        ".ai/memory/projections/claude-memory.md",
    ],
    "codex": [
        ".ai/memory/projections/codex-memory.md",
    ],
    "cursor": [
        ".ai/memory/projections/cursor-memory.md",
    ],
}


class MemoryProjection:
    """将记忆条目同步到工具原生文件。

    用法:
        store = MemoryStore(project_root=".")
        projection = MemoryProjection(store)
        projection.sync("claude")    # 同步 Claude Code 投影文件
        projection.sync_all()        # 同步所有工具
    """

    def __init__(self, store: MemoryStore) -> None:
        self._store = store
        self._root = getattr(store, '_root', Path("."))

    def sync(self, target: str) -> list[str]:
        """同步到指定工具，返回更新的文件路径列表。"""
        if target not in PROJECTION_OUTPUTS:
            logger.warning("Unknown projection target: %s", target)
            return []

        entries = self._store.load()
        confirmed = [e for e in entries if e.confidence == Confidence.CONFIRMED]
        updated: list[str] = []

        # 1. 写入 projections/ 文件
        for rel_path in PROJECTION_OUTPUTS[target]:
            full_path = self._root / rel_path
            self._write_full_projection(full_path, confirmed, target)
            updated.append(str(full_path))

        # 2. Claude 额外投影: CLAUDE.md 标记段
        if target == "claude":
            claude_md = self._root / "CLAUDE.md"
            if claude_md.exists():
                self._update_claude_md(claude_md, confirmed)
                updated.append(str(claude_md))

            # safety.md — 只同步 PROHIBITED
            safety_path = self._root / ".claude" / "rules" / "safety.md"
            self._write_category_projection(
                safety_path, confirmed, MemoryCategory.PROHIBITED,
                "安全与禁止事项", "由 AI Coding Loop Memory 系统自动生成",
            )

            # testing.md — 只同步 TESTING
            testing_path = self._root / ".claude" / "rules" / "testing.md"
            self._write_category_projection(
                testing_path, confirmed, MemoryCategory.TESTING,
                "测试经验与验证方式", "由 AI Coding Loop Memory 系统自动生成",
            )

        logger.info("Projection synced to '%s': %d files", target, len(updated))
        return updated

    def sync_all(self) -> dict[str, list[str]]:
        """同步到所有已配置的工具。"""
        results: dict[str, list[str]] = {}
        for target in PROJECTION_OUTPUTS:
            results[target] = self.sync(target)
        return results

    # ── 投影写策略 ────────────────────────────────────────

    def _update_claude_md(self, path: Path, entries: list[MemoryEntry]) -> None:
        """将关键规则注入 CLAUDE.md 的 AI Coding Loop 标记段。"""
        content = path.read_text(encoding="utf-8")

        start_marker = "<!-- AI_CODING_LOOP_MEMORY_START -->"
        end_marker = "<!-- AI_CODING_LOOP_MEMORY_END -->"

        proj_lines = self._render_projection_section(entries)

        if start_marker in content and end_marker in content:
            before = content.split(start_marker)[0]
            after = content.split(end_marker)[-1]
            new_content = before + start_marker + "\n" + proj_lines + "\n" + end_marker + after
        else:
            new_content = content.rstrip() + "\n\n" + start_marker + "\n" + proj_lines + "\n" + end_marker + "\n"

        path.write_text(new_content, encoding="utf-8")
        logger.info("Updated CLAUDE.md projection")

    def _write_full_projection(
        self, path: Path, entries: list[MemoryEntry], tool: str
    ) -> None:
        """写入完整投影缓存（.ai/memory/projections/）。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# AI Coding Loop — 记忆投影",
            "",
            f"> 目标工具: {tool}",
            f"> 最后同步: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"> 来源: .ai/memory.md (索引) + .ai/memory/entries/ (明细)",
            f"> 条目数: {len(entries)}",
            "",
            "> ⚠️ 此文件由系统自动生成，请勿手动编辑。权威源在 .ai/memory.md。",
            "",
            "---",
            "",
        ]
        lines.append(self._render_projection_section(entries))
        path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Wrote projection: %s", path)

    def _write_category_projection(
        self,
        path: Path,
        entries: list[MemoryEntry],
        category: MemoryCategory,
        title: str,
        comment: str = "",
    ) -> None:
        """写入单分类投影。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        filtered = [e for e in entries if e.category == category]
        lines = [
            f"# {title}",
            "",
            f"> {comment}",
            f"> 最后同步: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
        ]
        if filtered:
            for e in filtered:
                lines.append(f"- {e.content or e.title}")
                if e.source and e.source != "manual":
                    lines.append(f"  (来源: {e.source})")
        else:
            lines.append("<!-- 暂无条目 -->")
        lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Wrote %s projection: %s (%d entries)", category.value, path, len(filtered))

    # ── 渲染 ──────────────────────────────────────────────

    def _render_projection_section(self, entries: list[MemoryEntry]) -> str:
        """将条目列表渲染为投影文本。"""
        groups: dict[MemoryCategory, list[MemoryEntry]] = {}
        for e in entries:
            groups.setdefault(e.category, []).append(e)

        priority_order = [
            MemoryCategory.PROHIBITED,
            MemoryCategory.RULE,
            MemoryCategory.PITFALL,
            MemoryCategory.FAILURE_PATTERN,
        ]

        lines: list[str] = []
        for cat in priority_order:
            items = groups.pop(cat, [])
            if not items:
                continue
            lines.append(f"## {cat.value.upper()}")
            for item in items:
                lines.append(f"- {item.content or item.title}")
            lines.append("")

        for cat, items in groups.items():
            if not items:
                continue
            lines.append(f"## {cat.value.upper()}")
            for item in items:
                lines.append(f"- {item.content or item.title}")
            lines.append("")

        return "\n".join(lines)
