"""
Selenium + Xvfb 录制引擎（CentOS 7 兼容）
先渲染页面，暂停时间线，再开录 → 无黑屏无浏览器头
"""

import os, time, subprocess
from pathlib import Path
from rich.console import Console
from rich.progress import Progress
from config import config

console = Console()


def record_with_selenium(html_path: str, output_dir: str, duration: float) -> str:
    console.print("📹 [cyan]Selenium + Firefox 录制...[/cyan]")

    browser = _detect_browser()
    display_num = _find_free_display()

    # Xvfb
    xvfb_proc = subprocess.Popen(
        ["Xvfb", f":{display_num}", "-screen", "0", f"{config.VIDEO_WIDTH}x{config.VIDEO_HEIGHT}x24", "-ac"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    time.sleep(1)
    os.environ["DISPLAY"] = f":{display_num}"

    webm_path = os.path.join(output_dir, "recorded.webm")

    try:
        # 1. 打开页面，先渲染好
        driver = _create_driver(browser)
        driver.set_window_position(0, 0)
        driver.set_window_size(config.VIDEO_WIDTH, config.VIDEO_HEIGHT)
        abs_path = str(Path(html_path).resolve())
        driver.get(f"file:///{abs_path}")
        time.sleep(2)  # 等 CSS/粒子/初始画面渲染完

        # 2. 页面已渲染好，等 ffmpeg 就绪
        time.sleep(1)

        # 3. 开 ffmpeg 录制
        ffmpeg_proc = subprocess.Popen([
            "ffmpeg", "-f", "x11grab", "-video_size", f"{config.VIDEO_WIDTH}x{config.VIDEO_HEIGHT}",
            "-framerate", "30", "-i", f":{display_num}",
            "-c:v", "libvpx", "-crf", "10", "-b:v", "2M",
            "-pix_fmt", "yuv420p",
            "-t", str(int(duration) + 2), "-y", webm_path
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.5)

        # 4. 启动 JS 时间线
        driver.execute_script("window.__READY = true;")

        wait_ms = int((duration + 1) * 1000)
        console.print(f"   ⏱️  录制 {duration:.0f}s...")
        with Progress() as progress:
            task = progress.add_task("[cyan]录制中...", total=wait_ms // 1000)
            for _ in range(wait_ms // 1000):
                time.sleep(1)
                progress.advance(task)

        driver.quit()
        time.sleep(1)
        ffmpeg_proc.terminate()
        ffmpeg_proc.wait(timeout=10)

    finally:
        xvfb_proc.terminate()
        xvfb_proc.wait(timeout=5)

    if os.path.exists(webm_path) and os.path.getsize(webm_path) > 1000:
        console.print(f"✅ 录制完成: {webm_path}")
        return webm_path
    console.print("[red]录制失败[/red]")
    return ""


def _detect_browser():
    for p in ["/usr/bin/firefox", "/usr/bin/chromium-browser", "/usr/bin/google-chrome"]:
        if os.path.exists(p):
            return "firefox" if "firefox" in p else "chrome"
    return "firefox"


def _create_driver(browser):
    from selenium import webdriver
    if browser == "firefox":
        from selenium.webdriver.firefox.options import Options
        opts = Options()
        opts.add_argument("--kiosk")
        return webdriver.Firefox(options=opts)
    else:
        from selenium.webdriver.chrome.options import Options
        opts = Options()
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--headless=new")
        opts.add_argument("--kiosk")
        return webdriver.Chrome(options=opts)


def _find_free_display():
    for n in range(99, 110):
        if not os.path.exists(f"/tmp/.X{n}-lock"):
            return n
    return 99
