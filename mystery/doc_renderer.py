"""Mystery documentary renderer (prototype).

episode.json (scenes + narration beats) -> Kokoro narration -> per-scene frames (PIL, rendered in
parallel) -> synthesized score + SFX with voice ducking -> final 1080p MP4.

    python mystery/doc_renderer.py mystery/roopkund
"""
import json
import math
import os
import random
import subprocess
import sys
import time
import wave
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

W, H, FPS = 1920, 1080, 24
SR = 44100
FADE = 0.35                 # dip-to-black at scene edges
LEAD = 0.45                 # silence before the first line of a scene
VOICE, VOICE_SPEED = "af_heart", 0.95
FONT_DIR = os.path.join(ROOT, "assets", "fonts")
FF = imageio_ffmpeg.get_ffmpeg_exe()

AMBER, RED, GOLD = (245, 158, 11), (220, 38, 38), (212, 175, 55)
INK, MUTED = (236, 232, 222), (150, 150, 140)
STAMP_COLORS = {"red": RED, "gold": GOLD, "amber": AMBER}


# ------------------------------------------------------------------ helpers

@lru_cache(maxsize=None)
def font(name: str, size: int, variation: str = None) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(os.path.join(FONT_DIR, name), size)
    if variation:
        f.set_variation_by_name(variation)
    return f


def cinzel(size, weight="Bold"):
    return font("Cinzel.ttf", size, weight)


def oswald(size, weight="Bold"):
    return font("Oswald.ttf", size, weight)


def mont(size, weight="SemiBold"):
    return font("Montserrat.ttf", size, weight)


def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def prog(t, start, dur):
    return clamp((t - start) / dur) if dur > 0 else float(t >= start)


def ease_out(p):
    return 1 - (1 - p) ** 3


def ease_in_out(p):
    return 3 * p * p - 2 * p * p * p


