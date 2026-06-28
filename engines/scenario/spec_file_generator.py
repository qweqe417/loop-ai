"""Playwright .spec.ts 文件生成器 —— 从前端测试用例 YAML 生成 Playwright 测试代码。

输入: .ai/test-design/<feature>/frontend-cases.yaml
输出: tests/<folder>/<feature>.spec.ts

不影响任何被测项目源码。不生成 YAML，只生成 .spec.ts。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .models import (
    FrontendTestCase,
    FrontendStep,
    FrontendStepType,
    FrontendAssertion,
    FrontendAssertionType,
)

logger = logging.getLogger(__name__)

# Playwright 设备名称映射
DEVICE_MAP: dict[str | None, str] = {
    None: "Desktop Chrome",
    "pc": "Desktop Chrome",
    "mobile": "iPhone 14",
    "tablet": "iPad Pro",
    "iPhone 14": "iPhone 14",
    "iPad Pro": "iPad Pro",
}


class SpecFileGenerator:
    """将 FrontendTestCase 转换为 Playwright .spec.ts 文件。"""

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root)
        self.test_dir = self.project_root / "tests"

    def generate(self, test_case: FrontendTestCase) -> Path:
        """生成 .spec.ts 文件。

        Args:
            test_case: 前端测试用例模型

        Returns:
            Path: 生成的 .spec.ts 文件路径
        """
        output_dir = self.test_dir / test_case.folder
        output_dir.mkdir(parents=True, exist_ok=True)

        spec_name = self._sanitize_filename(test_case.name)
        spec_path = output_dir / f"{spec_name}.spec.ts"

        content = self._render(test_case)
        spec_path.write_text(content, encoding="utf-8")
        logger.info("Generated: %s", spec_path)

        return spec_path

    def _render(self, tc: FrontendTestCase) -> str:
        """将测试用例渲染为完整的 .spec.ts 文件内容。"""
        lines: list[str] = []

        # 文件头
        lines.append("import { test, expect } from '@playwright/test';")
        lines.append("")

        # test.describe
        test_name = self._escape_js_string(tc.name)
        lines.append(f"test.describe('{test_name}', () => {{")

        # beforeEach: 打开首页
        lines.append("  test.beforeEach(async ({ page }) => {")
        lines.append("    await page.goto('/');")
        lines.append("  });")
        lines.append("")

        # 主测试用例
        test_case_name = self._escape_js_string(tc.name)
        lines.append(f"  test('{test_case_name}', async ({{ page }}) => {{")

        # 步骤
        for step in tc.steps:
            lines.extend(self._render_step(step))

        # 断言
        for assertion in tc.assertions:
            lines.extend(self._render_assertion(assertion))

        lines.append("  });")

        # 额外用例（metadata 中可扩展）
        extra_cases = tc.metadata.get("extra_cases", [])
        for extra in extra_cases:
            lines.extend(self._render_extra_case(extra))

        lines.append("});")

        return "\n".join(lines)

    def _render_step(self, step: FrontendStep) -> list[str]:
        """将单个前端步骤渲染为 Playwright 代码行。"""
        lines: list[str] = []
        cfg = step.config
        step_type = step.type.value if hasattr(step.type, 'value') else step.type

        if step_type == FrontendStepType.UI_NAVIGATE.value:
            page = cfg.get("page", "/")
            lines.append(f"    await page.goto('{page}');")

        elif step_type == FrontendStepType.UI_CLICK.value:
            selector = cfg.get("selector", "")
            lines.append(f"    await page.click('{selector}');")

        elif step_type == FrontendStepType.UI_FILL.value:
            fields = cfg.get("fields", {})
            for field, value in fields.items():
                escaped_field = field.replace("'", "\\'")
                escaped_val = str(value).replace("'", "\\'")
                lines.append(f"    await page.fill('{escaped_field}', '{escaped_val}');")

        elif step_type == FrontendStepType.UI_SELECT.value:
            selector = cfg.get("selector", "")
            value = cfg.get("value", "")
            lines.append(f"    await page.selectOption('{selector}', '{value}');")

        elif step_type == FrontendStepType.UI_WAIT.value:
            ms = cfg.get("timeout", 1000)
            lines.append(f"    await page.waitForTimeout({ms});")

        elif step_type == FrontendStepType.UI_PRESS.value:
            selector = cfg.get("selector", "")
            key = cfg.get("key", "")
            if selector:
                lines.append(f"    await page.press('{selector}', '{key}');")
            else:
                lines.append(f"    await page.keyboard.press('{key}');")

        elif step_type == FrontendStepType.UI_SCREENSHOT.value:
            name = cfg.get("name", "screenshot")
            lines.append(f"    await page.screenshot({{ path: 'screenshots/{name}.png', fullPage: true }});")

        return lines

    def _render_assertion(self, assertion: FrontendAssertion) -> list[str]:
        """将单个断言渲染为 Playwright expect 代码行。"""
        lines: list[str] = []
        atype = assertion.type.value if hasattr(assertion.type, 'value') else assertion.type
        target = assertion.target
        expected = assertion.expected
        operator = assertion.operator
        msg = assertion.message or f"Assertion failed: {atype}"

        if atype == FrontendAssertionType.URL_CONTAIN.value:
            lines.append(f"    await expect(page).toHaveURL(/{target}/);")

        elif atype == FrontendAssertionType.URL_MATCH.value:
            lines.append(f"    await expect(page).toHaveURL(/{target}/);")

        elif atype == FrontendAssertionType.DOM_VISIBLE.value:
            if expected:
                lines.append(f"    await expect(page.locator('{target}')).toBeVisible();")
            else:
                lines.append(f"    await expect(page.locator('{target}')).toBeHidden();")

        elif atype == FrontendAssertionType.DOM_HIDDEN.value:
            lines.append(f"    await expect(page.locator('{target}')).toBeHidden();")

        elif atype == FrontendAssertionType.DOM_TEXT.value:
            if operator == "contains":
                lines.append(f"    await expect(page.locator('{target}')).toContainText('{expected}');")
            else:
                lines.append(f"    await expect(page.locator('{target}')).toHaveText('{expected}');")

        elif atype == FrontendAssertionType.DOM_COUNT.value:
            lines.append(f"    await expect(page.locator('{target}')).toHaveCount({expected});")

        elif atype == FrontendAssertionType.DOM_VALUE.value:
            lines.append(f"    await expect(page.locator('{target}')).toHaveValue('{expected}');")

        elif atype == FrontendAssertionType.TITLE.value:
            if operator == "contains":
                lines.append(f"    await expect(page).toHaveTitle(/{target}/);")
            else:
                lines.append(f"    await expect(page).toHaveTitle('{target}');")

        return lines

    def _render_extra_case(self, extra: dict[str, Any]) -> list[str]:
        """渲染 metadata 中定义的额外用例。"""
        lines: list[str] = []
        name = self._escape_js_string(extra.get("name", "extra case"))
        lines.append(f"")
        lines.append(f"  test('{name}', async ({{ page }}) => {{")
        for step_data in extra.get("steps", []):
            step = FrontendStep(
                name=step_data.get("name", ""),
                type=FrontendStepType(step_data.get("type", "ui_navigate")),
                config=step_data.get("config", {}),
            )
            lines.extend(self._render_step(step))
        for assertion_data in extra.get("assertions", []):
            assertion = FrontendAssertion(
                type=FrontendAssertionType(assertion_data.get("type", "dom_visible")),
                target=assertion_data.get("target", ""),
                operator=assertion_data.get("operator", "eq"),
                expected=assertion_data.get("expected"),
                message=assertion_data.get("message", ""),
            )
            lines.extend(self._render_assertion(assertion))
        lines.append("  });")
        return lines

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """将用例名转换为合法的文件名（纯 ASCII）。"""
        import re
        # 中文字符转拼音或直接去掉
        chinese_map = {
            "登录": "login", "注册": "register", "首页": "home",
            "搜索": "search", "添加": "add", "删除": "delete",
            "修改": "edit", "提交": "submit", "取消": "cancel",
        }
        for cn, en in chinese_map.items():
            name = name.replace(cn, en)
        # 剩余中文字符转拼音缩写（取首字拼音首字母）
        name = re.sub(r'[\u4e00-\u9fff]+', lambda m: m.group(0)[:2], name)
        # 清理非法字符
        name = re.sub(r"[^\w\-]", "_", name)
        name = re.sub(r"_+", "_", name)
        return name.strip("_").lower()[:50]

    @staticmethod
    def _escape_js_string(s: str) -> str:
        """转义 JS 字符串中的特殊字符。"""
        return s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ")

    def load_from_yaml(self, yaml_path: Path) -> list[FrontendTestCase]:
        """从 YAML 文件加载前端测试用例列表。

        Args:
            yaml_path: .ai/test-design/<feature>/frontend-cases.yaml 路径

        Returns:
            list[FrontendTestCase]: 用例列表
        """
        try:
            import yaml as _yaml
        except ImportError:
            logger.warning("PyYAML not installed, cannot parse YAML")
            return []

        if not yaml_path.exists():
            logger.warning("YAML file not found: %s", yaml_path)
            return []

        try:
            data = _yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("Failed to parse YAML %s: %s", yaml_path, exc)
            return []

        if not data:
            return []

        # 支持单用例（dict）或用例列表（list）
        if isinstance(data, dict):
            data = [data]

        cases: list[FrontendTestCase] = []
        for item in data:
            try:
                cases.append(FrontendTestCase.model_validate(item))
            except Exception as exc:
                logger.warning("Skipping invalid test case: %s", exc)
                continue

        return cases