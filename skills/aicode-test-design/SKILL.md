---
name: aicode-test-design
user-invocable: true
description: "从 PRD / Spec / 需求描述生成测试用例。支持 --scope backend/frontend/fullstack，默认输出人读 Markdown 表格。"
---

# /aicode-test-design — 生成测试用例

> **核心原则：用最少的测试用例覆盖最多的场景。**
>
> **不编造业务规则、不修改代码、不执行测试。**
>
> **统一输出 Markdown 表格，不生成 Excel。**

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
# 视图A（默认人读 → 输出 .md，只需需求文档）
/aicode-test-design --from docs/spec/order.md
/aicode-test-design --from docs/spec/order.md --scope frontend
/aicode-test-design "用户可以创建订单，库存不足时失败"

# 视图B（全量自动化资产 → 需要需求文档 + Plan）
/aicode-test-design --from docs/spec/order.md --plan docs/plan/order.md --mode full
/aicode-test-design --from docs/spec/order.md --plan docs/plan/order.md --mode full --scope fullstack
```

---

## 核心原则：用最少用例覆盖最多场景

### 测试设计策略（最少用例最大化覆盖）

在生成测试用例之前，必须应用以下技术：

#### 1. 等价类划分
- 每个输入字段分为有效类/无效类
- 为每个有效类设计 1 条用例
- 无效类合并为边界用例

#### 2. 边界值分析
- 对数值范围、分页参数、字符串长度等取边界值
- 典型边界：min, min+1, max-1, max

#### 3. 状态转换图
- 如果业务有状态机，为每条转换路径设计用例
- 避免组合爆炸

#### 4. 正交矩阵
- 当多个条件独立时，用正交表减少组合用例
- 例如：权限 × 操作 × 资源

#### 5. 异常场景合并
- 多个异常可合并在一条用例中
- 用步骤或参数覆盖，不作为独立 Scenario

#### 6. Happy Path + 关键异常
- 每个 API 至少 1 条 Happy Path
- 加上高危业务异常的用例
- 不追求 100% 组合覆盖

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

### 步骤 A2.5：测试设计策略（最少用例最大化覆盖）

在生成用例前，先应用「核心原则」中的测试设计策略：

1. **等价类划分**：列出所有输入字段的有效/无效类
2. **边界值分析**：识别关键边界
3. **状态转换图**：如业务有状态机
4. **设计用例矩阵**：输出给用户确认（可选）

示例输出（内部使用，可不展示）：
```
| 用例ID | 设计策略 | 覆盖的等价类 | 覆盖的边界值 |
|--------|----------|--------------|--------------|
| TC-001 | 等价类-有效类 | 用户名: 5-20字符 | - |
| TC-002 | 边界值 | - | 用户名长度: 1, 5, 20, 50 |
| TC-003 | 状态转换 | 订单: 新建→支付→完成 | - |
```

### ⚠️ 步骤 A2.6：HUMAN_CONFIRM（未决问题阻断）

**如果分析过程中出现了未决问题（open_questions），AI 必须在此处暂停，将问题列出给用户，等待用户澄清后继续。**

```
AI: 分析过程中发现以下不确定点，请澄清：

1. [问题描述] — 影响范围: [哪些用例]
2. [问题描述] — 影响范围: [哪些用例]

