import os
import subprocess
import signal
import threading
import imageio_ffmpeg
from config import YOUTUBE_RTMP_URL, DEFAULT_STREAM_KEY, OUTPUT_DIR

class BroadcastStreamer:
    def __init__(self):
        self.process = None
        self.is_streaming = False
        self.current_target = None
        self.log_lines = []
        self._lock = threading.Lock()

    def get_status(self) -> dict:
        with self._lock:
            return {
                "is_streaming": self.is_streaming,
                "target": self.current_target,
                "logs": self.log_lines[-20:] if self.log_lines else []
            }

    def start_youtube_stream(self, video_file: str, stream_key: str = None) -> bool:
        """Start streaming video file continuously to YouTube Live RTMP."""
        with self._lock:
            if self.is_streaming:
                return False

            key = stream_key or DEFAULT_STREAM_KEY
            if not key:
                raise ValueError("YouTube Stream Key is required!")

            video_path = os.path.join(OUTPUT_DIR, video_file)
            if not os.path.exists(video_path):
                raise FileNotFoundError(f"Video file {video_file} not found!")

            rtmp_url = f"{YOUTUBE_RTMP_URL}/{key}"
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

            # Command for YouTube Live 1080p 30fps RTMP streaming
            cmd = [
                ffmpeg_exe,
                "-re",                              # Read input at native frame rate
                "-stream_loop", "-1",               # Continuous infinite loop
                "-i", video_path,
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-b:v", "4500k",
                "-maxrate", "5000k",
                "-bufsize", "9000k",
                "-pix_fmt", "yuv420p",
                "-g", "60",                         # 2-second keyframe interval
                "-c:a", "aac",
                "-b:a", "192k",
                "-ar", "44100",
                "-f", "flv",
                rtmp_url
            ]

            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            self.is_streaming = True
            self.current_target = "YouTube Live (RTMP)"

            # Monitor thread
            threading.Thread(target=self._read_output, daemon=True).start()
            return True

    def _read_output(self):
        if not self.process:
            return
        for line in self.process.stdout:
            with self._lock:
                self.log_lines.append(line.strip())
                if len(self.log_lines) > 200:
                    self.log_lines.pop(0)
        with self._lock:
            self.is_streaming = False
            self.current_target = None

    def stop_stream(self):
        """Safely terminate streaming process."""
        with self._lock:
            if self.process and self.is_streaming:
                try:
                    self.process.terminate()
                    self.process.wait(timeout=4)
                except Exception:
                    try:
                        self.process.kill()
                    except Exception:
                        pass
                self.is_streaming = False
                self.current_target = None
                return True
            return False

streamer_instance = BroadcastStreamer()

if __name__ == "__main__":
    print("BroadcastStreamer initialized.")
