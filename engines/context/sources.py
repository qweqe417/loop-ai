"""Context 数据来源 —— 读文件 / 调 CodeGraph / 读 Memory。

每个 Source 只做一件事：返回 ContextPiece 列表。
不关心调用者是谁，不关心优先级和预算 —— 那些由策略层和 Router 处理。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

from .models import ContextPiece

logger = logging.getLogger(__name__)

# 缓存 CodeGraph CLI 可用性
_CODEGRAPH_CLI_AVAILABLE: bool | None = None


def _is_codegraph_available() -> bool:
    """检测 codegraph CLI 是否在 PATH 上（缓存结果）。"""
    global _CODEGRAPH_CLI_AVAILABLE
    if _CODEGRAPH_CLI_AVAILABLE is None:
        try:
            result = subprocess.run(
                ["codegraph", "status"],
                capture_output=True, text=True,
                timeout=5,
            )
            _CODEGRAPH_CLI_AVAILABLE = result.returncode == 0
        except Exception:
            _CODEGRAPH_CLI_AVAILABLE = False
    return _CODEGRAPH_CLI_AVAILABLE


# ── 文件来源 ──────────────────────────────────────────────────────

class FileSource:
    """直接读取项目文件。

    两种读取模式:
    - read_summary: 只读前 N 行 + 函数签名（用于浏览、不改的文件）
    - read_full: 读全文（仅 EXECUTE 阶段要改的文件）
    """

    def __init__(self, project_root: str | Path = ".") -> None:
        self._root = Path(project_root).resolve()

    # ── 读取 ──────────────────────────────────────

    def read_full(self, rel_path: str | Path) -> ContextPiece:
        """读取文件完整内容。"""
        fp = self._root / rel_path
        content = ""
        lines = 0
        if fp.exists():
            try:
                content = fp.read_text(encoding="utf-8")
                lines = content.count("\n") + 1
            except Exception as e:
                content = f"[read error: {e}]"
        return ContextPiece(
            source="file",
            path=str(rel_path),
            content=content,
            token_estimate=_estimate(content),
            priority=2,
            metadata={"mode": "full", "lines": lines},
        )

    def read_summary(self, rel_path: str | Path, max_lines: int = 80) -> ContextPiece:
        """读取文件摘要：前 max_lines 行，不包含完整实现。"""
        fp = self._root / rel_path
        content = ""
        total = 0
        if fp.exists():
            try:
                text = fp.read_text(encoding="utf-8")
                total = text.count("\n") + 1
                head = "\n".join(text.splitlines()[:max_lines])
                content = _summarize_file(head, total_lines=total)
            except Exception as e:
                content = f"[read error: {e}]"
        return ContextPiece(
            source="file",
            path=str(rel_path),
            content=content,
            token_estimate=_estimate(content),
            priority=3,
            metadata={"mode": "summary", "lines": min(total, max_lines), "total_lines": total},
        )

    def read_many_full(self, paths: list[str]) -> list[ContextPiece]:
        """批量读取完整文件。"""
        return [self.read_full(p) for p in paths]

    def read_many_summaries(self, paths: list[str], max_lines: int = 60) -> list[ContextPiece]:
        """批量读取文件摘要。"""
        return [self.read_summary(p, max_lines) for p in paths]

    # ── 扫描 ──────────────────────────────────────

    def find_files(self, pattern: str) -> list[str]:
        """按 glob 模式查找文件，返回相对路径列表。"""
        from glob import glob
        cwd = os.getcwd()
        try:
            os.chdir(self._root)
            return sorted(glob(pattern, recursive=True))
        finally:
            os.chdir(cwd)

    def scan_structure(self) -> ContextPiece:
        """Fallback 项目地图 —— 没有 CodeGraph 时扫描目录树。"""
        lines: list[str] = []
        lines.append("# Project Structure (file scan)")
        lines.append(f"Root: {self._root.name}")
        lines.append("")

        # 只扫描两层
        def _walk(d: Path, depth: int = 0) -> None:
            if depth > 2 or d.name.startswith("."):
                return
            if d.is_dir():
                indent = "  " * depth
                lines.append(f"{indent}{d.name}/")
                try:
                    for child in sorted(d.iterdir()):
                        if child.name.startswith(".") and child.name not in (".env.example",):
                            continue
                        if child.is_dir():
                            _walk(child, depth + 1)
                        elif depth <= 2:
                            lines.append(f"{indent}  {child.name}")
                except PermissionError:
                    pass

        _walk(self._root)
        content = "\n".join(lines)
        return ContextPiece(
            source="file",
            path="project_structure",
            content=content,
            token_estimate=_estimate(content),
            priority=1,
            metadata={"mode": "directory_tree"},
        )


# ── CodeGraph 来源 ────────────────────────────────────────────────

class CodeGraphSource:
    """调用 CodeGraph MCP 工具获取结构化代码信息。

    直接调 MCP 工具，不封装、不抽象。没有 .codegraph/ 时 marked unavailable，
    Router 自动 fallback 到 FileSource.scan_structure()。
    """

    def __init__(self, project_root: str | Path = ".") -> None:
        self._root = Path(project_root).resolve()
        self.available = (self._root / ".codegraph").is_dir()
        if self.available:
            logger.info("CodeGraph index detected at %s/.codegraph", self._root)
        else:
            logger.info("CodeGraph not available, will use file-scan fallback")

    # ── 项目地图 ──────────────────────────────────────

    def get_project_map(self) -> ContextPiece:
        """获取项目文件结构（codegraph_files）。"""
        if not self.available:
            return ContextPiece(source="codegraph", path="", content="[codegraph unavailable]", priority=3)
        try:
            raw = _invoke_codegraph("codegraph_files", {"format": "tree"})
            return ContextPiece(
                source="codegraph",
                path="project_map",
                content=raw,
                token_estimate=_estimate(raw),
                priority=1,
                metadata={"provider": "codegraph_files"},
            )
        except Exception as e:
            logger.warning("codegraph_files failed: %s", e)
            return ContextPiece(source="codegraph", path="", content=f"[error: {e}]", priority=3)

    # ── 上下文查询 ────────────────────────────────────

    def get_context(self, task: str, max_nodes: int = 12) -> ContextPiece:
        """用任务描述查 codegraph，返回入口点 + 相关符号 + 代码。"""
        if not self.available:
            return ContextPiece(source="codegraph", path="", content="[codegraph unavailable]", priority=3)
        try:
            raw = _invoke_codegraph("codegraph_context", {
                "task": task,
                "maxNodes": max_nodes,
                "includeCode": True,
            })
            return ContextPiece(
                source="codegraph",
                path=f"context:{_snip(task, 40)}",
                content=raw,
                token_estimate=_estimate(raw),
                priority=2,
                metadata={"provider": "codegraph_context", "task": task},
            )
        except Exception as e:
            logger.warning("codegraph_context failed: %s", e)
            return ContextPiece(source="codegraph", path="", content=f"[error: {e}]", priority=3)

    def get_impact(self, symbol: str, depth: int = 2) -> ContextPiece:
        """分析修改一个符号的影响范围。"""
        if not self.available:
            return ContextPiece(source="codegraph", path="", content="[codegraph unavailable]", priority=3)
        try:
            raw = _invoke_codegraph("codegraph_impact", {"symbol": symbol, "depth": depth})
            return ContextPiece(
                source="codegraph",
                path=f"impact:{symbol}",
                content=raw,
                token_estimate=_estimate(raw),
                priority=1,
                metadata={"provider": "codegraph_impact", "symbol": symbol},
            )
        except Exception as e:
            logger.warning("codegraph_impact failed: %s", e)
            return ContextPiece(source="codegraph", path="", content=f"[error: {e}]", priority=3)

    def get_callers(self, symbol: str, limit: int = 10) -> ContextPiece:
        """查找谁调用了指定符号。"""
        if not self.available:
            return ContextPiece(source="codegraph", path="", content="[codegraph unavailable]", priority=3)
        try:
            raw = _invoke_codegraph("codegraph_callers", {"symbol": symbol, "limit": limit})
            return ContextPiece(
                source="codegraph",
                path=f"callers:{symbol}",
                content=raw,
                token_estimate=_estimate(raw),
                priority=2,
                metadata={"provider": "codegraph_callers", "symbol": symbol},
            )
        except Exception as e:
            logger.warning("codegraph_callers failed: %s", e)
            return ContextPiece(source="codegraph", path="", content=f"[error: {e}]", priority=3)

    def get_callees(self, symbol: str, limit: int = 10) -> ContextPiece:
        """查找指定符号调用了谁。"""
        if not self.available:
            return ContextPiece(source="codegraph", path="", content="[codegraph unavailable]", priority=3)
        try:
            raw = _invoke_codegraph("codegraph_callees", {"symbol": symbol, "limit": limit})
            return ContextPiece(
                source="codegraph",
                path=f"callees:{symbol}",
                content=raw,
                token_estimate=_estimate(raw),
                priority=2,
                metadata={"provider": "codegraph_callees", "symbol": symbol},
            )
        except Exception as e:
            logger.warning("codegraph_callees failed: %s", e)
            return ContextPiece(source="codegraph", path="", content=f"[error: {e}]", priority=3)


# ── Memory 来源 ───────────────────────────────────────────────────

class MemorySource:
    """从 .ai/memory.md 召回相关记忆条目。"""

    def __init__(self, project_root: str | Path = ".") -> None:
        self._root = Path(project_root).resolve()

    def load_all(self) -> str:
        """读取完整的 .ai/memory.md。"""
        fp = self._root / ".ai" / "memory.md"
        if fp.exists():
            try:
                return fp.read_text(encoding="utf-8")
            except Exception:
                return ""
        return ""

    def load_relevant(self, keywords: list[str] | None = None, limit: int = 5) -> ContextPiece:
        """召回与关键词相关的记忆条目。

        简单实现：按行解析 markdown 中的 `- [xxx] title content` 条目，
        匹配关键词，最多返回 limit 条。
        """
        text = self.load_all()
        if not text or not keywords:
            # 无关键词时返回最近 5 条
            entries = _parse_memory_entries(text)[:limit]
        else:
            entries = _search_memory_entries(text, keywords)[:limit]

        if not entries:
            return ContextPiece(
                source="memory",
                path=".ai/memory.md",
                content="[no relevant memory entries]",
                token_estimate=3,
                priority=3,
                metadata={"entries": 0},
            )

        # 每条只给标题 + 一句话
        content = "\n".join(f"- {e['title']}: {e['summary']}" for e in entries)
        return ContextPiece(
            source="memory",
            path=".ai/memory.md",
            content=content,
            token_estimate=_estimate(content),
            priority=2,
            metadata={"entries": len(entries), "keywords": keywords or []},
        )

    def load_recent_failures(self, limit: int = 3) -> ContextPiece:
        """召回最近失败记录（REPAIR 阶段专用）。"""
        text = self.load_all()
        if not text:
            return ContextPiece(source="memory", path="", content="[no memory]", token_estimate=3, priority=3)

        entries = _search_memory_entries(text, ["fail", "error", "bug", "pitfall"])[:limit]
        if not entries:
            return ContextPiece(
                source="memory",
                path=".ai/memory.md",
                content="[no failure records]",
                token_estimate=3,
                priority=3,
            )

        content = "\n".join(f"- {e['title']}: {e['summary']}" for e in entries)
        return ContextPiece(
            source="memory",
            path=".ai/memory.md",
            content=content,
            token_estimate=_estimate(content),
            priority=2,
            metadata={"entries": len(entries), "category": "failures"},
        )


# ── 内部工具函数 ──────────────────────────────────────────────────

def _estimate(text: str) -> int:
    """粗略 token 估算：字符数 / 3.5。"""
    return max(1, len(text) // 3)


def _snip(s: str, n: int) -> str:
    """截断字符串。"""
    return s if len(s) <= n else s[:n] + "..."


def _summarize_file(head: str, total_lines: int) -> str:
    """给文件头部加上行数信息。"""
    if total_lines <= 80:
        return head
    return f"[showing first 80 of {total_lines} lines]\n\n{head}"


def _parse_memory_entries(text: str) -> list[dict]:
    """简单解析 .ai/memory.md 中的条目。

    支持格式:
      - [id] Title: summary
      - **Title**: content
    """
    entries: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        body = line[2:]
        # 尝试 [id] title: summary 格式
        if body.startswith("[") and "]" in body:
            bracket_end = body.index("]")
            eid = body[1:bracket_end]
            rest = body[bracket_end + 1:].strip()
            if ":" in rest:
                title, _, summary = rest.partition(":")
                entries.append({"id": eid, "title": title.strip(), "summary": summary.strip()})
            else:
                entries.append({"id": eid, "title": rest, "summary": ""})
        else:
            entries.append({"id": "", "title": body[:80], "summary": ""})
    return entries


def _search_memory_entries(text: str, keywords: list[str]) -> list[dict]:
    """按关键词匹配记忆条目。"""
    all_entries = _parse_memory_entries(text)
    scored: list[tuple[int, dict]] = []
    for entry in all_entries:
        combined = f"{entry['title']} {entry['summary']} {entry.get('id', '')}".lower()
        score = sum(1 for kw in keywords if kw.lower() in combined)
        if score > 0:
            scored.append((score, entry))
    scored.sort(key=lambda x: -x[0])
    return [e for _, e in scored]


def _invoke_codegraph(tool: str, params: dict) -> str:
    """调用 CodeGraph MCP 工具（跨进程调用，薄封装）。

    优先级:
      1. codegraph CLI (如果可用)
      2. 返回提示消息引导使用 MCP tool
    """
    if not _is_codegraph_available():
        return (
            f"[CodeGraph {tool}: CLI 不可用]\n"
            "提示: 运行 'codegraph init' 初始化项目索引，"
            "或通过 MCP server 连接 CodeGraph。\n"
            f"Params: {json.dumps(params)}"
        )

    try:
        result = subprocess.run(
            ["codegraph", "query", "--tool", tool, "--params", json.dumps(params)],
            capture_output=True, text=True,
            cwd=str(Path.cwd()),
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
        return f"[CodeGraph {tool}: no output]\nParams: {json.dumps(params)}"
    except Exception as e:
        return f"[CodeGraph {tool}: {e}]"
