---
name: aicode-plan
user-invocable: true
description: "Generate an Execution Plan — break requirements into tasks with boundaries, budget, and contracts"
---

# /aicode-plan — 生成执行计划

> **核心原则：确定需求来源 → 评估是否需要 Spec → 加载上下文 → superpowers 实现分析 → 生成 Plan → 质量门禁 → 用户确认。**
>
> **Plan 阶段不写代码，不加载 Memory，不修改任何配置文件。**

---

## 完整流程

### 步骤 0：理解用户输入模式

用户可能进入 Plan 的 5 种模式：

| # | 模式 | 说明 |
|---|------|------|
| 1 | **Spec 自然过渡** | 刚从 /aicode-spec 确认了 spec，直接进 plan |
| 2 | `--from <spec-name>` | 显式指定 `docs/spec/<name>.md` |
| 3 | `/aicode-plan <文字描述>` | 用户直接用文字描述需求 |
| 4 | `/aicode-plan --from-prd <目录>` | 用户指定 PRD 目录 |
| 5 | `/aicode-plan` | 无任何附加内容 |

记下当前是哪种模式。

---

### 步骤 1：强检 superpowers（阻断）

尝试调用 `Skill: superpowers:writing-plans`。

- **成功** → 继续步骤 2。
- **失败**（skill not found）→ 告诉用户："superpowers 是 plan 生成的必需依赖，正在自动安装..."

  执行安装（根据当前工具选择命令）：
  - Claude Code: `claude plugins install superpowers`
  - Codex: `codex plugin install superpowers`

  安装完成后继续步骤 2。

---

### 步骤 2：提醒 CodeGraph（非阻断，区分场景）

- **从 Spec 过渡而来**（模式 1）→ 跳过。spec 阶段已提醒过。
- **直接进入 /aicode-plan**（模式 2/3/4/5）→ 尝试 `codegraph_status`：
  - 已初始化 → 继续。
  - 未初始化 → 告诉用户："建议安装 CodeGraph 以便理解项目结构（`codegraph init -i`），跳过不影响 plan 生成。"

不阻断，继续下一步。

---

### 步骤 3：确定需求来源（按优先级）

| 优先 | 来源 | 处理方式 |
|------|------|---------|
| 1 | Spec 过渡（模式 1） | 直接用刚生成的 `docs/spec/<name>.md` |
| 2 | `--from <name>`（模式 2） | Read `docs/spec/<name>.md` |
| 3 | `docs/spec/` 自动发现 | Glob `docs/spec/*.md`，单个直接用，多个 AskUserQuestion 让用户选 |
| 4 | `.ai/prd/` 下有文件 | Glob `.ai/prd/*.{md,txt}`，单个直接用，多个让用户选 |
| 5 | 用户输入文字（模式 3） | 用文字作为需求 |
| 6 | 什么都没有（模式 5） | 询问用户"你有什么需求？或把文档放到 .ai/prd/ 下" |

---

### 步骤 4：评估是否需要先生成 Spec

- **来源是 1/2/3（已有 Spec）→ 跳过评估。** Spec 已充分。
- **来源是 4/5/6（PRD / 用户文字 / 无输入）**：
  - **内容明确**（如"给 OrderService 加分页查询接口"）→ 不需要 Spec，直接 Plan。
  - **需求模糊**（范围不清、目标不明确）→ 用 AskUserQuestion 询问：
    > "需求范围不太明确，建议先 `/aicode-spec` 明确需求和边界。你也可以坚持直接生成 Plan。"
    - 用户接受 → 跳转 `/aicode-spec`
    - 用户坚持 → 继续 Plan，但在 Plan 文件开头标注 `> ⚠️ 无 Spec，可能遗漏边界`

---

### 步骤 5：加载项目上下文

- `codegraph_context` 了解模块结构和依赖关系（**必须**）
- 有 Spec → Read `docs/spec/<name>.md`
- 有 PRD → Read `.ai/prd/<name>.md`

**不读** CLAUDE.md、rules（系统 prompt 已自动加载）
**不读** Memory（Execute/Repair 阶段才需要）

---

### 步骤 6：真正调用 superpowers 生成 Plan（关键！）

**必须直接调用 skill，不能只是描述性地"调用"：**

```bash
Skill: superpowers:writing-plans
```

在调用时，传递：
- 需求：Spec 文件内容 + codegraph 返回的模块结构
- 输出路径：告诉 superpowers 保存到 `docs/plan/<name>.md`（覆盖默认的 `docs/superpowers/plans/`）

**superpowers 会产出详细格式的 Plan，包含每个 Step 的代码块和 Run 命令。**

如果 skill 调用失败或输出不完整，在步骤 7 自行补充详细步骤。

---

### 步骤 7：验证并补充 Plan

如果步骤 6 superpowers 成功生成了详细 Plan：
- 直接 Read 生成的 plan 文件
- 补充 Spec 关联（如 `> 关联 Spec: docs/spec/xxx.md`）
- 跳到步骤 8

如果步骤 6 失败或未完成：
- 基于步骤 5 的上下文，按照下面的模板自己生成详细 Plan
- 每个 Step 必须有：代码块 + `Run:` 命令 + `Expected:` 预期

文件内容：

