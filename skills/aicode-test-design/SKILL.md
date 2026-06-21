---
name: aicode-test-design
user-invocable: true
description: "从 PRD / Spec / 需求描述生成测试用例。支持 --scope backend/frontend/fullstack，默认输出人读表格。"
---

# /aicode-test-design — 生成测试用例

> **核心原则：默认只输出一份人读 Excel。自动化资产按需生成。**
>
> **不编造业务规则、不修改代码、不执行测试。**
>
> **Excel 生成统一走 CLI。不要自己写 openpyxl/xlsxwriter 代码。**

## engines CLI 路径解析

文中 `{engines_cmd}` 按以下优先级解析：

1. 如果系统已提供 `{engines_cmd}` / `{engines_cmd_win}` 变量 → 直接使用
2. 否则，根据当前 skill 文件路径反推 engines：
   - skill 在 `<plugin>/skills/aicode-test-design/SKILL.md`
   - 则 engines CLI = `<plugin>/engines/cli.py`
   - 执行方式：`python <plugin>/engines/cli.py test-design ...`
3. 如果找不到 → **不要跳过！** 用 `Glob **/engines/cli.py` 在当前项目和插件目录搜索，找到后直接 `python <path>` 执行

**绝对不允许跳过 CLI 步骤。找不到就搜索，搜索不到就报错，不能静默跳过。**

---

## 触发方式

```bash
# 视图A（默认人读 → 输出 .xlsx）
/aicode-test-design --from docs/spec/order.md
/aicode-test-design --from docs/spec/order.md --scope frontend
/aicode-test-design "用户可以创建订单，库存不足时失败"

# 视图B（全量自动化资产 → 输出 YAML + Scenario + 质量报告，另附 .xlsx）
/aicode-test-design --from docs/spec/order.md --mode full
/aicode-test-design --from docs/spec/order.md --mode full --scope fullstack
```

---

## 步骤 0：判断模式和范围

**模式判断：**
- 用户加了 `--mode full` → **走视图B**（步骤 B1-B6）
- 用户只说了"生成测试用例" → **走视图A**（步骤 A1-A4）
- Loop TEST_DESIGN 阶段调起 → **走视图B**

**范围判断（`--scope`）：**

| scope | 默认场景 | Step Action 形态 | 断言形态 | 自动化建议 |
|-------|----------|-----------------|----------|-----------|
| `backend`（默认） | 接口/数据/服务端逻辑 | api_call, db_query, redis_get, mq_check, log_check | HTTP status/body + data_assertions(mysql/redis) | scenario / pytest |
| `frontend` | UI 交互/页面/组件 | ui_navigate, ui_click, ui_fill, ui_select, ui_hover, ui_wait | DOM 断言(dom_visible/dom_text/dom_value/dom_attribute/dom_count/dom_hidden) | playwright / cypress |
| `fullstack` | 用户路径贯穿前后端 | ui_click/等 + api_call + db_query | DOM 断言 + HTTP 断言 + data_assertions | playwright |

**用户没有指定 scope 时，默认 backend。** Loop 集成时，由 Intake 阶段分析结果或用户配置决定。

---

## 视图A：人读模式（默认）

### 步骤 A1：确认需求来源

按优先级：
1. `--from` 指定的文件 → Read
2. 用户直接写了文字 → 用文字
3. `.ai/prd/` 或 `docs/spec/` 下查找 → 让用户选
4. 都没有 → 让用户提供

### 步骤 A2：分析需求

根据 `--scope` 侧重不同的分析维度：

**backend：**
- 接口路径/方法/参数
- 业务规则和状态流转
- 数据变化（哪些表/缓存受影响）
- 权限和越权场景

**frontend：**
- 页面路径和组件
- 用户交互（点击/输入/导航）
- 元素状态（可见/隐藏/启用/禁用）
- 文案和样式

**fullstack：**
- 完整用户路径（从页面操作到数据落地）
- 中间每一步的可验证点

不明确的规则 → 记入"未决问题"。

### ⚠️ 步骤 A2.5：HUMAN_CONFIRM（未决问题阻断）

**如果分析过程中出现了未决问题（open_questions），AI 必须在此处暂停，将问题列出给用户，等待用户澄清后继续。**

