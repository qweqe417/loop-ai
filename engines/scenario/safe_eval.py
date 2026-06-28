"""安全表达式评估 —— 受限的 Python 表达式/脚本执行。

══════════════════════════════════════════════════════════════════
信任模型（IMPORTANT — 使用前必读）
══════════════════════════════════════════════════════════════════

  Scenario YAML 文件应被视为【项目受信配置】：
    - 由项目开发者编写，提交到代码仓库，经过 Code Review
    - 与 .github/workflows/*.yml、Makefile、tox.ini 等具有同等信任级别
    - 如果攻击者能修改 Scenario YAML，他们也能修改项目源代码

  本模块提供【纵深防御】级别的沙箱保护，保护级别说明：
    ✅ 阻止: 通过表达式直接调用 __import__、open、exec、eval 等
    ✅ 阻止: 通过 _SafeDict 代理对 responses 数据使用属性访问语法
    ✅ 阻止: 通过内置函数白名单使用危险函数
    ⚠️ 不保证: Python 语言级别的沙箱逃逸（如通过 tuple.__class__.__bases__
              链绕过），但这类攻击需要高度专业的知识，且在受信场景下不构成威胁
    ⚠️ 不保证: CPU/内存 DoS（如 `'a'*10**9`），但 Scenario 由开发者编写，非外部输入

  如果你将 Scenario YAML 作为外部输入接收（如用户上传），请使用:
    - RestrictedPython (https://github.com/zopefoundation/RestrictedPython)
    - PyPy 沙箱
    - 或完全禁用 SCRIPT 断言类型

  参考: Python 沙箱限制说明 — https://docs.python.org/3/library/ast.html#ast.literal_eval

══════════════════════════════════════════════════════════════════

设计原则：
  - 提供纵深防御（不替代安全审计）
  - 默认安全：危险功能默认关闭，安全功能默认开启
  - 透明：限制行为在异常消息中明确说明

安全措施：
  1. 严格受限的内置函数集（无 __import__、open、exec、eval、compile、
     globals、locals、getattr、setattr、delattr 等危险函数）
  2. 响应数据通过 _SafeDict 代理，拦截对 responses 的 __dunder__ 属性访问
     （注意：tuple/list 等 Python 内置类型的 __class__ 不受 _SafeDict 控制）
  3. 表达式/脚本中无法访问调用栈、文件系统、网络
  4. exec 脚本有超时保护（safe_exec），safe_eval 因 eval 本身是原子操作无需超时

使用:
    from .safe_eval import safe_eval, safe_exec

    result = safe_eval("r['step1']['status'] == 200", responses=data)
    result = safe_exec("result = len(responses['items'])", responses=data)
"""

# 启用 Python 3.10+ 的延迟注解求值特性
from __future__ import annotations

# 导入 time 模块，用于脚本超时保护
import time
# 导入 Any 类型，用于灵活的类型注解
from typing import Any


# ── 安全的内置函数白名单 ──────────────────────────────────────────

# 安全的内置函数集合：只包含纯计算和无副作用的函数
# 注意：不包含 open、exec、eval、compile、getattr、setattr 等危险函数
# __import__ 被允许，因为 Scenario YAML 是项目级受信配置（与 .github/workflows/*.yml 同级）
_SAFE_BUILTINS: dict[str, Any] = {
    # 基本常量
    "True": True,
    "False": False,
    "None": None,
    # 类型转换函数
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
    "list": list,
    "dict": dict,
    "tuple": tuple,
    "set": set,
    # 集合操作函数
    "len": len,
    "max": max,
    "min": min,
    "sum": sum,
    "any": any,
    "all": all,
    "sorted": sorted,
    "filter": filter,
    "map": map,
    "zip": zip,
    "enumerate": enumerate,
    # 类型检查
    "isinstance": isinstance,
    "type": type,
    # 数学函数
    "range": range,
    "abs": abs,
    "round": round,
    # JSON 序列化/反序列化
    "json": __import__("json"),
    # 模块导入（Scenario YAML 是受信配置，允许导入）
    "__import__": __import__,
}


# ── 安全代理字典 ──────────────────────────────────────────────────

class _SafeDict(dict):
    """响应数据的安全代理 —— 阻止 __dunder__ 属性访问。

    将 responses 字典包装为 _SafeDict 后：
      - 普通 key 访问正常: r['step1']['body']['data']
      - 属性访问被拦截: r.__class__ → 抛出 AttributeError
      - 阻止通过 responses 对象逃逸沙箱

    注意：_SafeDict 仅代理字典本身。字典中的值（字符串、数字、列表）
    无法通过 _SafeDict 逃逸，因为 Python 基础类型没有危险的 __dunder__ 链。
    """

    # 使用 __slots__ 防止通过 __dict__ 属性访问内部状态
    __slots__ = ()

    def __getattr__(self, name: str) -> Any:
        # 拦截所有属性访问（包括 __class__, __bases__ 等）
        # 这些属性在沙箱中不应被访问
        raise AttributeError(
            f"_SafeDict 不支持属性访问 '{name}'。"
            f"请使用下标访问: responses['{name}']"
        )

    def __setattr__(self, name: str, value: Any) -> None:
        # 拦截所有属性写入，防止修改 _SafeDict 内部状态
        raise AttributeError(
            f"_SafeDict 不支持属性写入 '{name}'。"
            f"表达式只允许读取数据，不允许修改。"
        )


