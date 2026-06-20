"""MemoryProjection —— 将 .ai/memory.md 投影到工具文件。

投影方向：
    .ai/memory.md (权威源)
        → CLAUDE.md (核心规则摘要)
        → .claude/aicode/memory.md (完整投影)
        → .claude/rules/safety.md (禁止事项)
        → .claude/rules/testing.md (测试经验)
        → .codex/aicode/memory.md (Codex 投影)
        → .cursor/rules/aicode-memory.md (Cursor 投影)
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from .models import Confidence, MemoryCategory, MemoryEntry
from .store import MemoryStore

logger = logging.getLogger(__name__)

# 投影目标文件路径（相对于项目根目录）
PROJECTION_TARGETS: dict[str, list[str]] = {
    "claude": [
        "CLAUDE.md",
        ".claude/aicode/memory.md",
        ".claude/rules/safety.md",
        ".claude/rules/testing.md",
    ],
    "codex": [
        ".codex/aicode/memory.md",
    ],
    "cursor": [
        ".cursor/rules/aicode-memory.md",
    ],
}


class MemoryProjection:
    """将记忆条目同步到工具原生文件。

    用法:
        store = MemoryStore(project_root=".")
        projection = MemoryProjection(store)
        projection.sync("claude")   # 只同步 Claude Code 文件
        projection.sync_all()       # 同步所有工具
    """

    def __init__(self, store: MemoryStore) -> None:
        self._store = store
        self._root = store._root if hasattr(store, '_root') else Path(".")

    def sync(self, target: str) -> list[str]:
        """同步到指定工具，返回更新的文件路径列表。"""
        if target not in PROJECTION_TARGETS:
            logger.warning("Unknown projection target: %s", target)
            return []

        entries = self._store.load()
        confirmed = [e for e in entries if e.confidence == Confidence.CONFIRMED]
        updated: list[str] = []

        for rel_path in PROJECTION_TARGETS[target]:
            full_path = self._root / rel_path

            if rel_path == "CLAUDE.md":
                self._update_claude_md(full_path, confirmed)
            elif "memory.md" in rel_path:
                self._write_full_projection(full_path, confirmed)
            elif "safety.md" in rel_path:
                self._write_category_projection(
                    full_path, confirmed, MemoryCategory.PROHIBITED,
                    "安全与禁止事项", "本文件由 AI Coding Loop Memory 系统自动生成/更新。"
                )
            elif "testing.md" in rel_path:
                self._write_category_projection(
                    full_path, confirmed, MemoryCategory.TESTING,
                    "测试经验与验证方式", "本文件由 AI Coding Loop Memory 系统自动生成/更新。"
                )

            updated.append(str(full_path))

        logger.info("Projection synced to '%s': %d files updated", target, len(updated))
        return updated

    def sync_all(self) -> dict[str, list[str]]:
        """同步到所有已配置的工具。"""
        results: dict[str, list[str]] = {}
        for target in PROJECTION_TARGETS:
            results[target] = self.sync(target)
        return results

    # ── 投影策略 ──────────────────────────────────────────

    def _update_claude_md(
        self, path: Path, entries: list[MemoryEntry]
    ) -> None:
        """将关键规则注入 CLAUDE.md 的 AI Coding Loop 段。

        CLAUDE.md 由 project init 生成，投影只更新标记段内的内容。
        """
        if not path.exists():
            logger.info("CLAUDE.md not found at %s, skipping projection", path)
            return

        content = path.read_text(encoding="utf-8")

        # 找到或创建投影段
        start_marker = "<!-- AI_CODING_LOOP_MEMORY_START -->"
        end_marker = "<!-- AI_CODING_LOOP_MEMORY_END -->"

        proj_lines = self._render_projection_section(entries)

        if start_marker in content and end_marker in content:
            # 替换现有段
            before = content.split(start_marker)[0]
            after = content.split(end_marker)[-1]
            new_content = before + start_marker + "\n" + proj_lines + "\n" + end_marker + after
        else:
            # 追加到末尾
            new_content = content.rstrip() + "\n\n" + start_marker + "\n" + proj_lines + "\n" + end_marker + "\n"

        path.write_text(new_content, encoding="utf-8")
        logger.info("Updated CLAUDE.md projection at %s", path)

    def _write_full_projection(
        self, path: Path, entries: list[MemoryEntry]
    ) -> None:
        """写入完整投影（.claude/aicode/memory.md 等）。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# AI Coding Loop — 记忆投影",
            "",
            f"> 最后同步: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"> 来源: .ai/memory.md",
            f"> 条目数: {len(entries)}",
            "",
            "---",
            "",
        ]
        lines.append(self._render_projection_section(entries))
        path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Wrote full projection to %s", path)

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
                    lines.append(f"  (来源: task {e.source})")
        else:
            lines.append("<!-- 暂无条目 -->")
        lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Wrote %s projection to %s (%d entries)", category.value, path, len(filtered))

    # ── 渲染 ──────────────────────────────────────────────

    def _render_projection_section(self, entries: list[MemoryEntry]) -> str:
        """将条目列表渲染为投影文本。"""
        lines: list[str] = []

        # 按分类分组
        groups: dict[MemoryCategory, list[MemoryEntry]] = {}
        for e in entries:
            groups.setdefault(e.category, []).append(e)

        priority_order = [
            MemoryCategory.PROHIBITED,
            MemoryCategory.RULE,
            MemoryCategory.PITFALL,
            MemoryCategory.FAILURE_PATTERN,
        ]

        for cat in priority_order:
            items = groups.pop(cat, [])
            if not items:
                continue
            cat_label = cat.value.upper()
            lines.append(f"## {cat_label}")
            for item in items:
                lines.append(f"- {item.content or item.title}")
            lines.append("")

        # 剩余分类
        for cat, items in groups.items():
            if not items:
                continue
            cat_label = cat.value.upper()
            lines.append(f"## {cat_label}")
            for item in items:
                lines.append(f"- {item.content or item.title}")
            lines.append("")

        return "\n".join(lines)
