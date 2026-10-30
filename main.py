import signal
import subprocess
import sys
import time
from pathlib import Path
import requests

TIKTOK_SESSION_ID = "98c5aad3c24b45ac50a786f813f312d4"
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
    """استخراج رابط RTMP بضبط الـ Session وتخطي حماية الأمان"""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.tiktok.com/live/creator",
        "Cookie": f"sessionid={TIKTOK_SESSION_ID}; sessionid_ss={TIKTOK_SESSION_ID};"
    })

    # استخدام Endpoint البث الخاص بـ Webcast
    url = "https://webcast.tiktok.com/webcast/room/create/"
    
    params = {
        "aid": "1988",
        "app_language": "en",
        "app_name": "tiktok_web",
        "device_platform": "web",
        "mode": "3",  # Studio / OBS mode
        "title": "تلاوات قرآنية 24 ساعة",
        "enable_gift": "false",
        "enable_live_gift": "0",
        "enable_multi_guest": "true",
        "multi_guest_permission": "1"
    }

    try:
        response = session.post(url, params=params, timeout=12)
        data = response.json()

        # فحص الاستجابة
        if data.get("status_code") == 0 and "data" in data:
            rtmp_url = data["data"]["stream_url"]["rtmp_push_url"]
            log("[TIKTOK API] Successfully generated RTMP Stream URL!")
            return rtmp_url
        else:
            log(f"[TIKTOK API] Error Response: {data}")
            return None
    except Exception as e:
        log(f"[TIKTOK API] Request Exception: {e}")
        return None

def start_live_stream():
    global main_ffmpeg
    if not VIDEO_FILE.is_file():
        raise FileNotFoundError(f"Video file not found: {VIDEO_FILE}")

    while not stop_requested:
        log("[LIVE] Fetching TikTok RTMP Stream URL...")
        target = get_tiktok_rtmp_url()

        if not target:
            log("[STANDBY] Retrying to fetch RTMP URL in 15 seconds...")
            time.sleep(15)
            continue

        log("[LIVE] Connecting FFmpeg to TikTok RTMP...")

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

        if main_ffmpeg.poll() is not None:
            log("[STANDBY] FFmpeg disconnected. Retrying in 5 seconds...")
            time.sleep(5)
            continue

        log("[LIVE] Stream is LIVE on TikTok!")
        while not stop_requested:
            retcode = main_ffmpeg.poll()
            if retcode is not None:
                log(f"[WARN] Stream dropped (Code {retcode}). Reconnecting in 5 seconds...")
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
    log("=" * 55)
    log("[SYSTEM] Radio Audio + loop.mp4 -> TikTok Live (Continuous 24/7)")

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