请逐条回答后我将继续生成测试用例。
```

**用户未回复前，禁止进入步骤 A3。**

**如果 30 分钟内无回复，AI 将使用 `inferred_source: ai` 标注继续生成，并记录待确认问题到 `.ai/test-design/<feature>/open-questions.md`，事后人工复核。**

### 步骤 A3：生成测试用例表格

1. **生成 Markdown 表格** Write 到 `.ai/test-design/<feature>/测试用例.md`。

2. 表格结构 — 三个 Sheet 用 Markdown 分隔：

**Sheet 1「测试用例」** — 主表

列因 scope 不同：

| scope | 列 |
|-------|----|
| backend | 编号 / 标题 / 优先级 / 前置条件 / 测试步骤 / 预期结果 / 数据校验点 |
| frontend | 编号 / 标题 / 优先级 / 前置条件 / 操作步骤 / 预期页面表现 / UI 校验点 |
| fullstack | 编号 / 标题 / 优先级 / 前置条件 / 操作步骤 / 预期结果 / 接口校验点 / 数据/UI 校验点 |

**Sheet 2「覆盖矩阵」** — 需求项 vs 用例对照：
| 需求编号 | 用例编号 | 覆盖状态 | 备注 |

**Sheet 3「未决问题」**（如有）：
| 问题编号 | 问题描述 | 影响范围 | 阻塞用例 |

**内容规则：**
- **不写具体 API 路径**（如 `GET /api/model/page?page=1&size=10`），用业务描述代替（如"打开模型列表页"）
- 测试步骤用业务语言描述（如"填写表单并提交"），不用技术语言（如"POST /orders"）
- 校验点描述业务含义（如"订单状态变为已创建"），不写 SQL 或 curl 命令

末尾附一行覆盖率小结：
> 覆盖正常 X 条 / 异常 X 条 / 边界 X 条 / 权限 X 条，共 X 条。P0/P1 覆盖 X/X。

### 步骤 A4：展示结果

告诉用户文件路径、用例总数、覆盖小结、未决问题。

**视图A 到此结束。不生成任何 YAML/JSON/Scenario。**

---

## 视图B：全量模式（自动化资产）

### 步骤 B1：确认 Spec

1. **Spec**（必需）:
   - `--from` 指定 → Read
   - `docs/spec/<feature>.md` 查找
   - 都没有 → ❌ **阻断**，提示"请先 /aicode-spec"

2. **Plan**（可选）:
   - `--plan` 指定 → Read
   - `docs/plan/<feature>.md` 查找
   - 没有 → 接口路径 AI 推断，标注 `inferred_source: ai`

### 步骤 B1.5：测试设计策略（最少用例最大化覆盖）

**在生成 Scenario 之前，必须应用以下策略：**

#### 1. 等价类划分
列出所有输入字段的有效/无效类：
- 有效类：每类 1 条用例
- 无效类：合并为边界用例

#### 2. 边界值分析
识别关键边界：
- 数值范围：min, min+1, max-1, max
- 字符串长度：0, 1, 最大长度
- 分页参数：0, 1, 最大页

#### 3. 状态转换图
如业务有状态机（如订单流程），为每条转换路径设计用例

#### 4. 正交矩阵
多个独立条件时，使用正交表减少组合：
- 示例：权限(3) × 操作(4) × 资源(5) = 60 → 正交后 12 条

#### 5. 异常场景合并
多个异常合并在一条 Scenario 中：
- 用 params 字段参数化
- 或用循环步骤

#### 6. Happy Path + 关键异常
- 每个 API 至少 1 条 Happy Path
- 高危业务异常单独用例
- 不追求 100% 组合覆盖

**输出用例设计表（给用户确认，可选）：**
```
| Scenario ID | 设计策略 | 覆盖需求 | 参数化 |
|-------------|----------|----------|--------|
| order-create-success | Happy Path | REQ-001 | - |
| order-create-boundary | 边界值 | REQ-001 | quantity: [0, 1, 999999] |
```

### 步骤 B2：生成 Scenario YAML

**每个 Scenario 一个独立文件。文件必须放在 feature 子目录下，不能直接放 `.ai/scenarios/` 根目录。**

#### ① 先建目录（用 Bash，不要跳过）

Feature 名 = Spec 文件名去掉 `.md`，必须是 kebab-case。

```bash
mkdir -p .ai/scenarios/<feature>
```

#### ①.5 查表结构（有 mysql fixture 时必做，禁止跳过）

**任何包含 `type: mysql` + `action: insert/update` 的 fixture，写 data 之前必须先用 CLI 查表结构：**

```bash
{engines_cmd} data query --source main_db --target "SHOW COLUMNS FROM <table>"
```

输出每一列的 `Field / Type / Null / Key / Default / Extra`。

**根据结果确定 fixture data 必须包含的字段：**
1. `Null = NO` 且 `Default IS NULL` 且非 `auto_increment` → **必须出现在 data 中**
2. `Null = NO` 且有默认值 → 可选，但建议写出以明确意图
3. `Null = YES` → 可选
4. 只写实际存在的列名，**禁止猜列名**

**示例：**

```bash
# 查询 sys_tenant 表结构
{engines_cmd} data query --source main_db --target "SHOW COLUMNS FROM sys_tenant"
```

#### ② 再写文件

每个 Scenario Write 到 `.ai/scenarios/<feature>/<scenario-id>.yaml`。路径必须包含 `<feature>/` 子目录。

#### ③ 文件格式（支持参数化）

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
  design_strategy: happy_path
```

#### ③.5 参数化 Scenario（减少冗余）

**同类用例使用 params 字段参数化，减少文件数量：**

```yaml
# 参数化示例：用一条 Scenario 覆盖多个等价类
id: order-create-boundary-quantity
name: 创建订单边界数量测试
params:
  - {quantity: 1, expected_status: 200, expected_stock: 9}
  - {quantity: 0, expected_status: 400, expected_stock: 10}
  - {quantity: 999999, expected_status: 400, expected_stock: 10}

steps:
  - name: 调用创建订单接口
    type: http_call
    config:
      method: POST
      url: /api/orders
      body: {sku: SKU-A001, quantity: "{{quantity}}"}
      headers:
        Authorization: "Bearer ${auth_token}"

assertions:
  - type: http_status
    target: status
    operator: eq
    expected: "{{expected_status}}"

metadata:
  requirement_refs: [REQ-001, REQ-002]
  priority: P1
  design_strategy: boundary_value
```

