"""Selenium + Firefox 录制引擎。

Linux 使用 Xvfb + x11grab，Windows 使用 Firefox 无头截图帧录制。
两端共用 Firefox 渲染器和 Selenium 时间线启动逻辑。
"""

import os, time, subprocess
from pathlib import Path
from rich.console import Console
from rich.progress import Progress
from config import config

console = Console()


def _stop_recording_process(process: subprocess.Popen | None, label: str, timeout: int = 10):
    """Stop ffmpeg reliably so a slow X11 teardown does not fail the task."""
    if not process or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        console.print(f"[yellow]{label} 未在 {timeout}s 内退出，正在强制结束...[/yellow]")
        process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            console.print(f"[yellow]{label} 强制结束后仍未退出，将继续检查已生成的视频文件[/yellow]")


def _log_server_progress(current: int, total: int, label: str):
    """非交互日志环境无法渲染动态进度条，定期输出普通日志。"""
    if console.is_terminal or total <= 0:
        return
    interval = max(1, min(10, total // 10))
    if current == 1 or current == total or current % interval == 0:
        percent = min(100, round(current / total * 100))
        console.print(f"   {label}: {current}/{total} ({percent}%)")


def record_with_selenium(html_path: str, output_dir: str, duration: float) -> str:
    console.print("📹 [cyan]Selenium + Firefox 录制...[/cyan]")
    if os.name == "nt":
        return _record_with_screenshots(html_path, output_dir, duration)
    return _record_with_x11(html_path, output_dir, duration)


def _record_with_x11(html_path: str, output_dir: str, duration: float) -> str:
    if not _command_exists("Xvfb"):
        raise RuntimeError("Selenium Firefox 服务器录制需要安装 Xvfb")
    display_num = _find_free_display()
    xvfb_proc = subprocess.Popen(
        ["Xvfb", f":{display_num}", "-screen", "0", f"{config.VIDEO_WIDTH}x{config.VIDEO_HEIGHT}x24", "-ac"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    time.sleep(1)
    os.environ["DISPLAY"] = f":{display_num}"

    # libvpx is too slow for 1080x1920 X11 capture on the server.  H.264 with
    # the ultrafast preset keeps up in real time and can be passed directly to
    # the existing ffmpeg audio muxing step.
    video_path = os.path.join(output_dir, "recorded.mp4")
    driver = None
    ffmpeg_proc = None

    try:
        driver = _create_firefox_driver(headless=False)
        driver.set_window_position(0, 0)
        driver.set_window_size(config.VIDEO_WIDTH, config.VIDEO_HEIGHT)
        abs_path = str(Path(html_path).resolve())
        driver.get(f"file:///{abs_path}")
        time.sleep(2)  # 等 CSS/粒子/初始画面渲染完

        # 2. 页面已渲染好，等 ffmpeg 就绪
        time.sleep(1)

        # 3. 开 ffmpeg 录制
        recording_seconds = max(1, int(duration) + 2)
        ffmpeg_proc = subprocess.Popen([
            "ffmpeg", "-nostdin", "-f", "x11grab", "-video_size", f"{config.VIDEO_WIDTH}x{config.VIDEO_HEIGHT}",
            "-framerate", "30", "-i", f":{display_num}",
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-crf", "28",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", "-t", str(recording_seconds), "-y", video_path
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # 4. 录屏启动后立即启动 JS 时间线，避免页面切换与最终音频产生固定偏移。
        driver.execute_script(
            "window.__READY = true;"
            "if (typeof startTimeline === 'function') startTimeline();"
        )

        wait_ms = int(duration * 1000)
        console.print(f"   ⏱️  录制 {duration:.0f}s...")
        with Progress() as progress:
            task = progress.add_task("[cyan]录制中...", total=wait_ms // 1000)
            for current in range(1, wait_ms // 1000 + 1):
                time.sleep(1)
                progress.advance(task)
                _log_server_progress(current, wait_ms // 1000, "录制进度")

        # 等待 ffmpeg 录满设定时长并正常写完 MP4 尾部；提前终止会产生无法解码的零字节文件。
        ffmpeg_proc.wait(timeout=max(30, recording_seconds + 15))
        ffmpeg_proc = None
        driver.quit()
        driver = None

    finally:
        if ffmpeg_proc and ffmpeg_proc.poll() is None:
            _stop_recording_process(ffmpeg_proc, "ffmpeg 录制进程")
        if driver:
            driver.quit()
        xvfb_proc.terminate()
        xvfb_proc.wait(timeout=5)

    if os.path.exists(video_path) and os.path.getsize(video_path) > 1000:
        console.print(f"✅ 录制完成: {video_path}")
        return video_path
    console.print("[red]录制失败[/red]")
    return ""


def _record_with_screenshots(html_path: str, output_dir: str, duration: float) -> str:
    """Windows 使用 Firefox 无头截图流录制，保持与服务器相同的渲染器。
    
    自动检测视频类型：
    - 口播模式：使用确定性逐页渲染（wave_frames）
    - 科普/图文模式：启动 JS 时间线，按帧率连续截图
    """
    webm_path = os.path.join(output_dir, "recorded.webm")
    fps = config.VIDEO_FPS
    driver = _create_firefox_driver(headless=True)
    ffmpeg_proc = None
    try:
        _set_viewport_size(driver, config.VIDEO_WIDTH, config.VIDEO_HEIGHT)
        driver.get(Path(html_path).resolve().as_uri())
        time.sleep(2)

        ffmpeg_proc = subprocess.Popen([
            "ffmpeg", "-f", "image2pipe", "-vcodec", "png",
            "-framerate", str(fps), "-i", "-",
            "-c:v", "libvpx", "-crf", "10", "-b:v", "2M",
            "-pix_fmt", "yuv420p", "-y", webm_path
        ], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # 检测视频类型
        video_type = driver.execute_script(
            "if (window.__timelineData && window.__timelineData.length) return 'narration';"
            "if (window.scenesData && window.scenesData.length) return 'gallery';"
            "if (window.scenes && window.scenes.length) return 'science';"
            "return 'unknown';"
        )
        console.print(f"   [dim]检测到视频类型: {video_type}[/dim]")

        if video_type == "narration":
            _record_narration_frames(driver, ffmpeg_proc, fps, duration, webm_path)
        else:
            # 科普/图文模式：启动时间线 + 连续截图
            _record_timeline_frames(driver, ffmpeg_proc, fps, duration)

        ffmpeg_proc.stdin.close()
        ffmpeg_proc.wait(timeout=max(30, int(duration)))
        ffmpeg_proc = None
    finally:
        driver.quit()
        if ffmpeg_proc and ffmpeg_proc.poll() is None:
            _stop_recording_process(ffmpeg_proc, "ffmpeg 录制进程")

    if os.path.exists(webm_path) and os.path.getsize(webm_path) > 1000:
        console.print(f"✅ 录制完成: {webm_path}")
        return webm_path
    console.print("[red]录制失败[/red]")
    return ""


def _record_timeline_frames(driver, ffmpeg_proc, fps: int, duration: float):
    """科普/图文模式：按帧确定性渲染，避免浏览器实时动画掉帧导致音画错位。"""
    total_frames = int(duration * fps)
    has_render_at = bool(driver.execute_script("return typeof window.__renderAt === 'function';"))
    if not has_render_at:
        driver.execute_script("window.__READY = true;")
    
    with Progress() as progress:
        task = progress.add_task("[cyan]录制中...", total=total_frames)
        frame_interval = 1.0 / fps
        for i in range(total_frames):
            start_tick = time.perf_counter()
            if has_render_at:
                driver.execute_script("window.__renderAt(arguments[0]);", i / fps)
            png = driver.get_screenshot_as_png()
            ffmpeg_proc.stdin.write(png)
            elapsed = time.perf_counter() - start_tick
            sleep_time = 0 if has_render_at else frame_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
            progress.advance(task)
            _log_server_progress(i + 1, total_frames, "录制帧")


def _record_narration_frames(driver, ffmpeg_proc, fps: int, duration: float, webm_path: str):
    """口播模式：确定性逐页渲染（保留原有逻辑）"""
    timeline = driver.execute_script(
        "return {"
        "data: window.__timelineData || [],"
        "total: window.__timelineTotal || 0,"
        "delay: window.__visualSwitchDelay || 0"
        "};"
    )
    driver.execute_script(
        "if (typeof window.__stopTimeline === 'function') window.__stopTimeline();"
        "window.__READY=false;"
    )
    record_duration = duration
    total_frames = max(1, int(record_duration * fps))
    written_frames = 0

    data = timeline.get("data") or []
    delay = float(timeline.get("delay") or 0)
    starts = [0.0]
    elapsed = 0.0
    for item in data[:-1]:
        elapsed += float(item.get("duration") or 0)
        starts.append(elapsed + delay)
    starts.append(record_duration)

    with Progress() as progress:
        task = progress.add_task("[cyan]录制中...", total=max(1, len(data)))
        for idx in range(max(1, len(data))):
            rendered_text = driver.execute_script(
                "if (typeof window.__renderSentence === 'function') "
                "return window.__renderSentence(arguments[0]);"
                "const el=document.getElementById('sentence');"
                "if(!el)return '';"
                "el.style.animation='none';"
                "el.style.opacity='1';"
                "el.style.transform='none';"
                "if(typeof window.__setSentenceText === 'function') "
                "window.__setSentenceText(arguments[1]);"
                "else el.textContent=arguments[1];"
                "window._curScene=arguments[0];"
                "return typeof window.__getSentenceText === 'function' "
                "? window.__getSentenceText() : el.textContent;",
                idx, str(data[idx].get("text") or "") if idx < len(data) else "",
            )
            expected_text = str(data[idx].get("text") or "") if idx < len(data) else ""
            if rendered_text != expected_text:
                raise RuntimeError(
                    f"第 {idx + 1} 页渲染校验失败：期望 {expected_text!r}，实际 {rendered_text!r}"
                )
            driver.execute_async_script(
                "const done=arguments[arguments.length-1];"
                "requestAnimationFrame(()=>requestAnimationFrame(done));"
            )
            wave_frames = []
            for phase_idx in range(6):
                driver.execute_script(
                    "const el=document.getElementById('sentence');"
                    "if(typeof window.__setSentenceText === 'function') "
                    "window.__setSentenceText(arguments[1]);"
                    "else if(el)el.textContent=arguments[1];"
                    "if (typeof window.__renderWave === 'function') "
                    "window.__renderWave(arguments[0]);",
                    phase_idx * 0.9, expected_text,
                )
                driver.execute_async_script(
                    "const done=arguments[arguments.length-1];"
                    "requestAnimationFrame(()=>requestAnimationFrame(done));"
                )
                phase_png = driver.get_screenshot_as_png()
                phase_text = driver.execute_script(
                    "return typeof window.__getSentenceText === 'function' "
                    "? window.__getSentenceText() "
                    ": (document.getElementById('sentence')||{}).textContent||'';"
                )
                if phase_text != expected_text:
                    raise RuntimeError(
                        f"第 {idx + 1} 页音波帧正文闪回：期望 {expected_text!r}，实际 {phase_text!r}"
                    )
                wave_frames.append(phase_png)
            target_frames = total_frames if idx == len(data) - 1 else min(
                total_frames, int(starts[idx + 1] * fps)
            )
            page_frame = 0
            frames_per_wave_phase = max(1, fps // 6)
            while written_frames < target_frames:
                wave_idx = (page_frame // frames_per_wave_phase) % len(wave_frames)
                ffmpeg_proc.stdin.write(wave_frames[wave_idx])
                written_frames += 1
                page_frame += 1
            progress.advance(task)
            _log_server_progress(idx + 1, max(1, len(data)), "页面渲染进度")


def _create_firefox_driver(headless: bool):
    from selenium import webdriver
    from selenium.webdriver.firefox.options import Options
    from selenium.webdriver.firefox.service import Service

    opts = Options()
    if headless:
        opts.add_argument("-headless")
    else:
        opts.add_argument("--kiosk")
    firefox_binary = _find_firefox_binary()
    if firefox_binary:
        opts.binary_location = firefox_binary
    # Firefox renders local HTML during recording and must not inherit a stale
    # system proxy from the desktop environment.
    opts.set_preference("network.proxy.type", 0)
    geckodriver = _find_geckodriver()
    proxy_keys = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
    saved_proxies = {key: os.environ.pop(key) for key in proxy_keys if key in os.environ}
    try:
        service = Service(executable_path=geckodriver) if geckodriver else Service()
        return webdriver.Firefox(options=opts, service=service)
    except Exception as exc:
        detail = f" Firefox: {firefox_binary or '未找到'}；geckodriver: {geckodriver or '未找到'}。"
        raise RuntimeError(
            "无法启动 Firefox Selenium。" + detail + f" 原因: {exc}"
        ) from exc
    finally:
        os.environ.update(saved_proxies)


def _find_firefox_binary() -> str:
    candidates = []
    if os.name == "nt":
        candidates.extend(_find_firefox_from_registry())
        candidates.extend([
            os.path.join(os.environ.get("PROGRAMFILES", ""), "Mozilla Firefox", "firefox.exe"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Mozilla Firefox", "firefox.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Mozilla Firefox", "firefox.exe"),
        ])
    else:
        candidates.extend(["/usr/bin/firefox", "/usr/local/bin/firefox"])
    return next((p for p in candidates if p and os.path.exists(p)), "")


def _find_firefox_from_registry() -> list[str]:
    """读取 Windows App Paths，兼容 Firefox 安装在非系统盘的情况。"""
    if os.name != "nt":
        return []
    import winreg

    paths = []
    key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\firefox.exe"
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for access in (winreg.KEY_READ, winreg.KEY_READ | winreg.KEY_WOW64_32KEY, winreg.KEY_READ | winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(root, key_path, 0, access) as key:
                    value, _ = winreg.QueryValueEx(key, None)
                    if value:
                        paths.append(value)
            except OSError:
                pass
    return paths


def _find_geckodriver() -> str:
    """优先使用显式配置和项目内驱动，避免 Selenium Manager 联网下载。"""
    import shutil

    configured = config.GECKODRIVER_PATH.strip()
    driver_name = "geckodriver.exe" if os.name == "nt" else "geckodriver"
    candidates = [
        str(Path(configured).resolve()) if configured else "",
        str((Path(__file__).resolve().parent.parent / "tools" / driver_name).resolve()),
        shutil.which("geckodriver") or "",
    ]
    for candidate in candidates:
        if not candidate or not os.path.isfile(candidate):
            continue
        if os.name != "nt":
            if candidate.lower().endswith(".exe") or not os.access(candidate, os.X_OK):
                continue
        return candidate
    return ""


def _set_viewport_size(driver, width: int, height: int):
    driver.set_window_size(width, height)
    viewport = driver.execute_script("return [window.innerWidth, window.innerHeight];")
    driver.set_window_size(width + (width - viewport[0]), height + (height - viewport[1]))


def _command_exists(command: str) -> bool:
    import shutil
    return shutil.which(command) is not None


def _find_free_display():
    for n in range(99, 110):
        if not os.path.exists(f"/tmp/.X{n}-lock"):
            return n
    return 99
