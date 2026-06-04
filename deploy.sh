#!/bin/bash
# 发版脚本：拉代码 → 更新依赖 → 前端 → 重启
set -e
cd /data2/video_agent

echo "📥 拉取代码..."
git pull origin main

source venv/bin/activate
echo "📦 更新依赖..."
pip install -r requirements.txt -q

echo "🖥️ 更新前端..."
cp static/index.html /usr/share/nginx/html/video/
cp -r static/avatars /usr/share/nginx/html/video/ 2>/dev/null || true
cp -r static/backgrounds /usr/share/nginx/html/video/ 2>/dev/null || true

echo "🔄 重启后端..."
bash start_backend.sh

echo "🔁 重载 Nginx..."
nginx -s reload

echo "✅ 发版完成"
