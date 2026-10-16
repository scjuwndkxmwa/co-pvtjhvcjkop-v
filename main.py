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

# رابط بث يوتيوب المباشر للصوت
YOUTUBE_LIVE_URL = "https://www.youtube.com/watch?v=IRvOLSvFI6Y"

VIDEO_FILE = Path(os.getenv("VIDEO_FILE", "loop.mp4"))
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
    """استخراج رابط الصوت المباشر باستخدام yt-dlp مع التجاوز"""
    log(f"[YOUTUBE] Extracting audio stream URL from: {youtube_url}")
    cmd = [
        "yt-dlp",
        "-g",
        "-f", "ba*/b",
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "--extractor-args", "youtube:player_client=android,web",
        "--no-check-certificates",
        youtube_url
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        audio_url = result.stdout.strip().split('\n')[0]
        if audio_url:
            log("[YOUTUBE] Audio URL extracted successfully.")
            return audio_url
    except Exception as exc:
        log(f"[ERROR] Failed to extract audio URL via yt-dlp: {exc}")
        if hasattr(exc, 'stderr') and exc.stderr:
            log(f"[YOUTUBE STDERR] {exc.stderr.strip()}")
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
