"""
Indian news-channel style motion graphics for AIT News broadcasts.

Every frame is composited in Python (PIL + numpy) and piped as raw RGB into
FFmpeg. The look follows mainstream Indian English news channels: full-screen
footage, a "BREAKING NEWS" stinger, a hashtag box, corner logo with LIVE tag,
a bold red super band that flips through the key points in sync with the
anchor, a yellow strap, a NEWS ALERT ticker and a headline flipper with clock.
"""
import math
import os
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import subprocess

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from assets_builder import build_sfx_track, ensure_news_bed
from config import ASSETS_DIR, OUTPUT_DIR, VIDEO_FPS, VIDEO_HEIGHT, VIDEO_WIDTH

W, H, FPS = VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_FPS

RED = (214, 18, 30)
DARK_RED = (118, 0, 10)
YELLOW = (255, 214, 0)
AMBER = (246, 172, 0)
WHITE = (255, 255, 255)
BLACK = (12, 12, 14)
NAVY = (8, 22, 66)
BLUE = (0, 86, 196)
INK = (16, 22, 40)

LEAD_IN = 1.4          # seconds of stinger before the anchor starts speaking
TAIL = 0.6             # breathing room after the sign-off
KB = 1.14              # Ken Burns headroom on full-screen footage
XFADE = 0.6            # footage dissolve length
FLIP = 0.36            # super band flip length
DISPLAY_TZ = timezone.utc          # on-air times are global (UTC), not a local zone

# Every clip is encoded identically and YouTube-Live-ready (2 s keyframes, constant bitrate,
# stereo AAC) so the 24/7 streamer can splice clips with -c copy and never re-encode.
STREAM_ENCODE_ARGS = [
    "-c:v", "libx264", "-preset", "veryfast", "-profile:v", "high", "-level", "4.1",
    "-b:v", "4500k", "-maxrate", "4500k", "-bufsize", "9000k",
    "-g", str(VIDEO_FPS * 2), "-keyint_min", str(VIDEO_FPS * 2), "-sc_threshold", "0",
    "-pix_fmt", "yuv420p", "-r", str(VIDEO_FPS),
    "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2",
    "-movflags", "+faststart",
]

# Bottom graphics stack
TAB_Y, TAB_H = 770, 50
SUPER_Y, SUPER_H = 820, 124
STRAP_Y, STRAP_H = 944, 48
TICK_Y, TICK_H = 992, 48
BAR_Y, BAR_H = 1040, 40
SUPER_TEXT_X = 46

FONT_DIR = os.path.join(ASSETS_DIR, "fonts")      # bundled OFL fonts: identical look on Windows and Linux
IMAGES_DIR = os.path.join(ASSETS_DIR, "images")


# ----------------------------------------------------------------- helpers

@lru_cache(maxsize=None)
def font(name: str, size: int, variation: str = None) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(os.path.join(FONT_DIR, name), size)
    if variation:
        f.set_variation_by_name(variation)
    return f


def cond(size: int, weight: str = "Bold") -> ImageFont.FreeTypeFont:
    """Oswald: the heavy condensed caps look of Indian news supers."""
    return font("Oswald.ttf", size, weight)


def heavy(size: int) -> ImageFont.FreeTypeFont:
    return font("Montserrat.ttf", size, "Black")


def body(size: int) -> ImageFont.FreeTypeFont:
    return font("Montserrat.ttf", size, "SemiBold")


_EMOJI = re.compile("[\U00010000-\U0010FFFF\u2600-\u27BF\uFE0F\u200d\ufffd]")


def clean(text: str) -> str:
    """Drop emoji/pictographs the system fonts can't draw (they render as tofu boxes)."""
    return re.sub(r"\s+", " ", _EMOJI.sub("", text or "")).strip()


def wrap(text: str, fnt, max_w: int) -> list[str]:
    lines, cur = [], ""
    for word in clean(text).split():
        test = f"{cur} {word}".strip()
        if not cur or fnt.getlength(test) <= max_w:
            cur = test
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def fit_line(text: str, fnt, max_w: int) -> str:
    text = clean(text)
    if fnt.getlength(text) <= max_w:
        return text
    while text and fnt.getlength(text + "…") > max_w:
        text = text[:-1]
    return text.rstrip(" .,;:-") + "…"


def clause_cut(text: str, max_chars: int) -> str:
    """Shorten at a natural clause break instead of mid-sentence."""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    for sep in (", ", " — ", " – ", "; ", ": ", " as ", " but ", " after ", " and "):
        i = cut.rfind(sep)
        if i > max_chars * 0.45:
            return cut[:i].rstrip(" ,;:")
    return cut.rsplit(" ", 1)[0].rstrip(" ,;:") + "…"


def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def prog(t, start, dur):
    return clamp((t - start) / dur) if dur > 0 else float(t >= start)


def ease_out(p):
    return 1 - (1 - p) ** 3


def ease_in(p):
    return p ** 3


def ease_in_out(p):
    return 4 * p ** 3 if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2


def ease_back(p, s=1.4):
    p -= 1
    return 1 + (s + 1) * p ** 3 + s * p ** 2


def lerp(a, b, p):
    return a + (b - a) * p


@lru_cache(maxsize=256)
def _alpha_lut(a: float) -> list[int]:
    return [int(v * a) for v in range(256)]


