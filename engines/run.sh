#!/bin/bash
# AI Coding Loop - Linux/Mac 引擎入口
# 用法: bash engines/run.sh <command> [args...]
# AI 通过调用此脚本与 Python 引擎通信

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# 强制 Python 使用 UTF-8 编码（Windows Git Bash 下避免中文乱码）
export PYTHONIOENCODING=utf-8

# 自动找到可用的 Python（跳过 Windows App Store 存根）
find_python() {
    # 1. 插件自带的 .venv 优先
    if [ -f "$PROJECT_ROOT/.venv/Scripts/python.exe" ]; then
        echo "$PROJECT_ROOT/.venv/Scripts/python.exe"
        return
    fi

    # 2. Windows: py.exe launcher（官方 Python Launcher，永远能找到已安装的 Python）
    if command -v py >/dev/null 2>&1; then
        local py_path
        py_path=$(py -c "import sys; print(sys.executable)" 2>/dev/null)
        if [ -n "$py_path" ] && [ -f "$py_path" ]; then
            echo "$py_path"
            return
        fi
    fi
    # 也检查 py 在常见 Windows Launcher 路径
    for py_launcher in "/c/Users/$USER/AppData/Local/Programs/Python/Launcher/py.exe" \
                       "/c/Program Files/Python/Launcher/py.exe"; do
        if [ -f "$py_launcher" ]; then
            local py_path
            py_path=$("$py_launcher" -c "import sys; print(sys.executable)" 2>/dev/null)
            if [ -n "$py_path" ] && [ -f "$py_path" ]; then
                echo "$py_path"
                return
            fi
        fi
    done

    # 3. python3（跳过 Windows Store 存根）
    if command -v python3 >/dev/null 2>&1; then
        local py3_path
        py3_path=$(command -v python3)
        case "$py3_path" in
            *WindowsApps*|*/AppExecutionAlias*)
                ;;  # 跳过 Windows Store 桩
            *)
                local py3_ver=$(python3 --version 2>&1)
                if [ $? -eq 0 ] && [ -n "$py3_ver" ]; then
                    echo "python3"
                    return
                fi
                ;;
        esac
    fi

    # 4. python（跳过 Windows Store 存根）
    if command -v python >/dev/null 2>&1; then
        local py_path
        py_path=$(command -v python)
        case "$py_path" in
            *WindowsApps*|*/AppExecutionAlias*)
                ;;  # 跳过 Windows Store 桩
            *)
                local py_ver=$(python --version 2>&1)
                if [ $? -eq 0 ] && [ -n "$py_ver" ]; then
                    echo "python"
                    return
                fi
                ;;
        esac
    fi

    # 5. 常见 Windows 安装路径（glob 匹配多版本）
    for base in "/c/Python"*/python.exe \
                "/c/Users/$USER/AppData/Local/Programs/Python/Python"*/python.exe \
                "/c/Program Files/Python"*/python.exe \
                "/d/Python"*/python.exe \
                "/d/ruanjian/python/python.exe"; do
        # 展开 glob，取第一个匹配的
        for py in $base; do
            if [ -f "$py" ]; then
                echo "$py"
                return
            fi
        done
    done

    echo "python"  # last resort
}

PYTHON=$(find_python)
# 不 cd — 保持在用户项目目录，让 Python 用 cwd() 找到 .ai/loop-config.json
exec "$PYTHON" "$SCRIPT_DIR/cli.py" "$@"
