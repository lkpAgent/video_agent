#!/bin/bash
cd "$(dirname "$0")"

# 激活 venv
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
    echo "已激活 venv: $(which python)"
fi

export PYTHONPATH="$(pwd):$PYTHONPATH"

# 杀掉旧进程
OLD_PID=$(lsof -ti:8888 2>/dev/null)
if [ -n "$OLD_PID" ]; then
    echo "关闭旧进程 PID: $OLD_PID"
    kill -9 $OLD_PID 2>/dev/null
    sleep 1
fi

# 验证目录
if [ ! -d "modules" ]; then
    echo "ERROR: modules/ 目录不存在"
    exit 1
fi

echo "启动后端: http://0.0.0.0:8888"
nohup python -u web_server.py > /var/log/video-agent.log 2>&1 &
echo "PID: $!"