**Runner 执行参数化 Scenario 时，会对每组 params 执行一次断言。**

#### ④ 复杂场景示例

**多步骤依赖：**
```yaml
steps:
  - name: 创建用户
    type: http_call
    config:
      method: POST
      url: /api/users
      body: {username: "test"}
  - name: 使用上一步响应
    type: http_call
    config:
      method: GET
      url: "/api/users/${STEP_1.response.data.id}"
```

**异步回调验证：**
```yaml
steps:
  - name: 触发异步任务
    type: http_call
    config:
      method: POST
      url: /api/tasks
  - name: 等待消息队列回调
    type: mq_consume
    config:
      queue: task_completed
      timeout: 30
  - name: 验证结果
    type: http_call
    config:
      method: GET
      url: "/api/tasks/${STEP_1.response.data.taskId}/status"
```

**并发冲突模拟：**
```yaml
steps:
  - name: 并发请求A
    type: http_call
    config:
      method: POST
      url: /api/inventory/lock
      body: {sku: SKU-A001}
  - name: 并发请求B（同一SKU）
    type: http_call
    config:
      method: POST
      url: /api/inventory/lock
      body: {sku: SKU-A001}

assertions:
  - type: http_status
    target: "[0].status"
    operator: eq
    expected: 200
  - type: http_status
    target: "[1].status"
    operator: eq
    expected: 409
```

**Scenario 字段说明：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | str | ✅ | 唯一标识，kebab-case |
| name | str | ✅ | 场景名称 |
| description | str | | 描述 |
| params | list[dict] | | 参数化数据，每组执行一次 |
| scope | backend/frontend/fullstack | | 默认 backend |
| requires | list[str] | | http_service, mysql, redis, mq, browser 等 |
| fixtures | list[Fixture] | | 前置数据，type=mysql/redis/http/script |
| steps | list[ScenarioStep] | ✅ | 执行步骤，type=http_call/wait/setup/script/ui_* |
| assertions | list[Assertion] | ✅ | 断言，type=http_status/json_path/db_query 等 |
| dom_assertions | list[DomAssertion] | | 前端 DOM 断言 |
| teardown | list[Fixture] | | 后置清理 |
| metadata | dict | | 优先级/风险/关联需求/设计策略 |

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

**如果 30 分钟内无回复，AI 将使用 `inferred_source: ai` 标注继续生成，并记录待确认问题到 `.ai/test-design/<feature>/open-questions.md`，事后人工复核。**

### 步骤 B2.3：增量生成（首次可跳过）

如果 `.ai/scenarios/<feature>/` 下已有文件，先 Read 已有 yaml，列出已覆盖的 requirement_refs，只生成新增/变更的。首次生成跳过此步。

### 步骤 B3：调 Python 校验 + 覆盖校验

每个生成的 Scenario 文件必须通过校验：

```bash
{engines_cmd} scenario validate --dir .ai/scenarios/<feature>/
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

**使用 CLI 自动输出覆盖矩阵：**

```bash
{engines_cmd} scenario validate --dir .ai/scenarios/<feature>/ --coverage docs/spec/<feature>.md
```

自动输出：
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
| 设计策略 | 等价类(3) + 边界值(2) + Happy Path(1) |

文件:
  .ai/scenarios/<feature>/
    ├── order-create-success.yaml
    ├── order-create-boundary-quantity.yaml  # 参数化
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
- **HUMAN_CONFIRM** — 有 open_questions 时先澄清再继续，超时 30 分钟自动继续并记录
- **视图B 调 `engines scenario validate`** — Pydantic 格式校验 + 基本健全性
- **视图A 只输出 .md 文件** — 不生成 Excel

### 内容规则
- **文件路径: `.ai/scenarios/<feature>/<id>.yaml`** — 不直接放根目录
- **Spec 文件名必须是 kebab-case** — 直接作为 feature 目录名
- **写 mysql fixture 前必须先查表结构** — `{engines_cmd} data query --source main_db --target "SHOW COLUMNS FROM <table>"`，禁止猜列名、禁止遗漏 NOT NULL 无默认值列
- **不编造业务规则** — 不确定的写入 open_questions
- **接口路径来自 Plan** — 无 Plan 时标注 `inferred_source: ai`
- **涉及数据变化必须有 db_query/db_count 断言**（backend/fullstack）
- **涉及 UI 必须有 dom_assertions**（frontend/fullstack）
- **P0/P1 必须有覆盖**
- **每个 backend/fullstack 场景必须有 teardown 清理步骤**
- **同类用例使用 params 参数化** — 减少冗余文件
- **不修改代码**

### 测试设计规则
- **等价类划分** — 每类 1 条用例
- **边界值分析** — min, min+1, max-1, max
- **状态转换图** — 每条路径 1 条用例
- **异常合并** — 多异常合并，不独立 Scenario
- **Happy Path + 关键异常** — 不追求 100% 组合
- **参数化** — 同类用例用 params 合并