def put(frame: Image.Image, sprite: Image.Image, x, y, alpha: float = 1.0, clip=None):
    """Paste an RGBA sprite with optional opacity, clipped to a box (default: frame)."""
    if alpha <= 0.01:
        return
    x, y = int(round(x)), int(round(y))
    cx0, cy0, cx1, cy1 = (int(v) for v in clip) if clip else (0, 0, W, H)
    sw, sh = sprite.size
    x0, y0 = max(x, cx0), max(y, cy0)
    x1, y1 = min(x + sw, cx1), min(y + sh, cy1)
    if x1 <= x0 or y1 <= y0:
        return
    sub = sprite if (x0, y0, x1, y1) == (x, y, x + sw, y + sh) else sprite.crop((x0 - x, y0 - y, x1 - x, y1 - y))
    if sub.mode == "RGBA":
        mask = sub.getchannel("A")
        if alpha < 0.99:
            mask = mask.point(_alpha_lut(round(alpha, 2)))
        frame.paste(sub, (x0, y0), mask)
    elif alpha < 0.99:
        frame.paste(sub, (x0, y0), Image.new("L", sub.size, int(255 * alpha)))
    else:
        frame.paste(sub, (x0, y0))


def rrect(size, radius, fill=(0, 0, 0, 0), outline=None, width=0, ss=3) -> Image.Image:
    """Anti-aliased rounded rectangle sprite (supersampled)."""
    w, h = size
    big = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
    ImageDraw.Draw(big).rounded_rectangle(
        [0, 0, w * ss - 1, h * ss - 1], radius * ss, fill=fill, outline=outline, width=width * ss
    )
    return big.resize((w, h), Image.LANCZOS)


def gradient(w: int, h: int, c1, c2, a1=255, a2=255, vertical=True) -> Image.Image:
    n = h if vertical else w
    p = np.linspace(0, 1, n)
    rgb = np.array(c1, float)[None, :] * (1 - p[:, None]) + np.array(c2, float)[None, :] * p[:, None]
    a = (a1 * (1 - p) + a2 * p)[:, None]
    line = np.concatenate([rgb, a], axis=1).astype(np.uint8)
    arr = np.repeat(line[:, None, :], w, axis=1) if vertical else np.repeat(line[None, :, :], h, axis=0)
    return Image.fromarray(arr, "RGBA")


def gloss(w: int, h: int, c1, c2) -> Image.Image:
    """Glossy broadcast band: vertical gradient, top highlight, crisp edges."""
    band = gradient(w, h, c1, c2)
    hi = gradient(w, h // 2, WHITE, WHITE, 70, 8)
    band.alpha_composite(hi, (0, 0))
    d = ImageDraw.Draw(band)
    d.line([(0, 0), (w, 0)], fill=(255, 255, 255, 150), width=1)
    d.line([(0, h - 2), (w, h - 2)], fill=(0, 0, 0, 120), width=2)
    return band


def shine_sprite(h: int) -> Image.Image:
    w = 70
    a = np.zeros((h, w), np.uint8)
    a[:] = (np.sin(np.linspace(0, math.pi, w)) ** 2 * 150).astype(np.uint8)
    img = Image.new("RGBA", (w, h), WHITE + (0,))
    img.putalpha(Image.fromarray(a))
    return img.transform((w + h // 3, h), Image.AFFINE, (1, -0.33, 0, 0, 1, 0), Image.BICUBIC)


def text_layer(lines: list[str], fnt, fill, line_h: int, size, align_y="center", stroke=0, shadow=True) -> Image.Image:
    """Render lines into a fixed-size sprite, vertically centred, with drop shadow."""
    w, h = size
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    asc, desc = fnt.getmetrics()
    block = line_h * (len(lines) - 1) + asc + desc
    y0 = (h - block) // 2 if align_y == "center" else 0
    if shadow:
        sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sh)
        for i, line in enumerate(lines):
            sd.text((3, y0 + i * line_h + 3), line, font=fnt, fill=(0, 0, 0, 170))
        img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(2)))
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        d.text((0, y0 + i * line_h), line, font=fnt, fill=fill, stroke_width=stroke, stroke_fill=BLACK)
    return img


_STOP = {
    "the", "a", "an", "of", "to", "for", "and", "or", "in", "on", "at", "by", "with", "is", "are", "was",
    "as", "its", "it", "this", "that", "from", "after", "over", "new", "will", "who", "has", "have",
    "says", "say", "said", "now", "no", "longer", "how", "why", "what", "here", "s",
}