def tracked(draw, xy, text, fnt, fill, tracking=0, anchor="lt"):
    """Draw text with letter spacing. anchor 'mt' centres horizontally on x."""
    widths = [draw.textlength(c, font=fnt) for c in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x, y = xy
    if anchor == "mt":
        x -= total / 2
    for c, w in zip(text, widths):
        draw.text((x, y), c, font=fnt, fill=fill)
        x += w + tracking
    return total


def wrap(text, fnt, max_w, draw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=fnt) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


# ------------------------------------------------------------------ film look

@lru_cache(maxsize=1)
def vignette() -> Image.Image:
    y, x = np.ogrid[:H, :W]
    d = np.sqrt(((x - W / 2) / (W / 2)) ** 2 + ((y - H / 2) / (H / 2)) ** 2)
    a = np.clip((d - 0.55) / 0.85, 0, 1) ** 1.6 * 215
    v = np.zeros((H, W, 4), np.uint8)
    v[..., 3] = a.astype(np.uint8)
    return Image.fromarray(v, "RGBA")


@lru_cache(maxsize=1)
def grain_frames():
    rng = np.random.default_rng(3)
    out = []
    for _ in range(6):
        n = rng.normal(128, 40, (H // 2, W // 2)).clip(0, 255).astype(np.uint8)
        g = Image.fromarray(n, "L").resize((W, H), Image.BILINEAR)
        rgba = Image.merge("RGBA", (g, g, g, Image.new("L", (W, H), 16)))
        out.append(rgba)
    return out


def finish(frame: Image.Image, f: int, t: float, dur: float) -> Image.Image:
    """Vignette, grain and dip-to-black at the scene edges."""
    frame = frame.convert("RGBA")
    frame.alpha_composite(vignette())
    frame.alpha_composite(grain_frames()[f % 6])
    k = min(prog(t, 0, FADE), 1 - prog(t, dur - FADE, FADE))
    out = frame.convert("RGB")
    if k < 1:
        out = Image.blend(Image.new("RGB", (W, H)), out, ease_in_out(k))
    return out


def grade(img: Image.Image, look: str) -> Image.Image:
    img = img.convert("RGB")
    sat, bright, tint, amt = {"cold": (0.55, 0.78, (18, 34, 58), 0.20),
                              "dusk": (0.70, 0.74, (70, 38, 18), 0.16),
                              "dark": (0.45, 0.45, (10, 14, 22), 0.30)}[look]
    img = ImageEnhance.Color(img).enhance(sat)
    img = ImageEnhance.Contrast(img).enhance(1.15)
    img = ImageEnhance.Brightness(img).enhance(bright)
    return Image.blend(img, Image.new("RGB", img.size, tint), amt)


def cover(img: Image.Image, w: int, h: int) -> Image.Image:
    s = max(w / img.width, h / img.height)
    img = img.resize((math.ceil(img.width * s), math.ceil(img.height * s)), Image.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


class KenBurns:
    HEAD = 1.16

    def __init__(self, path, look, move, dur):
        self.plate = cover(grade(Image.open(path), look), int(W * self.HEAD), int(H * self.HEAD))
        self.move, self.dur = move, dur

    def at(self, t):
        p = ease_in_out(clamp(t / self.dur))
        pw, ph = self.plate.size
        if self.move in ("in", "out"):
            z = 1 + (self.HEAD - 1) * (p if self.move == "in" else 1 - p)
            cw, ch = pw / z, ph / z
            x, y = (pw - cw) / 2, (ph - ch) / 2
        else:
            cw, ch = W * 1.04, H * 1.04
            span = pw - cw
            x = span * (p if self.move == "right" else 1 - p)
            y = (ph - ch) / 2
        return self.plate.resize((W, H), Image.BILINEAR, box=(x, y, x + cw, y + ch))


def credit_text(credits, key):
    c = credits.get(key)
    if not c:
        return ""
    artist = c["artist"].replace("\n", " ").split("Derivative")[0].replace("Original:", "").strip()
    return f"Photo: {artist} / {c['license']} / Wikimedia Commons"


def draw_credit(frame, text):
    if text:
        d = ImageDraw.Draw(frame)
        f = mont(15, "Medium")
        d.text((W - 28 - d.textlength(text, font=f), H - 34), text, font=f, fill=(170, 170, 160))


# ------------------------------------------------------------------ scenes

def render_photo(sc, t, ctx):
    frame = ctx["kb"].at(t)
    d = ImageDraw.Draw(frame)
    if sc.get("caption"):
        p = ease_out(prog(t, 0.9, 0.7))
        if p > 0:
            x, y = 90, H - 175
            d.rectangle((x, y, x + int(70 * p), y + 4), fill=AMBER)
            lay = Image.new("RGBA", (W, H))
            ImageDraw.Draw(lay).text((x, y + 18), sc["caption"], font=oswald(44), fill=INK + (int(255 * p),))
            frame = frame.convert("RGBA")
            frame.alpha_composite(lay)
    draw_credit(frame, ctx["credit"])
    return frame


def render_title(sc, t, ctx):
    frame = ctx["kb"].at(t)
    frame = ImageEnhance.Brightness(frame).enhance(0.45)
    lay = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(lay)
    ep = ctx["episode"]
    a1 = ease_out(prog(t, 0.15, 0.8))
    tracked(d, (W / 2, 330), ep["series"], oswald(30, "Medium"), AMBER + (int(255 * a1),), tracking=14, anchor="mt")
    a2 = ease_out(prog(t, 0.45, 1.4))
    spacing = 6 + 30 * (1 - a2)
    tracked(d, (W / 2, 430), ep["title"].upper(), cinzel(118, "Black"), INK + (int(255 * a2),), tracking=spacing, anchor="mt")
    a3 = ease_out(prog(t, 1.4, 0.8))
    lw = int(260 * a3)
    d.rectangle((W / 2 - lw, 610, W / 2 + lw, 612), fill=AMBER + (int(220 * a3),))
    tracked(d, (W / 2, 640), ep["subtitle"].upper(), mont(34, "Medium"), MUTED + (int(255 * a3),), tracking=8, anchor="mt")
    frame = frame.convert("RGBA")
    frame.alpha_composite(lay)
    return frame


def render_chapter(sc, t, ctx):
    frame = Image.new("RGB", (W, H), (8, 9, 12))
    lay = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(lay)
    a1 = ease_out(prog(t, 0.2, 0.6))
    tracked(d, (W / 2, 420), sc["num"], oswald(34, "Medium"), AMBER + (int(255 * a1),), tracking=16, anchor="mt")
    a2 = ease_out(prog(t, 0.45, 0.9))
    tracked(d, (W / 2, 490 + 20 * (1 - a2)), sc["name"], cinzel(104, "Bold"), INK + (int(255 * a2),), tracking=8, anchor="mt")
    lw = int(180 * ease_out(prog(t, 0.6, 1.0)))
    d.rectangle((W / 2 - lw, 640, W / 2 + lw, 641), fill=AMBER + (160,))
    frame = frame.convert("RGBA")
    frame.alpha_composite(lay)
    return frame


@lru_cache(maxsize=1)
def world():
    gj = json.load(open(os.path.join(ROOT, "mystery", "ne_50m_countries.geojson"), encoding="utf-8"))
    polys = []
    for feat in gj["features"]:
        name = feat["properties"].get("ADMIN", "")
        g = feat["geometry"]
        rings = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        for poly in rings:
            ring = np.array(poly[0], dtype=np.float64)
            polys.append((name, ring, ring[:, 0].min(), ring[:, 0].max(), ring[:, 1].min(), ring[:, 1].max()))
    return polys


def render_map(sc, t, ctx):
    dur = ctx["dur"]
    p = ease_in_out(prog(t, 0.3, min(6.0, dur * 0.55)))
    s0, s1 = 7.0, 150.0                                         # px per degree: world -> region
    s = math.exp(math.log(s0) + (math.log(s1) - math.log(s0)) * p)
    cx = 78 + (sc["lon"] - 78) * p
    cy = 24 + (sc["lat"] - 24) * p
    ss = 2                                                       # supersample for smooth edges
    img = Image.new("RGB", (W * ss, H * ss), (9, 13, 20))
    d = ImageDraw.Draw(img)
    half_w, half_h = W / 2 / s, H / 2 / s
    lon0, lon1, lat0, lat1 = cx - half_w, cx + half_w, cy - half_h, cy + half_h

    def to_px(lon, lat):
        return ((lon - cx) * s + W / 2) * ss, ((cy - lat) * s + H / 2) * ss

    step = 10 if s < 30 else 2
    for g in np.arange(math.floor(lon0 / step) * step, lon1 + step, step):
        d.line([to_px(g, lat0), to_px(g, lat1)], fill=(20, 28, 40), width=ss)
    for g in np.arange(math.floor(lat0 / step) * step, lat1 + step, step):
        d.line([to_px(lon0, g), to_px(lon1, g)], fill=(20, 28, 40), width=ss)
    for name, ring, x0, x1, y0, y1 in world():
        if x1 < lon0 or x0 > lon1 or y1 < lat0 or y0 > lat1:
            continue
        pts = np.column_stack(((ring[:, 0] - cx) * s + W / 2, (cy - ring[:, 1]) * s + H / 2)) * ss
        pts = [tuple(q) for q in pts]
        if name == "India":
            d.polygon(pts, fill=(52, 42, 26), outline=AMBER, width=3 * ss)
        else:
            d.polygon(pts, fill=(27, 32, 41), outline=(62, 70, 84), width=ss)
    frame = img.resize((W, H), Image.LANCZOS)
    d = ImageDraw.Draw(frame)

    if 0.25 < p < 0.85:                                          # country label on the way in
        a = int(200 * min(prog(p, 0.25, 0.15), 1 - prog(p, 0.7, 0.15)))
        lay = Image.new("RGBA", (W, H))
        ix, iy = to_px(79, 22)
        tracked(ImageDraw.Draw(lay), (ix / ss, iy / ss), "INDIA", cinzel(64, "Bold"), INK + (a,), tracking=14, anchor="mt")
        frame = frame.convert("RGBA")
        frame.alpha_composite(lay)
        frame = frame.convert("RGB")
        d = ImageDraw.Draw(frame)

    pin_t = 0.3 + min(6.0, dur * 0.55)
    a = ease_out(prog(t, pin_t, 0.6))
    if a > 0:
        px, py = to_px(sc["lon"], sc["lat"])
        px, py = px / ss, py / ss
        for k in range(3):                                       # pulsing rings
            ph = ((t - pin_t) * 0.8 + k / 3) % 1
            r = 14 + 70 * ph
            col = tuple(int(c * (1 - ph) * a + 9 * (1 - (1 - ph) * a)) for c in RED)
            d.ellipse((px - r, py - r, px + r, py + r), outline=col, width=3)
        d.ellipse((px - 11, py - 11, px + 11, py + 11), fill=RED, outline=(255, 255, 255), width=3)
        lay = Image.new("RGBA", (W, H))
        ld = ImageDraw.Draw(lay)
        bx, by = px + 105, py - 52
        ld.rectangle((bx, by, bx + 6, by + 104), fill=AMBER + (int(255 * a),))
        ld.text((bx + 26, by - 6), sc["label"], font=cinzel(66, "Black"), fill=INK + (int(255 * a),))
        ld.text((bx + 28, by + 72), sc["sub"], font=oswald(30, "Medium"), fill=MUTED + (int(255 * a),))
        frame = frame.convert("RGBA")
        frame.alpha_composite(lay)
    ImageDraw.Draw(frame).text((W - 330, H - 34), "Map data: Natural Earth", font=mont(15, "Medium"), fill=(120, 120, 115))
    return frame


def render_theory(sc, t, ctx):
    frame = ctx["kb"].at(t).convert("RGBA")
    shade = np.zeros((H, W, 4), np.uint8)
    shade[..., 3] = (np.clip((np.arange(W) - 700) / 600, 0, 1) * 225).astype(np.uint8)[None, :]
    frame.alpha_composite(Image.fromarray(shade, "RGBA"))
    lay = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(lay)
    x = 1080
    a1 = ease_out(prog(t, 0.3, 0.6))
    tracked(d, (x + 30 * (1 - a1), 300), sc["tag"], oswald(36, "Medium"), AMBER + (int(255 * a1),), tracking=10)
    a2 = ease_out(prog(t, 0.6, 0.8))
    y = 360
    for line in wrap(sc["head"], cinzel(70, "Bold"), 740, d):
        d.text((x + 30 * (1 - a2), y), line, font=cinzel(70, "Bold"), fill=INK + (int(255 * a2),))
        y += 88
    d.rectangle((x, y + 24, x + int(120 * a2), y + 27), fill=AMBER + (int(255 * a2),))
    frame.alpha_composite(lay)

    st = ctx["stamp_at"]
    if t >= st:                                                  # rubber stamp slams in
        p = prog(t, st, 0.35)
        z = 1 + 0.9 * (1 - ease_out(p))
        col = STAMP_COLORS[sc["stamp_color"]]
        f = oswald(92, "Bold")
        tw = int(ImageDraw.Draw(lay).textlength(sc["stamp"], font=f))
        stamp = Image.new("RGBA", (tw + 80, 150))
        sd = ImageDraw.Draw(stamp)
        sd.rectangle((4, 4, tw + 76, 146), outline=col + (235,), width=8)
        sd.text((40, 10), sc["stamp"], font=f, fill=col + (235,))
        stamp = stamp.rotate(-11, expand=True, resample=Image.BICUBIC)
        stamp = stamp.resize((int(stamp.width * z), int(stamp.height * z)), Image.BILINEAR)
        if p < 1:
            stamp.putalpha(stamp.getchannel("A").point(lambda v: int(v * ease_out(p))))
        frame.alpha_composite(stamp, (int(x + 30 + 230 - stamp.width / 2), int(y + 170 - stamp.height / 2)))
    frame = frame.convert("RGB")
    draw_credit(frame, ctx["credit"])
    return frame


def render_timeline(sc, t, ctx):
    frame = Image.new("RGB", (W, H), (9, 11, 15))
    lay = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(lay)
    x0, x1, y = 260, W - 260, 560
    p = ease_out(prog(t, 0.3, 1.6))
    d.rectangle((x0, y - 2, x0 + (x1 - x0) * p, y + 2), fill=(90, 90, 85, 255))
    evs = sc["events"]
    for i, (year, label) in enumerate(evs):
        ex = x0 + (x1 - x0) * (i + 0.5) / len(evs)
        a = ease_out(prog(t, 0.6 + i * 0.55, 0.6))
        if a <= 0:
            continue
        last = i == len(evs) - 1
        col = RED if last else AMBER
        if last:
            glow = 22 + 10 * math.sin(t * 4)
            d.ellipse((ex - glow, y - glow, ex + glow, y + glow), fill=col + (int(60 * a),))
        d.ellipse((ex - 13, y - 13, ex + 13, y + 13), fill=col + (int(255 * a),))
        tracked(d, (ex, y - 150 + 20 * (1 - a)), year, cinzel(96 if last else 80, "Black"), (INK if last else MUTED) + (int(255 * a),), tracking=4, anchor="mt")
        tracked(d, (ex, y + 48), label.upper(), oswald(34, "Medium"), (INK if last else MUTED) + (int(255 * a),), tracking=4, anchor="mt")
    frame = frame.convert("RGBA")
    frame.alpha_composite(lay)
    return frame


def render_data(sc, t, ctx):
    frame = Image.new("RGB", (W, H), (9, 9, 11))
    lay = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(lay)
    target = int(sc["big"].replace(",", ""))
    p = ease_out(prog(t, 0.3, 1.8))
    tracked(d, (W / 2, 250), f"{int(target * p):,}", cinzel(280, "Black"), AMBER + (255,), tracking=6, anchor="mt")
    a = ease_out(prog(t, 1.4, 0.7))
    tracked(d, (W / 2, 610), sc["unit"], oswald(70, "Bold"), INK + (int(255 * a),), tracking=18, anchor="mt")
    a2 = ease_out(prog(t, 2.0, 0.7))
    tracked(d, (W / 2, 720), sc["note"], mont(36, "Medium"), MUTED + (int(255 * a2),), tracking=3, anchor="mt")
    frame = frame.convert("RGBA")
    frame.alpha_composite(lay)
    return frame


def render_outro(sc, t, ctx):
    frame = Image.new("RGB", (W, H), (8, 9, 12))
    lay = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(lay)
    a = ease_out(prog(t, 0.2, 0.9))
    tracked(d, (W / 2, 380), "WHAT DO YOU THINK", cinzel(92, "Bold"), INK + (int(255 * a),), tracking=6, anchor="mt")
    tracked(d, (W / 2, 490), "HAPPENED?", cinzel(92, "Bold"), AMBER + (int(255 * a),), tracking=6, anchor="mt")
    a2 = ease_out(prog(t, 1.2, 0.8))
    tracked(d, (W / 2, 660), "COMMENT BELOW   ·   SUBSCRIBE FOR THE NEXT CASE", oswald(34, "Medium"), MUTED + (int(255 * a2),), tracking=6, anchor="mt")
    tracked(d, (W / 2, 900), ctx["episode"]["series"], oswald(30, "Medium"), AMBER + (int(200 * a2),), tracking=14, anchor="mt")
    frame = frame.convert("RGBA")
    frame.alpha_composite(lay)
    return frame


RENDER = {"photo": render_photo, "title": render_title, "chapter": render_chapter, "map": render_map,
          "theory": render_theory, "timeline": render_timeline, "data": render_data, "outro": render_outro}


def render_scene(job):
    """Worker: render one scene to a silent H.264 segment."""
    sc, dur, n, out, ep_dir, episode, credits, stamp_at = job
    ctx = {"dur": dur, "episode": episode, "stamp_at": stamp_at, "credit": ""}
    img_key = sc.get("img") or ("lake2" if sc["type"] == "title" else None)
    if img_key:
        ctx["kb"] = KenBurns(os.path.join(ep_dir, "img", img_key + ".jpg"), sc.get("grade", "cold"),
                             sc.get("move", "in"), dur)
        ctx["credit"] = credit_text(credits, img_key)
    cmd = [FF, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
           "-pix_fmt", "yuv420p", out]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for f in range(n):
        t = f / FPS
        proc.stdin.write(finish(RENDER[sc["type"]](sc, t, ctx), f, t, dur).tobytes())
    proc.stdin.close()
    proc.wait()
    return out


# ------------------------------------------------------------------ audio

def synth_score(n: int, booms: list[float], whooshes: list[float]) -> tuple[np.ndarray, np.ndarray]:
    """Original dark ambient bed (drone + wind + eerie pad) and an SFX track. No licensing needed."""
    rng = np.random.default_rng(11)
    t = np.arange(n) / SR
    bed = np.zeros(n)
    for f, a in [(55.0, 0.30), (82.41, 0.18), (110.0, 0.12), (164.81, 0.05)]:
        bed += a * np.sin(2 * np.pi * f * t + 0.8 * np.sin(2 * np.pi * 0.05 * t + f))
    bed *= 0.75 + 0.25 * np.sin(2 * np.pi * 0.06 * t)
    pad = 0.035 * (np.sin(2 * np.pi * 440 * t) + np.sin(2 * np.pi * 659.25 * t + 1)) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.03 * t)) ** 3
    spec = np.fft.rfft(rng.normal(0, 1, n))
    freqs = np.fft.rfftfreq(n, 1 / SR)
    spec *= np.where((freqs > 80) & (freqs < 900), 1.0, 0.0) / (1 + freqs / 300)
    wind = np.fft.irfft(spec, n)
    wind = wind / (np.abs(wind).max() + 1e-9) * 0.18 * (0.6 + 0.4 * np.sin(2 * np.pi * 0.04 * t + 2))
    bed = bed + pad + wind
    bed = bed / np.abs(bed).max() * 0.6

    fx = np.zeros(n)
    for b in booms:                                              # low cinematic hit
        i = int(b * SR)
        L = min(int(3.5 * SR), n - i)
        if L <= 0:
            continue
        tt = np.arange(L) / SR
        hit = np.sin(2 * np.pi * (38 + 30 * np.exp(-tt * 6)) * tt) * np.exp(-tt * 1.4)
        hit += 0.4 * rng.normal(0, 1, L) * np.exp(-tt * 18)
        fx[i:i + L] += 0.9 * hit
    for w in whooshes:                                           # airy transition swish
        L = int(0.9 * SR)
        i = max(0, int(w * SR) - L // 2)
        L = min(L, n - i)
        if L <= 0:
            continue
        sp = np.fft.rfft(rng.normal(0, 1, L))
        fr = np.fft.rfftfreq(L, 1 / SR)
        sp *= np.exp(-((fr - 1800) / 1400) ** 2)
        sw = np.fft.irfft(sp, L)
        env = np.sin(np.pi * np.arange(L) / L) ** 2
        fx[i:i + L] += 0.35 * sw / (np.abs(sw).max() + 1e-9) * env
    return bed, fx


def write_wav(path, x):
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def resample(x, sr_in):
    if sr_in == SR:
        return x
    n = int(len(x) * SR / sr_in)
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)


# ------------------------------------------------------------------ main

def build(ep_dir: str):
    t_start = time.time()
    episode = json.load(open(os.path.join(ep_dir, "episode.json"), encoding="utf-8"))
    credits = {c["key"]: c for c in json.load(open(os.path.join(ep_dir, "img", "credits.json"), encoding="utf-8"))}
    work = os.path.join(ep_dir, "build")
    os.makedirs(work, exist_ok=True)

    from voice_engine import get_kokoro
    kokoro = get_kokoro()

    # 1) narration: voice every beat, lay scenes out on a frame-exact timeline
    plan, cursor = [], 0.0
    for i, sc in enumerate(episode["scenes"]):
        local, beats = (LEAD if sc["beats"][0][0] else 0.0), []
        for text, pause in sc["beats"]:
            if text:
                a, sr = kokoro.create(text, voice=VOICE, speed=VOICE_SPEED, lang="en-us")
                a = resample(a.astype(np.float64), sr)
                beats.append((local, a))
                local += len(a) / SR
            local += pause
        n = int(math.ceil(local * FPS))
        stamp_at = beats[-1][0] if beats else 0.0
        plan.append(dict(sc=sc, start=cursor, dur=n / FPS, n=n, beats=beats, stamp_at=stamp_at))
        cursor += n / FPS
    total = cursor
    print(f"narration ready: {total:.1f}s across {len(plan)} scenes ({time.time() - t_start:.0f}s)", flush=True)

    # 2) video: render scenes in parallel
    jobs = [(p["sc"], p["dur"], p["n"], os.path.join(work, f"scene_{i:02d}.mp4"), ep_dir, episode, credits, p["stamp_at"])
            for i, p in enumerate(plan)]
    workers = max(1, (os.cpu_count() or 4) - 2)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        segs = list(pool.map(render_scene, jobs))
    print(f"scenes rendered ({time.time() - t_start:.0f}s)", flush=True)
    concat = os.path.join(work, "concat.txt")
    with open(concat, "w") as fh:
        fh.writelines(f"file '{os.path.abspath(s)}'\n" for s in segs)

    # 3) audio: voice + ducked score + SFX
    n_samp = int(total * SR) + SR
    voice = np.zeros(n_samp)
    for p in plan:
        for at, a in p["beats"]:
            i = int((p["start"] + at) * SR)
            voice[i:i + len(a)] += a[:n_samp - i]
    booms = [p["start"] + 0.15 for p in plan if p["sc"].get("boom")]
    booms += [p["start"] + p["stamp_at"] for p in plan if p["sc"]["type"] == "theory"]
    whooshes = [p["start"] for p in plan[1:]]
    bed, fx = synth_score(n_samp, booms, whooshes)
    env = np.convolve(np.abs(voice), np.ones(int(0.25 * SR)) / int(0.25 * SR), mode="same")
    env = np.clip(env / (env.max() + 1e-9) * 4, 0, 1)
    duck = 0.30 - 0.20 * env
    mix = voice / (np.abs(voice).max() + 1e-9) * 0.85 + bed * duck + fx * 0.6
    fade = int(1.5 * SR)
    mix[-fade:] *= np.linspace(1, 0, fade)
    audio = os.path.join(work, "mix.wav")
    write_wav(audio, mix / max(1.0, np.abs(mix).max() / 0.95))

    out = os.path.join(ep_dir, "preview.mp4")
    subprocess.run([FF, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", concat, "-i", audio,
                    "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-t", f"{total:.3f}", "-movflags", "+faststart", out], check=True)
    print(f"done: {out}  ({total:.1f}s video, built in {time.time() - t_start:.0f}s)", flush=True)
    return out


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "mystery", "roopkund"))
