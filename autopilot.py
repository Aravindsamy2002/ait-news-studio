"""
AIT News 24/7 autopilot: live feeds -> render queue -> rotating playlist -> YouTube Live.

The stream never waits for rendering:
  * a scheduler refreshes the feeds and decides which stories belong on air;
  * a pool of worker processes renders missing clips in the background (one clip per
    story version, cached on disk, never re-rendered unless the story changes or stops
    being "breaking");
  * one long-lived FFmpeg pushes to YouTube with -c copy (no re-encoding), fed clip by
    clip from the current rotation, so new stories join without the stream dropping.
    When nothing is ready yet, a branded standby slate plays.

Usage:
  python autopilot.py                              # stream to YouTube (YOUTUBE_STREAM_KEY)
  python autopilot.py --output test.flv --minutes 5  # local dry run into a file
  python autopilot.py --render-only                # just keep the clip library up to date
"""
import argparse
import hashlib
import json
import multiprocessing
import os
import shutil
import subprocess
import threading
import time
from concurrent.futures import ProcessPoolExecutor

import imageio_ffmpeg
from PIL import Image, ImageDraw

from config import (
    CLIP_RETENTION_HOURS, CLIPS_DIR, DEFAULT_STREAM_KEY, DEFAULT_VOICE, NEWS_REFRESH_MINUTES, OUTPUT_DIR,
    RENDER_WORKERS, ROTATION_SIZE, VIDEO_HEIGHT, VIDEO_WIDTH, YOUTUBE_RTMP_URL,
)

RENDER_VERSION = "7"          # bump to force every clip to re-render after a design change
STANDBY_CLIP = os.path.join(CLIPS_DIR, "standby.mp4")
SCHEDULE_SECONDS = 60
os.makedirs(CLIPS_DIR, exist_ok=True)


def log(msg: str):
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


def ffmpeg_exe() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def clip_duration(path: str) -> float:
    from voice_engine import get_audio_duration
    return get_audio_duration(path)


# ------------------------------------------------------------------ rendering (worker processes)

def _lowest_priority():
    """Render workers yield the CPU to everything else (the live stream, other services on the VM)."""
    if hasattr(os, "nice"):
        os.nice(19)


def clip_path_for(story: dict, voice_key: str) -> str:
    """One file per story *version*: a change of wording, breaking status or voice is a new clip."""
    fingerprint = json.dumps([
        RENDER_VERSION, voice_key, story["title"], story["bullets"], story["is_breaking"],
    ], ensure_ascii=False)
    digest = hashlib.sha1(fingerprint.encode()).hexdigest()[:10]
    return os.path.join(CLIPS_DIR, f"{story['id']}__{digest}.mp4")


def render_clip(story: dict, ticker: str, out_path: str, voice_key: str) -> str:
    """Runs in a worker process: analysis -> voice -> motion graphics -> atomic move into the library.

    The voice track and phase timings are kept next to the clip so the vertical Short can be
    rendered later from the exact same narration, only for stories that actually get uploaded.
    """
    from analysis import with_analysis
    from motion_renderer import render_animated_story, story_phase_count
    from script_writer import with_engaging_script
    from renderer import compute_phase_durations
    from voice_engine import generate_segmented_speech

    s = with_engaging_script(with_analysis(story))      # checked Gemini lines; verbatim on any doubt
    audio_name = f"clip_audio_{s['id']}.mp3"
    audio_path, duration, timings = generate_segmented_speech(s["narration_segments"], audio_name, voice_key=voice_key)
    n_phases = story_phase_count(s)
    phase_durations = compute_phase_durations(duration, timings[:n_phases], n_phases)
    tmp_path = out_path.replace(".mp4", ".part.mp4")
    kept_audio = out_path.replace(".mp4", ".mp3")
    try:
        render_animated_story(s, audio_path, duration, ticker, tmp_path, phase_durations)
        os.replace(tmp_path, out_path)
        os.replace(audio_path, kept_audio)
        with open(out_path.replace(".mp4", ".json"), "w", encoding="utf-8") as f:
            json.dump({
                "id": s["id"], "title": s["title"], "outlet": s.get("outlet", ""),
                "published_ts": s.get("published_ts", ""), "is_breaking": s.get("is_breaking", False),
                "has_analysis": bool(s.get("analysis")), "rendered_at": time.time(),
                "audio": kept_audio, "phase_durations": phase_durations, "story": s,
            }, f, indent=2, ensure_ascii=False)
    finally:
        for p in (audio_path, tmp_path):
            if os.path.exists(p):
                os.remove(p)
    return out_path


