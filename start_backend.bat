@echo off
REM 启动后端 API 服务
cd /d %~dp0
python web_server.py
