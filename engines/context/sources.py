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

    def read_smart(
        self, rel_path: str | Path, max_header: int = 60, max_full: int = 300,
        max_outline: int = 50,
    ) -> ContextPiece:
        """智能读取：小文件全文，大文件头 + 符号大纲。

        策略:
        - ≤ max_full 行: 读全文（AI 需要完整上下文的小文件）
        - > max_full 行: 读前 max_header 行 (imports + 顶层定义)
          + 提取类/函数签名作为大纲，帮助 AI 理解文件结构
        这样既保留了必要的结构信息，又避免大文件 token 爆炸。
        """
        import re
        fp = self._root / rel_path
        content = ""
        total_lines = 0
        mode = "full"

        if not fp.exists():
            return ContextPiece(
                source="file", path=str(rel_path),
                content=f"[file not found: {rel_path}]",
                token_estimate=5, priority=2,
                metadata={"mode": "error", "lines": 0},
            )

        try:
            text = fp.read_text(encoding="utf-8")
            total_lines = text.count("\n") + 1
        except Exception as e:
            return ContextPiece(
                source="file", path=str(rel_path),
                content=f"[read error: {e}]",
                token_estimate=5, priority=2,
                metadata={"mode": "error", "lines": 0},
            )

        if total_lines <= max_full:
            content = text
            mode = "full"
        else:
            # 大文件: 头 + 符号大纲（上限 max_outline 条）
            header_lines = text.splitlines()[:max_header]
            header = "\n".join(header_lines)

            # 提取顶层类/函数签名作为快速导航
            all_outline: list[str] = []
            for line in text.splitlines():
                stripped = line.strip()
                if re.match(r'^\s*(def |class |async def )', stripped):
                    all_outline.append(stripped[:100])

            outline_text = ""
            if all_outline:
                if len(all_outline) > max_outline:
                    # 超限时均匀采样: 前 20 + 中 10 + 后 20
                    sampled = (
                        all_outline[:20]
                        + [f"... ({len(all_outline) - 40} 个符号省略) ..."]
                        + all_outline[-20:]
                    )
                    outline = sampled
                else:
                    outline = all_outline
                outline_text = (
                    f"\n\n# ── 文件符号大纲 (共 {len(all_outline)} 个顶层定义"
                    f"{'，显示 ' + str(len(outline)) + ' 个' if len(all_outline) > max_outline else ''}) ──\n"
                    + "\n".join(outline)
                )

            content = (
                f"[smart read: 显示前 {max_header}/{total_lines} 行 + 符号大纲]\n\n"
                f"{header}"
                f"{outline_text}"
            )
            mode = "smart"

        return ContextPiece(
            source="file",
            path=str(rel_path),
            content=content,
            token_estimate=_estimate(content),
            priority=2,
            metadata={"mode": mode, "lines": min(total_lines, max_header), "total_lines": total_lines},
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
    """通过 CodeGraph CLI 获取结构化代码信息。

    当 .codegraph/ 索引不存在或 CLI 不可用时，所有方法返回 None，
    策略层自动 fallback 到 FileSource 或静默跳过。
    """

    def __init__(self, project_root: str | Path = ".") -> None:
        self._root = Path(project_root).resolve()
        self.available = (self._root / ".codegraph").is_dir()
        if self.available:
            logger.info("CodeGraph index detected at %s/.codegraph", self._root)
        else:
            logger.info("CodeGraph not available, will use file-scan fallback")

    # ── 项目地图 ──────────────────────────────────────

    def get_project_map(self) -> ContextPiece | None:
        """获取项目文件结构（codegraph files）。"""
        if not self.available:
            return None
        raw = _invoke_codegraph("codegraph_files", {"format": "tree"})
        if raw is None:
            return None
        return ContextPiece(
            source="codegraph",
            path="project_map",
            content=raw,
            token_estimate=_estimate(raw),
            priority=1,
            metadata={"provider": "codegraph_files"},
        )

    # ── 上下文查询 ────────────────────────────────────

    def get_context(self, task: str, max_nodes: int = 12) -> ContextPiece | None:
        """用任务描述查 codegraph，返回入口点 + 相关符号 + 代码。"""
        if not self.available:
            return None
        raw = _invoke_codegraph("codegraph_context", {
            "task": task,
            "maxNodes": max_nodes,
            "includeCode": True,
        })
        if raw is None:
            return None
        return ContextPiece(
            source="codegraph",
            path=f"context:{_snip(task, 40)}",
            content=raw,
            token_estimate=_estimate(raw),
            priority=2,
            metadata={"provider": "codegraph_context", "task": task},
        )

    def get_impact(self, symbol: str, depth: int = 2) -> ContextPiece | None:
        """分析修改一个符号的影响范围。"""
        if not self.available:
            return None
        raw = _invoke_codegraph("codegraph_impact", {"symbol": symbol, "depth": depth})
        if raw is None:
            return None
        return ContextPiece(
            source="codegraph",
            path=f"impact:{symbol}",
            content=raw,
            token_estimate=_estimate(raw),
            priority=1,
            metadata={"provider": "codegraph_impact", "symbol": symbol},
        )

    def get_callers(self, symbol: str, limit: int = 10) -> ContextPiece | None:
        """查找谁调用了指定符号。"""
        if not self.available:
            return None
        raw = _invoke_codegraph("codegraph_callers", {"symbol": symbol, "limit": limit})
        if raw is None:
            return None
        return ContextPiece(
            source="codegraph",
            path=f"callers:{symbol}",
            content=raw,
            token_estimate=_estimate(raw),
            priority=2,
            metadata={"provider": "codegraph_callers", "symbol": symbol},
        )

    def get_callees(self, symbol: str, limit: int = 10) -> ContextPiece | None:
        """查找指定符号调用了谁。"""
        if not self.available:
            return None
        raw = _invoke_codegraph("codegraph_callees", {"symbol": symbol, "limit": limit})
        if raw is None:
            return None
        return ContextPiece(
            source="codegraph",
            path=f"callees:{symbol}",
            content=raw,
            token_estimate=_estimate(raw),
            priority=2,
            metadata={"provider": "codegraph_callees", "symbol": symbol},
        )


# ── Memory 来源 ───────────────────────────────────────────────────

class MemorySource:
    """从 .ai/memory.md 索引 + entries/ 明细层召回相关记忆。

    召回策略:
        - 永不全量读 entries/ 正文
        - 按关键词 + 阶段优先级匹配 memory.md 索引行
        - 限制 top 3~5 条
    """

    def __init__(self, project_root: str | Path = ".") -> None:
        self._root = Path(project_root).resolve()

    def load_all(self) -> str:
        """读取 memory.md 索引全文（轻量级）。"""
        from engines.memory.store import MemoryStore
        store = MemoryStore(project_root=self._root)
        return store.index_path.read_text(encoding="utf-8") if store.index_path.exists() else ""

    def load_relevant(
        self, keywords: list[str] | None = None, stage: str = "", limit: int = 5
    ) -> ContextPiece:
        """分级召回：关键词 + 阶段优先级，只返回索引摘要。"""
        from engines.memory.store import MemoryStore
        store = MemoryStore(project_root=self._root)
        entries = store.recall(keywords=keywords or [], stage=stage, limit=limit)

        if not entries:
            return ContextPiece(
                source="memory",
                path=".ai/memory.md",
                content="[no relevant memory entries]",
                token_estimate=3,
                priority=3,
                metadata={"entries": 0},
            )

        # 每条只给标题 + content（1~3句结论），不载入 entries/ 明细
        lines = []
        for e in entries:
            tags_str = f"[{','.join(e.tags)}]" if e.tags else ""
            lines.append(f"- [{e.id}] {e.content or e.title} {tags_str}")

        content = "\n".join(lines)
        return ContextPiece(
            source="memory",
            path=".ai/memory.md",
            content=content,
            token_estimate=_estimate(content),
            priority=2,
            metadata={"entries": len(entries), "keywords": keywords or [], "stage": stage},
        )

    def load_recent_failures(self, limit: int = 3) -> ContextPiece:
        """召回最近失败记录（REPAIR 阶段专用）。"""
        from engines.memory import MemoryCategory
        from engines.memory.store import MemoryStore
        store = MemoryStore(project_root=self._root)
        entries = store.recall_by_category(
            [MemoryCategory.FAILURE_PATTERN, MemoryCategory.PITFALL], limit=limit
        )

        if not entries:
            return ContextPiece(
                source="memory",
                path=".ai/memory.md",
                content="[no failure records]",
                token_estimate=3,
                priority=3,
            )

        lines = [f"- [{e.id}] {e.content or e.title}" for e in entries]
        content = "\n".join(lines)
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



# ── CodeGraph CLI 子命令映射 ──────────────────────────────────────
# 将逻辑工具名映射到 codegraph CLI 的实际子命令和参数构建方式

def _build_codegraph_cmd(tool: str, params: dict) -> list[str]:
    """将逻辑工具名映射为 codegraph CLI 子命令 + 参数列表。

    codegraph CLI 子命令（v1.0.1+）:
        files, explore <query>, node <name>, query <search>,
        callers <symbol>, callees <symbol>, impact <symbol>
    """
    if tool == "codegraph_files":
        return ["codegraph", "files"]
    elif tool == "codegraph_explore":
        query = params.get("query", params.get("task", ""))
        max_files = params.get("maxFiles", params.get("max_files", 12))
        cmd = ["codegraph", "explore", query]
        if max_files:
            cmd.extend(["--max-files", str(max_files)])
        return cmd
    elif tool == "codegraph_node":
        symbol = params.get("symbol", "")
        include_code = params.get("includeCode", params.get("include_code", True))
        cmd = ["codegraph", "node", symbol]
        if include_code:
            cmd.append("--include-code")
        file = params.get("file", "")
        if file:
            cmd.extend(["--file", file])
        return cmd
    elif tool == "codegraph_context":
        # codegraph_context → codegraph explore (语义等价)
        query = params.get("task", "")
        max_nodes = params.get("maxNodes", params.get("max_nodes", 12))
        cmd = ["codegraph", "explore", query]
        if max_nodes:
            cmd.extend(["--max-files", str(max_nodes)])
        return cmd
    elif tool == "codegraph_search":
        return ["codegraph", "query", params.get("query", params.get("symbol", ""))]
    elif tool == "codegraph_callers":
        symbol = params.get("symbol", "")
        limit = params.get("limit", 20)
        return ["codegraph", "callers", symbol, "--limit", str(limit)]
    elif tool == "codegraph_callees":
        symbol = params.get("symbol", "")
        limit = params.get("limit", 20)
        return ["codegraph", "callees", symbol, "--limit", str(limit)]
    elif tool == "codegraph_impact":
        symbol = params.get("symbol", "")
        depth = params.get("depth", 1)
        return ["codegraph", "impact", symbol, "--depth", str(depth)]
    else:
        return ["codegraph", "query", str(params)]


def _invoke_codegraph(tool: str, params: dict) -> str | None:
    """调用 CodeGraph CLI 子命令，返回 stdout 或 None。

    当 codegraph CLI 不可用或 .codegraph/ 索引不存在时返回 None，
    调用方应静默跳过，不注入任何占位噪音。
    """
    if not _is_codegraph_available():
        return None

    try:
        cmd = _build_codegraph_cmd(tool, params)
        result = subprocess.run(
            cmd,
            capture_output=True, text=True,
            cwd=str(Path.cwd()),
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        # 有 stderr 信息时记录但不返回（如 "no results" 不是错误）
        if result.stderr.strip():
            logger.debug("codegraph %s stderr: %s", tool, result.stderr.strip()[:200])
        return None
    except FileNotFoundError:
        logger.debug("codegraph CLI not found on PATH")
        return None
    except Exception as e:
        logger.debug("codegraph %s failed: %s", tool, e)
        return None