def make_hashtag(title: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", clean(title).replace("’", "'").replace("'s ", " "))
    keep = [w for w in words if w.lower() not in _STOP and len(w) > 1]
    caps = [w for w in keep if w[0].isupper() or w[0].isdigit()]
    chosen = caps[:3] if len(caps) >= 2 else keep[:3]
    tag = ""
    for w in chosen:
        if len(tag) + len(w) > 15:
            break
        tag += w.upper()
    return "#" + (tag or "TECHNEWS")


def screen_points(story: dict) -> list[str]:
    """On-air points in phase order: the source's key points, then the analysis if any."""
    points = [clean(b) for b in (story.get("bullets") or []) if clean(b)]
    if clean(story.get("analysis", "")):
        points.append(clean(story["analysis"]))
    return points


def story_phase_count(story: dict) -> int:
    """Intro/headline phase plus one phase per on-air point."""
    return 1 + len(screen_points(story))


# ------------------------------------------------------------------ media

def story_photos(story: dict) -> list[Image.Image]:
    """Genuine article images only: no auto-generated crops, no icons/avatars."""
    paths = list(story.get("article_images") or [])
    if story.get("image_path"):
        paths.append(story["image_path"])
    sid = story.get("id", "")
    if sid:
        paths += [os.path.join(IMAGES_DIR, f"{sid}_img{i}.jpg") for i in range(6)]
    photos, seen = [], set()
    for p in paths:
        if not p or "_cam" in os.path.basename(p) or p in seen or not os.path.exists(p):
            continue
        seen.add(p)
        try:
            img = Image.open(p)
            img.load()
            img = img.convert("RGB")
        except Exception:
            continue
        if min(img.size) >= 200:
            photos.append(img)
    large = [im for im in photos if im.width >= 600]
    return large or photos


def make_plate(img: Image.Image, w: int, h: int) -> Image.Image:
    """Colour-graded full-screen footage plate. Odd shapes / small images sit on a blurred fill."""
    pw, ph = int(w * KB), int(h * KB)
    aspect = img.width / img.height
    if abs(math.log(aspect / (pw / ph))) > 0.28 or img.width < pw * 0.42:
        back = ImageOps.fit(img, (pw // 8, ph // 8)).filter(ImageFilter.GaussianBlur(3))
        back = ImageEnhance.Brightness(back.resize((pw, ph), Image.BICUBIC)).enhance(0.45)
        scale = min(pw * 0.86 / img.width, ph * 0.72 / img.height, 2.6)
        fg = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
        fx, fy = (pw - fg.width) // 2, int((ph * 0.8 - fg.height) / 2)
        shadow = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rectangle([fx + 8, fy + 12, fx + fg.width + 8, fy + fg.height + 12], fill=(0, 0, 0, 200))
        plate = Image.alpha_composite(back.convert("RGBA"), shadow.filter(ImageFilter.GaussianBlur(18))).convert("RGB")
        plate.paste(fg, (fx, fy))
    else:
        plate = ImageOps.fit(img, (pw, ph), Image.LANCZOS, centering=(0.5, 0.4))
    plate = ImageEnhance.Contrast(plate).enhance(1.08)
    plate = ImageEnhance.Color(plate).enhance(1.15)
    if img.width < pw:
        plate = plate.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2))
    return plate


def placeholder_plate(w: int, h: int) -> Image.Image:
    pw, ph = int(w * KB), int(h * KB)
    yy, xx = np.mgrid[0:ph, 0:pw]
    r = np.clip(np.hypot((xx - pw / 2) / pw, (yy - ph / 2) / ph) * 1.6, 0, 1)[..., None]
    arr = np.array(BLUE, float) * (1 - r) + np.array(NAVY, float) * r
    return Image.fromarray(arr.astype(np.uint8), "RGB")


# Slow camera moves: (dx, dy, zoom_in)
CAMERA_MOVES = [(-1, -0.3, True), (1, 0.4, False), (0.5, -1, True), (-0.7, 0.8, False), (0, 0, True)]


def ken_burns(plate: Image.Image, w: int, h: int, p: float, move: int) -> Image.Image:
    pw, ph = plate.size
    dx, dy, zoom_in = CAMERA_MOVES[move % len(CAMERA_MOVES)]
    z = lerp(1.0, KB, p) if zoom_in else lerp(KB, 1.02, p)
    vw, vh = pw / z, ph / z
    sx, sy = (pw - vw) / 2, (ph - vh) / 2
    drift = lerp(-0.8, 0.8, p)
    cx = clamp(pw / 2 + dx * sx * drift, vw / 2, pw - vw / 2)
    cy = clamp(ph / 2 + dy * sy * drift, vh / 2, ph - vh / 2)
    return plate.resize((w, h), Image.BILINEAR, box=(cx - vw / 2, cy - vh / 2, cx + vw / 2, cy + vh / 2))


# ------------------------------------------------------------------ scene

class NewsScene:
    def __init__(self, story: dict, ticker_text: str, phase_durations: list[float]):
        self.story = story
        self.durs = list(phase_durations)
        self.starts = [sum(self.durs[:i]) for i in range(len(self.durs))]
        self.total = sum(self.durs)
        self.title = clean(story.get("title", ""))
        self.points = screen_points(story)[: len(self.durs) - 1]
        self.analysis_phase = len(self.points) if story.get("analysis") and len(self.points) == len(self.durs) - 1 else -1
        self.outlet = clean(story.get("outlet") or story.get("source") or "").upper()
        self.category = clean(story.get("category") or "TECHNOLOGY").upper()
        # Fresh stories only are "BREAKING"; the bar shows the story's real publish time, not a fake live clock
        self.breaking = bool(story.get("is_breaking"))
        self.tag_words = ("BREAKING", "NEWS") if self.breaking else ("BIG", "STORY")
        try:
            self.published = datetime.fromisoformat(story.get("published_ts", "")).astimezone(DISPLAY_TZ)
        except ValueError:
            self.published = None

        photos = story_photos(story)
        self.plates = [make_plate(p, W, H) for p in photos[:5]] or [placeholder_plate(W, H)]
        self._plan_shots()
        self._build_overlays()
        self._build_logo()
        self._build_hashtag()
        self._build_tab()
        self._build_super()
        self._build_strap()
        self._build_ticker(ticker_text)
        self._build_bottom_bar()
        self._build_sting()

    # ---- static assets

    def _plan_shots(self):
        """One shot per phase; long phases get a second angle so the picture keeps moving."""
        self.shots = []
        k = 0
        for s, d in zip(self.starts, self.durs):
            n = 2 if d > 9 else 1
            for j in range(n):
                self.shots.append((s + d * j / n, d / n, k % len(self.plates), k))
                k += 1

    def _build_overlays(self):
        self.bottom_shade = gradient(W, 380, BLACK, BLACK, 0, 200)
        self.top_shade = gradient(W, 170, BLACK, BLACK, 130, 0)
        self.shine_tall = shine_sprite(SUPER_H)
        self.shine_mid = shine_sprite(120)

    def _build_logo(self):
        lw, lh = 176, 118
        logo = Image.new("RGBA", (lw + 30, lh + 30), (0, 0, 0, 0))
        sh = Image.new("RGBA", logo.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).rectangle([15, 21, 15 + lw, 21 + lh], fill=(0, 0, 0, 160))
        logo.alpha_composite(sh.filter(ImageFilter.GaussianBlur(8)))
        body = gloss(lw, lh, (236, 30, 40), (150, 0, 12))
        d = ImageDraw.Draw(body)
        d.rectangle([0, lh - 38, lw, lh], fill=WHITE + (255,))
        d.text((lw // 2, (lh - 38) // 2 + 2), "AIT", font=heavy(66), fill=WHITE, anchor="mm")
        d.text((lw // 2, lh - 19), "NEWS", font=cond(32), fill=RED, anchor="mm")
        d.rectangle([0, 0, lw - 1, lh - 1], outline=(255, 255, 255, 230), width=3)
        logo.alpha_composite(body, (15, 15))
        self.logo = logo
        self.logo_pos = (W - 48 - lw - 15, 34 - 15)
        self.logo_body = (W - 48 - lw, 34, W - 48, 34 + lh)

        live = gloss(110, 40, (40, 40, 44), (10, 10, 12))
        ImageDraw.Draw(live).text((70, 20), "LIVE", font=cond(28), fill=WHITE, anchor="mm")
        self.live = live
        self.live_pos = (W - 48 - 110, 34 + lh + 10)

    def _build_hashtag(self):
        tag = make_hashtag(self.title)
        f = cond(46)
        tw = int(f.getlength(tag[1:])) + 44
        h = 70
        hs = Image.new("RGBA", (h + tw, h), (0, 0, 0, 0))
        sq = gloss(h, h, (255, 224, 40), AMBER)
        ImageDraw.Draw(sq).text((h // 2, h // 2 + 2), "#", font=cond(54), fill=BLACK, anchor="mm")
        band = gloss(tw, h, (236, 30, 40), (150, 0, 12))
        ImageDraw.Draw(band).text((20, h // 2 + 2), tag[1:], font=f, fill=WHITE, anchor="lm")
        hs.alpha_composite(sq, (0, 0))
        hs.alpha_composite(band, (h, 0))
        self.hashtag = hs
        self.hashtag_pos = (48, 46)

    def _build_tab(self):
        f = cond(34)
        label = " ".join(self.tag_words)
        tw = int(f.getlength(label)) + 44
        a = gloss(tw, TAB_H, (255, 224, 40), AMBER)
        ImageDraw.Draw(a).text((tw // 2, TAB_H // 2 + 2), label, font=f, fill=(150, 0, 12), anchor="mm")
        b = gloss(tw, TAB_H, (236, 30, 40), (150, 0, 12))
        ImageDraw.Draw(b).text((tw // 2, TAB_H // 2 + 2), label, font=f, fill=WHITE, anchor="mm")
        self.tab_flash = [a, b]
        info = f"{self.category}   |   {self.outlet}" if self.outlet else self.category
        f_info = cond(28, "SemiBold")
        iw = int(f_info.getlength(info)) + 50
        band = gloss(iw, TAB_H, (18, 40, 110), NAVY)
        ImageDraw.Draw(band).text((24, TAB_H // 2 + 1), info, font=f_info, fill=WHITE, anchor="lm")
        self.tab_info = band
        self.tab_w = tw

    def _super_sprite(self, text: str) -> Image.Image:
        max_w = W - SUPER_TEXT_X * 2 - 20
        text = clean(text).upper()
        size = (max_w, SUPER_H)
        for s in (66, 60, 54):
            f = cond(s)
            if f.getlength(text) <= max_w:
                return text_layer([text], f, WHITE, s, size)
        for s in (46, 42, 39, 36):
            f = cond(s)
            lines = wrap(text, f, max_w)
            if len(lines) <= 2:
                return text_layer(lines, f, WHITE, int(s * 1.22), size)
        f = cond(36)
        lines = wrap(clause_cut(text, 160), f, max_w)[:2]
        lines[-1] = fit_line(lines[-1], f, max_w)
        return text_layer(lines, f, WHITE, 44, size)

    def _build_super(self):
        band = gloss(W, SUPER_H, (226, 24, 36), DARK_RED)
        d = ImageDraw.Draw(band)
        d.rectangle([0, 0, 14, SUPER_H], fill=YELLOW + (255,))
        d.line([(0, 2), (W, 2)], fill=(255, 210, 90, 160), width=2)
        self.super_band = band
        self.super_texts = [self._super_sprite(self.title)] + [self._super_sprite(p) for p in self.points]

    def _build_strap(self):
        band = gloss(W, STRAP_H, (255, 226, 50), AMBER)
        self.strap_band = band
        f = cond(32)
        max_w = W - 90
        intro = f"{self.category}  •  {self.outlet}" if self.outlet else self.category
        topic = fit_line(clause_cut(self.title, 90).upper(), f, max_w)
        sprites = {}
        self.strap_texts = []
        for phase in range(len(self.durs)):
            txt = intro if phase == 0 else ("WHAT IT MEANS" if phase == self.analysis_phase else topic)
            if txt not in sprites:                       # same text -> same sprite, so it doesn't re-slide
                sprites[txt] = text_layer([txt.upper()], f, BLACK, 32, (max_w, STRAP_H), shadow=False)
            self.strap_texts.append(sprites[txt])

    def _build_ticker(self, ticker_text: str):
        bg = Image.new("RGBA", (W, TICK_H), (246, 246, 248, 255))
        label = gloss(240, TICK_H, (236, 30, 40), (150, 0, 12))
        ImageDraw.Draw(label).text((120, TICK_H // 2 + 1), "NEWS ALERT", font=cond(30), fill=WHITE, anchor="mm")
        bg.alpha_composite(label)
        notch = Image.new("RGBA", (18, TICK_H), (0, 0, 0, 0))
        ImageDraw.Draw(notch).polygon([(0, 0), (18, TICK_H // 2), (0, TICK_H)], fill=(190, 10, 22, 255))
        bg.alpha_composite(notch, (240, 0))
        self.ticker_bg = bg

        f_title = body(27)
        self.headlines = []
        for raw in (ticker_text or "").split("   •   "):
            raw = clean(raw)
            if raw:
                _, _, title = raw.partition(": ")
                self.headlines.append(title or raw)
        if not self.headlines:
            self.headlines = [self.title]
        widths = [f_title.getlength(t) + 70 for t in self.headlines]
        sw = max(int(sum(widths)) + 10, W)
        strip = Image.new("RGBA", (sw, TICK_H), (0, 0, 0, 0))
        d = ImageDraw.Draw(strip)
        cx = 0.0
        cy = TICK_H // 2 + 1
        for t in self.headlines:
            d.text((cx, cy), t, font=f_title, fill=INK, anchor="lm")
            cx += f_title.getlength(t) + 35
            d.rectangle([cx - 6, cy - 6, cx + 6, cy + 6], fill=RED + (255,))
            cx += 35
        self.ticker_strip = strip
        self.ticker_w = sw

    def _build_bottom_bar(self):
        bar = gloss(W, BAR_H, (20, 44, 120), NAVY)
        lbl = gloss(220, BAR_H, (0, 110, 230), BLUE)
        ImageDraw.Draw(lbl).text((110, BAR_H // 2 + 1), "TOP HEADLINES", font=cond(24), fill=WHITE, anchor="mm")
        bar.alpha_composite(lbl)
        self.bar = bar
        self.clock_box = gloss(250, BAR_H, (236, 30, 40), (150, 0, 12))
        f = cond(24, "SemiBold")
        max_w = W - 220 - 250 - 50
        self.bar_heads = [text_layer([fit_line(h.upper(), f, max_w)], f, WHITE, 24, (max_w, BAR_H), shadow=False)
                          for h in self.headlines[:10]]
        self.f_clock = cond(26)

    def _build_sting(self):
        yy, xx = np.mgrid[0:H, 0:W]
        r = np.clip(np.hypot((xx - W / 2) / (W / 2), (yy - H / 2) / (H / 2)) / 1.25, 0, 1)[..., None]
        arr = np.array((236, 34, 30), float) * (1 - r) + np.array((58, 0, 6), float) * r
        self.sting_bg = Image.fromarray(arr.astype(np.uint8), "RGB")
        s = 2300
        rays = Image.new("L", (s, s), 0)
        d = ImageDraw.Draw(rays)
        for k in range(24):
            d.pieslice([0, 0, s, s], k * 15, k * 15 + 6, fill=34)
        self.sting_rays = rays.filter(ImageFilter.GaussianBlur(5))

        f = heavy(200)
        word, box_word = self.tag_words
        bw = int(f.getlength(word)) + 60
        brk = Image.new("RGBA", (bw, 260), (0, 0, 0, 0))
        sh = Image.new("RGBA", brk.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).text((38, 38), word, font=f, fill=(0, 0, 0, 200))
        brk.alpha_composite(sh.filter(ImageFilter.GaussianBlur(8)))
        ImageDraw.Draw(brk).text((30, 20), word, font=f, fill=WHITE, stroke_width=5, stroke_fill=(110, 0, 8))
        self.sting_breaking = brk
        nf = heavy(150)
        nw = int(nf.getlength(box_word)) + 90
        news = gloss(nw, 190, (255, 228, 50), AMBER)
        ImageDraw.Draw(news).text((nw // 2, 92), box_word, font=nf, fill=(150, 0, 12), anchor="mm")
        self.sting_news = news

    # ---- per-frame

    def phase_at(self, t: float) -> int:
        idx = 0
        for i, s in enumerate(self.starts):
            if t >= s:
                idx = i
        return idx

    def _shot_frame(self, i: int, t: float) -> Image.Image:
        start, dur, plate_idx, move = self.shots[i]
        p = clamp((t - start) / max(0.1, dur), 0, 1.15)
        return ken_burns(self.plates[plate_idx], W, H, p, move)

    def render(self, t: float) -> Image.Image:
        if t < 1.0:
            return self._sting_frame(t)

        i = 0
        for k, shot in enumerate(self.shots):
            if t >= shot[0]:
                i = k
        frame = self._shot_frame(i, t)
        if i > 0 and t - self.shots[i][0] < XFADE:
            old = self._shot_frame(i - 1, t)
            frame = Image.blend(old, frame, ease_in_out((t - self.shots[i][0]) / XFADE))

        put(frame, self.top_shade, 0, 0)
        put(frame, self.bottom_shade, 0, H - 380)
        phase = self.phase_at(t)
        d = ImageDraw.Draw(frame)
        self._draw_logo(frame, d, t)
        self._draw_hashtag(frame, t)
        self._draw_bottom_bar(frame, d, t)
        self._draw_ticker(frame, t)
        self._draw_strap(frame, t, phase)
        self._draw_super(frame, d, t, phase)
        self._draw_tab(frame, t, phase)

        if t < 1.45:
            sting = self._sting_frame(t)
            e = ease_in(prog(t, 1.0, 0.45))
            edge = lerp(W + 320, -320, e)
            mask = Image.new("L", (W, H), 0)
            ImageDraw.Draw(mask).polygon([(0, 0), (edge + 160, 0), (edge - 160, H), (0, H)], fill=255)
            frame.paste(sting, (0, 0), mask)
            d.polygon([(edge + 160, 0), (edge + 210, 0), (edge - 110, H), (edge - 160, H)], fill=YELLOW)
            d.polygon([(edge + 210, 0), (edge + 222, 0), (edge - 98, H), (edge - 110, H)], fill=WHITE)
        return frame

    def _sting_frame(self, t: float) -> Image.Image:
        img = self.sting_bg.copy()
        s = self.sting_rays.size[0]
        rays = self.sting_rays.rotate(t * 28, resample=Image.BILINEAR)
        ox, oy = (s - W) // 2, (s - H) // 2
        img.paste((255, 190, 170), (0, 0, W, H), rays.crop((ox, oy, ox + W, oy + H)))

        p = ease_out(prog(t, 0.0, 0.33))
        scale = lerp(2.6, 1.0, p) * (1 + 0.035 * t)
        b = self.sting_breaking
        bw, bh = int(b.width * scale), int(b.height * scale)
        put(img, b.resize((bw, bh), Image.BILINEAR), W / 2 - bw / 2, H / 2 - 170 - bh / 2 + 40, alpha=prog(t, 0, 0.1))
        pn = ease_back(prog(t, 0.28, 0.32))
        n = self.sting_news
        nscale = 1 + 0.035 * t
        nw, nh = int(n.width * nscale), int(n.height * nscale)
        put(img, n.resize((nw, nh), Image.BILINEAR), lerp(W + 50, W / 2 - nw / 2, pn), H / 2 + 60)
        flash = 1 - prog(t, 0.33, 0.25)
        if 0.33 <= t and flash > 0:
            img = Image.blend(img, Image.new("RGB", (W, H), WHITE), 0.65 * flash)
        return img

    def _draw_logo(self, frame, d, t):
        e = ease_out(prog(t, 1.15, 0.45))
        dx = 320 * (1 - e)
        put(frame, self.logo, self.logo_pos[0] + dx, self.logo_pos[1])
        shine_t = (t - 2.0) % 6.0
        if t > 2.0 and shine_t < 0.7:
            x0, y0, x1, y1 = self.logo_body
            sx = lerp(x0 - 90, x1 + 10, shine_t / 0.7)
            put(frame, self.shine_mid, sx + dx, y0, clip=(x0 + dx, y0, x1 + dx, y1))
        lx, ly = self.live_pos
        put(frame, self.live, lx + dx, ly)
        if (t % 1.0) < 0.6:
            d.ellipse([lx + dx + 14, ly + 13, lx + dx + 28, ly + 27], fill=(255, 40, 40))

    def _draw_hashtag(self, frame, t):
        e = ease_back(prog(t, 1.25, 0.5))
        x, y = self.hashtag_pos
        hx = x - (self.hashtag.width + 60) * (1 - e)
        put(frame, self.hashtag, hx, y)
        shine_t = (t - 3.0) % 7.0
        if t > 3.0 and shine_t < 0.8:
            sx = lerp(hx - 90, hx + self.hashtag.width, shine_t / 0.8)
            put(frame, self.shine_mid, sx, y - 20, clip=(hx, y, hx + self.hashtag.width, y + self.hashtag.height))

    def _rise(self, t, start, y):
        return (H - y + 10) * (1 - ease_out(prog(t, start, 0.4)))

    def _draw_bottom_bar(self, frame, d, t):
        dy = self._rise(t, 1.0, BAR_Y)
        put(frame, self.bar, 0, BAR_Y + dy)
        idx = int(max(0.0, t - 1.6) // 4.5)
        local = max(0.0, t - 1.6) % 4.5
        clip = (230, BAR_Y + int(dy), W - 260, H)
        cur = self.bar_heads[idx % len(self.bar_heads)]
        if local < 0.35 and t > 1.6 + 4.5:
            e = ease_in_out(local / 0.35)
            prev = self.bar_heads[(idx - 1) % len(self.bar_heads)]
            put(frame, prev, 244, BAR_Y + dy - BAR_H * e, clip=clip)
            put(frame, cur, 244, BAR_Y + dy + BAR_H * (1 - e), clip=clip)
        else:
            put(frame, cur, 244, BAR_Y + dy, clip=clip)
        cx = W - 250
        put(frame, self.clock_box, cx, BAR_Y + dy)
        stamp = self.published.strftime("UPDATED %H:%M UTC") if self.published else ""
        d.text((cx + 125, BAR_Y + dy + BAR_H // 2 + 1), stamp, font=self.f_clock, fill=WHITE, anchor="mm")

    def _draw_ticker(self, frame, t):
        dy = self._rise(t, 1.05, TICK_Y)
        put(frame, self.ticker_bg, 0, TICK_Y + dy)
        offset = max(0.0, t - 1.3) * 150 % self.ticker_w
        clip = (262, TICK_Y + int(dy), W, TICK_Y + int(dy) + TICK_H)
        sx = 290 - offset
        while sx < W:
            put(frame, self.ticker_strip, sx, TICK_Y + dy, clip=clip)
            sx += self.ticker_w

    def _draw_strap(self, frame, t, phase):
        dy = self._rise(t, 1.12, STRAP_Y)
        put(frame, self.strap_band, 0, STRAP_Y + dy)
        clip = (30, STRAP_Y + int(dy), W - 30, STRAP_Y + int(dy) + STRAP_H)
        x = SUPER_TEXT_X
        switch = prog(t, self.starts[phase], 0.45) if phase > 0 else 1.0
        if switch < 1.0 and self.strap_texts[phase - 1] is not self.strap_texts[phase]:
            e = ease_in_out(switch)
            put(frame, self.strap_texts[phase - 1], x - W * e, STRAP_Y + dy, clip=clip)
            put(frame, self.strap_texts[phase], x + W * (1 - e), STRAP_Y + dy, clip=clip)
        else:
            e = ease_out(prog(t, 1.5, 0.4))
            put(frame, self.strap_texts[phase], x + 80 * (1 - e), STRAP_Y + dy, alpha=e, clip=clip)

    def _draw_super(self, frame, d, t, phase):
        dy = self._rise(t, 1.18, SUPER_Y)
        y = SUPER_Y + dy
        reveal = ease_out(prog(t, 1.18, 0.5))
        put(frame, self.super_band, 0, y, clip=(0, y, W * reveal, y + SUPER_H))
        txt_idx = min(phase, len(self.super_texts) - 1)
        prev_idx = min(phase - 1, len(self.super_texts) - 1)
        flip = prog(t, self.starts[phase], FLIP) if phase > 0 and prev_idx != txt_idx else 1.0
        if flip < 1.0:
            if flip < 0.5:
                spr, s = self.super_texts[prev_idx], 1 - ease_in(flip * 2)
            else:
                spr, s = self.super_texts[txt_idx], ease_out((flip - 0.5) * 2)
        else:
            spr, s = self.super_texts[txt_idx], ease_out(prog(t, 1.5, 0.3))
        if s > 0.02:
            sh = max(1, int(SUPER_H * s))
            put(frame, spr.resize((spr.width, sh), Image.BILINEAR), SUPER_TEXT_X, y + (SUPER_H - sh) / 2)
        if flip < 1.0:
            glow = 1 - abs(flip - 0.5) * 2
            d.rectangle([0, y + SUPER_H / 2 - 2, W, y + SUPER_H / 2 + 2],
                        fill=tuple(int(lerp(c, 255, glow)) for c in (226, 24, 36)))
        shine_t = (t - 2.6) % 5.5
        if t > 2.6 and shine_t < 0.9:
            sx = lerp(-120, W + 40, shine_t / 0.9)
            put(frame, self.shine_tall, sx, y, clip=(0, y, W, y + SUPER_H))

    def _draw_tab(self, frame, t, phase):
        e = ease_back(prog(t, 1.4, 0.4))
        y = TAB_Y + self._rise(t, 1.18, SUPER_Y)
        x = -self.tab_w * (1 - e)
        flashing = self.breaking and (phase == 0 or prog(t, self.starts[phase], 1.2) < 1.0)
        tab = self.tab_flash[int(t / 0.42) % 2] if flashing and t > 1.8 else self.tab_flash[1]
        ie = ease_out(prog(t, 1.6, 0.4))
        put(frame, self.tab_info, self.tab_w - (self.tab_info.width) * (1 - ie), y,
            clip=(self.tab_w, y, W, y + TAB_H))
        put(frame, tab, x, y)


# ----------------------------------------------------------------- render

def render_animated_story(
    story: dict,
    audio_path: str,
    duration: float,
    ticker_text: str,
    output_video_path: str,
    phase_durations: list[float],
) -> str:
    """Render one story. The anchor starts after a LEAD_IN stinger; phases shift accordingly."""
    durs = on_air_durations(phase_durations)
    scene = NewsScene(story, ticker_text, durs)
    return encode_scene(scene, (W, H), audio_path, sum(durs), output_video_path, story.get("id", "story"))


def on_air_durations(phase_durations: list[float]) -> list[float]:
    """Voice phase lengths plus the stinger before the anchor and the breathing room after."""
    durs = list(phase_durations)
    durs[0] += LEAD_IN
    durs[-1] += TAIL
    return durs


def encode_scene(scene, size: tuple, audio_path: str, total: float, output_video_path: str, tag: str) -> str:
    """Pipe a scene's frames into FFmpeg with the broadcast audio mix (voice chain, ducked bed, SFX)."""
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    width, height = size
    n_frames = int(math.ceil(total * FPS))
    sfx_path = os.path.join(OUTPUT_DIR, f"temp_sfx_{tag}_{width}x{height}.wav")
    build_sfx_track(sfx_path, total, impact_at=0.33, exit_at=1.0, flip_times=scene.starts[1:])

    delay_ms = int(LEAD_IN * 1000)
    audio_filter = (
        # Broadcast voice chain: rumble cut, gentle compression, presence lift, subtle room
        f"[1:a]aresample=44100,highpass=f=75,"
        f"acompressor=threshold=0.125:ratio=3:attack=5:release=90:makeup=1.6,"
        f"equalizer=f=180:t=q:w=1:g=1.5,equalizer=f=3200:t=q:w=1.2:g=2.5,"
        f"aecho=0.8:0.85:22|37:0.06|0.04,"
        f"adelay={delay_ms}:all=1,apad[vox];"
        f"[vox]asplit=2[vox1][vox2];"
        f"[2:a]aresample=44100,volume=0.30[bed];"
        f"[bed][vox2]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=450[bedd];"
        f"[3:a]aresample=44100,volume=0.85[fx];"
        f"[vox1][bedd][fx]amix=inputs=3:duration=longest:normalize=0,"
        f"alimiter=limit=0.95,afade=t=out:st={max(0.0, total - 0.5):.2f}:d=0.5[aout]"
    )
    cmd = [
        ffmpeg_exe, "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", str(FPS), "-i", "-",
        "-i", audio_path,
        "-stream_loop", "-1", "-i", ensure_news_bed(),
        "-i", sfx_path,
        "-filter_complex", audio_filter,
        "-map", "0:v", "-map", "[aout]",
        "-t", f"{total:.3f}",
        *STREAM_ENCODE_ARGS,
        output_video_path,
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for f in range(n_frames):
            proc.stdin.write(scene.render(f / FPS).tobytes())
    finally:
        proc.stdin.close()
        proc.wait()
        try:
            os.remove(sfx_path)
        except OSError:
            pass
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg exited with code {proc.returncode} while encoding {output_video_path}")
    return output_video_path


def render_preview_frame(story: dict, t: float, output_path: str, ticker_text: str = "") -> str:
    """Render a single still of the animated scene (handy for quick look checks)."""
    n_points = len(screen_points(story))
    durs = [6.0 + LEAD_IN] + [7.0] * n_points
    NewsScene(story, ticker_text, durs).render(t).save(output_path)
    return output_path


def render_thumbnail(story: dict, output_path: str) -> str:
    """1280x720 YouTube thumbnail in a calm, BBC-like editorial style (AIT branding)."""
    tw, th = 1280, 720
    pad = 56
    photos = story_photos(story)
    if photos:
        img = ImageOps.fit(photos[0], (tw, th), Image.LANCZOS, centering=(0.5, 0.4))
        img = ImageEnhance.Contrast(img).enhance(1.05)            # natural colour, no heavy grading
    else:
        img = placeholder_plate(tw, th).resize((tw, th))
    img = img.convert("RGBA")
    # Eased bottom shade: text stays readable even over white backgrounds
    shade_h = 560
    a = (np.linspace(0, 1, shade_h) ** 0.55 * 225).astype(np.uint8)
    shade = Image.new("RGBA", (tw, shade_h), BLACK + (0,))
    shade.putalpha(Image.fromarray(np.repeat(a[:, None], tw, axis=1)))
    img.alpha_composite(shade, (0, th - shade_h))
    img.alpha_composite(gradient(tw, 150, BLACK, BLACK, 110, 0), (0, 0))

    # Flat, minimal brand mark: red AIT block + dark NEWS block
    f_logo = font("Montserrat.ttf", 34, "ExtraBold")
    f_news = font("Montserrat.ttf", 34, "Bold")
    mark_w = int(f_logo.getlength("AIT")) + 28
    news_w = int(f_news.getlength("NEWS")) + 28
    logo_layer = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    ld = ImageDraw.Draw(logo_layer)
    ld.rectangle([pad, 44, pad + mark_w, 96], fill=RED + (255,))
    ld.rectangle([pad + mark_w, 44, pad + mark_w + news_w, 96], fill=(15, 15, 18, 200))
    ld.text((pad + mark_w // 2, 70), "AIT", font=f_logo, fill=WHITE, anchor="mm")
    ld.text((pad + mark_w + news_w // 2, 70), "NEWS", font=f_news, fill=WHITE, anchor="mm")
    img.alpha_composite(logo_layer)

    # Sentence-case headline, white, soft shadow, no outlines
    title = clause_cut(clean(story.get("title", "")), 72)
    lines, f = [], None
    for size in (74, 68, 62, 56, 50):
        f = font("Montserrat.ttf", size, "ExtraBold")
        lines = wrap(title, f, tw - pad * 2)
        if len(lines) <= 3:
            break
    lines = lines[:3]
    lh = int(f.size * 1.18)
    y = th - pad - lh * len(lines) + 8
    shadow = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    for i, line in enumerate(lines):
        sd.text((pad + 2, y + i * lh + 3), line, font=f, fill=(0, 0, 0, 170))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(4)))
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        d.text((pad, y + i * lh), line, font=f, fill=WHITE)

    # Red accent + kicker (BREAKING for fresh stories, else the topic), like an editorial label
    f_kick = font("Montserrat.ttf", 28, "Bold")
    kicker = "BREAKING" if story.get("is_breaking") else clean(story.get("category", "Technology")).title()
    ky = y - 58
    if story.get("is_breaking"):
        kw = int(f_kick.getlength(kicker)) + 28
        d.rectangle([pad, ky, pad + kw, ky + 42], fill=RED)
        d.text((pad + kw // 2, ky + 21), kicker, font=f_kick, fill=WHITE, anchor="mm")
    else:
        ks = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
        ImageDraw.Draw(ks).text((pad + 24, ky + 23), kicker, font=f_kick, fill=(0, 0, 0, 200), anchor="lm")
        img.alpha_composite(ks.filter(ImageFilter.GaussianBlur(3)))
        d = ImageDraw.Draw(img)
        d.rectangle([pad, ky + 6, pad + 8, ky + 36], fill=RED)
        d.text((pad + 22, ky + 21), kicker, font=f_kick, fill=WHITE, anchor="lm")
    img.convert("RGB").save(output_path, "JPEG", quality=92)
    return output_path
