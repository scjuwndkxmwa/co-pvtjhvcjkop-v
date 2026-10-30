import signal
import subprocess
import sys
import time
from pathlib import Path
import requests

# TikTok Session ID
TIKTOK_SESSION_ID = "98c5aad3c24b45ac50a786f813f312d4"

# الرابط المباشر الدائم لملف الصوت
RADIO_STREAM_URL = "https://qurango.net/radio/yasser_aldosari"

VIDEO_FILE = Path("loop.mp4")

AUDIO_BITRATE = "128k"
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


def get_tiktok_rtmp_url():
    """استخرج رابط البث RTMP من تيك توك باستخدام Session ID"""
    url = "https://www.tiktok.com/api/live/web/room/create/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Cookie": f"sessionid={TIKTOK_SESSION_ID};",
    }
    params = {
        "title": "تلاوات قرآنية 24 ساعة",
        "mode": "3",  # mode 3 مخصص للبث عبر برامج OBS / RTMP
    }

    try:
        response = requests.post(url, headers=headers, params=params, timeout=10)
        data = response.json()

        # استخراج رابط البث المباشر
        rtmp_url = data.get("data", {}).get("stream_url", {}).get("rtmp_push_url")
        if rtmp_url:
            log("[TIKTOK API] Successfully fetched TikTok RTMP Stream URL!")
            return rtmp_url
        else:
            log(f"[TIKTOK API] Failed to fetch stream URL. Response: {data}")
            return None
    except Exception as e:
        log(f"[TIKTOK API] Error connecting to TikTok API: {e}")
        return None


def start_live_stream():
    global main_ffmpeg
    if not VIDEO_FILE.is_file():
        raise FileNotFoundError(f"Video file not found: {VIDEO_FILE}")

    while not stop_requested:
        log("[LIVE] Fetching new TikTok Stream RTMP URL...")
        target = get_tiktok_rtmp_url()

        if not target:
            log("[STANDBY] Could not get TikTok RTMP URL. Retrying in 10 seconds...")
            time.sleep(10)
            continue

        log("[LIVE] Attempting connection to TikTok Live...")

        command = [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "warning",
            "-stream_loop",
            "-1",
            "-re",
            "-i",
            str(VIDEO_FILE),
            "-reconnect",
            "1",
            "-reconnect_streamed",
            "1",
            "-reconnect_delay_max",
            "10",
            "-rw_timeout",
            "20000000",
            "-i",
            RADIO_STREAM_URL,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            AUDIO_BITRATE,
            "-ar",
            AUDIO_RATE,
            "-ac",
            AUDIO_CHANNELS,
            "-fflags",
            "+genpts+discardcorrupt+nobuffer+fastseek",
            "-avoid_negative_ts",
            "make_zero",
            "-use_wallclock_as_timestamps",
            "1",
            "-tune",
            "zerolatency",
            "-flvflags",
            "no_duration_filesize",
            "-f",
            "flv",
            target,
        ]

        main_ffmpeg = subprocess.Popen(command)
        time.sleep(3)

        if main_ffmpeg.poll() is not None