```
AI: 分析过程中发现以下不确定点，请澄清：

1. [问题描述] — 影响范围: [哪些用例]
2. [问题描述] — 影响范围: [哪些用例]

请逐条回答后我将继续生成测试用例。
```

**用户未回复前，禁止进入步骤 A3。**

### 步骤 A3：生成测试用例 Excel

1. **先把已分析的用例按 YAML Schema 组装**（不需要 coverage/open_questions 完整体），Write 到 `.ai/test-design/<feature>/test-cases.yaml`
2. **调 CLI 生成 xlsx**：

```bash
{engines_cmd} test-design export-xlsx --input .ai/test-design/<feature>/test-cases.yaml --output .ai/test-design/<feature>/测试用例.xlsx
```

3. **删除临时 YAML**（视图A 不保留机器文件）

**xlsx 生成失败时降级为 Markdown 表格**（`.ai/test-design/<feature>/测试用例.md`，格式同 Excel 三 Sheet）。

Excel 结构：

**Sheet 1「测试用例」** — 主表，列因 scope 不同：

| scope | 列 |
|-------|----|
| backend | 编号 / 标题 / 优先级 / 前置条件 / 测试步骤 / 预期结果 / 数据校验点 |
| frontend | 编号 / 标题 / 优先级 / 前置条件 / 操作步骤 / 预期页面表现 / UI 校验点 |
| fullstack | 编号 / 标题 / 优先级 / 前置条件 / 操作步骤 / 预期结果 / 接口校验点 / 数据/UI 校验点 |

**Sheet 2「覆盖矩阵」** — 需求项 vs 用例对照：
| 需求编号 | 用例编号 | 覆盖状态 | 备注 |

**Sheet 3「未决问题」**（如有）：
| 问题编号 | 问题描述 | 影响范围 | 阻塞用例 |

**Excel 内容规则：**
- **不写具体 API 路径**（如 `GET /api/model/page?page=1&size=10`），用业务描述代替（如"打开模型列表页"）
- 测试步骤用业务语言描述（如"填写表单并提交"），不用技术语言（如"POST /orders"）
- 校验点描述业务含义（如"订单状态变为已创建"），不写 SQL 或 curl 命令

末尾附一行覆盖率小结：
> 覆盖正常 X 条 / 异常 X 条 / 边界 X 条 / 权限 X 条，共 X 条。P0/P1 覆盖 X/X。

### 步骤 A4：展示结果

告诉用户文件路径、用例总数、覆盖小结、未决问题。

**视图A 到此结束。不生成任何 YAML/JSON/Scenario。**

---

## 视图B：全量模式

### 步骤 B1：确认需求来源

同 A1。

### 步骤 B2：AI 生成结构化 YAML

按以下 Schema 生成。**注意：steps 必须是 Action Pipeline 结构化数组，不能是纯文本列表。**

