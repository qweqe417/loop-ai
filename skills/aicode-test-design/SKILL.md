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
   - 执行方式：`python <plugin>/engines/cli.py scenario ...`
3. 如果找不到 → **不要跳过！** 用 `Glob **/engines/cli.py` 在当前项目和插件目录搜索，找到后直接 `python <path>` 执行

**绝对不允许跳过 CLI 步骤。找不到就搜索，搜索不到就报错，不能静默跳过。**

---

## 触发方式

```bash
# 视图A（默认人读 → 输出 .xlsx，只需需求文档）
/aicode-test-design --from docs/spec/order.md
/aicode-test-design --from docs/spec/order.md --scope frontend
/aicode-test-design "用户可以创建订单，库存不足时失败"

# 视图B（全量自动化资产 → 需要需求文档 + Plan）
/aicode-test-design --from docs/spec/order.md --plan docs/plan/order.md --mode full
/aicode-test-design --from docs/spec/order.md --plan docs/plan/order.md --mode full --scope fullstack
```

---

## 标准

```
测什么: Spec   ← 唯一覆盖标准
怎么测: Plan   ← 提供接口路径和参数
原材料: PRD    ← 先跑 /aicode-spec 转成 Spec

Spec 存在  → 可以出视图B（Scenario YAML）
Spec 不存在 → 只能出视图A（人读表格），或先跑 /aicode-spec
```

| Spec | Plan | 视图A | 视图B |
|------|------|-------|-------|
| ✅ | ✅ | ✅ | ✅ 最优：业务规则 + 接口契约齐全 |
| ✅ | ❌ | ✅ | ✅ 接口路径 AI 推断，标注 `inferred_source: ai` |
| ❌ | ✅ | ✅ | ❌ 阻断：提示"请先 /aicode-spec，Plan 不管业务规则" |
| ❌ | ❌ | ✅ | ❌ 阻断：同上 |

---

## 步骤 0：判断模式、输入和范围

### 决策树

```
用户触发 /aicode-test-design
  │
  ├─ 用户加了 --mode full（视图B）
  │   │
  │   ├─ 有 Spec？
  │   │   ├─ YES → ✅ 直接生成 Scenario YAML
  │   │   │         Plan 有 → 接口路径来自 Plan
  │   │   │         Plan 无 → 接口路径 AI 推断，标注 inferred_source: ai
  │   │   └─ NO  → ❌ 阻断: "需要 Spec。请先 /aicode-spec"
  │   │
  │   └─ 用户没有 --mode full（默认视图A）
  │       │
  │       ├─ 有 Spec/PRD → ✅ 直接出 Markdown 表格
  │       ├─ 一句话 → ⚠️ 先澄清再出
  │       └─ 什么都没有 → ❌ 提示用户提供需求
```

**Loop TEST_DESIGN 阶段 → 走视图B。**

### 文件位置

```
Spec: docs/spec/<feature>.md
Plan: docs/plan/<feature>.md
PRD:  docs/prd/<feature>.md 或 .ai/prd/<feature>.md
```

### Plan 发现（视图B 辅助）

1. 用户 `--plan` 指定 → 直接使用
2. `docs/plan/<feature>.md`
3. 都没有 → 接口路径 AI 推断，标注 `inferred_source: ai`

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

### 步骤 A3：生成测试用例表格

1. **生成 Markdown 表格** Write 到 `.ai/test-design/<feature>/测试用例.md`。

2. 表格结构 — 三个 Sheet 用 Markdown 分隔：

**Sheet 1「测试用例」** — 主表

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

### 步骤 B1：确认 Spec

1. **Spec**（必需）:
   - `--from` 指定 → Read
   - `docs/spec/<feature>.md` 查找
   - 都没有 → ❌ **阻断**，提示"请先 /aicode-spec"

2. **Plan**（可选）:
   - `--plan` 指定 → Read
   - `docs/plan/<feature>.md` 查找
   - 没有 → 接口路径 AI 推断，标注 `inferred_source: ai`

