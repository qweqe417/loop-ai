"""MemoryStore —— 读写三层记忆体系。

三层结构:
    .ai/memory.md          — 权威索引（只放摘要，不放长文）
    .ai/memory/entries/    — 详细条目正文
    .ai/memory/sessions/   — 单次任务候选原料
    .ai/memory/archive/    — 废弃/低频归档
    .ai/memory/projections/— 工具投影缓存（非权威源）
    .ai/memory/stats.json  — 运营面板数据
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from .models import Confidence, MemoryCategory, MemoryEntry, MemoryGovernance, MemoryStats

logger = logging.getLogger(__name__)

# ── 路径常量 ──────────────────────────────────────────────────

DEFAULT_INDEX = ".ai/memory.md"
MEMORY_DIR = ".ai/memory"
ENTRIES_DIR = ".ai/memory/entries"
SESSIONS_DIR = ".ai/memory/sessions"
ARCHIVE_DEPRECATED = ".ai/memory/archive/deprecated"
ARCHIVE_STALE = ".ai/memory/archive/stale"
PROJECTIONS_DIR = ".ai/memory/projections"
STATS_FILE = ".ai/memory/stats.json"

# ── 索引行解析 ────────────────────────────────────────────────

# 格式: - [id] title `[confidence]` `[tag1,tag2]`
_INDEX_LINE_RE = re.compile(
    r"^-\s*\[(?P<id>[^\]]+)\]\s*(?P<title>.+?)\s*"
    r"`\[(?P<confidence>[^\]]+)\]`\s*"
    r"`\[(?P<tags>[^\]]*)\]`\s*$"
)

# 旧格式兼容: - [id] title (source: xxx)
_LEGACY_LINE_RE = re.compile(
    r"^-\s*\[(?P<id>[^\]]+)\]\s*(?P<title>.+?)\s*\(source:\s*(?P<source>[^)]+)\)\s*$"
)

# 节标题 → 分类
SECTION_TO_CATEGORY: dict[str, MemoryCategory] = {
    "通用规则": MemoryCategory.RULE,
    "rule": MemoryCategory.RULE,
    "rules": MemoryCategory.RULE,
    "历史坑": MemoryCategory.PITFALL,
    "pitfall": MemoryCategory.PITFALL,
    "pitfalls": MemoryCategory.PITFALL,
    "验证模式": MemoryCategory.VERIFICATION,
    "verification": MemoryCategory.VERIFICATION,
    "测试经验": MemoryCategory.TESTING,
    "testing": MemoryCategory.TESTING,
    "模块边界": MemoryCategory.MODULE_BOUNDARY,
    "module_boundary": MemoryCategory.MODULE_BOUNDARY,
    "module boundaries": MemoryCategory.MODULE_BOUNDARY,
    "架构决策": MemoryCategory.ARCHITECTURE,
    "architecture": MemoryCategory.ARCHITECTURE,
    "失败模式": MemoryCategory.FAILURE_PATTERN,
    "failure_pattern": MemoryCategory.FAILURE_PATTERN,
    "禁止事项": MemoryCategory.PROHIBITED,
    "prohibited": MemoryCategory.PROHIBITED,
    "代码风格": MemoryCategory.CODE_STYLE,
    "code_style": MemoryCategory.CODE_STYLE,
    "code style": MemoryCategory.CODE_STYLE,
}

CATEGORY_TO_SECTION: dict[MemoryCategory, str] = {
    MemoryCategory.RULE: "通用规则",
    MemoryCategory.PITFALL: "历史坑",
    MemoryCategory.VERIFICATION: "验证模式",
    MemoryCategory.TESTING: "测试经验",
    MemoryCategory.MODULE_BOUNDARY: "模块边界",
    MemoryCategory.ARCHITECTURE: "架构决策",
    MemoryCategory.FAILURE_PATTERN: "失败模式",
    MemoryCategory.PROHIBITED: "禁止事项",
    MemoryCategory.CODE_STYLE: "代码风格",
}

# memory.md 中分类的展示顺序
SECTION_ORDER = [
    MemoryCategory.RULE,
    MemoryCategory.PITFALL,
    MemoryCategory.VERIFICATION,
    MemoryCategory.TESTING,
    MemoryCategory.MODULE_BOUNDARY,
    MemoryCategory.ARCHITECTURE,
    MemoryCategory.FAILURE_PATTERN,
    MemoryCategory.PROHIBITED,
    MemoryCategory.CODE_STYLE,
]

# ── 阶段 → 优先召回分类 ─────────────────────────────────────

STAGE_RECALL_PRIORITY: dict[str, list[MemoryCategory]] = {
    "spec": [MemoryCategory.ARCHITECTURE, MemoryCategory.MODULE_BOUNDARY, MemoryCategory.RULE],
    "plan": [MemoryCategory.ARCHITECTURE, MemoryCategory.RULE, MemoryCategory.PITFALL],
    "test_design": [MemoryCategory.VERIFICATION, MemoryCategory.TESTING, MemoryCategory.ARCHITECTURE],
    "execute": [MemoryCategory.RULE, MemoryCategory.PITFALL, MemoryCategory.CODE_STYLE],
    "dev": [MemoryCategory.RULE, MemoryCategory.PITFALL, MemoryCategory.CODE_STYLE],
    "direct_execute": [MemoryCategory.RULE, MemoryCategory.PITFALL, MemoryCategory.CODE_STYLE],
    "verify": [MemoryCategory.VERIFICATION, MemoryCategory.TESTING, MemoryCategory.FAILURE_PATTERN],
    "repair": [MemoryCategory.FAILURE_PATTERN, MemoryCategory.PITFALL, MemoryCategory.RULE],
    "review": [MemoryCategory.PROHIBITED, MemoryCategory.PITFALL, MemoryCategory.MODULE_BOUNDARY],
    "memory": [MemoryCategory.RULE, MemoryCategory.PITFALL, MemoryCategory.FAILURE_PATTERN],
}

MAX_ENTRIES = 200
DRAFT_STALE_DAYS = 30


class MemoryStore:
    """项目权威记忆的读取与持久化。

    用法:
        store = MemoryStore(project_root=".")
        store.load_index()                # 只读 memory.md 索引
        store.add(entry)                  # 写入 entries/{id}.md + 更新索引
        results = store.recall(["支付"], stage="execute", limit=5)
    """

    def __init__(self, project_root: str | Path = ".") -> None:
        self._root = Path(project_root)
        self._entries: list[MemoryEntry] = []
        self._loaded = False

    # ── 路径属性 ──────────────────────────────────────────

    @property
    def index_path(self) -> Path:
        return self._root / DEFAULT_INDEX

    @property
    def entries_dir(self) -> Path:
        return self._root / ENTRIES_DIR

    @property
    def sessions_dir(self) -> Path:
        return self._root / SESSIONS_DIR

    @property
    def projections_dir(self) -> Path:
        return self._root / PROJECTIONS_DIR

    # ── 加载 ──────────────────────────────────────────────

    def load(self) -> list[MemoryEntry]:
        """加载所有条目（兼容旧接口，= load_index + 标记已加载）。"""
        self._loaded = True
        return self.load_index()

    def load_index(self) -> list[MemoryEntry]:
        """解析 memory.md 索引行。合并已有条目，保留 entry 文件的 3 段数据。"""
        if not self.index_path.exists():
            logger.debug("Index not found: %s", self.index_path)
            self._entries = []
            return []

        content = self.index_path.read_text(encoding="utf-8")
        new_entries = self._parse_index(content)

        # 合并：保留已有条目中的 3 段数据（trigger/error/fix）
        if self._entries:
            existing_map = {e.id: e for e in self._entries}
            for ne in new_entries:
                if ne.id in existing_map:
                    old = existing_map[ne.id]
                    # 保留已有详细数据
                    ne.trigger_conditions = ne.trigger_conditions or old.trigger_conditions
                    ne.error_pattern = ne.error_pattern or old.error_pattern
                    ne.fix_rule = ne.fix_rule or old.fix_rule
                    ne.relates_to = ne.relates_to or old.relates_to
                    ne.caused_by = ne.caused_by or old.caused_by
                    ne.fixed_by = ne.fixed_by or old.fixed_by
                    ne.effective_count = ne.effective_count or old.effective_count
                    ne.ineffective_count = ne.ineffective_count or old.ineffective_count

        self._entries = new_entries
        self._loaded = True
        logger.info("Loaded %d entries from index", len(self._entries))
        return list(self._entries)

    def load_entry(self, entry_id: str) -> MemoryEntry | None:
        """加载单条记忆的完整正文（从 entries/{id}.md）。"""
        entry_path = self.entries_dir / f"{entry_id}.md"
        if not entry_path.exists():
            # 回退到索引中的记录
            for e in self._entries:
                if e.id == entry_id:
                    return e
            return None
        return self._parse_entry_file(entry_path, entry_id)

    def _parse_index(self, content: str) -> list[MemoryEntry]:
        """解析 memory.md 索引行。"""
        # 检测旧格式: 旧格式条目行使用 (source: xxx)，新格式使用 `[confidence]`
        if "(source:" in content and "`[confirmed]" not in content and "`[draft]" not in content:
            return self._parse_legacy_index(content)

        entries: list[MemoryEntry] = []
        current_category: MemoryCategory | None = None

        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue

            if line.startswith("## "):
                section = line[3:].strip().lower()
                current_category = SECTION_TO_CATEGORY.get(section)
                continue

            if current_category is not None and line.startswith("- ["):
                m = _INDEX_LINE_RE.match(line)
                if m:
                    tags = [t.strip() for t in m.group("tags").split(",") if t.strip()]
                    entries.append(MemoryEntry(
                        id=m.group("id"),
                        category=current_category,
                        title=m.group("title"),
                        content=m.group("title"),  # 索引行 title 即摘要
                        confidence=Confidence(m.group("confidence")),
                        tags=tags,
                    ))
        return entries

    def _parse_legacy_index(self, content: str) -> list[MemoryEntry]:
        """解析旧格式 memory.md（兼容迁移）。"""
        entries: list[MemoryEntry] = []
        current_category: MemoryCategory | None = None

        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("## "):
                section = line[3:].strip().lower()
                current_category = SECTION_TO_CATEGORY.get(section)
                continue
            if current_category is not None and line.startswith("- ["):
                m = _LEGACY_LINE_RE.match(line)
                if m:
                    entries.append(MemoryEntry(
                        id=m.group("id"),
                        category=current_category,
                        title=m.group("title"),
                        content="",
                        source=m.group("source"),
                        confidence=Confidence.CONFIRMED,
                        tags=[],
                    ))
        return entries

    def _parse_entry_file(self, path: Path, entry_id: str) -> MemoryEntry | None:
        """解析 entries/{id}.md 完整条目文件。"""
        try:
            text = path.read_text(encoding="utf-8")
            return self._parse_entry_md(text, entry_id)
        except Exception:
            logger.warning("Failed to parse entry file: %s", path)
            return None

    def _parse_entry_md(self, text: str, entry_id: str) -> MemoryEntry | None:
        """解析 entries/{id}.md 文件。

        支持新格式 (YAML frontmatter + Markdown) 和旧格式 (HTML 注释)。
        """
        try:
            import yaml
        except ImportError:
            yaml = None

        # 尝试新格式: YAML frontmatter
        if yaml and text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                try:
                    meta = yaml.safe_load(parts[1])
                    body = parts[2].strip()
                    if meta and isinstance(meta, dict):
                        return self._parse_new_entry(meta, body, entry_id)
                except Exception:
                    pass  # fall through to legacy parser

        # 旧格式: HTML 注释
        return self._parse_legacy_entry(text, entry_id)

    def _parse_new_entry(self, meta: dict, body: str, entry_id: str) -> MemoryEntry:
        """解析 YAML frontmatter 格式。"""
        sections = _split_sections(body)

        title = meta.get("title", "")
        if not title:
            # Extract from # heading
            for line in body.splitlines():
                stripped = line.strip()
                if stripped.startswith("# ") and not stripped.startswith("## "):
                    title = stripped[2:].strip()
                    break

        return MemoryEntry(
            id=entry_id,
            category=MemoryCategory(meta.get("category", "rule")),
            title=title,
            content=meta.get("content", sections.get("Notes", "")),
            source=str(meta.get("source", "manual")),
            confidence=Confidence(meta.get("confidence", "draft")),
            tags=meta.get("tags", []),
            hit_count=int(meta.get("hit_count", 0)),
            last_hit_at=_parse_dt(meta.get("last_hit_at", "")),
            created_at=_parse_dt(meta.get("created_at", "")) or datetime.now(),
            updated_at=_parse_dt(meta.get("updated_at", "")) or datetime.now(),
            trigger_conditions=sections.get("Trigger", ""),
            error_pattern=sections.get("Failure Pattern", ""),
            fix_rule=sections.get("Fix Rule", ""),
            relates_to=meta.get("relates_to", []),
            caused_by=meta.get("caused_by", []),
            fixed_by=meta.get("fixed_by", []),
            effective_count=int(meta.get("effective_count", 0)),
            ineffective_count=int(meta.get("ineffective_count", 0)),
        )

    def _parse_legacy_entry(self, text: str, entry_id: str) -> MemoryEntry | None:
        """解析旧格式 (HTML 注释 + ## Summary/## Details)。"""
        lines = text.splitlines()
        meta: dict[str, str] = {}
        current_section: str | None = None
        sections: dict[str, list[str]] = {
            "Trigger": [],
            "Failure Pattern": [],
            "Fix Rule": [],
            "Notes": [],
        }

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("<!-- ") and stripped.endswith(" -->"):
                inner = stripped[5:-4].strip()
                if ": " in inner:
                    k, v = inner.split(": ", 1)
                    meta[k.strip()] = v.strip()
            elif stripped.startswith("## "):
                section_name = stripped[3:].strip()
                for key in sections:
                    if key.lower() in section_name.lower():
                        current_section = key
                        break
                else:
                    current_section = None
            elif current_section and current_section in sections:
                sections[current_section].append(line)

        if not meta:
            return None

        relates_to = [r.strip() for r in meta.get("relates_to", "").split(",") if r.strip()]
        caused_by = [r.strip() for r in meta.get("caused_by", "").split(",") if r.strip()]
        fixed_by = [r.strip() for r in meta.get("fixed_by", "").split(",") if r.strip()]

        return MemoryEntry(
            id=entry_id,
            category=MemoryCategory(meta.get("category", "rule")),
            title=meta.get("title", ""),
            content="\n".join(sections["Notes"]).strip(),
            source=meta.get("source", "manual"),
            confidence=Confidence(meta.get("confidence", "draft")),
            tags=[t.strip() for t in meta.get("tags", "").split(",") if t.strip()],
            hit_count=int(meta.get("hit_count", 0)),
            last_hit_at=_parse_dt(meta.get("last_hit_at", "")),
            created_at=_parse_dt(meta.get("created_at", "")) or datetime.now(),
            updated_at=_parse_dt(meta.get("updated_at", "")) or datetime.now(),
            trigger_conditions="\n".join(sections["Trigger"]).strip(),
            error_pattern="\n".join(sections["Failure Pattern"]).strip(),
            fix_rule="\n".join(sections["Fix Rule"]).strip(),
            relates_to=relates_to,
            caused_by=caused_by,
            fixed_by=fixed_by,
            effective_count=int(meta.get("effective_count", 0)),
            ineffective_count=int(meta.get("ineffective_count", 0)),
        )

    # ── 写入 ──────────────────────────────────────────────

    def save(self, entries: list[MemoryEntry] | None = None) -> str:
        """保存索引和所有条目文件，返回索引文件路径。"""
        if entries is not None:
            self._entries = entries
        self._save_index()
        logger.info("Saved %d entries to index and entries/", len(self._entries))
        return str(self.index_path)

    def _save_index(self) -> None:
        """写 memory.md 索引文件。"""
        self.index_path.parent.mkdir(parents=True, exist_ok=True)

        # 按分类分组
        groups: dict[MemoryCategory, list[MemoryEntry]] = {}
        for e in self._entries:
            groups.setdefault(e.category, []).append(e)

        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        total = len(self._entries)
        confirmed = sum(1 for e in self._entries if e.confidence == Confidence.CONFIRMED)
        draft = sum(1 for e in self._entries if e.confidence == Confidence.DRAFT)
        deprecated = sum(1 for e in self._entries if e.confidence == Confidence.DEPRECATED)

        lines: list[str] = [
            "# 项目记忆",
            "",
            f"> 更新: {now} | 总计: {total} | confirmed: {confirmed} | draft: {draft} | deprecated: {deprecated}",
            "",
        ]

        for cat in SECTION_ORDER:
            items = groups.pop(cat, [])
            section_title = CATEGORY_TO_SECTION.get(cat, cat.value)
            lines.append(f"## {section_title}")
            lines.append("")
            if items:
                for item in sorted(items, key=lambda e: e.id):
                    lines.append(item.summary_line())
            else:
                lines.append("<!-- 暂无条目 -->")
            lines.append("")

        # 剩余未归类分组
        for cat, items in groups.items():
            section_title = CATEGORY_TO_SECTION.get(cat, cat.value)
            lines.append(f"## {section_title}")
            lines.append("")
            for item in sorted(items, key=lambda e: e.id):
                lines.append(item.summary_line())
            lines.append("")

        self.index_path.write_text("\n".join(lines), encoding="utf-8")
        logger.debug("Index saved to %s", self.index_path)

    def save_entry(self, entry: MemoryEntry) -> None:
        """写入单条记忆到 entries/{id}.md。

        YAML frontmatter + 3 段式正文，人机可读。
        """
        import yaml

        self.entries_dir.mkdir(parents=True, exist_ok=True)
        path = self.entries_dir / f"{entry.id}.md"

        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

        frontmatter = {
            "id": entry.id,
            "category": entry.category.value,
            "confidence": entry.confidence.value,
            "tags": entry.tags,
            "source": entry.source,
            "hit_count": entry.hit_count,
            "last_hit_at": entry.last_hit_at.isoformat() if entry.last_hit_at else None,
            "effective_count": entry.effective_count,
            "ineffective_count": entry.ineffective_count,
            "relates_to": entry.relates_to,
            "caused_by": entry.caused_by,
            "fixed_by": entry.fixed_by,
            "created_at": entry.created_at.isoformat() if entry.created_at else now,
            "updated_at": now,
        }
        # 去掉 None 值
        frontmatter = {k: v for k, v in frontmatter.items() if v is not None and v != []}

        yaml_header = yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False, sort_keys=False).strip()

        lines = [
            "---",
            yaml_header,
            "---",
            "",
            f"# {entry.title}",
            "",
        ]
        if entry.trigger_conditions:
            lines.extend(["## Trigger", "", entry.trigger_conditions, ""])
        if entry.error_pattern:
            lines.extend(["## Failure Pattern", "", entry.error_pattern, ""])
        if entry.fix_rule:
            lines.extend(["## Fix Rule", "", entry.fix_rule, ""])
        if entry.content and entry.content != entry.error_pattern:
            lines.extend(["## Notes", "", entry.content, ""])

        path.write_text("\n".join(lines), encoding="utf-8")
        logger.debug("Entry saved: %s", path)

    def save_session(self, session: dict) -> str:
        """保存单次任务会话 → sessions/{task_id}.json。"""
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        task_id = session.get("task_id", "unknown")
        path = self.sessions_dir / f"{task_id}.json"

        # 序列化 datetime
        data = _json_ready(session)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Session saved: %s", path)
        return str(path)

    # ── CRUD ──────────────────────────────────────────────

    def add(self, entry: MemoryEntry) -> bool:
        """添加一条记忆：写 entries/{id}.md + 更新 memory.md 索引。"""
        if self._exists(entry.id):
            logger.debug("Duplicate skipped: %s", entry.id)
            return False

        # 上限检查
        while len(self._entries) >= MAX_ENTRIES:
            self._evict_one()

        entry.updated_at = datetime.now()
        self._entries.append(entry)

        # 写详细正文
        self.save_entry(entry)

        # 更新索引
        self._save_index()
        logger.info("Entry added: %s (%s)", entry.id, entry.title[:40])
        return True

    def remove(self, entry_id: str) -> bool:
        """移除记忆：删 entries/{id}.md + 从索引移除。"""
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.id != entry_id]
        if len(self._entries) < before:
            entry_file = self.entries_dir / f"{entry_id}.md"
            if entry_file.exists():
                entry_file.unlink()
            self._save_index()
            logger.info("Entry removed: %s", entry_id)
            return True
        return False

    def promote(self, entry_id: str) -> bool:
        """将 draft 升级为 confirmed。"""
        for e in self._entries:
            if e.id == entry_id and e.confidence == Confidence.DRAFT:
                e.confidence = Confidence.CONFIRMED
                e.updated_at = datetime.now()
                self.save_entry(e)
                self._save_index()
                logger.info("Promoted to CONFIRMED: %s", entry_id)
                return True
        return False

    def deprecate(self, entry_id: str) -> bool:
        """标记为 deprecated，移入 archive/deprecated/。"""
        for e in self._entries:
            if e.id == entry_id:
                e.confidence = Confidence.DEPRECATED
                e.updated_at = datetime.now()
                self._archive_entry_file(e, "deprecated")
                self._entries.remove(e)
                self._save_index()
                logger.info("Deprecated: %s", entry_id)
                return True
        return False

    def promote_by_tags(self, tags: list[str], min_matches: int = 2) -> int:
        """批量升级: 匹配指定 tags 且出现次数 ≥ min_matches 的 DRAFT 条目。"""
        upgraded = 0
        for e in self._entries:
            if e.confidence != Confidence.DRAFT:
                continue
            matches = sum(1 for t in tags if t in e.tags)
            if matches >= min_matches:
                e.confidence = Confidence.CONFIRMED
                e.updated_at = datetime.now()
                self.save_entry(e)
                upgraded += 1
        if upgraded:
            self._save_index()
            logger.info("Promoted %d entries by tags: %s", upgraded, tags)
        return upgraded

    def record_hit(self, entry_id: str) -> None:
        """记录一次召回命中（更新 hit_count/last_hit_at）。"""
        for e in self._entries:
            if e.id == entry_id:
                e.record_hit()
                try:
                    self.save_entry(e)
                except Exception:
                    pass
                return

    def record_effectiveness(self, entry_id: str, effective: bool) -> None:
        """记录记忆效果：effective=True 表示修复规则被应用且通过验证。"""
        for e in self._entries:
            if e.id == entry_id:
                if effective:
                    e.record_effective()
                else:
                    e.record_ineffective()

                # 自动状态转换
                if e.effective_count >= 3 and e.confidence == Confidence.DRAFT:
                    e.confidence = Confidence.CONFIRMED
                    logger.info("Auto-promoted %s: 3x effective (draft→confirmed)", entry_id)
                if e.ineffective_count >= 3 and e.confidence == Confidence.CONFIRMED:
                    e.confidence = Confidence.DEPRECATED
                    logger.info("Auto-deprecated %s: 3x ineffective", entry_id)

                try:
                    self.save_entry(e)
                except Exception:
                    pass
                self._save_index()
                return

    def _find_by_id(self, entry_id: str) -> MemoryEntry | None:
        """按 ID 查找记忆条目。"""
        for e in self._entries:
            if e.id == entry_id:
                return e
        return None

    # ── 召回 ──────────────────────────────────────────────

    def recall(
        self,
        keywords: list[str] | None = None,
        stage: str = "",
        limit: int = 5,
        confidence_filter: list[Confidence] | None = None,
        hop_relationships: bool = True,
    ) -> list[MemoryEntry]:
        """分级召回：关键词 + 阶段优先级 + 效果衰减 + 关系跳数。

        不读取 entries/ 正文，只在索引层匹配。

        Args:
            keywords: 搜索关键词
            stage: 当前阶段（用于阶段优先级加权）
            limit: 返回上限
            confidence_filter: 置信度过滤
            hop_relationships: 是否沿关系图谱 ±1 跳扩展候选
        """
        if not self._loaded:
            self.load_index()

        if confidence_filter is None:
            confidence_filter = [Confidence.CONFIRMED, Confidence.DRAFT]

        # 过滤 deprecated + 效果衰减过滤
        candidates = [
            e for e in self._entries
            if e.confidence in confidence_filter
            and not (e.ineffective_count >= 3 and e.confidence == Confidence.CONFIRMED)
        ]

        if not candidates:
            return []

        # 按阶段优先级排序
        priority_cats = STAGE_RECALL_PRIORITY.get(stage.lower(), [])

        scored: list[tuple[float, float, MemoryEntry]] = []

        for entry in candidates:
            score = 0.0
            keywords_lower = [kw.lower() for kw in (keywords or [])]
            combined = f"{entry.title} {' '.join(entry.tags)} {entry.category.value} {entry.trigger_conditions}".lower()

            # 关键词匹配（trigger_conditions 也算）
            for kw in keywords_lower:
                if kw in combined:
                    score += 3.0

            # 阶段优先级
            if entry.category in priority_cats:
                cat_idx = priority_cats.index(entry.category)
                score += len(priority_cats) - cat_idx  # 越靠前加分越多

            # 置信度加权
            confidence_weight = {
                Confidence.CONFIRMED: 1.0,
                Confidence.DRAFT: 0.5,
                Confidence.DEPRECATED: 0.0,
            }
            score *= confidence_weight.get(entry.confidence, 0.5)

            # 效果衰减：连续无效的记忆降权
            if entry.ineffective_count >= 3:
                score *= 0.3
            elif entry.effective_count >= 3:
                score *= 1.2  # 连续有效加权

            # 最近命中加分
            if entry.last_hit_at:
                days_ago = (datetime.now() - entry.last_hit_at).days
                if days_ago < 7:
                    score += 1.0
                elif days_ago > 30:
                    score -= 1.0  # 冷记忆降权

            if score > 0 or not keywords:
                scored.append((score, entry.hit_count * 0.1, entry))

        # 排序：分数 > 命中次数 > updated_at
        scored.sort(key=lambda x: (
            -x[0],
            -x[1],
            -(x[2].updated_at.timestamp() if x[2].updated_at else 0),
        ))

        results = [e for _, _, e in scored[:limit]]

        # 关系跳数扩展：±1 跳
        if hop_relationships:
            expanded: list[MemoryEntry] = list(results)
            seen_ids = {e.id for e in results}
            for entry in results:
                for rel_id in entry.relates_to + entry.caused_by + entry.fixed_by:
                    if rel_id not in seen_ids:
                        rel_entry = self._find_by_id(rel_id)
                        if rel_entry and rel_entry.confidence in confidence_filter:
                            expanded.append(rel_entry)
                            seen_ids.add(rel_id)
            # 关系扩展不超 limit + 3
            results = expanded[:limit + 3]

        # 记录命中
        for e in results:
            e.record_hit()

        return results

    def recall_by_category(
        self, categories: list[MemoryCategory], limit: int = 5
    ) -> list[MemoryEntry]:
        """按分类召回（REPAIR 阶段专用）。"""
        if not self._loaded:
            self.load_index()

        candidates = [
            e for e in self._entries
            if e.category in categories and e.confidence != Confidence.DEPRECATED
        ]
        candidates.sort(key=lambda e: (e.confidence == Confidence.CONFIRMED, e.hit_count), reverse=True)

        for e in candidates[:limit]:
            e.record_hit()

        return candidates[:limit]

    # ── 压缩与归档 ────────────────────────────────────────

    def evict_stale_drafts(self, days: int = DRAFT_STALE_DAYS) -> int:
        """淘汰过期 draft：长期未命中的 draft 移入 archive/stale/。"""
        if not self._loaded:
            self.load_index()

        cutoff = datetime.now() - timedelta(days=days)
        stale: list[MemoryEntry] = []

        for e in self._entries:
            if e.confidence != Confidence.DRAFT:
                continue
            last = e.last_hit_at or e.updated_at or e.created_at
            if last < cutoff:
                stale.append(e)

        for e in stale:
            self._archive_entry_file(e, "stale")
            self._entries.remove(e)

        if stale:
            self._save_index()
            logger.info("Evicted %d stale drafts", len(stale))

        return len(stale)

    def compress_duplicates(self, category: MemoryCategory | None = None) -> int:
        """合并同类条目：同一个 category + 相似 tags → 合并为模式总结。

        仅标记建议，不自动执行合并。返回候选合并组数。
        """
        if not self._loaded:
            self.load_index()

        cats = [category] if category else list(MemoryCategory)
        groups_found = 0

        for cat in cats:
            cat_entries = [e for e in self._entries if e.category == cat]
            if len(cat_entries) < 3:
                continue

            # 按 tag 集合相似度分组
            merged_ids: set[str] = set()
            for i, e1 in enumerate(cat_entries):
                if e1.id in merged_ids:
                    continue
                similar = [e1]
                for e2 in cat_entries[i + 1:]:
                    if e2.id in merged_ids:
                        continue
                    common = set(e1.tags) & set(e2.tags)
                    if len(common) >= 2:
                        similar.append(e2)

                if len(similar) >= 3:
                    groups_found += 1
                    logger.info(
                        "Compression candidate: %s — %d similar entries (%s)",
                        cat.value, len(similar),
                        ", ".join(e.id for e in similar),
                    )
                    merged_ids.update(e.id for e in similar)

        return groups_found

    # ── 治理数据 ──────────────────────────────────────────

    def governance(self) -> MemoryGovernance:
        """返回记忆系统治理统计。"""
        if not self._loaded:
            self.load_index()

        by_cat: dict[str, int] = {}
        confirmed = 0
        draft = 0
        deprecated = 0
        tag_counts: dict[str, int] = {}
        cold: list[str] = []

        for e in self._entries:
            by_cat[e.category.value] = by_cat.get(e.category.value, 0) + 1
            if e.confidence == Confidence.CONFIRMED:
                confirmed += 1
            elif e.confidence == Confidence.DRAFT:
                draft += 1
            elif e.confidence == Confidence.DEPRECATED:
                deprecated += 1

            for t in e.tags:
                tag_counts[t] = tag_counts.get(t, 0) + 1

            # 30天未命中 = 冷条目
            last = e.last_hit_at or e.updated_at or e.created_at
            if last and (datetime.now() - last).days > 30:
                cold.append(e.id)

        # 统计 archive 目录
        archived = 0
        archive_root = self._root / ".ai" / "memory" / "archive"
        for sub in ["deprecated", "stale"]:
            arc_dir = archive_root / sub
            if arc_dir.exists():
                archived += len(list(arc_dir.glob("*.md")))

        hot_tags = sorted(
            [{"tag": k, "count": v} for k, v in tag_counts.items()],
            key=lambda x: -x["count"],
        )[:10]

        return MemoryGovernance(
            total_entries=len(self._entries),
            by_category=by_cat,
            confirmed=confirmed,
            draft=draft,
            deprecated=deprecated,
            archived=archived,
            last_updated=datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            hot_tags=hot_tags,
            cold_entries=cold,
        )

    def stats(self) -> MemoryStats:
        """返回记忆库统计（兼容旧接口）。"""
        g = self.governance()
        return MemoryStats(
            total_entries=g.total_entries,
            by_category=g.by_category,
            confirmed=g.confirmed,
            draft=g.draft,
            deprecated=g.deprecated,
            last_updated=g.last_updated,
        )

    def find(
        self,
        category: MemoryCategory | None = None,
        tags: list[str] | None = None,
        confidence: Confidence | None = None,
    ) -> list[MemoryEntry]:
        """按条件查找条目。"""
        if not self._loaded:
            self.load_index()

        results = self._entries
        if category is not None:
            results = [e for e in results if e.category == category]
        if tags:
            results = [e for e in results if any(t in e.tags for t in tags)]
        if confidence is not None:
            results = [e for e in results if e.confidence == confidence]
        return results

    # ── 迁移 ──────────────────────────────────────────────

    def migrate_if_needed(self) -> bool:
        """检测旧格式 memory.md 并自动迁移到新结构。

        Returns: True 如果执行了迁移。
        """
        # 新目录已存在 → 无需迁移
        if self.entries_dir.exists() and any(self.entries_dir.iterdir()):
            return False

        # 旧文件存在 → 迁移
        if self.index_path.exists() and not self.entries_dir.exists():
            logger.info("Legacy memory.md detected, migrating...")
            self._migrate_from_legacy()
            return True
        return False

    def _migrate_from_legacy(self) -> None:
        """从旧 .ai/memory.md 迁移到新三层结构。"""
        content = self.index_path.read_text(encoding="utf-8")
        legacy_entries = self._parse_legacy_index(content)

        if not legacy_entries:
            logger.info("No entries to migrate")
            return

        # 创建新目录结构
        self._ensure_dirs()

        # 写入每个条目
        for entry in legacy_entries:
            entry.updated_at = datetime.now()
            if not entry.created_at:
                entry.created_at = datetime.now()
            self.save_entry(entry)

        self._entries = legacy_entries
        self._save_index()

        # 旧文件重命名为 .bak
        bak_path = self.index_path.with_suffix(".md.bak")
        self.index_path.rename(bak_path)

        logger.info(
            "Migrated %d entries to new structure. Old file renamed to %s",
            len(legacy_entries), bak_path,
        )

    # ── 内部方法 ──────────────────────────────────────────

    def _ensure_dirs(self) -> None:
        """创建所有目录结构。"""
        for d in [
            self.entries_dir,
            self.sessions_dir,
            self._root / ARCHIVE_DEPRECATED,
            self._root / ARCHIVE_STALE,
            self.projections_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)

    def _exists(self, entry_id: str) -> bool:
        return any(e.id == entry_id for e in self._entries)

    def _evict_one(self) -> None:
        """淘汰最旧的条目（LRU）。"""
        oldest = min(self._entries, key=lambda e: e.updated_at or datetime.min)
        self._entries.remove(oldest)
        # 也删掉 entry 文件
        entry_file = self.entries_dir / f"{oldest.id}.md"
        if entry_file.exists():
            entry_file.unlink()
        logger.info("Evicted: %s", oldest.id)

    def _archive_entry_file(self, entry: MemoryEntry, reason: str) -> None:
        """将条目文件移入 archive。"""
        src = self.entries_dir / f"{entry.id}.md"
        if not src.exists():
            return
        if reason == "deprecated":
            dst_dir = self._root / ARCHIVE_DEPRECATED
        else:
            dst_dir = self._root / ARCHIVE_STALE
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / f"{entry.id}.md"
        src.rename(dst)
        logger.debug("Archived %s → %s", entry.id, dst)


# ── 工具函数 ──────────────────────────────────────────────────

def _split_sections(body: str) -> dict[str, str]:
    """按 ## 标题切分 Markdown 正文。"""
    sections: dict[str, str] = {}
    current_section: str | None = None
    current_lines: list[str] = []

    for line in body.splitlines():
        if line.startswith("# ") and current_section is None:
            # 标题行 (e.g., "# 库存并发扣减超卖")
            continue
        elif line.startswith("## "):
            if current_section and current_lines:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = line[3:].strip()
            current_lines = []
        elif current_section:
            current_lines.append(line)

    if current_section and current_lines:
        sections[current_section] = "\n".join(current_lines).strip()

    return sections


def _parse_dt(s: str) -> datetime | None:
    """安全解析 ISO datetime 字符串。"""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _json_ready(obj: object) -> object:
    """将对象转为 JSON 可序列化格式。"""
    if isinstance(obj, dict):
        return {k: _json_ready(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_ready(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "value"):  # Enum
        return obj.value
    return obj