```yaml
version: 1
feature: <feature-name>
scope: backend  # backend | frontend | fullstack
source:
  type: spec
  path: <来源路径>

requirements:
  - id: REQ-001
    title: ...
    type: functional
    risk_level: high
    description: ...
    acceptance_criteria: [...]

test_cases:
  # ── backend 示例 ──
  - id: TC-XXX-001
    scope: backend
    title: 创建订单成功，库存正确扣减
    requirement_refs: [REQ-001]
    priority: P0
    risk_level: high
    test_level: scenario
    test_types: [functional, data_consistency]
    automation:
      candidate: high
      target: scenario
      reason: "接口稳定，断言明确"
    preconditions:
      - 用户已登录
      - SKU-A001 库存=10
    dependencies: [http_service, mysql, auth]
    test_data:
      users:
        - ref: buyer
          role: buyer
      database:
        inventory:
          sku: SKU-A001
          stock: 10
    steps:
      - seq: 1
        action: api_call
        description: "调用创建订单接口"
        config:
          method: POST
          path: /orders
          body:
            sku: SKU-A001
            quantity: 1
      - seq: 2
        action: db_query
        description: "查询订单表确认记录写入"
        config:
          query: "SELECT * FROM orders WHERE sku = 'SKU-A001'"
      - seq: 3
        action: db_query
        description: "查询库存表确认扣减"
        config:
          query: "SELECT stock FROM inventory WHERE sku = 'SKU-A001'"
    expected:
      response:
        status: 200
        body:
          orderStatus: CREATED
      data_assertions:
        - type: mysql
          target: orders
          operator: exists
          expected: {sku: SKU-A001, status: CREATED}
          message: "订单表存在已创建状态的记录"
        - type: mysql
          target: inventory
          operator: eq
          expected: {stock: 9}
          message: "库存从 10 扣减至 9"
      dom_assertions: []
    cleanup:
      required: true
      strategy: by_reference
      description: "删除测试订单记录，恢复库存至 10"
    notes: []
    open_questions: []

  # ── frontend 示例 ──
  - id: TC-XXX-005
    scope: frontend
    title: 点击创建按钮后弹出创建成功提示
    requirement_refs: [REQ-001]
    priority: P0
    risk_level: high
    test_level: e2e
    test_types: [functional, ui_interaction]
    automation:
      candidate: high
      target: playwright
      reason: "UI 交互可自动化"
    preconditions:
      - 用户已登录
      - 在订单列表页
    dependencies: [browser, http_service]
    test_data:
      users:
        - ref: buyer
          role: buyer
    steps:
      - seq: 1
        action: ui_navigate
        description: "打开订单列表页"
        config:
          page: /orders
      - seq: 2
        action: ui_click
        description: "点击「创建订单」按钮"
        config:
          selector: '[data-testid="create-order-btn"]'
      - seq: 3
        action: ui_fill
        description: "填写创建订单表单"
        config:
          fields:
            sku: SKU-A001
            quantity: "1"
      - seq: 4
        action: ui_click
        description: "点击提交按钮"
        config:
          selector: '[data-testid="submit-order-btn"]'
      - seq: 5
        action: ui_wait
        description: "等待页面响应"
        config:
          timeout: 3000
        assertions:
          - type: dom_visible
            target: '.toast-success'
            operator: exists
            message: "应弹出成功提示"
          - type: dom_text
            target: '.order-card .status'
            operator: eq
            expected: "已创建"
            message: "订单状态文案正确"
    expected:
      response: {}
      data_assertions: []
      dom_assertions:
        - type: dom_visible
          target: '.toast-success'
          operator: exists
          message: "应弹出成功提示"
        - type: dom_text
          target: '.order-card .status'
          operator: eq
          expected: "已创建"
          message: "订单状态文案正确"
    cleanup:
      required: true
      strategy: not_required
      description: "纯前端用例无需数据清理"
    notes: []
    open_questions: []

  # ── fullstack 示例 ──
  - id: TC-XXX-010
    scope: fullstack
    title: 用户从页面创建订单到数据落库全链路
    requirement_refs: [REQ-001]
    priority: P0
    risk_level: high
    test_level: scenario
    test_types: [functional, data_consistency, ui_interaction]
    automation:
      candidate: high
      target: playwright
      reason: "页面操作 + API 拦截 + 数据校验均可自动化"
    preconditions:
      - 用户已登录
      - SKU-A001 库存=10
    dependencies: [browser, http_service, mysql, auth]
    test_data:
      database:
        inventory:
          sku: SKU-A001
          stock: 10
    steps:
      - seq: 1
        action: ui_navigate
        description: "打开订单创建页"
        config:
          page: /orders/create
      - seq: 2
        action: ui_fill
        description: "填写表单"
        config:
          fields:
            sku: SKU-A001
            quantity: "1"
      - seq: 3
        action: ui_click
        description: "点击提交按钮"
        config:
          selector: '[data-testid="submit-order-btn"]'
      - seq: 4
        action: api_call
        description: "验证创建订单 API 返回"
        config:
          method: POST
          path: /orders
      - seq: 5
        action: db_query
        description: "查询 orders 表确认记录写入"
        config:
          query: "SELECT * FROM orders WHERE sku = 'SKU-A001'"
      - seq: 6
        action: db_query
        description: "查询 inventory 表确认库存变化"
        config:
          query: "SELECT stock FROM inventory WHERE sku = 'SKU-A001'"
    expected:
      response:
        status: 200
        body: {orderStatus: CREATED}
      data_assertions:
        - type: mysql
          target: orders
          operator: exists
          expected: {sku: SKU-A001, status: CREATED}
          message: "订单表存在已创建状态的记录"
        - type: mysql
          target: inventory
          operator: eq
          expected: {stock: 9}
          message: "库存从 10 扣减至 9"
      dom_assertions:
        - type: dom_visible
          target: '.toast-success'
          operator: exists
          message: "应弹出成功提示"
    cleanup:
      required: true
      strategy: by_reference
      description: "删除测试订单，恢复 inventory 库存至 10"
    notes: []
    open_questions: []

coverage:
  - requirement_ref: REQ-001
    test_case_ids: [TC-XXX-001, TC-XXX-005, TC-XXX-010]
    status: covered

open_questions: []
```