### 步骤 B2：生成 Scenario YAML

**每个 Scenario 一个独立文件。文件必须放在 feature 子目录下，不能直接放 `.ai/scenarios/` 根目录。**

#### ① 先建目录（用 Bash，不要跳过）

Feature 名 = Spec 文件名去掉 `.md`。比如 `docs/spec/order-management.md` → `order-management`。

```bash
mkdir -p .ai/scenarios/<feature>
```

#### ② 再写文件

每个 Scenario Write 到 `.ai/scenarios/<feature>/<scenario-id>.yaml`。路径必须包含 `<feature>/` 子目录。

```
.ai/scenarios/
  order-management/           ← 一个 Spec 一个子目录
    order-create-success.yaml
    order-create-stock-insufficient.yaml
  user-auth/                  ← 另一个 Spec 的子目录
    login-success.yaml
```

#### ③ 文件格式（单 Scenario，非数组）

```yaml
# .ai/scenarios/order-management/order-create-success.yaml
id: order-create-success
name: 创建订单成功，库存正确扣减
description: 覆盖 REQ-001
scope: backend
requires: [http_service, mysql, auth]

fixtures:
  - name: inventory_fixture
    type: mysql
    action: insert
    target: inventory
    data: {sku: SKU-A001, stock: 10}

steps:
  - name: 调用创建订单接口
    type: http_call
    config:
      method: POST
      url: /api/orders
      body: {sku: SKU-A001, quantity: 1}
      headers:
        Authorization: "Bearer ${auth_token}"
  - name: 等待写入完成
    type: wait
    config: {duration: 1}

assertions:
  - type: http_status
    target: status
    operator: eq
    expected: 200
  - type: json_path
    target: $.data.orderStatus
    operator: eq
    expected: CREATED
  - type: db_query
    target: "SELECT status FROM orders WHERE sku='SKU-A001'"
    operator: eq
    expected: CREATED
  - type: db_query
    target: "SELECT stock FROM inventory WHERE sku='SKU-A001'"
    operator: eq
    expected: 9

teardown:
  - name: cleanup_order
    type: mysql
    action: delete
    target: orders
    data: {sku: SKU-A001}

metadata:
  requirement_refs: [REQ-001]
  priority: P0
  risk_level: high
```

**Scenario 字段说明：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | str | ✅ | 唯一标识，kebab-case |
| name | str | ✅ | 场景名称 |
| description | str | | 描述 |
| scope | backend/frontend/fullstack | | 默认 backend |
| requires | list[str] | | http_service, mysql, redis, mq, browser 等 |
| fixtures | list[Fixture] | | 前置数据，type=mysql/redis/http/script |
| steps | list[ScenarioStep] | ✅ | 执行步骤，type=http_call/wait/setup/script/ui_* |
| assertions | list[Assertion] | ✅ | 断言，type=http_status/json_path/db_query/db_count/redis_key/redis_value 等 |
| dom_assertions | list[DomAssertion] | | 前端 DOM 断言 |
| teardown | list[Fixture] | | 后置清理 |
| metadata | dict | | 优先级/风险/关联需求等 |

**交叉校验规则（生成时执行）：**
- steps[].config 中的接口路径/参数 → 来自 Plan
- assertions 中的业务断言 → 来自 Spec/PRD
- 两者不一致 → 标注 `inferred_source: ai`，写入未决问题

### ⚠️ 步骤 B2.5：HUMAN_CONFIRM（未决问题阻断）

**如果生成过程中产生了未决问题，AI 必须在此处暂停，将问题列出给用户。**

```
AI: 以下需求点不确定，请先澄清再生成 Scenario：

1. 库存不足时是否允许部分发货？— 影响: order-create-partial
2. 订单取消的时间窗口是多少？— 影响: order-cancel-timeout

请逐条回答。
```

