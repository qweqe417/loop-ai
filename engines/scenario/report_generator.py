"""测试报告生成器 —— HTML + JSON + Markdown。

用法:
    gen = ReportGenerator(output_dir=".ai/reports")
    paths = gen.generate(report, failures=[], repair_log=[])
    # paths: {"html": "...", "json": "...", "md": "..."}
"""

# 启用 Python 3.10+ 的延迟注解求值特性
from __future__ import annotations

# 导入 json 模块，用于生成 JSON 格式报告
import json
# 导入 datetime 模块，用于生成时间戳
from datetime import datetime
# 导入 Path 类，用于处理文件系统路径
from pathlib import Path
# 导入 Any 类型，用于灵活的类型注解
from typing import Any


class ReportGenerator:
    """三格式测试报告生成器。

    生成 HTML（可视化） + JSON（机器可读） + Markdown（简洁）三份报告。
    """

    def __init__(self, output_dir: str | Path = ".ai/reports") -> None:
        # 报告输出目录，解析为 Path 对象
        self._output_dir = Path(output_dir)
        # 确保输出目录存在
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        report: Any,
        failures: list[dict] | None = None,
        repair_log: list[dict] | None = None,
    ) -> dict[str, str]:
        """生成 HTML + JSON + MD 三份报告。

        Args:
            report: ScenarioReport 对象
            failures: 失败断言列表
            repair_log: 修复记录列表

        Returns:
            {"html": "/path/to/report.html", "json": "/path/to/report.json", "md": "/path/to/report.md"}
        """
        # 生成时间戳文件名
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = self._output_dir / f"test-report-{ts}"

        paths: dict[str, str] = {}
        # 生成 HTML 报告
        paths["html"] = str(self._write_html(
            base.with_suffix(".html"), report, failures, repair_log,
        ))
        # 生成 JSON 报告
        paths["json"] = str(self._write_json(
            base.with_suffix(".json"), report, failures, repair_log,
        ))
        # 生成 Markdown 报告
        paths["md"] = str(self._write_markdown(
            base.with_suffix(".md"), report, failures, repair_log,
        ))
        return paths

    # ── HTML ──

    def _write_html(
        self, path: Path, report: Any,
        failures: list[dict] | None, repair_log: list[dict] | None,
    ) -> Path:
        """生成 HTML 格式测试报告。

        Args:
            path: 输出文件路径
            report: ScenarioReport 对象
            failures: 失败断言列表
            repair_log: 修复记录列表

        Returns:
            Path: 输出文件路径
        """
        # 从 report 对象中提取统计数据
        passed = getattr(report, "passed", 0)
        failed = getattr(report, "failed", 0)
        total = getattr(report, "total", 0)
        duration = getattr(report, "total_duration_ms", 0)
        results = getattr(report, "results", [])

        # 构建 HTML 模板（包含 CSS 样式）
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>测试报告 — {datetime.now().strftime("%Y-%m-%d %H:%M")}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 960px; margin: 40px auto; padding: 20px; background: #f8f9fa; color: #1a1a2e; }}
h1 {{ font-size: 24px; margin-bottom: 8px; }}
.subtitle {{ color: #6b7280; font-size: 14px; margin-bottom: 24px; }}
.summary {{ display: flex; gap: 20px; margin: 20px 0; }}
.card {{ background: white; border-radius: 12px; padding: 20px 28px; box-shadow: 0 1px 3px rgba(0,0,0,.08); flex: 1; text-align: center; }}
.card .num {{ font-size: 36px; font-weight: 700; }}
.card .label {{ font-size: 13px; color: #6b7280; margin-top: 4px; }}
.passed {{ color: #22c55e; }}
.failed {{ color: #ef4444; }}
.rate {{ background: white; border-radius: 12px; padding: 20px 28px; box-shadow: 0 1px 3px rgba(0,0,0,.08); margin-bottom: 24px; }}
.rate strong {{ font-size: 28px; color: #1a1a2e; }}
.scenario {{ background: white; border-radius: 8px; padding: 16px 20px; margin: 10px 0; box-shadow: 0 1px 3px rgba(0,0,0,.06); }}
.scenario.pass {{ border-left: 4px solid #22c55e; }}
.scenario.fail {{ border-left: 4px solid #ef4444; }}
.scenario .name {{ font-weight: 600; font-size: 15px; }}
.scenario .meta {{ font-size: 13px; color: #6b7280; }}
.diff {{ background: #fef2f2; padding: 10px 14px; border-radius: 6px; margin: 8px 0; font-family: 'SF Mono', 'Fira Code', monospace; font-size: 13px; }}
h2 {{ margin: 28px 0 12px; font-size: 18px; }}
</style>
</head>
<body>
<h1>自动化测试报告</h1>
<p class="subtitle">生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>

<div class="summary">
<div class="card"><div class="num passed">{passed}</div><div class="label">通过</div></div>
<div class="card"><div class="num failed">{failed}</div><div class="label">失败</div></div>
<div class="card"><div class="num">{total - passed - failed}</div><div class="label">跳过</div></div>
</div>

<div class="rate">
通过率: <strong>{passed / max(1, total) * 100:.1f}%</strong> |
总耗时: {duration / 1000:.1f}s |
场景总数: {total}
</div>

<h2>场景结果</h2>
"""
        # 添加每个场景的结果
        for r in results:
            status = "pass" if getattr(r, "passed", False) else "fail"
            icon = "✅" if status == "pass" else "❌"
            name = getattr(r, "name", "") or getattr(r, "scenario_id", "unknown")
            dur = getattr(r, "duration_ms", 0)
            html += f'<div class="scenario {status}">'
            html += f'<div class="name">{icon} {name}</div>'
            html += f'<div class="meta">{dur:.0f}ms</div>'
            for err in getattr(r, "errors", []):
                html += f'<div class="diff">{err}</div>'
            html += '</div>\n'

        # 添加修复记录
        if repair_log:
            html += '<h2>修复记录</h2>\n'
            for entry in repair_log:
                html += (
                    f'<div class="scenario">'
                    f'<strong>第 {entry.get("attempt", "?")} 次修复:</strong> '
                    f'{entry.get("summary", "")}</div>\n'
                )

        html += '</body></html>'
        # 写入 HTML 文件
        path.write_text(html, encoding="utf-8")
        return path

    # ── JSON ──

    def _write_json(
        self, path, report, failures, repair_log,
    ) -> Path:
        """生成 JSON 格式测试报告。

        Returns:
            Path: 输出文件路径
        """
        # 构建 JSON 数据结构
        data = {
            "timestamp": datetime.now().isoformat(),
            "passed": getattr(report, "passed", 0),
            "failed": getattr(report, "failed", 0),
            "total": getattr(report, "total", 0),
            "total_duration_ms": getattr(report, "total_duration_ms", 0),
            "results": [
                {
                    "scenario_id": getattr(r, "scenario_id", ""),
                    "name": getattr(r, "name", ""),
                    "passed": getattr(r, "passed", False),
                    "errors": getattr(r, "errors", []),
                    "duration_ms": getattr(r, "duration_ms", 0),
                }
                for r in getattr(report, "results", [])
            ],
            "failures": failures or [],
            "repair_log": repair_log or [],
        }
        # 写入 JSON 文件（ensure_ascii=False 保留中文）
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    # ── Markdown ──

    def _write_markdown(
        self, path, report, failures, repair_log,
    ) -> Path:
        """生成 Markdown 格式测试报告。

        Returns:
            Path: 输出文件路径
        """
        passed = getattr(report, "passed", 0)
        failed = getattr(report, "failed", 0)
        total = getattr(report, "total", 0)
        duration = getattr(report, "total_duration_ms", 0)

        # 构建 Markdown 模板
        md = f"""# 测试报告

**生成时间:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

| 指标 | 数值 |
|------|------|
| 通过 | {passed} |
| 失败 | {failed} |
| 总计 | {total} |
| 通过率 | {passed / max(1, total) * 100:.1f}% |
| 总耗时 | {duration / 1000:.1f}s |

## 场景结果
"""
        # 添加每个场景的结果
        for r in getattr(report, "results", []):
            icon = "✅" if getattr(r, "passed", False) else "❌"
            name = getattr(r, "name", "") or getattr(r, "scenario_id", "?")
            dur = getattr(r, "duration_ms", 0)
            md += f"\n- {icon} **{name}** ({dur:.0f}ms)"
            for err in getattr(r, "errors", []):
                md += f"\n  - {err}"

        # 添加修复记录
        if repair_log:
            md += "\n\n## 修复记录\n"
            for entry in repair_log:
                md += f"\n- 第 {entry.get('attempt', '?')} 次: {entry.get('summary', '')}"

        # 写入 Markdown 文件
        path.write_text(md, encoding="utf-8")
        return path