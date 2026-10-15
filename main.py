import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

# إعداد سيرفر ومفتاح البث الخاص بـ Restream
RESTREAM_SERVER = os.getenv("RESTREAM_SERVER", "rtmp://live.restream.io/live")
RESTREAM_STREAM_KEY = os.getenv(
    "RESTREAM_STREAM_KEY",
    "re_12443993_event75ad3a866bd44208b87e754787eef597",
).strip()

VIDEO_FILE = Path(os.getenv("VIDEO_FILE", "loop.mp4"))
LINKS_FILE = Path(os.getenv("LINKS_FILE", "surah_links.txt"))

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


def load_surahs():
    if not LINKS_FILE.is_file():
        raise FileNotFoundError(f"Missing {LINKS_FILE}; add surah_links.txt to the repository.")
    text = LINKS_FILE.read_text(encoding="utf-8")
    found = re.findall(r"(?m)^\s*\d+\.\s*(.*?)\s*\n(https?://\S+)", text)
    if not found:
        raise RuntimeError("No audio URLs found in surah_links.txt")
    log(f"[PLAYLIST] Loaded {len(found)} audio URLs.")
    return found


def start_live_ffmpeg():
    global main_ffmpeg
    if not VIDEO_FILE.is_file():
        raise FileNotFoundError(f"Video not found: {VIDEO_FILE}. Add loop.mp4 to the repository root.")
    
    target = f"{RESTREAM_SERVER.rstrip('/')}/{RESTREAM_STREAM_KEY}"
    command = [
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "warning",
        "-stream_loop", "-1", "-re", "-i", str(VIDEO_FILE),
        "-thread_queue_size", "1024",
        "-f", "s16le", "-ar", AUDIO_RATE, "-ac", AUDIO_CHANNELS, "-i", "pipe:0",
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
    log("[LIVE] Starting FFmpeg -> Restream (loop.mp4 repeating continuously)...")
    main_ffmpeg = subprocess.Popen(command, stdin=subprocess.PIPE)
    time.sleep(2)
    if main_ffmpeg.poll() is not None:
        raise RuntimeError(f"Main FFmpeg exited with code {main_ffmpeg.returncode}")


def stream_surah(name, url, number, total):
    if stop_requested or main_ffmpeg is None or main_ffmpeg.poll() is not None:
        return False
    log(f"[AUDIO] {number}/{total}: {name}")
    command = [
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "warning", "-re",
        "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "10",
        "-rw_timeout", "20000000", "-i", url, "-vn", "-sn", "-dn",
        "-ac", AUDIO_CHANNELS, "-ar", AUDIO_RATE, "-c:a", "pcm_s16le",
        "-f", "s16le", "pipe:1",
    ]
    audio_proc = None
    bytes_sent = 0
    try:
        audio_proc = subprocess.Popen(command, stdout=subprocess.PIPE)
        while not stop_requested:
            chunk = audio_proc.stdout.read(64 * 1024)
            if not chunk:
                break
            if main_ffmpeg.poll() is not None:
                log(f"[ERROR] Main FFmpeg stopped: {main_ffmpeg.returncode}")
                return False
            try:
                main_ffmpeg.stdin.write(chunk)
                main_ffmpeg.stdin.flush()
                bytes_sent += len(chunk)
            except (BrokenPipeError, OSError) as exc:
                log(f"[ERROR] Audio pipe failed: {exc}")
                return False
        try:
            code = audio_proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            audio_proc.terminate()
            code = audio_proc.wait(timeout=5)
        if bytes_sent == 0 or code != 0:
            log(f"[WARN] Audio source failed/no data (exit={code}, bytes={bytes_sent}); skipping.")
        else:
            log(f"[AUDIO] Finished {name}; streamed {bytes_sent:,} bytes.")
        return True
    except Exception as exc:
        log(f"[WARN] Could not play {name}: {exc}; skipping.")
        return True
    finally:
        if audio_proc is not None and audio_proc.poll() is None:
            audio_proc.terminate()
            try:
                audio_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                audio_proc.kill()
        if audio_proc is not None and audio_proc.stdout:
            audio_proc.stdout.close()


def cleanup():
    global main_ffmpeg
    if main_ffmpeg is None:
        return
    try:
        if main_ffmpeg.stdin and not main_ffmpeg.stdin.closed:
            main_ffmpeg.stdin.close()
    except Exception:
        pass
    if main_ffmpeg.poll() is None:
        try:
            main_ffmpeg.wait(timeout=15)
        except subprocess.TimeoutExpired:
            main_ffmpeg.terminate()
            try:
                main_ffmpeg.wait(timeout=5)
            except subprocess.TimeoutExpired:
                main_ffmpeg.kill()
                main_ffmpeg.wait()
    log("[SYSTEM] Relay stopped.")


def main():
    if not RESTREAM_STREAM_KEY:
        raise RuntimeError("RESTREAM_STREAM_KEY is empty.")
    surahs = load_surahs()
    log("=" * 55)
    log("[SYSTEM] Quran MP3 URLs -> loop.mp4 -> Restream (Continuous Loop)")
    
    start_live_ffmpeg()
    try:
        while not stop_requested and main_ffmpeg.poll() is None:
            for number, (name, url) in enumerate(surahs, start=1):
                if stop_requested or main_ffmpeg.poll() is not None:
                    break
                success = stream_surah(name, url, number, len(surahs))
                if not success:
                    break
            if not stop_requested and main_ffmpeg.poll() is None:
                log("[PLAYLIST] Finished all surahs; restarting from Al-Fatiha...")
    finally:
        cleanup()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"[FATAL] {exc}")
        sys.exit(1)
