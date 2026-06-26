@echo off
REM AI Coding Loop - Windows engine entry point
REM Usage: engines\run.bat <command> [args...]

set PYTHONIOENCODING=utf-8
cd /d "%~dp0\.."
python engines\cli.py %*
