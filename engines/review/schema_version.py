"""Schema Version 记录器。

检测 DDL/migration 文件变更，自动记录到 .ai/schema_version.md，
用于追踪数据库 schema 演变历史。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engines.state.models import RunState

logger = logging.getLogger(__name__)

# DDL/Migration 文件匹配模式
MIGRATION_PATTERNS: list[str] = [
    # SQL 文件
    r"\.sql$",
    # Django/Alembic/Flyway/Liquibase 迁移
    r"migrations?/.+\.(py|sql|xml|yaml|yml|json)$",
    r"alembic/versions/.+\.py$",
    r"db/migrate/.+",
    r"flyway/migrations?/.+",
    # Prisma
    r"prisma/.+\.prisma$",
    r"prisma/migrations/.+",
    # Sequelize / TypeORM
    r"migrations?/\d{8,14}.+\.(js|ts)$",
    r"migrations?/timestamp.+\.(js|ts)$",
    # 常见 schema 文件
    r"schema\.(sql|prisma|graphqls?)$",
    r"models\.py$",  # Django models
    r"models/.+\.py$",
    # DDL 相关
    r"ddl?/.+",
    r"database/schema/.+",
    r"db/schema/.+",
    r"sql/create.+\.sql$",
    r"sql/alter.+\.sql$",
    # 配置文件中的 schema 定义
    r"type-defs/.+\.(graphqls?|ts)$",
    r"types?\.(ts|go|rs|py)$",  # 可能包含 schema 定义
]

# 非 migration 文件排除（减少误报）
EXCLUDE_PATTERNS: list[str] = [
    r"node_modules/",
    r"__pycache__/",
    r"\.(test|spec)\.(ts|js|py|go)$",
    r"venv/",
    r"\.venv/",
    r"dist/",
    r"build/",
]


def is_migration_file(filepath: str) -> bool:
    """判断是否为 DDL/migration 文件。"""
    # 排除
    for pat in EXCLUDE_PATTERNS:
        if re.search(pat, filepath):
            return False
    # 匹配
    for pat in MIGRATION_PATTERNS:
        if re.search(pat, filepath, re.IGNORECASE):
            return True
    return False


def detect_migration_files(changed_files: list[str]) -> list[str]:
    """从变更文件列表中筛选 DDL/migration 文件。"""
    return [f for f in changed_files if is_migration_file(f)]


class SchemaVersionRecorder:
    """Schema 版本记录器。

    用法:
        recorder = SchemaVersionRecorder(project_root=".")
        recorder.record(changed_files=["migrations/001_add_users.py"], task_id="T1")
    """

    OUTPUT_PATH = ".ai/schema_version.md"

    def __init__(self, project_root: str | Path = ".") -> None:
        self._root = Path(project_root)
        self._path = self._root / self.OUTPUT_PATH

    def record(
        self,
        changed_files: list[str],
        task_id: str = "",
        description: str = "",
    ) -> str | None:
        """检测并记录 schema 变更。

        Returns:
            记录的版本条目文本，无变更时返回 None。
        """
        migration_files = detect_migration_files(changed_files)
        if not migration_files:
            return None

        # 读取现有记录
        existing = self._read_existing()

        # 计算新版本号
        version = self._next_version(existing)

        # 生成新条目
        entry = self._format_entry(
            version=version,
            task_id=task_id,
            files=migration_files,
            description=description,
        )

        # 追加写入
        existing.append(entry)
        self._write(existing)

        logger.info(
            "Schema version recorded: v%d, files=%s, task=%s",
            version, migration_files, task_id,
        )
        return entry

    def record_from_state(self, state: RunState) -> str | None:
        """从 RunState 自动提取变更并记录。"""
        # 收集所有 task_logs 中的 changed_files
        all_files: list[str] = []
        for log in state.task_state.task_logs:
            all_files.extend(log.changed_files)

        if not all_files:
            return None

        return self.record(
            changed_files=all_files,
            task_id=state.task_id or "",
            description=state.metadata.get("user_input", ""),
        )

    # ── 内部方法 ──────────────────────────────────────────

    def _read_existing(self) -> list[str]:
        """读取现有 schema_version.md，返回条目列表。"""
        if not self._path.exists():
            return []
        content = self._path.read_text(encoding="utf-8")
        # 提取版本条目（以 "## v" 开头的行开始，到下一个 "## v" 或文件尾）
        entries: list[str] = []
        current: list[str] = []
        for line in content.splitlines(True):
            if re.match(r"^## v\d+", line):
                if current:
                    entries.append("".join(current))
                current = [line]
            elif current:  # 只在已有条目头时累加内容
                current.append(line)
        if current:
            entries.append("".join(current))
        return entries

    def _next_version(self, existing: list[str]) -> int:
        """计算下一个版本号。"""
        max_v = 0
        for entry in existing:
            m = re.match(r"^## v(\d+)", entry)
            if m:
                max_v = max(max_v, int(m.group(1)))
        return max_v + 1

    def _format_entry(
        self,
        version: int,
        task_id: str,
        files: list[str],
        description: str,
    ) -> str:
        """格式化版本条目。"""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = [
            f"## v{version}",
            f"",
            f"- **日期**: {ts}",
            f"- **任务**: {task_id or 'N/A'}",
        ]
        if description:
            lines.append(f"- **描述**: {description}")
        lines.append(f"- **变更文件**:")
        for f in sorted(files):
            lines.append(f"  - `{f}`")
        lines.append("")
        return "\n".join(lines) + "\n"

    def _write(self, entries: list[str]) -> None:
        """写回 schema_version.md。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)

        header = (
            "# Schema 版本记录\n\n"
            "> 自动记录 DDL/migration 文件变更，用于追踪数据库 schema 演变。\n"
            f"> 最后更新: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            "---\n\n"
        )
        self._path.write_text(header + "\n".join(entries), encoding="utf-8")
        logger.info("Schema version written to %s", self._path)
