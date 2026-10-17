import os
import asyncio
import subprocess
import edge_tts
import imageio_ffmpeg
from config import VOICE_PROFILES, DEFAULT_VOICE, OUTPUT_DIR

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
    voice_id = profile["voice_id"]
    rate = profile.get("rate", "+0%")
    pitch = profile.get("pitch", "+0Hz")

    output_path = os.path.join(OUTPUT_DIR, output_filename)

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

if __name__ == "__main__":
    sample_text = "This is AIT News. Anthropic and OpenAI have unveiled next-generation autonomous benchmarks."
    path, dur, times = generate_speech(sample_text, "sample_anchor_test.mp3")
    print(f"Generated voice at: {path} (Duration: {dur:.2f}s, Timings: {len(times)})")
