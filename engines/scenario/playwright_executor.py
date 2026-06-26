"""Playwright 执行器 —— 通过 Playwright Skill 的 run.js 执行前端测试。

从 Scenario YAML 的 ui_* action 生成 Playwright 脚本，
通过 subprocess 调用 Playwright Skill 执行，返回 DOM 快照 + 截图 + 控制台日志。
"""

# 启用 Python 3.10+ 的延迟注解求值特性
from __future__ import annotations

# 导入 json 模块，用于解析 Playwright 输出
import json
# 导入日志模块，用于记录执行过程
import logging
# 导入子进程模块，用于执行 Node.js 脚本
import subprocess
# 导入 tempfile 模块，用于创建临时脚本文件
import tempfile
# 导入 Path 类，用于处理文件系统路径
from pathlib import Path
# 导入 Any 和 Optional 类型
from typing import Any, Optional

# 获取当前模块的日志记录器
logger = logging.getLogger(__name__)


def _find_run_js() -> Optional[str]:
    """搜索 Playwright Skill 的 run.js 路径。

    在用户 home 目录下搜索 .claude/skills/playwright-skill/run.js。

    Returns:
        str | None: run.js 的路径，未找到时返回 None
    """
    home = Path.home()
    # 候选路径列表（按优先级排列）
    candidates = [
        home / ".claude" / "skills" / "playwright-skill" / "run.js",
        home / ".claude" / "skills" / "playwright-skill" / "skills" / "playwright-skill" / "run.js",
        home / ".claude" / "plugins" / "cache" / "claude-plugins-official" / "playwright-skill" / "run.js",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    # 通配搜索：在 .claude 目录下递归搜索
    matches = list(home.glob(".claude/**/playwright-skill/run.js"))
    return str(matches[0]) if matches else None


class PlaywrightExecutor:
    """前端场景执行器。

    用法:
        executor = PlaywrightExecutor(headless=True, timeout=60)
        if not executor.available:
            raise RuntimeError("Playwright Skill not installed")

        result = executor.execute_scenario(
            scenario_steps=[...],
            device="mobile",
        )
        # result: {"dom_snapshot": {...}, "screenshots": [...], "console": [...]}

    超时配置:
        - timeout 默认 30s，可通过构造函数设置
        - 对复杂前端流程（多页面跳转、表单填写），建议 60~120s
        - 可通过 execute_scenario(timeout=...) 按场景覆盖
    """

    # 设备配置映射表：设备类型 → Playwright 设备名称
    DEVICE_PROFILES = {
        "pc": None,  # PC 端使用默认视口
        "mobile": "iPhone 14",
        "tablet": "iPad Pro",
    }

    def __init__(self, headless: bool = True, timeout: int = 30) -> None:
        # 查找 Playwright Skill 的 run.js 路径
        self._run_js = _find_run_js()
        # 是否使用无头模式（不显示浏览器窗口）
        self._headless = headless
        # 默认超时时间（秒）
        self._timeout = timeout

    @property
    def available(self) -> bool:
        """Playwright Skill 是否可用。"""
        return self._run_js is not None and Path(self._run_js).exists()

    def execute_scenario(
        self, steps: list[dict], device: str = "pc", timeout: int | None = None,
    ) -> dict:
        """将 Scenario steps 翻译为 Playwright 脚本并执行。

        Args:
            steps: ScenarioStep 列表（action=ui_* 的步骤）
            device: pc | mobile | tablet
            timeout: 超时秒数（覆盖构造函数中的默认值）

        Returns:
            {"dom_snapshot": ..., "screenshots": [...], "console": [...]}
            或 {"error": "..."}
        """
        if not self.available:
            return {"error": "Playwright Skill run.js not found"}

        # 生成 Playwright 脚本
        script = self._generate_script(steps, device)

        # 写入临时文件
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".js", delete=False, encoding="utf-8",
        ) as f:
            f.write(script)
            script_path = f.name

        # 确定实际使用的超时时间
        effective_timeout = timeout if timeout is not None else self._timeout

        try:
            # 执行 Node.js 脚本
            result = subprocess.run(
                ["node", self._run_js, script_path],
                capture_output=True, text=True, timeout=effective_timeout,
            )
            # 解析输出
            return self._parse_output(result.stdout, result.stderr)
        except subprocess.TimeoutExpired:
            return {"error": f"Playwright execution timed out ({effective_timeout}s)"}
        except FileNotFoundError:
            return {"error": "Node.js not found — install Node.js and Playwright Skill"}
        except Exception as exc:
            return {"error": str(exc)}
        finally:
            # 清理临时脚本文件
            Path(script_path).unlink(missing_ok=True)

    def _generate_script(self, steps: list[dict], device: str) -> str:
        """从 Scenario ui_* steps 生成完整 Playwright 脚本。

        Args:
            steps: 场景步骤列表
            device: 设备类型

        Returns:
            str: 完整的 JavaScript 脚本字符串
        """
        # 获取设备配置
        device_profile = self.DEVICE_PROFILES.get(device)

        # 构建脚本头部（导入 Playwright 模块）
        lines = [
            "const { chromium } = require('playwright');",
            "const devices = require('playwright').devices || {};",
            "",
            "(async () => {",
            f"  const browser = await chromium.launch({{ headless: {str(self._headless).lower()} }});",
        ]

        # 根据设备类型设置 context
        if device_profile and device_profile in ("iPhone 14", "iPad Pro"):
            lines.append(f"  const context = await browser.newContext({{ ...devices['{device_profile}'] }});")
        else:
            lines.append("  const context = await browser.newContext();")

        # 初始化页面和结果收集器
        lines.extend([
            "  const page = await context.newPage();",
            "  const results = { dom_snapshot: null, screenshots: [], console: [] };",
            "",
            "  page.on('console', msg => results.console.push({ type: msg.type(), text: msg.text() }));",
            "  page.on('pageerror', err => results.console.push({ type: 'error', text: err.message }));",
            "",
        ])

        # 翻译每个步骤为 Playwright 操作
        for step in steps:
            action = step.get("action", "")
            config = step.get("config", {})

            if action == "ui_navigate":
                # 页面导航
                page = config.get("page", "/").replace("'", "\\'")
                lines.append(f"  await page.goto('{page}');")

            elif action == "ui_click":
                # 点击元素
                selector = config.get("selector", "")
                escaped = selector.replace("'", "\\'")
                lines.append(f"  await page.click('{escaped}');")

            elif action == "ui_fill":
                # 填充表单字段
                for field, value in config.get("fields", {}).items():
                    escaped_field = field.replace("'", "\\'")
                    escaped_val = str(value).replace("'", "\\'")
                    lines.append(f"  await page.fill('{escaped_field}', '{escaped_val}');")

            elif action == "ui_select":
                # 下拉选择
                selector = config.get("selector", "").replace("'", "\\'")
                value = str(config.get("value", "")).replace("'", "\\'")
                lines.append(f"  await page.selectOption('{selector}', '{value}');")

            elif action == "ui_wait":
                # 等待指定时间
                timeout = config.get("timeout", 1000)
                lines.append(f"  await page.waitForTimeout({timeout});")

            elif action == "ui_screenshot":
                # 截屏
                name = config.get("name", "screenshot")
                lines.append(f"  await page.screenshot({{ path: '/tmp/{name}.png', fullPage: true }});")
                lines.append(f"  results.screenshots.push('/tmp/{name}.png');")

        # 脚本尾部：获取 DOM 快照、关闭浏览器、输出结果
        lines.extend([
            "",
            "  results.dom_snapshot = await page.accessibility.snapshot();",
            "  await browser.close();",
            "  console.log(JSON.stringify(results));",
            "})().catch(err => { console.error(JSON.stringify({ error: err.message })); process.exit(1); });",
        ])

        return "\n".join(lines)

    def _parse_output(self, stdout: str, stderr: str) -> dict:
        """解析 Playwright 脚本的输出。

        Args:
            stdout: 标准输出
            stderr: 标准错误

        Returns:
            dict: 解析后的结果字典
        """
        if stderr:
            logger.warning("Playwright stderr: %s", stderr[:300])
        try:
            # 取最后一行 JSON 输出（避免中间日志干扰）
            lines = stdout.strip().splitlines()
            return json.loads(lines[-1])
        except (json.JSONDecodeError, IndexError):
            return {"error": "Failed to parse Playwright output", "stdout": stdout[:300]}