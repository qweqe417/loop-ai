"""MemoryStore —— 读写 .ai/memory.md。

.ai/memory.md 是项目权威记忆文件，markdown 格式，人机可读。
MemoryStore 负责解析和回写该文件。
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .models import Confidence, MemoryCategory, MemoryEntry, MemoryStats

logger = logging.getLogger(__name__)

# 默认路径（相对于项目根目录）
DEFAULT_MEMORY_PATH = ".ai/memory.md"

# ── markdown ↔ MemoryEntry 转换 ──────────────────────────────────

# 节标题 → 分类映射
SECTION_TO_CATEGORY: dict[str, MemoryCategory] = {
    "代码风格": MemoryCategory.CODE_STYLE,
    "code style": MemoryCategory.CODE_STYLE,
    "历史坑": MemoryCategory.PITFALL,
    "pitfalls": MemoryCategory.PITFALL,
    "模块边界": MemoryCategory.MODULE_BOUNDARY,
    "module boundaries": MemoryCategory.MODULE_BOUNDARY,
    "测试经验": MemoryCategory.TESTING,
    "testing": MemoryCategory.TESTING,
    "架构决策": MemoryCategory.ARCHITECTURE,
    "architecture": MemoryCategory.ARCHITECTURE,
    "禁止事项": MemoryCategory.PROHIBITED,
    "prohibited": MemoryCategory.PROHIBITED,
    "验证模式": MemoryCategory.VERIFICATION,
    "verification": MemoryCategory.VERIFICATION,
    "失败模式": MemoryCategory.FAILURE_PATTERN,
    "failure patterns": MemoryCategory.FAILURE_PATTERN,
    "通用规则": MemoryCategory.RULE,
    "rules": MemoryCategory.RULE,
}

CATEGORY_TO_SECTION: dict[MemoryCategory, str] = {
    MemoryCategory.CODE_STYLE: "代码风格",
    MemoryCategory.PITFALL: "历史坑",
    MemoryCategory.MODULE_BOUNDARY: "模块边界",
    MemoryCategory.TESTING: "测试经验",
    MemoryCategory.ARCHITECTURE: "架构决策",
    MemoryCategory.PROHIBITED: "禁止事项",
    MemoryCategory.VERIFICATION: "验证模式",
    MemoryCategory.FAILURE_PATTERN: "失败模式",
    MemoryCategory.RULE: "通用规则",
}

# 条目行正则: - [id] title (source: xxx)
ENTRY_LINE_RE = re.compile(
    r"^-\s*\[(?P<id>[^\]]+)\]\s*(?P<title>.+?)\s*\(source:\s*(?P<source>[^)]+)\)\s*$"
)


class MemoryStore:
    """项目权威记忆的读取与持久化。

    用法:
        store = MemoryStore(project_root="/path/to/project")
        entries = store.load()
        store.add(MemoryEntry(id="pitfall-001", ...))
        store.save()

    限制:
        - max_entries (默认 200): 防止记忆无限膨胀
        - max_file_size_kb (默认 50): 防止 memory.md 过大影响上下文预算
    """

    MAX_ENTRIES = 200
    MAX_FILE_SIZE_KB = 50

    def __init__(self, project_root: str | Path = ".", max_entries: int = 0) -> None:
        self._root = Path(project_root)
        self._path = self._root / DEFAULT_MEMORY_PATH
        self._entries: list[MemoryEntry] = []
        self._max_entries = max_entries or self.MAX_ENTRIES

    @property
    def path(self) -> Path:
        return self._path

    # ── 读取 ──────────────────────────────────────────────

    def load(self) -> list[MemoryEntry]:
        """从 .ai/memory.md 加载所有条目。"""
        if not self._path.exists():
            logger.info("Memory file not found: %s, starting empty", self._path)
            self._entries = []
            return []

        content = self._path.read_text(encoding="utf-8")
        self._entries = self._parse(content)
        logger.info("Loaded %d memory entries from %s", len(self._entries), self._path)
        return list(self._entries)

    def _parse(self, content: str) -> list[MemoryEntry]:
        """解析 markdown 内容为 MemoryEntry 列表。"""
        entries: list[MemoryEntry] = []
        current_category: MemoryCategory | None = None

        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue

            # 检测节标题: ## 代码风格
            if line.startswith("## "):
                section = line[3:].strip().lower()
                current_category = SECTION_TO_CATEGORY.get(section)
                continue

            # 检测条目行: - [id] title (source: xxx)
            if current_category is not None and line.startswith("- ["):
                m = ENTRY_LINE_RE.match(line)
                if m:
                    entries.append(
                        MemoryEntry(
                            id=m.group("id"),
                            category=current_category,
                            title=m.group("title"),
                            content="",  # 单行条目 content 同 title
                            source=m.group("source"),
                        )
                    )

        return entries

    # ── 写入 ──────────────────────────────────────────────

    def save(self, entries: list[MemoryEntry] | None = None) -> str:
        """将条目写回 .ai/memory.md，返回文件路径。"""
        if entries is not None:
            self._entries = entries

        self._path.parent.mkdir(parents=True, exist_ok=True)
        content = self._render(self._entries)
        self._path.write_text(content, encoding="utf-8")
        logger.info("Saved %d entries to %s", len(self._entries), self._path)
        return str(self._path)

    def _render(self, entries: list[MemoryEntry]) -> str:
        """渲染条目列表为 markdown。"""
        # 按分类分组
        groups: dict[MemoryCategory, list[MemoryEntry]] = {}
        for e in entries:
            groups.setdefault(e.category, []).append(e)

        lines: list[str] = [
            "# 项目记忆",
            "",
            f"> 最后更新: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"> 条目总数: {len(entries)}",
            "",
            "---",
            "",
        ]

        # 按固定顺序输出
        section_order = [
            MemoryCategory.CODE_STYLE,
            MemoryCategory.RULE,
            MemoryCategory.PROHIBITED,
            MemoryCategory.PITFALL,
            MemoryCategory.FAILURE_PATTERN,
            MemoryCategory.MODULE_BOUNDARY,
            MemoryCategory.ARCHITECTURE,
            MemoryCategory.TESTING,
            MemoryCategory.VERIFICATION,
        ]

        for cat in section_order:
            items = groups.pop(cat, [])
            section_title = CATEGORY_TO_SECTION.get(cat, cat.value)
            lines.append(f"## {section_title}")
            lines.append("")
            if items:
                for item in sorted(items, key=lambda e: e.id):
                    content_line = item.content if item.content != item.title else ""
                    line = f"- [{item.id}] {item.title}"
                    if item.source and item.source != "manual":
                        line += f" (source: {item.source})"
                    else:
                        line += " (source: manual)"
                    lines.append(line)
                    if content_line:
                        lines.append(f"  {content_line}")
            else:
                lines.append("<!-- 暂无条目 -->")
            lines.append("")

        # 未分类的剩余分组
        for cat, items in groups.items():
            section_title = CATEGORY_TO_SECTION.get(cat, cat.value)
            lines.append(f"## {section_title}")
            lines.append("")
            for item in sorted(items, key=lambda e: e.id):
                lines.append(f"- [{item.id}] {item.title} (source: {item.source})")
            lines.append("")

        return "\n".join(lines)

    # ── CRUD ──────────────────────────────────────────────

    def add(self, entry: MemoryEntry) -> bool:
        """添加一条记忆（自动去重 + 上限裁剪 + LRU 淘汰）。

        超过上限时淘汰最旧的条目（按 updated_at 排序）。
        """
        if self._exists(entry.id):
            logger.debug("Duplicate entry skipped: %s", entry.id)
            return False

        # 上限检查: LRU 淘汰最旧条目
        while len(self._entries) >= self._max_entries:
            oldest = min(self._entries, key=lambda e: e.updated_at or datetime.min)
            self._entries.remove(oldest)
            logger.info(
                "Memory limit reached (%d), evicted oldest: %s (%s)",
                self._max_entries, oldest.id, oldest.title[:40],
            )

        entry.updated_at = datetime.now()
        self._entries.append(entry)
        logger.info("Memory entry added: %s (%s)", entry.id, entry.title)
        return True

    def promote(self, entry_id: str) -> bool:
        """将指定条目从 DRAFT 升级为 CONFIRMED。

        当一条记忆被成功应用（如相同 pitfall 被避免）时调用。
        """
        for e in self._entries:
            if e.id == entry_id and e.confidence == Confidence.DRAFT:
                e.confidence = Confidence.CONFIRMED
                e.updated_at = datetime.now()
                logger.info("Memory entry promoted to CONFIRMED: %s", entry_id)
                return True
        return False

    def promote_by_tags(self, tags: list[str], min_matches: int = 2) -> int:
        """批量升级: 匹配指定 tags 且出现次数 ≥ min_matches 的 DRAFT 条目。

        启发式: 相同 tag 的条目被多次提取 → 可能是可复现的模式 → 值得确认。
        """
        upgraded = 0
        for e in self._entries:
            if e.confidence != Confidence.DRAFT:
                continue
            matches = sum(1 for t in tags if t in e.tags)
            if matches >= min_matches:
                e.confidence = Confidence.CONFIRMED
                e.updated_at = datetime.now()
                upgraded += 1
        if upgraded:
            logger.info("Promoted %d entries by tags: %s", upgraded, tags)
        return upgraded

    def remove(self, entry_id: str) -> bool:
        """按 ID 移除条目。"""
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.id != entry_id]
        removed = before - len(self._entries)
        if removed:
            logger.info("Memory entry removed: %s", entry_id)
        return removed > 0

    def find(
        self,
        category: MemoryCategory | None = None,
        tags: list[str] | None = None,
        confidence: Confidence | None = None,
    ) -> list[MemoryEntry]:
        """按条件查找条目。"""
        results = self._entries
        if category is not None:
            results = [e for e in results if e.category == category]
        if tags:
            results = [e for e in results if any(t in e.tags for t in tags)]
        if confidence is not None:
            results = [e for e in results if e.confidence == confidence]
        return results

    def stats(self) -> MemoryStats:
        """返回记忆库统计。"""
        by_cat: dict[str, int] = {}
        confirmed = 0
        draft = 0
        deprecated = 0
        for e in self._entries:
            by_cat[e.category.value] = by_cat.get(e.category.value, 0) + 1
            if e.confidence == Confidence.CONFIRMED:
                confirmed += 1
            elif e.confidence == Confidence.DRAFT:
                draft += 1
            elif e.confidence == Confidence.DEPRECATED:
                deprecated += 1

        last = max((e.updated_at for e in self._entries), default=None)

        return MemoryStats(
            total_entries=len(self._entries),
            by_category=by_cat,
            confirmed=confirmed,
            draft=draft,
            deprecated=deprecated,
            last_updated=last,
        )

    def _exists(self, entry_id: str) -> bool:
        return any(e.id == entry_id for e in self._entries)
