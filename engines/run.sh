#!/bin/bash
# AI Coding Loop - Linux/Mac 引擎入口
# 用法: bash engines/run.sh <command> [args...]
# AI 通过调用此脚本与 Python 引擎通信

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"
python "$SCRIPT_DIR/cli.py" "$@"
