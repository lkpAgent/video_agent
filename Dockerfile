FROM python:3.11-slim

# 国内镜像加速
RUN sed -i 's|http://deb.debian.org|http://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|http://deb.debian.org|http://mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null || true

# 先装编译工具链和 ffmpeg
RUN apt-get update -o Acquire::http::Timeout=30 && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    ffmpeg wget ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
RUN pip install --no-cache-dir playwright \
    -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com

# 装 Chromium
RUN PLAYWRIGHT_DOWNLOAD_HOST=https://playwright.azureedge.net \
    playwright install --with-deps chromium

COPY . .

EXPOSE 8888
CMD ["python", "web_server.py"]
