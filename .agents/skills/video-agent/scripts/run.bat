@echo off
REM 视频智能体快捷启动脚本
REM 用法: run.bat "你的主题"

cd /d C:\Users\lkp\video-agent

if "%1"=="" (
    python main.py
) else (
    python main.py %*
)
