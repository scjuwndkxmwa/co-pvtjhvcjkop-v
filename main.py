import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# إعداد سيرفر ومفتاح البث
RESTREAM_SERVER = os.getenv("RESTREAM_SERVER", "rtmp://live.restream.io/live")
RESTREAM_STREAM_KEY = (
    os.getenv("RESTREAM_STREAM_KEY") or 
    os.getenv("YOUTUBE_STREAM_KEY") or 
    "re_12443993_event75ad3a866bd44208b87e754787eef597"
).strip()

# رابط بث يوتيوب المباشر للصوت الجديد
YOUTUBE_LIVE_URL = "https://www.youtube.com/live/eC4LfEVxvKg?si=jecdUqpsOinLHcbU"

VIDEO_FILE = Path(os.getenv("VIDEO_FILE", "loop.mp4"))
COOKIES_FILE = Path("cookies.txt")

AUDIO_BITRATE = os.getenv("AUDIO_BITRATE", "128k")
AUDIO_RATE = "44100"
AUDIO_CHANNELS = "2"

stop_requested = False
main_ffmpeg = None


def log(message):
    print(message, flush=True)


def request_stop(signum, frame):
    global stop_requested
    stop_requested = True
    log("[SYSTEM] Stop requested; shutting down...")


signal.signal(signal.SIGTERM, request_stop)
signal.signal(signal.SIGINT, request_stop)


def get_audio_stream_url(youtube_url):
    """استخراج رابط البث المباشر بأعلى مرونة ممكنة عبر خيارات متعددة"""
    log(f"[YOUTUBE] Extracting stream URL from: {youtube_url}")

    strategies = [
        # 1. yt-dlp عبر مشغلات الهواتف (بدون كوكيز لتجنب Skipping client)
        {
            "name": "yt-dlp (ios,android without cookies)",
            "cmd": [
                "yt-dlp", "-g",
                "-f", "ba/ba*/worst/best",
                "--extractor-args", "youtube:player_client=ios,android",
                "--js-runtimes", "deno,node",
                "--no-check-certificates",
                youtube_url
            ],
            "use_cookies": False
        },
        # 2. Streamlink (طلب الجودات المتاحة للبث المباشر)
        {
            "name": "streamlink (worst,360p,best)",
            "cmd": [
                "streamlink", "--stream-url",
                youtube_url,
                "worst,360p,best"
            ],
            "use_cookies": False
        },
        # 3. yt-dlp مع مشغلات الويب وتمرير الكوكيز
        {
            "name": "yt-dlp (web,mweb,tv with cookies)",
            "cmd": [
                "yt-dlp", "-g",
                "-f", "ba/ba*/worst/best",
                "--extractor-args", "youtube:player_client=web,mweb,tv",
                "--remote-components", "ejs:github",
                "--js-runtimes", "deno,node",
                "--no-check-certificates",
                youtube_url
            ],
            "use_cookies": True
        },
        # 4. yt-dlp الافتراضي بدون كوكيز
        {
            "name": "yt-dlp (default clean)",
            "cmd": [
                "yt-dlp", "-g",
                "-f", "ba/ba*/worst/best",
                "--remote-components", "ejs:github",
                "--js-runtimes", "deno,node",
                "--no-check-certificates",
                youtube_url
            ],
            "use_cookies": False
        }
    ]

    for strat in strategies:
        cmd = list(strat["cmd"])
        if strat["use_cookies"] and COOKIES_FILE.is_file() and COOKIES_FILE.stat().st_size > 0:
            cmd.extend(["--cookies", str(COOKIES_FILE)])

        log(f"[YOUTUBE] Trying strategy: {strat['name']}...")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            audio_url = result.stdout.strip().split('\n')[0]
            if audio_url and audio_url.startswith("http"):
                log(f"[YOUTUBE] Success via {strat['name']}!")
                return audio_url
        except Exception as exc:
            stderr_msg = exc.stderr.strip() if hasattr(exc, 'stderr') and exc.stderr else str(exc)
            log(f"[WARN] Strategy '{strat['name']}' failed: {stderr_msg[:150]}")

    log("[ERROR] All audio extraction strategies failed.")
    return None


def start_live_stream():
    global main_ffmpeg
    if not VIDEO_FILE.is_file():
        raise FileNotFoundError(f"Video file not found: {VIDEO_FILE}")

    target = f"{RESTREAM_SERVER.rstrip('/')}/{RESTREAM_STREAM_KEY}"

    while not stop_requested:
        log("[LIVE] Attempting connection to Restream...")
        audio_url = get_audio_stream_url(YOUTUBE_LIVE_URL)
        if not audio_url:
            log("[WARN] Retrying audio URL extraction in 10 seconds...")
            time.sleep(10)
            continue

        command = [
            "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "warning",
            "-stream_loop", "-1", "-re", "-i", str(VIDEO_FILE),
            "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "10",
            "-rw_timeout", "20000000", "-i", audio_url,
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ar", AUDIO_RATE, "-ac", AUDIO_CHANNELS,
            "-fflags", "+genpts+discardcorrupt+nobuffer+fastseek",
            "-avoid_negative_ts", "make_zero",
            "-use_wallclock_as_timestamps", "1",
            "-tune", "zerolatency",
            "-flvflags", "no_duration_filesize",
            "-f", "flv", target,
        ]

        main_ffmpeg = subprocess.Popen(command)
        time.sleep(3)

        if main_ffmpeg.poll() is not None:
            log("[STANDBY] Stream key busy. Retrying in 5 seconds...")
            time.sleep(5)
            continue

        log("[LIVE] Stream connected successfully and live!")
        while not stop_requested:
            retcode = main_ffmpeg.poll()
            if retcode is not None:
                log(f"[WARN] FFmpeg exited with code {retcode}. Reconnecting in 5 seconds...")
                time.sleep(5)
                break
            time.sleep(3)


def cleanup():
    global main_ffmpeg
    if main_ffmpeg and main_ffmpeg.poll() is None:
        main_ffmpeg.terminate()
        try:
            main_ffmpeg.wait(timeout=5)
        except subprocess.TimeoutExpired:
            main_ffmpeg.kill()
    log("[SYSTEM] Stream runner stopped.")


def main():
    if not RESTREAM_STREAM_KEY:
        raise RuntimeError("RESTREAM_STREAM_KEY is empty.")
    log("=" * 55)
    log("[SYSTEM] YouTube Live Audio + loop.mp4 -> Restream (Continuous 24/7)")
    
    try:
        start_live_stream()
    finally:
        cleanup()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"[FATAL] {exc}")
        sys.exit(1)