#### Action Pipeline 说明

**Step 是结构化对象，不是字符串：**

```
Step {
  seq: int           # 步骤序号
  action: StepAction # 动作类型（枚举）
  description: str   # 业务描述
  config: dict       # 动作参数（selector / path / body / query 等）
  assertions: list[StepAssertion]  # 该步骤的即时断言（可选）
}

StepAction 枚举值:
  ui_navigate, ui_click, ui_fill, ui_select, ui_hover, ui_wait   # 前端
  api_call                                                         # 后端
  db_query, redis_get, mq_check, log_check                        # 数据/中间件
  script                                                           # 自定义脚本
```

**为什么用结构化 Step：** Scenario Runner 和 Playwright 可以直接消费 `config` 字段执行自动化，不需要再解析自然语言字符串。

**Step 的双字段设计（人读 vs 机读）：**

```
description  →  人读（Excel 表格用）  →  业务语言，不写 API 路径/选择器/SQL
config       →  机读（Scenario Runner 用）  →  技术参数，path/selector/query
```

| ❌ 错误（description 写了技术细节） | ✅ 正确（description 用业务语言，技术细节放 config） |
|---|---|
| `POST /api/provider/test-connection {baseUrl:"http://notexist.local:9999"}` | description: "填写不可达的服务器地址，点击测试连接" |
| `GET /api/model/page?page=1&size=10` | description: "打开模型列表页，查看第一页数据" |
| `SELECT * FROM orders WHERE status='CREATED'` | description: "检查订单表中是否存在已创建状态的订单" |

#### Cleanup 说明

**每个 backend / fullstack 用例必须声明 cleanup 策略：**

```yaml
cleanup:
  required: true           # 是否需要清理
  strategy: by_reference   # not_required | by_reference | full_cleanup
  description: "删除测试订单，恢复库存至 10"  # 清理描述
```

- `not_required`: 无需清理（纯前端/只读查询）
- `by_reference`: 引用 fixture 中标记 cleanup 的数据
- `full_cleanup`: 需要完整的清理脚本

### ⚠️ 步骤 B2.5：HUMAN_CONFIRM（未决问题阻断）

**如果生成过程中产生了未决问题（YAML 中 `open_questions` 非空），AI 必须在此处暂停，将问题列出给用户，等待用户澄清后继续。**

```
AI: 以下需求点不确定，请先澄清再生成测试资产：

1. [Q-001] 库存不足时是否允许部分发货？— 影响: TC-XXX-002, TC-XXX-003
2. [Q-002] 订单取消的时间窗口是多少？— 影响: TC-XXX-008

请逐条回答。
```

**用户未回复前，禁止进入步骤 B3（调 Python 校验）。**

### 步骤 B3：调 Python 一键管道（校验 + 质量门禁 + Scenario 映射）

Write YAML 到 `.ai/test-design/<feature>/test-cases.yaml`，然后：

```bash
{engines_cmd} test-design process --input .ai/test-design/<feature>/test-cases.yaml
```

这个命令在一个管道里完成三件事：
1. **Schema 校验** — Pydantic 验证所有字段
2. **质量门禁** — 运行硬阻断 + 软警告检查
3. **Scenario 映射** — 筛选 automation.candidate=high/medium 的用例做映射

返回 JSON：

```json
{
  "success": true,
  "validate": {
    "test_cases_count": 12,
    "requirements_count": 5,
    "coverage_entries": 5,
    "open_questions": 0
  },
  "quality": {
    "passed": true,
    "errors": [],
    "warnings": [...],
    "summary": {...},
    "blocked_requirements": []
  },
  "scenarios": [...],
  "scenarios_count": 5
}
```

如果 `success: false` → 根据 `error` 字段修正 YAML，最多重试 3 次。

