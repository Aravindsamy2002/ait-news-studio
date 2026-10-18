import os
import asyncio
import subprocess
import threading
import urllib.request
import edge_tts
import imageio_ffmpeg
import numpy as np
from config import VOICE_PROFILES, DEFAULT_VOICE, OUTPUT_DIR, ASSETS_DIR

KOKORO_DIR = os.path.join(ASSETS_DIR, "models")
KOKORO_RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
KOKORO_MODEL = os.path.join(KOKORO_DIR, "kokoro-v1.0.onnx")
KOKORO_VOICES = os.path.join(KOKORO_DIR, "voices-v1.0.bin")
_kokoro = None
_kokoro_lock = threading.Lock()

def get_kokoro():
    """Load the local Kokoro TTS model once, downloading the model files on first use."""
    global _kokoro
    with _kokoro_lock:
        if _kokoro is None:
            from kokoro_onnx import Kokoro
            os.makedirs(KOKORO_DIR, exist_ok=True)
            for path in (KOKORO_MODEL, KOKORO_VOICES):
                if not os.path.exists(path) or os.path.getsize(path) < 1_000_000:
                    print(f"Downloading {os.path.basename(path)} ...")
                    tmp = path + ".part"
                    urllib.request.urlretrieve(f"{KOKORO_RELEASE}/{os.path.basename(path)}", tmp)
                    os.replace(tmp, path)
            _kokoro = Kokoro(KOKORO_MODEL, KOKORO_VOICES)
        return _kokoro

def _kokoro_speech(segments: list[str], profile: dict, output_path: str, gap: float) -> tuple[str, float, list[dict]]:
    """Voice segments with Kokoro locally; timings come straight from sample counts."""
    kokoro = get_kokoro()
    chunks, timings, cursor, sr = [], [], 0.0, 24000
    for text in segments:
        samples, sr = kokoro.create(
            text, voice=profile["voice_id"], speed=profile.get("speed", 1.0), lang=profile.get("lang", "en-us")
        )
        dur = len(samples) / sr
        timings.append({"start": cursor, "end": cursor + dur, "text": text})
        chunks += [samples, np.zeros(int(gap * sr), np.float32)]
        cursor += dur + gap
    audio = np.concatenate(chunks).astype(np.float32)
    subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
         "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "-",
         "-c:a", "libmp3lame", "-b:a", "160k", output_path],
        input=audio.tobytes(), check=True,
    )
    return output_path, len(audio) / sr, timings

def get_audio_duration(file_path: str) -> float:
    """Accurately measure audio duration in seconds using ffmpeg."""
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    try:
        res = subprocess.run(
            [ffmpeg_exe, "-i", file_path],
            capture_output=True,
            text=True
        )
        for line in res.stderr.splitlines():
            if "Duration:" in line:
                part = line.split("Duration:")[1].split(",")[0].strip()
                h, m, s = part.split(":")
                return float(h) * 3600 + float(m) * 60 + float(s)
    except Exception as e:
        print(f"Error measuring audio duration: {e}")
    return 15.0

async def generate_speech_async(
    text: str,
    output_filename: str,
    voice_key: str = DEFAULT_VOICE
) -> tuple[str, float, list[dict]]:
    """Generate crystal clear neural news anchor audio with sentence boundary timings."""
    profile = VOICE_PROFILES.get(voice_key, VOICE_PROFILES[DEFAULT_VOICE])
    output_path = os.path.join(OUTPUT_DIR, output_filename)
    if profile.get("engine") == "kokoro":
        return await asyncio.to_thread(_kokoro_speech, [text], profile, output_path, 0.0)

    voice_id = profile["voice_id"]
    rate = profile.get("rate", "+0%")
    pitch = profile.get("pitch", "+0Hz")

    tts = edge_tts.Communicate(text, voice_id, rate=rate, pitch=pitch)
    audio_data = bytearray()
    timings = []

    async for chunk in tts.stream():
        if chunk["type"] == "audio":
            audio_data.extend(chunk["data"])
        elif chunk["type"] == "SentenceBoundary":
            start_sec = chunk["offset"] / 10_000_000
            dur_sec = chunk["duration"] / 10_000_000
            timings.append({
                "start": start_sec,
                "end": start_sec + dur_sec,
                "text": chunk.get("text", "")
            })

    with open(output_path, "wb") as f:
        f.write(audio_data)

    duration = get_audio_duration(output_path)
    return output_path, duration, timings

def generate_speech(
    text: str,
    output_filename: str,
    voice_key: str = DEFAULT_VOICE
) -> tuple[str, float, list[dict]]:
    """Safe synchronous wrapper for speech generation in or out of event loops."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, generate_speech_async(text, output_filename, voice_key)).result()
    else:
        return asyncio.run(generate_speech_async(text, output_filename, voice_key))

async def generate_segmented_speech_async(
    segments: list[str],
    output_filename: str,
    voice_key: str = DEFAULT_VOICE,
    gap: float = 0.35
) -> tuple[str, float, list[dict]]:
    """Voice each narration segment separately and join them with a natural pause.

    Returns exact start/end times per segment, so on-screen graphics can switch
    precisely when the anchor moves to the next point.
    """
    profile = VOICE_PROFILES.get(voice_key, VOICE_PROFILES[DEFAULT_VOICE])
    output_path = os.path.join(OUTPUT_DIR, output_filename)
    if profile.get("engine") == "kokoro":
        return await asyncio.to_thread(_kokoro_speech, segments, profile, output_path, gap)

    base = os.path.splitext(output_path)[0]
    seg_paths = []
    try:
        for i, text in enumerate(segments):
            tts = edge_tts.Communicate(
                text, profile["voice_id"],
                rate=profile.get("rate", "+0%"), pitch=profile.get("pitch", "+0Hz")
            )
            seg_path = f"{base}_seg{i}.mp3"
            await tts.save(seg_path)
            seg_paths.append(seg_path)

        timings, cursor = [], 0.0
        for path, text in zip(seg_paths, segments):
            dur = get_audio_duration(path)
            timings.append({"start": cursor, "end": cursor + dur, "text": text})
            cursor += dur + gap

        cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error"]
        for path in seg_paths:
            cmd += ["-i", path]
        chain = "".join(f"[{i}:a]apad=pad_dur={gap}[a{i}];" for i in range(len(seg_paths)))
        joined = "".join(f"[a{i}]" for i in range(len(seg_paths)))
        cmd += [
            "-filter_complex", f"{chain}{joined}concat=n={len(seg_paths)}:v=0:a=1[out]",
            "-map", "[out]", "-c:a", "libmp3lame", "-b:a", "160k", output_path
        ]
        subprocess.run(cmd, check=True)
    finally:
        for path in seg_paths:
            try:
                os.remove(path)
            except OSError:
                pass

    return output_path, get_audio_duration(output_path), timings

def generate_segmented_speech(
    segments: list[str],
    output_filename: str,
    voice_key: str = DEFAULT_VOICE
) -> tuple[str, float, list[dict]]:
    """Synchronous wrapper for generate_segmented_speech_async."""
    coro = generate_segmented_speech_async(segments, output_filename, voice_key)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)

if __name__ == "__main__":
    sample_text = "This is AIT News. Anthropic and OpenAI have unveiled next-generation autonomous benchmarks."
    path, dur, times = generate_speech(sample_text, "sample_anchor_test.mp3")
    print(f"Generated voice at: {path} (Duration: {dur:.2f}s, Timings: {len(times)})")