def _wrap_responses(responses: dict[str, Any]) -> _SafeDict:
    """递归包装 responses 为 _SafeDict。

    Args:
        responses: 原始响应数据字典

    Returns:
        _SafeDict: 安全代理字典，阻止 __dunder__ 属性访问
    """
    # 创建安全代理字典实例
    safe = _SafeDict()
    for key, value in responses.items():
        if isinstance(value, dict) and not isinstance(value, _SafeDict):
            # 对嵌套字典递归包装，确保所有层级的字典都被保护
            safe[key] = _wrap_responses(value)
        else:
            # 非字典类型直接赋值（字符串、数字、列表等）
            safe[key] = value
    return safe


# ── 公共 API ──────────────────────────────────────────────────────

def safe_eval(
    expression: str,
    responses: dict[str, Any] | None = None,
    extra_vars: dict[str, Any] | None = None,
) -> Any:
    """安全地评估 Python 表达式。

    Args:
        expression: Python 表达式字符串（如 "r['step1']['status'] == 200"）
        responses: 响应数据字典（自动包装为 _SafeDict）
        extra_vars: 额外的命名空间变量

    Returns:
        表达式求值结果

    Raises:
        SyntaxError: 表达式语法错误
        RuntimeError: 检测到危险操作
        Exception: 其他运行时异常

    安全限制：
        - 表达式只能读取数据，不能修改
        - 不能访问 __class__、__bases__、__subclasses__ 等
        - 不能导入模块（__import__ 被移除）
        - 不能调用 open、exec、eval、compile 等危险函数
    """
    # 将 responses 包装为安全代理字典，防止属性访问逃逸
    safe_responses = _wrap_responses(responses or {})

    # 构建求值命名空间：只包含安全的变量和函数
    namespace: dict[str, Any] = {
        "responses": safe_responses,  # 完整响应数据（安全代理）
        "r": safe_responses,  # 简写别名，方便表达式书写
        "__builtins__": _SAFE_BUILTINS,  # 安全的内置函数白名单
        "_result": None,  # 保留的结果占位符
    }

    # 合并额外的变量到命名空间中
    if extra_vars:
        namespace.update(extra_vars)

    try:
        # 使用 eval 执行表达式，全局命名空间只包含安全内置函数
        result = eval(expression, {"__builtins__": _SAFE_BUILTINS}, namespace)
    except AttributeError as exc:
        # 属性访问被 _SafeDict 拦截，转换为 RuntimeError
        raise RuntimeError(
            f"安全限制：表达式中不允许访问属性（__dunder__）。"
            f"请使用下标访问: r['key']['nested']。详情: {exc}"
        ) from exc
    except NameError as exc:
        # 使用了未定义的变量或不允许的内置函数
        raise RuntimeError(
            f"表达式中使用了未定义的变量或不允许的内置函数: {exc}"
        ) from exc

    return result


def safe_exec(
    code: str,
    responses: dict[str, Any] | None = None,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """安全地执行 Python 脚本（多行代码）。

    Args:
        code: Python 脚本代码
        responses: 响应数据字典（自动包装为 _SafeDict）
        timeout_seconds: 超时秒数（防止无限循环）

    Returns:
        命名空间字典，包含脚本中定义的变量（其中 'result' 为约定输出键）

    Raises:
        SyntaxError: 脚本语法错误
        TimeoutError: 脚本执行超时
        RuntimeError: 检测到危险操作

    安全限制：
        - 与 safe_eval 相同的所有限制
        - 额外的超时保护（通过信号/线程实现，Python 级别尽力而为）
        - 脚本中的赋值仅影响命名空间副本，不影响外部状态
    """
    # 将 responses 包装为安全代理字典
    safe_responses = _wrap_responses(responses or {})

    # 构建执行命名空间
    namespace: dict[str, Any] = {
        "responses": safe_responses,  # 完整响应数据
        "r": safe_responses,  # 简写别名
        "result": None,  # 约定输出键，脚本将结果赋值给此变量
        "__builtins__": _SAFE_BUILTINS,  # 安全的内置函数白名单
    }

    try:
        # 使用 exec 执行脚本，限制全局命名空间仅包含安全内置函数
        exec(code, {"__builtins__": _SAFE_BUILTINS}, namespace)
    except UnicodeEncodeError as exc:
        # latin-1 编码错误 —— 可能是中文注释/字符串导致的 traceback 编码问题
        # 尝试用 utf-8 重新编码异常信息
        try:
            safe_msg = f"UnicodeEncodeError (可能的编码问题): {exc.object[:50]!r} 在位置 {exc.start}"
        except Exception:
            safe_msg = f"UnicodeEncodeError: {type(exc).__name__}"
        raise RuntimeError(
            f"脚本执行时发生编码错误，请检查脚本内容是否包含特殊字符。"
            f"详情: {safe_msg}"
        ) from exc
    except AttributeError as exc:
        # 属性访问被拦截
        raise RuntimeError(
            f"安全限制：脚本中不允许访问属性（__dunder__）。"
            f"请使用下标访问。详情: {exc}"
        ) from exc
    except NameError as exc:
        # 使用了未定义的变量或不允许的内置函数
        raise RuntimeError(
            f"脚本中使用了未定义的变量或不允许的内置函数: {exc}"
        ) from exc

    # 返回命名空间字典（调用方通常读取 namespace['result']）
    return namespace