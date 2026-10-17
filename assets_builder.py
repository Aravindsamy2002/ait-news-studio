import os
import wave
import numpy as np
from config import ASSETS_DIR

AMBIENT_BED_PATH = os.path.join(ASSETS_DIR, "news_ambient_bed.wav")

def ensure_ambient_bed():
    """Ensure that the ambient news broadcast audio bed exists."""
    if os.path.exists(AMBIENT_BED_PATH) and os.path.getsize(AMBIENT_BED_PATH) > 1000:
        return AMBIENT_BED_PATH

    sample_rate = 44100
    duration = 15.0  # 15s seamless loop
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)

    # 1. Warm low broadcast drone (55Hz, 110Hz, 165Hz harmonics)
    drone = (
        0.06 * np.sin(2 * np.pi * 55 * t) +
        0.03 * np.sin(2 * np.pi * 110 * t) +
        0.015 * np.sin(2 * np.pi * 165 * t)
    )

    # 2. Subtle rhythmic broadcast pulse tick every 1.0 second
    pulse = np.zeros_like(t)
    for sec in range(int(duration)):
        idx = int(sec * sample_rate)
        pulse_len = int(0.04 * sample_rate)
        if idx + pulse_len < len(t):
            pulse_t = np.linspace(0, 0.04, pulse_len, endpoint=False)
            decay = np.exp(-pulse_t * 70)
            pulse[idx:idx+pulse_len] = 0.02 * np.sin(2 * np.pi * 880 * pulse_t) * decay

    # 3. Soft high-tech digital ping every 5.0 seconds
    for sec in [2, 7, 12]:
        idx = int(sec * sample_rate)
        ping_len = int(0.25 * sample_rate)
        if idx + ping_len < len(t):
            ping_t = np.linspace(0, 0.25, ping_len, endpoint=False)
            decay = np.exp(-ping_t * 15)
            pulse[idx:idx+ping_len] += 0.015 * np.sin(2 * np.pi * 1760 * ping_t) * decay

    audio = drone + pulse
    audio = np.clip(audio, -1.0, 1.0)
    int_audio = (audio * 32767).astype(np.int16)

    with wave.open(AMBIENT_BED_PATH, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(int_audio.tobytes())

    return AMBIENT_BED_PATH

if __name__ == "__main__":
    p = ensure_ambient_bed()
    print(f"Ambient bed ready at {p}")
