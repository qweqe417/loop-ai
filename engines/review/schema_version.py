"""Schema Version 记录器。

检测 DDL/migration 文件变更，自动记录到 .ai/schema_version.md，
用于追踪数据库 schema 演变历史。
"""

# 启用延迟注解求值
from __future__ import annotations

# 导入 logging 库，用于日志记录
import logging
# 导入 re 库，用于正则匹配
import re
# 导入 datetime 用于生成时间戳
from datetime import datetime
# 导入 Path 类，用于处理文件路径
from pathlib import Path
# 导入 TYPE_CHECKING，用于类型检查时避免循环导入
from typing import TYPE_CHECKING

# 仅在类型检查时导入，避免运行时循环导入
if TYPE_CHECKING:
    from engines.state.models import RunState

# 创建当前模块的日志记录器
logger = logging.getLogger(__name__)

# DDL/Migration 文件匹配模式列表
MIGRATION_PATTERNS: list[str] = [
    # SQL 文件
    r"\.sql$",
    # Django/Alembic/Flyway/Liquibase 迁移
    r"migrations?/.+\.(py|sql|xml|yaml|yml|json)$",
    r"alembic/versions/.+\.py$",
    r"db/migrate/.+",
    r"flyway/migrations?/.+",
    # Prisma 迁移
    r"prisma/.+\.prisma$",
    r"prisma/migrations/.+",
    # Sequelize / TypeORM 迁移
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

# 非 migration 文件排除模式（减少误报）
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
    """判断是否为 DDL/migration 文件。

    先执行排除模式匹配，再执行迁移文件模式匹配。

    Args:
        filepath: 文件路径

    Returns:
        是否为迁移文件
    """
    # 排除：匹配排除模式的文件不是迁移文件
    for pat in EXCLUDE_PATTERNS:
        if re.search(pat, filepath):
            return False
    # 匹配：匹配迁移模式的文件是迁移文件
    for pat in MIGRATION_PATTERNS:
        if re.search(pat, filepath, re.IGNORECASE):
            return True
    return False


def detect_migration_files(changed_files: list[str]) -> list[str]:
    """从变更文件列表中筛选 DDL/migration 文件。

    Args:
        changed_files: 变更文件路径列表

    Returns:
        迁移文件路径列表
    """
    return [f for f in changed_files if is_migration_file(f)]


class SchemaVersionRecorder:
    """Schema 版本记录器。

    用法:
        recorder = SchemaVersionRecorder(project_root=".")
        recorder.record(changed_files=["migrations/001_add_users.py"], task_id="T1")
    """

    # 输出文件路径
    OUTPUT_PATH = ".ai/schema_version.md"

    def __init__(self, project_root: str | Path = ".") -> None:
        # 项目根目录
        self._root = Path(project_root)
        # 输出文件完整路径
        self._path = self._root / self.OUTPUT_PATH

    def record(
        self,
        changed_files: list[str],
        task_id: str = "",
        description: str = "",
    ) -> str | None:
        """检测并记录 schema 变更。

        从变更文件中筛选迁移文件，生成版本条目并追加到 schema_version.md。

        Args:
            changed_files: 变更文件列表
            task_id: 任务标识
            description: 变更描述

        Returns:
            记录的版本条目文本，无变更时返回 None
        """
        # 筛选迁移文件
        migration_files = detect_migration_files(changed_files)
        if not migration_files:
            return None

        # 读取现有记录
        existing = self._read_existing()

        # 计算新版本号（自动递增）
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
        """从 RunState 自动提取变更并记录。

        收集所有 task_logs 中的 changed_files，自动筛选并记录。

        Args:
            state: 运行状态

        Returns:
            记录的版本条目文本，无变更时返回 None
        """
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
        """读取现有 schema_version.md，返回条目列表。

        每个条目以 "## v" 开头的行开始，到下一个 "## v" 或文件尾结束。

        Returns:
            版本条目文本列表
        """
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
        """计算下一个版本号。

        扫描已有条目中的最大版本号，加 1 返回。

        Args:
            existing: 已有版本条目列表

        Returns:
            下一个版本号
        """
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
        """格式化版本条目为 Markdown 文本。

        Args:
            version: 版本号
            task_id: 任务标识
            files: 迁移文件列表
            description: 变更描述

        Returns:
            格式化的 Markdown 条目文本
        """
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
        """写回 schema_version.md。

        Args:
            entries: 版本条目列表
        """
        # 确保父目录存在
        self._path.parent.mkdir(parents=True, exist_ok=True)

        # 文件头部
        header = (
            "# Schema 版本记录\n\n"
            "> 自动记录 DDL/migration 文件变更，用于追踪数据库 schema 演变。\n"
            f"> 最后更新: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            "---\n\n"
        )
        self._path.write_text(header + "\n".join(entries), encoding="utf-8")
        logger.info("Schema version written to %s", self._path)