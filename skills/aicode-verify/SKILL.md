---
name: aicode-verify
user-invocable: true
description: "场景验证 — Python 引擎全自动执行 HTTP + DB/Redis/MQ 测试，AI 只在失败时介入修复"
---

# /aicode-verify — 场景验证

**你只做两件事：① 跑命令 ② 看结果决定要不要修代码。除此之外什么都不做。**

---

## 暂停协议

引擎跑完后可能会暂停，要求你修复代码。看 `pending_action`：

```
pending_action: "repair"       → 分析根因修代码
```

### 数据源断言

Python 引擎通过 DataSourceRegistry 自动执行 DB/Redis/MQ 断言（配置在 loop-config.json 的 data_sources 中）。

**如果断言失败且错误信息包含"适配器未配置"** → 告诉用户检查 loop-config.json 的 data_sources 配置。

---

## Trigger → 命令映射

```
/aicode-verify --auto-fix --scenario-dir <dir>  →  {engines_cmd} loop verify-loop --scenario-dir <dir>
/aicode-verify --auto-fix --all                 →  {engines_cmd} loop verify-loop
/aicode-verify --auto-fix <id>                  →  {engines_cmd} loop verify-loop --scenario <id>
/aicode-verify --all                            →  {engines_cmd} loop verify
/aicode-verify <id>                             →  {engines_cmd} verify --scenario <id>
```

## 严禁

- ❌ 给命令加额外参数（--debug、-v、--verbose 等），命令映射表里没有的不加
- ❌ 手动 mvn / npm / gradle 编译或启动服务
- ❌ 手动 curl / httpie 发请求
- ❌ 手动 netstat / taskkill / kill 杀进程
- ❌ 手动修改 loop-config.json
- ❌ 手动获取验证码或登录
- ❌ 跳过引擎命令自己跑场景
- ❌ Python 还没出结果就开始分析

**Python 引擎自动完成以上全部。你只负责跑命令、看结果。**

## 流程

### 1. 跑命令

根据 Trigger 选一条命令，执行，等待完成。

### 2. 看结果

读 `.ai/reports/test-report-*.json` 最新一份。

**断言结果直接看：**
- **DB/Redis/MQ 断言失败** → Python 引擎已直接查询数据源并返回 actual vs expected，看具体差异
- **"适配器未配置" 错误** → 告诉用户检查 .ai/loop-config.json data_sources 配置和驱动安装
- ENVIRONMENT 失败 → 告诉用户检查环境
- 全部通过 → 输出报告，结束

### 3. 修代码（仅 REAL_BUG）

1. 找根因 — 读代码追踪数据流，定位出错行
2. 最小修复 — 只改出问题的地方
3. 复测 — `{engines_cmd} loop continue --state-file run.json`
4. 最多 3 轮，超过升级给用户

## Guardrails

- 结果用中文呈现
- 不删断言让测试通过
- 环境故障不进 REPAIR
- 最多 3 轮修复
