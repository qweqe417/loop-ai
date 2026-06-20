@echo off
REM AI Coding Loop - Windows 引擎入口
REM 用法: engines\run.bat <command> [args...]
REM AI 通过调用此脚本与 Python 引擎通信

cd /d "%~dp0\.."
python engines\cli.py %*