### 步骤 B4：判断质量门禁结果

**查看 `quality.passed`：**

**passed = false（有硬阻断 errors）：**
- **必须修复所有 errors 后才能写入文件**
- 打印 errors 给用户，让用户修复后重新走 B2→B3→B4
- 常见硬阻断：
  - `P0/P1 需求缺少用例覆盖`
  - `数据变更用例缺少 data_assertions`
  - `存在未决问题，必须先澄清`
  - `自动化候选用例缺少 dependencies`
  - （cleanup 缺失为软警告，不阻断）

**passed = true（通过或仅有 warnings）：**
- 继续到 B5。warnings 会在质量报告中标注。

### 步骤 B5：写入文件

**必须生成全部 4 个文件，缺一不可。**

按顺序执行：

1. **生成 xlsx（人读）** — 调 CLI，从已校验的 YAML 生成：

```bash
{engines_cmd} test-design export-xlsx --input .ai/test-design/<feature>/test-cases.yaml --output .ai/test-design/<feature>/测试用例.xlsx
```

**失败则降级 `.ai/test-design/<feature>/测试用例.md`。**

2. `.ai/test-design/<feature>/test-cases.yaml` — 已存在（B3 写入），无需再写

3. `.ai/test-design/<feature>/scenario-drafts.yaml` — Write 工具写入 B3 返回的 scenarios

4. `.ai/test-design/<feature>/quality-report.md` — Write 工具写入，模板：

   ```markdown
   # 质量报告 — <feature>

   ## 覆盖概览
   | 指标 | 数值 |
   |------|------|
   | ...来自 quality.summary |

   ## 门禁结果
   **通过** / **未通过**

   ### 硬阻断
   （来自 quality.errors，无则写"无"）

   ### 软警告
   （来自 quality.warnings，无则写"无"）

   *生成时间: <当前时间>*
   ```

### 步骤 B6：验证 + 展示摘要

**先确认 4 个文件都已生成：**

```bash
ls .ai/test-design/<feature>/测试用例.xlsx .ai/test-design/<feature>/test-cases.yaml .ai/test-design/<feature>/scenario-drafts.yaml .ai/test-design/<feature>/quality-report.md
```

缺少任何文件 → 补生成后再展示。

然后展示摘要：

```
AI: 测试设计完成。

| 项目 | 数值 |
|------|------|
| Scope | backend |
| 总用例 | 12 |
| P0/P1 | 5 |
| 自动化候选 | 5 |
| 门禁 | 通过 (0 errors, 2 warnings) |
| 未决问题 | 0 |

文件:
  .ai/test-design/<feature>/test-cases.yaml
  .ai/test-design/<feature>/scenario-drafts.yaml
  .ai/test-design/<feature>/quality-report.md
  .ai/test-design/<feature>/测试用例.xlsx
```

---

## Guardrails

### 流程规则
- **默认视图A + scope=backend** — 除非用户明确指定
- **视图A HUMAN_CONFIRM** — 有 open_questions 时先澄清再生成 Excel
- **视图B HUMAN_CONFIRM** — YAML 中 open_questions 非空时先澄清再调 Python
- **视图B 硬阻断** — quality.passed=false 时禁止写文件，必须先修复
- **视图A 只输出一个 .xlsx 文件**（CLI export-xlsx）
- **视图B 输出 4 个文件**（3 个机器资产 + 1 份人读 .xlsx）
- **不手动写 openpyxl/xlsxwriter** — Excel 生成统一走 CLI export-xlsx
- **xlsx 不可用时降级 Markdown** — 不中断流程

### 内容规则
- **不编造业务规则** — 不确定的写入 open_questions
- **人读 vs 机读分离** — `description` 用业务语言（给 Excel），`config` 放技术参数（给机器）。详见 Action Pipeline 对照表
- **scope 决定 StepAction 和 Assertion 形态** — frontend 用 ui_* + dom_*，backend 用 api_call/db_query + data_assertions
- **涉及数据变化必须有 data_assertions**（backend/fullstack）
- **涉及 UI 必须有 dom_assertions**（frontend/fullstack）
- **P0/P1 必须有覆盖**
- **backend/fullstack 用例必须声明 cleanup 策略**
- **自动化候选（candidate=high/medium）必须声明 dependencies**
- **不修改代码**