def ensure_standby_clip():
    """A plain branded slate (no news content) shown only until the first story clip is ready."""
    if os.path.exists(STANDBY_CLIP):
        return
    from assets_builder import ensure_news_bed
    from motion_renderer import NAVY, RED, STREAM_ENCODE_ARGS, WHITE, YELLOW, cond, heavy

    img = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), NAVY)
    d = ImageDraw.Draw(img)
    cx, cy = VIDEO_WIDTH // 2, VIDEO_HEIGHT // 2
    d.rectangle([cx - 230, cy - 170, cx + 230, cy + 60], fill=RED)
    d.text((cx, cy - 60), "AIT", font=heavy(170), fill=WHITE, anchor="mm")
    d.rectangle([cx - 230, cy + 60, cx + 230, cy + 130], fill=WHITE)
    d.text((cx, cy + 95), "NEWS", font=cond(60), fill=RED, anchor="mm")
    d.text((cx, cy + 230), "TOP TECHNOLOGY STORIES  •  STAY TUNED", font=cond(44), fill=YELLOW, anchor="mm")
    slate = os.path.join(CLIPS_DIR, "standby.png")
    img.save(slate)
    subprocess.run([
        ffmpeg_exe(), "-y", "-loglevel", "error",
        "-loop", "1", "-i", slate, "-stream_loop", "-1", "-i", ensure_news_bed(),
        "-t", "8", "-af", "volume=0.5", *STREAM_ENCODE_ARGS, STANDBY_CLIP,
    ], check=True)
    os.remove(slate)


# ------------------------------------------------------------------ scheduler

class Scheduler:
    """Keeps the on-air rotation in sync with the live feeds and queues missing clips."""

    def __init__(self, workers: int, voice_key: str, publisher=None):
        # "spawn", not fork: forked workers would inherit the live stream's pipes and keep them open
        self.pool = ProcessPoolExecutor(max_workers=workers, initializer=_lowest_priority,
                                        mp_context=multiprocessing.get_context("spawn"))
        self.voice_key = voice_key
        self.publisher = publisher   # YouTube uploads + live title (optional)
        self.story_for = {}          # clip path -> story, for uploading once the clip is ready
        self.pending = {}            # clip path -> future
        self.failures = {}           # clip path -> failure count
        self.rotation = []           # ready clip paths, in on-air order
        self.wanted = set()
        self.lock = threading.Lock()
        self.last_fetch = 0.0
        self.stories = []

    def tick(self):
        from fetcher import build_ticker_string, fetch_all_news, prepare_story

        if not self.stories or time.time() - self.last_fetch > NEWS_REFRESH_MINUTES * 60:
            try:
                self.stories = fetch_all_news()
                log(f"Feeds refreshed: {len(self.stories)} fresh stories")
            except Exception as e:
                log(f"Feed refresh failed, keeping previous stories: {e}")
            self.last_fetch = time.time()

        # Re-prepare every tick so "breaking" status expires on time
        candidates = [prepare_story(s) for s in self.stories]
        candidates = [s for s in candidates if s.get("article_images")]   # never air a story without its real picture
        candidates.sort(key=lambda s: s.get("published_ts", ""), reverse=True)
        # Breaking stories lead the rotation, then everything else newest first
        on_air = ([s for s in candidates if s["is_breaking"]] +
                  [s for s in candidates if not s["is_breaking"]])[:ROTATION_SIZE]
        ticker = build_ticker_string(self.stories)
        if self.publisher and on_air:
            self.publisher.submit_headline(on_air[0]["title"])

        ready, wanted = [], set()
        for s in on_air:
            path = clip_path_for(s, self.voice_key)
            wanted.add(path)
            if os.path.exists(path):
                ready.append(path)
            elif path not in self.pending and self.failures.get(path, 0) < 2:
                self.pending[path] = self.pool.submit(render_clip, s, ticker, path, self.voice_key)
                self.story_for[path] = s
                log(f"Queued render: {s['title'][:70]}")

        for path, fut in list(self.pending.items()):
            if fut.done():
                del self.pending[path]
                story = self.story_for.pop(path, None)
                if fut.exception():
                    self.failures[path] = self.failures.get(path, 0) + 1
                    log(f"Render failed ({os.path.basename(path)}): {fut.exception()}")
                else:
                    log(f"Clip ready: {os.path.basename(path)}")
                    if self.publisher and story:
                        self.publisher.submit_story(path, story)

        with self.lock:
            self.rotation = ready
            self.wanted = wanted
        self._cleanup(wanted)

    def _cleanup(self, wanted: set):
        """Delete clips older than CLIP_RETENTION_HOURS that are off air (the daily bulletin reuses the day's clips)."""
        for name in os.listdir(CLIPS_DIR):
            path = os.path.join(CLIPS_DIR, name)
            if (not name.endswith(".mp4") or name.endswith("_short.mp4") or path == STANDBY_CLIP
                    or path in wanted or ".part" in name):
                continue
            if time.time() - os.path.getmtime(path) > CLIP_RETENTION_HOURS * 3600:
                for p in (path, path.replace(".mp4", ".json"), path.replace(".mp4", ".mp3"),
                          path.replace(".mp4", "_short.mp4")):
                    if os.path.exists(p):
                        os.remove(p)

    def current_rotation(self) -> list[str]:
        with self.lock:
            return list(self.rotation)

    def run_forever(self, stop: threading.Event):
        while not stop.is_set():
            try:
                self.tick()
            except Exception as e:
                log(f"Scheduler error: {e}")
            stop.wait(SCHEDULE_SECONDS)

    def shutdown(self):
        """Stop at once: unfinished renders are dropped (their .part files are cleaned on next start)."""
        processes = list((getattr(self.pool, "_processes", None) or {}).values())
        self.pool.shutdown(wait=False, cancel_futures=True)
        for p in processes:
            if p.is_alive():
                p.terminate()
        for name in os.listdir(CLIPS_DIR):
            if ".part" in name:
                try:
                    os.remove(os.path.join(CLIPS_DIR, name))
                except OSError:
                    pass


