@echo off
REM 启动前端服务（开发模式，用 Python 简易 HTTP 服务器）
cd /d %~dp0\static
echo 前端运行在 http://localhost:3000
python -m http.server 3000
