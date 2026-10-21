import signal
import subprocess
import sys
import time
from pathlib import Path

# إعداد سيرفر ومفتاح البث مباشرة
RESTREAM_SERVER = "rtmp://live.restream.io/live"
RESTREAM_STREAM_KEY = "re_12443993_event57fd896c7bb84afa8bc5627a989a6be1"

# الرابط المباشر الدائم لملف الصوت
RADIO_STREAM_URL = "https://n08.radiojar.com/4wqre23fytzuv"

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

def start_live_stream():
    global main_ffmpeg
    if not VIDEO_FILE.is_file():
        raise FileNotFoundError(f"Video file not found: {VIDEO_FILE}")

    target = f"{RESTREAM_SERVER.rstrip('/')}/{RESTREAM_STREAM_KEY}"

    while not stop_requested:
        log("[LIVE] Attempting connection to Restream...")

        command = [
            "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "warning",
            "-stream_loop", "-1", "-re", "-i", str(VIDEO_FILE),
            "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "10",
            "-rw_timeout", "20000000", "-i", RADIO_STREAM_URL,
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
                log(f"[WARN] FFmpeg exited with code {ret