```markdown
# Plan: <特性名称>

> 关联 Spec: docs/spec/<name>.md（有则写，无则标注"⚠️ 无 Spec"）

**Goal**: <一句话描述这个 Plan 要实现什么>
**Architecture**: <2-3 句话描述技术方案>
**Tech Stack**: <关键技术栈>

---

## Task 列表

### T1: <标题>

**Files:**
- Create: `src/xxx.java`
- Modify: `src/yyy.java:123-145`
- Test: `test/zzz/Test.java`

**Files Summary:**
- 创建 `entity/XxxEntity.java`：定义租户字段 + 业务字段
- 修改 `service/XxxService.java`：注入 EntityMapper，实现 CRUD
- 创建 `controller/XxxController.java`：REST 端点

---

**Step 1: 创建 Entity**

```java
// src/entity/XxxEntity.java
@Data
@TableName("sys_xxx")
public class XxxEntity {
    private Long id;
    private Long tenantId;    // 租户隔离字段
    private String name;
    private Integer status;
    private Integer deleted;  // 逻辑删除
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
```

**Run**: `grep -r "tenant_id" src/entity/ | head -5` 验证租户字段模式
**Expected**: 现有 Entity 都使用 `tenantId` 而非 `tenant_id`

---

**Step 2: 创建 Mapper 接口和 XML**

```java
// src/mapper/XxxMapper.java
@Mapper
public interface XxxMapper extends BaseMapper<XxxEntity> {
    // 自定义查询
    List<XxxEntity> selectByTenantId(@Param("tenantId") Long tenantId);
}
```

```xml
<!-- resources/mapper/XxxMapper.xml -->
<select id="selectByTenantId" resultType="XxxEntity">
    SELECT * FROM sys_xxx WHERE tenant_id = #{tenantId} AND deleted = 0
</select>
```

**Run**: `mvn compile -pl data-module` 验证 Mapper 编译
**Expected**: BUILD SUCCESS

---

**Step 3: 实现 Service 层**

```java
// src/service/impl/XxxServiceImpl.java
@Service
public class XxxServiceImpl implements XxxService {
    @Autowired private XxxMapper mapper;

    @Override
    public XxxEntity create(XxxEntity entity) {
        // 租户上下文由 BaseService 注入
        entity.setTenantId(TenantContext.get());
        mapper.insert(entity);
        return entity;
    }
}
```

**Run**: `mvn compile -pl business-module` 验证 Service 编译
**Expected**: BUILD SUCCESS

---

**Step 4: 实现 Controller**

```java
// src/controller/XxxController.java
@RestController
@RequestMapping("/api/xxx")
public class XxxController {
    @Autowired private XxxService service;

    @PostMapping
    public R<XxxEntity> create(@RequestBody XxxCreateRequest req) {
        return R.ok(service.create(toEntity(req)));
    }

    @GetMapping("/{id}")
    public R<XxxEntity> getById(@PathVariable Long id) {
        return R.ok(service.getById(id));
    }
}
```

**Run**: `mvn compile -pl api-module` 验证 Controller 编译
**Expected**: BUILD SUCCESS

---

**Step 5: 单元测试**

```java
@Test
public void testCreate() {
    // given
    XxxEntity entity = new XxxEntity();
    entity.setName("测试");
    // when
    XxxEntity result = service.create(entity);
    // then
    assertNotNull(result.getId());
    assertEquals("测试", result.getName());
}
```

**Run**: `mvn test -pl business-module -Dtest=XxxServiceTest`
**Expected**: Tests run: 1, Failures: 0, Errors: 0

---

**Done When**: `mvn compile` 全模块通过，POST /api/xxx 返回 200 + 新增记录

**Budget**: maxFiles=4, maxLines=200

---

### T2: <标题>
...（同上格式）

## Budget 汇总

| Task | 文件数 | 预计行数 |
|------|--------|---------|
| T1   | 4      | 200     |
| T2   | 3      | 150     |

## 风险点
- T1 涉及多表事务，需确保 Mapper XML 的 JOIN 条件正确
- ...
```

---

### 步骤 8：Plan 质量门禁

自查以下项：

- [ ] 如果有 Spec，每个 Acceptance Criteria 都绑定到至少一个 Task？
- [ ] 每个 Task 都有 **Files 列表**（Create/Modify/Test）？
- [ ] 每个 Task 都有 **Step 1-N**（且每个 Step 有代码块）？
- [ ] 每个 Step 都有 `Run:` 命令 + `Expected:` 预期输出？
- [ ] 每个 Task 都有 **Done When**（且可验证，不是"做好了"）？
- [ ] 没有 Task 超过 5 个文件？（超过则需拆分）
- [ ] 禁止范围膨胀：没有无关重构/格式化/新抽象？
- [ ] 无 Spec 时 Plan 文件开头标注了风险？

不通过 → 补写。通过 → 进入步骤 9。

---

### 步骤 9：呈现给用户确认

```
✅ Plan 生成完成

文件: docs/plan/<name>.md
Task 数: 3  |  总预算: 6 files / ~270 lines

T1: <标题>  (2 files, 80 lines)
T2: <标题>  (3 files, 150 lines)
T3: <标题>  (1 file, 40 lines)

确认后执行 /aicode-dev 开始开发。
```

等待用户确认。

---

## Guardrails

- **不写代码** — Plan 阶段只写计划文档
- **不加载 Memory** — 方案设计不受历史经验限制
- **codegraph 获取结构** — 不手动 grep 项目文件
- **superpowers 优先** — 优先调用 superpowers:writing-plans 生成详细步骤
- **每个 Task 有边界** — Files 列表必填（Create/Modify/Test）
- **每个 Step 有验证** — Run 命令 + Expected 输出
- **禁止范围膨胀** — 不允许在同一个 Task 中混入无关重构、格式化或新抽象