# ------------------------------------------------------------------ streamer

class ContinuousStreamer:
    """One persistent FFmpeg to the target; clips are spliced in as MPEG-TS with continuous timestamps."""

    def __init__(self, target: str, scheduler: Scheduler):
        self.target = target
        self.scheduler = scheduler
        self.proc = None
        self.offset = 0.0
        self.last = None

    def _start(self):
        fmt = ["-f", "flv"] if self.target.startswith("rtmp") or self.target.endswith(".flv") else []
        self.proc = subprocess.Popen([
            ffmpeg_exe(), "-hide_banner", "-loglevel", "warning",
            "-re", "-f", "mpegts", "-i", "-",
            "-c", "copy", "-bsf:a", "aac_adtstoasc", *fmt, self.target,
        ], stdin=subprocess.PIPE)
        self.offset = 0.0
        log("Stream encoder started (copy mode, no re-encode)")

    def _next_clip(self) -> str:
        """The clip after the one just aired, so new arrivals never cause a repeat."""
        rotation = [p for p in self.scheduler.current_rotation() if os.path.exists(p)]
        if not rotation:
            return STANDBY_CLIP
        if self.last in rotation:
            clip = rotation[(rotation.index(self.last) + 1) % len(rotation)]
        else:
            clip = rotation[0]
        self.last = clip
        return clip

    def _feed(self, clip: str):
        dur = clip_duration(clip)
        remux = subprocess.Popen([
            ffmpeg_exe(), "-loglevel", "error", "-i", clip,
            "-c", "copy", "-bsf:v", "h264_mp4toannexb",
            "-muxdelay", "0", "-muxpreload", "0", "-output_ts_offset", f"{self.offset:.3f}",
            "-mpegts_flags", "+initial_discontinuity",          # clean splice: CC reset is announced, not "corrupt"
            "-f", "mpegts", "-",
        ], stdout=subprocess.PIPE)
        try:
            shutil.copyfileobj(remux.stdout, self.proc.stdin, 1 << 16)
        finally:
            remux.stdout.close()
            remux.wait()
        self.offset += dur + 0.1        # small gap absorbs AAC priming so timestamps never overlap

    def run(self, stop: threading.Event):
        backoff = 2
        while not stop.is_set():
            if self.proc is None or self.proc.poll() is not None:
                if self.proc is not None:
                    log(f"Stream encoder exited ({self.proc.returncode}); restarting in {backoff}s")
                    stop.wait(backoff)
                    backoff = min(backoff * 2, 60)
                self._start()
            clip = self._next_clip()
            try:
                log(f"On air: {os.path.basename(clip)}")
                self._feed(clip)
                backoff = 2
            except (BrokenPipeError, OSError) as e:
                log(f"Stream pipe broke: {e}")
                self.proc = None
        if self.proc and self.proc.stdin:
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=10)
            except Exception:
                self.proc.kill()


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser(description="AIT News 24/7 autopilot")
    ap.add_argument("--output", help="RTMP URL or local .flv file (default: YouTube with YOUTUBE_STREAM_KEY)")
    ap.add_argument("--minutes", type=float, default=0, help="stop after N minutes (for dry runs)")
    ap.add_argument("--render-only", action="store_true", help="maintain the clip library without streaming")
    ap.add_argument("--workers", type=int, default=RENDER_WORKERS)
    ap.add_argument("--voice", default=DEFAULT_VOICE)
    args = ap.parse_args()

    target = args.output
    if not target and not args.render_only:
        key = DEFAULT_STREAM_KEY
        if key:
            target = f"{YOUTUBE_RTMP_URL}/{key}"
        else:
            # No stream key yet: keep rendering and uploading story videos; add the key and restart to go live
            log("No YOUTUBE_STREAM_KEY set: running in render + upload mode (no live stream)")
            args.render_only = True

    ensure_standby_clip()
    stop = threading.Event()
    from youtube_uploader import Publisher
    publisher = Publisher()
    publisher.start()
    scheduler = Scheduler(args.workers, args.voice, publisher)
    threading.Thread(target=scheduler.run_forever, args=(stop,), daemon=True).start()
    if args.minutes:
        threading.Timer(args.minutes * 60, stop.set).start()

    log(f"Autopilot running: {args.workers} render workers, rotation of {ROTATION_SIZE} stories")
    try:
        if args.render_only:
            stop.wait()
        else:
            ContinuousStreamer(target, scheduler).run(stop)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        scheduler.shutdown()
        log("Autopilot stopped")


if __name__ == "__main__":
    main()