**用户未回复前，禁止进入步骤 B3。**

### 步骤 B2.3：增量生成（首次可跳过）

如果 `.ai/scenarios/<feature>/` 下已有文件，先 Read 已有 yaml，列出已覆盖的 requirement_refs，只生成新增/变更的。首次生成跳过此步。

### 步骤 B3：调 Python 校验

每个生成的 Scenario 文件必须通过校验：

```bash
{engines_cmd} scenario validate --dir .ai/scenarios/
```

返回 JSON：

```json
{
  "success": true,
  "all_valid": true,
  "results": [
    {"file": "order-create-success.yaml", "valid": true, "errors": [], "warnings": []},
    ...
  ]
}
```

**校验逻辑（Python）：**
1. Pydantic 格式校验（类型错误直接报错）
2. fixture 类型合法性（mysql/redis/http/script/mq）
3. 有 insert/update fixture 必须有对应 teardown → warning
4. 断言不为空、步骤类型合法、声明了 mysql 但没有 db_query 断言 → warning

如果某个文件 `valid: false` → 根据 errors 修正，重试 ≤3 次。

### 步骤 B4：覆盖校验

逐条对比 Spec 的 requirements vs 已生成 Scenario 的 `metadata.requirement_refs`：

```
| Spec 需求 | 覆盖的 Scenario | 状态 |
|-----------|----------------|------|
| REQ-001 创建订单 | order-create-success | ✅ |
| REQ-002 取消订单 | order-cancel | ✅ |
| REQ-003 退款 | — | ❌ 缺失 |
```

**所有 ❌ 必须有解释：**
- "退款是下一期需求" → 在 Spec 中标注，跳过
- "漏了" → 补写 Scenario

不编造、不跳过——每个 Spec 中的 requirement 都必须被覆盖或有合理解释。

### 步骤 B5：展示结果

校验+覆盖通过后输出摘要：

```
AI: 测试设计完成。

| 项目 | 数值 |
|------|------|
| Scope | backend |
| 场景数 | 5 |
| P0/P1 | 3 |
| 断言总数 | 18 |
| 校验 | 通过 (0 errors, 1 warning) |

文件:
  .ai/scenarios/<feature>/
    ├── order-create-success.yaml
    ├── order-create-stock-insufficient.yaml
    └── ...
```

**视图B 到此结束。不再生成 TestCase YAML、Scenario Draft、Quality Report 等中间文件。**

---

## Guardrails

### 流程规则
- **默认视图A + scope=backend** — 除非用户明确指定
- **视图A 只需需求文档** — 有 PRD/Spec/一句话(澄清后) 即可
- **视图B 需要需求文档 + Plan** — 无 Plan 触发降级（标记 `inferred_source: ai`）
- **视图B 直接生成 Scenario YAML** — 不再走 TestCase 中间格式
- **视图B 交叉校验** — 接口路径/参数对 Plan，业务断言对 Spec，不一致写 open_questions
- **HUMAN_CONFIRM** — 有 open_questions 时先澄清再继续
- **视图B 调 `engines scenario validate`** — Pydantic 格式校验 + 基本健全性
- **视图A 只输出 .xlsx 文件**（Excel 由 skill 自行生成，走 Markdown 表格降级）
- **不手动写 openpyxl/xlsxwriter** — Excel/Markdown 由 skill 处理

### 内容规则
- **文件路径: `.ai/scenarios/<feature>/<id>.yaml`** — 不直接放根目录
- **不编造业务规则** — 不确定的写入 open_questions
- **接口路径来自 Plan** — 无 Plan 时标注 `inferred_source: ai`
- **涉及数据变化必须有 db_query/db_count 断言**（backend/fullstack）
- **涉及 UI 必须有 dom_assertions**（frontend/fullstack）
- **P0/P1 必须有覆盖**
- **每个 backend/fullstack 场景必须有 teardown 清理步骤**
- **不修改代码**
