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

NEWS_BED_PATH = os.path.join(ASSETS_DIR, "news_bed_music.wav")
SR = 44100


def _write_wav(path: str, audio: np.ndarray, sample_rate: int = SR):
    audio = audio / (np.max(np.abs(audio)) + 1e-9) * 0.89
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes((audio * 32767).astype(np.int16).tobytes())


def _midi(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


def _tone(freq: float, length: float, harmonics: int = 5, decay: float = 0.0, rolloff: float = 1.0) -> np.ndarray:
    t = np.arange(int(length * SR)) / SR
    sig = sum((1 / h ** rolloff) * np.sin(2 * np.pi * freq * h * t) for h in range(1, harmonics + 1))
    return sig * np.exp(-t * decay) if decay else sig


def _lp_noise(length: float, cutoff: float, rng) -> np.ndarray:
    x = rng.standard_normal(int(length * SR))
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    x = np.fft.irfft(spec / (1 + (f / cutoff) ** 4), len(x))
    return x / (np.max(np.abs(x)) + 1e-9)


def ensure_news_bed() -> str:
    """Tense, pulsing news-room music bed (seamless 8-bar loop) synthesised once."""
    if os.path.exists(NEWS_BED_PATH) and os.path.getsize(NEWS_BED_PATH) > 1000:
        return NEWS_BED_PATH

    rng = np.random.default_rng(11)
    beat = 60 / 100
    chords = [[57, 60, 64]] * 2 + [[53, 57, 60]] * 2 + [[50, 53, 57]] * 2 + [[52, 56, 59]] * 2
    n = int(len(chords) * 4 * beat * SR)
    out = np.zeros(n)

    def place(sig, at):
        idx = (np.arange(len(sig)) + int(at * SR)) % n      # wrap around -> seamless loop
        np.add.at(out, idx, sig)

    kick_t = np.arange(int(0.3 * SR)) / SR
    kick = np.sin(2 * np.pi * np.cumsum(45 + 70 * np.exp(-kick_t * 25)) / SR) * np.exp(-kick_t * 9)
    tick = np.diff(rng.standard_normal(int(0.03 * SR) + 1)) * np.exp(-np.arange(int(0.03 * SR)) / SR * 140)

    for bar, notes in enumerate(chords):
        bt = bar * 4 * beat
        for m in notes:                                       # soft string pad
            length = 4 * beat
            tt = np.arange(int(length * SR)) / SR
            env = np.minimum(1, tt / 0.35) * np.minimum(1, (length - tt) / 0.35)
            pad = _tone(_midi(m), length, 5, rolloff=1.4) + _tone(_midi(m) * 1.004, length, 5, rolloff=1.4)
            place(pad * env * 0.045, bt)
        root = notes[0] - 24
        arp = [notes[0] + 12, notes[1] + 12, notes[2] + 12, notes[1] + 12]
        for e in range(8):
            place(_tone(_midi(root), beat / 2 * 0.95, 4, decay=7) * 0.17, bt + e * beat / 2)   # driving bass
            place(_tone(_midi(arp[e % 4]), 0.3, 3, decay=12, rolloff=1.5) * 0.035, bt + e * beat / 2)
            if e % 2:
                place(tick * 0.05, bt + e * beat / 2)
        for b in (0, 2):
            place(kick * 0.32, bt + b * beat)
        if bar % 4 == 0:                                      # timpani-style swell hit
            tt = np.arange(int(1.8 * SR)) / SR
            place(np.sin(2 * np.pi * _midi(notes[0] - 24) * tt) * np.exp(-tt * 2.2) * 0.25, bt)

    _write_wav(NEWS_BED_PATH, out)
    return NEWS_BED_PATH


def build_sfx_track(path: str, total: float, impact_at: float, exit_at: float, flip_times: list[float]) -> str:
    """Broadcast stinger hit, whooshes and graphic-flip swooshes for one story."""
    rng = np.random.default_rng(5)
    n = int((total + 2) * SR)
    out = np.zeros(n)

    def place(sig, at):
        i = int(max(0.0, at) * SR)
        seg = sig[: max(0, n - i)]
        out[i:i + len(seg)] += seg

    def whoosh(length, cutoff=2600):
        x = _lp_noise(length, cutoff, rng)
        env = np.sin(np.linspace(0, np.pi, len(x))) ** 2 * np.linspace(0.3, 1.0, len(x))
        return x * env

    t = np.arange(int(1.8 * SR)) / SR
    boom = np.sin(2 * np.pi * np.cumsum(38 + 75 * np.exp(-t * 6)) / SR) * np.exp(-t * 2.6)
    crack = np.zeros_like(t)
    crack[: int(0.3 * SR)] = _lp_noise(0.3, 5000, rng) * np.exp(-t[: int(0.3 * SR)] * 22)
    metal = sum(np.sin(2 * np.pi * f * t) for f in (196, 311, 466, 740)) * np.exp(-t * 3.2) * 0.12
    place(whoosh(impact_at + 0.05) * 0.55, 0.0)
    place(boom * 1.0 + crack * 0.5 + metal, impact_at)
    place(whoosh(0.45, 3500) * 0.45, exit_at)
    for ft in flip_times:
        place(whoosh(0.32, 3000) * 0.28, ft - 0.08)
        place(_tone(1320, 0.12, 2, decay=40) * 0.06, ft + 0.1)

    _write_wav(path, out)
    return path


if __name__ == "__main__":
    print(f"News bed ready at {ensure_news_bed()}")
    p = ensure_ambient_bed()
    print(f"Ambient bed ready at {p}")
