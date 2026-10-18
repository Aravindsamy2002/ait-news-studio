"""
Daily long-form "Tech News Today" bulletin: the day's top stories in one video with chapters.

Reuses the already-rendered 16:9 story clips (identical stream-ready encoding, so they join
with -c copy and nothing is re-rendered), wrapped in a voiced intro and outro card.

    python bulletin.py --out output/bulletins/2026-10-18.mp4
writes the video, its thumbnail and a .json with title / description / tags / chapters.
"""
import argparse
import json
import os
import re
import subprocess
import time
from datetime import datetime, timedelta, timezone

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageOps

from config import BULLETIN_ROUNDUP, BULLETIN_STORIES, CLIPS_DIR, DEFAULT_VOICE
from motion_renderer import (
    BLACK, LEAD_IN, NAVY, RED, TAIL, W, H, WHITE, YELLOW,
    clean, clause_cut, cond, ease_back, ease_out, encode_scene, fit_line, font, gradient, heavy,
    on_air_durations, prog, put, story_photos, wrap,
)

MIN_CLIP_SECONDS = 12          # YouTube chapters must be at least 10 s long
INTRO_TEXT = "This is AIT News. Here are today's top stories in technology."
OUTRO_TEXT = "That's all for today. Follow AIT for the latest technology news, every day."


def log(msg: str):
    print(time.strftime("[%H:%M:%S] ") + f"[bulletin] {msg}", flush=True)


def _duration(path: str) -> float:
    from voice_engine import get_audio_duration
    return get_audio_duration(path)


# ------------------------------------------------------------------ choose the day's stories

def pick_clips(limit: int = BULLETIN_STORIES) -> list[dict]:
    """Latest rendered version of each story from the last 24 hours, breaking first, then newest."""
    from fetcher import get_cached_news

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    allowed = {s["id"] for s in get_cached_news()}        # today's filtered story list (non-news/off-topic removed)
    best = {}
    for name in os.listdir(CLIPS_DIR):
        if not name.endswith(".json") or name.startswith("standby"):
            continue
        meta_path = os.path.join(CLIPS_DIR, name)
        clip = meta_path[:-5] + ".mp4"
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            published = datetime.fromisoformat(meta["story"]["published_ts"])
        except Exception:
            continue                                    # clips from before stories were stored
        if not os.path.exists(clip) or published < cutoff or meta["id"] not in allowed:
            continue
        duration = _duration(clip)
        if duration < MIN_CLIP_SECONDS:
            continue
        sid = meta["id"]
        if sid not in best or meta.get("rendered_at", 0) > best[sid]["rendered_at"]:
            best[sid] = {"clip": clip, "story": meta["story"], "duration": duration,
                         "rendered_at": meta.get("rendered_at", 0), "published": published}
    items = sorted(best.values(), key=lambda x: importance(x["story"], x["published"]), reverse=True)
    picked = []
    for it in items:                                      # one story per topic: no three Meta-scraping items
        if not any(same_topic(it["story"], p["story"]) for p in picked):
            picked.append(it)
        if len(picked) >= limit:
            break
    return picked


_STOP = {"that", "this", "with", "from", "have", "after", "over", "into", "about", "says", "said", "will",
         "would", "could", "their", "which", "while", "they", "them", "more", "than", "news", "report", "reports"}


def _stems(text: str) -> set[str]:
    return {w.lower()[:5] for w in re.findall(r"[A-Za-z][A-Za-z'’\-]+", text) if len(w) > 3 and w.lower() not in _STOP}


def same_topic(a: dict, b: dict) -> bool:
    """Two outlets covering one event: overlapping key words, or the same company plus shared details."""
    ta = _stems(a["title"] + " " + " ".join((a.get("bullets") or [])[:1]))
    tb = _stems(b["title"] + " " + " ".join((b.get("bullets") or [])[:1]))
    if ta and tb and len(ta & tb) / len(ta | tb) >= 0.25:
        return True
    names_a = {m.group(0).lower() for m in _MAJOR.finditer(a["title"])}
    names_b = {m.group(0).lower() for m in _MAJOR.finditer(b["title"])}
    return bool(names_a & names_b) and len((ta & tb) - {n[:5] for n in names_a}) >= 2


# Companies whose news most viewers care about; a story about them leads ahead of a small funding round
_MAJOR = re.compile(r"\b(openai|chatgpt|google|gemini|alphabet|apple|iphone|meta|facebook|instagram|whatsapp|"
                    r"microsoft|windows|amazon|aws|nvidia|anthropic|claude|tesla|musk|spacex|samsung|tiktok|"
                    r"netflix|intel|amd|tsmc|qualcomm|x\.com|youtube|deepseek|sony|nintendo)\b", re.I)


def importance(story: dict, published: datetime) -> float:
    """Lead with what matters most: big names, wide coverage, fresh/breaking, then recency."""
    from fetcher import _title_tokens, get_cached_news

    title = clean(story.get("title", ""))
    score = 2.0 if _MAJOR.search(title) else 0.0
    tokens = _title_tokens(title)
    others = [_title_tokens(s["title"]) for s in get_cached_news() if s.get("id") != story.get("id")]
    score += min(2.0, 0.7 * sum(1 for o in others if tokens and len(tokens & o) / len(tokens | o) >= 0.25))
    if story.get("is_breaking"):
        score += 1.0
    age_h = (datetime.now(timezone.utc) - published).total_seconds() / 3600
    return score + max(0.0, 1.0 - age_h / 24)


def short_headline(title: str, max_chars: int) -> str:
    """Headline for titles/thumbnails: drop ', which ... ,' style asides, then cut at a natural break."""
    t = re.sub(r",\s*(which|who|whose|behind|maker of|owner of|the company behind|a company that|an? \w+ that)\b[^,]*,", "", clean(title))
    t = re.sub(r"\s*\([^)]*\)", "", t)
    if len(t) <= max_chars:
        return t
    cut = clause_cut(t, max_chars).rstrip("…").rstrip(" ,;:-")
    if len(cut) < max_chars * 0.6:
        cut = t[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:-")
    words = cut.split()
    while len(words) > 3 and words[-1].lower() in {"of", "to", "the", "a", "an", "and", "or", "for", "in", "on",
                                                    "with", "at", "by", "from", "its", "their", "as"}:
        words.pop()                                      # never end a headline on a dangling small word
    return " ".join(words).rstrip(" ,;:-")


# ------------------------------------------------------------------ intro / outro cards

class CardScene:
    """Full-screen branded card (intro with the day's top headlines, or outro call to action)."""

    def __init__(self, kind: str, date_label: str, headlines: list[str], total: float):
        self.kind = kind
        self.total = total
        self.starts = [0.0]
        bg = gradient(W, H, (14, 28, 74), (6, 10, 26)).convert("RGB")
        d = ImageDraw.Draw(bg)
        for x in range(0, W, 80):
            d.line([(x, 0), (x, H)], fill=(22, 38, 84))
        for y in range(0, H, 80):
            d.line([(0, y), (W, y)], fill=(22, 38, 84))
        self.bg = bg
        self.date_label = date_label
        self.f_big = heavy(118)
        self.f_date = cond(54)
        f_head = font("Montserrat.ttf", 42, "Bold")
        self.headlines = []
        for i, h in enumerate(headlines[:3]):
            spr = Image.new("RGBA", (1500, 90), (0, 0, 0, 0))
            sd = ImageDraw.Draw(spr)
            sd.rectangle([0, 10, 70, 80], fill=RED + (255,))
            sd.text((35, 45), str(i + 1), font=cond(52), fill=WHITE, anchor="mm")
            sd.text((96, 45), fit_line(h, f_head, 1380), font=f_head, fill=WHITE, anchor="lm")
            self.headlines.append(spr)

    def render(self, t: float) -> Image.Image:
        frame = self.bg.copy()
        d = ImageDraw.Draw(frame)
        e = ease_out(prog(t, 0.2, 0.6))
        band_w = int(W * e)
        d.rectangle([0, 250, band_w, 420], fill=RED)
        title = "TECH NEWS TODAY" if self.kind == "intro" else "FOLLOW AIT"
        if e > 0.6:
            d.text((140, 335), title, font=self.f_big, fill=WHITE, anchor="lm")
        sub = self.date_label if self.kind == "intro" else "TECHNOLOGY  •  AI  •  CYBERSECURITY  •  EVERY DAY"
        if prog(t, 0.7, 0.3) > 0:
            d.text((144, 480), sub, font=self.f_date, fill=YELLOW, anchor="lm")
        if self.kind == "intro":
            for i, spr in enumerate(self.headlines):
                p = ease_back(prog(t, LEAD_IN + 0.4 + i * 0.5, 0.45))
                put(frame, spr, 140 - 200 * (1 - p), 600 + i * 110, alpha=min(1.0, p))
        else:
            p = ease_back(prog(t, 0.9, 0.5))
            if p > 0:
                pill = font("Montserrat.ttf", 52, "ExtraBold")
                msg = "SUBSCRIBE FOR DAILY TECH NEWS"
                pw = int(pill.getlength(msg)) + 120
                x0 = W / 2 - pw / 2
                d.rounded_rectangle([x0, 680, x0 + pw * p, 800], 60, fill=RED)
                if p > 0.9:
                    d.text((W / 2, 740), msg, font=pill, fill=WHITE, anchor="mm")
        return frame


def make_card(kind: str, date_label: str, headlines: list[str], out_path: str, voice_key: str) -> float:
    from voice_engine import generate_segmented_speech

    text = INTRO_TEXT if kind == "intro" else OUTRO_TEXT
    audio, duration, _ = generate_segmented_speech([text], f"bulletin_{kind}.mp3", voice_key=voice_key)
    total = LEAD_IN + duration + (2.2 if kind == "intro" else 1.5) + TAIL
    try:
        encode_scene(CardScene(kind, date_label, headlines, total), (W, H), audio, total, out_path, f"bulletin_{kind}")
    finally:
        if os.path.exists(audio):
            os.remove(audio)
    return _duration(out_path)


# ------------------------------------------------------------------ "In brief" round-up

def pick_roundup(exclude_ids: set, limit: int = BULLETIN_ROUNDUP) -> list[dict]:
    """More of today's stories (headline + source only), newest first, not already in the bulletin."""
    from fetcher import get_cached_news, prepare_story

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    picked, seen = [], set(exclude_ids)
    for s in sorted((prepare_story(x) for x in get_cached_news()), key=lambda s: s.get("published_ts", ""), reverse=True):
        try:
            fresh = datetime.fromisoformat(s["published_ts"]) >= cutoff
        except (KeyError, ValueError):
            fresh = False
        if fresh and s["id"] not in seen and clean(s.get("title", "")):
            picked.append(s)
            seen.add(s["id"])
        if len(picked) >= limit:
            break
    return picked


def roundup_line(story: dict) -> str:
    from fetcher import spoken_headline

    return spoken_headline(clean(story["title"]), story.get("outlet", ""))


class RoundupScene:
    """'In brief' segment: one headline at a time with its source, flipping with the anchor."""

    def __init__(self, stories: list[dict], phase_durations: list[float]):
        self.durs = list(phase_durations)
        self.starts = [sum(self.durs[:i]) for i in range(len(self.durs))]
        bg = gradient(W, H, (14, 28, 74), (6, 10, 26)).convert("RGB")
        d = ImageDraw.Draw(bg)
        for x in range(0, W, 80):
            d.line([(x, 0), (x, H)], fill=(22, 38, 84))
        for y in range(0, H, 80):
            d.line([(0, y), (W, y)], fill=(22, 38, 84))
        d.rectangle([0, 120, W, 250], fill=RED)
        d.text((140, 185), "IN BRIEF", font=heavy(96), fill=WHITE, anchor="lm")
        d.text((W - 140, 185), "MORE TECH HEADLINES TODAY", font=cond(48), fill=WHITE, anchor="rm")
        self.bg = bg
        f_head = font("Montserrat.ttf", 64, "ExtraBold")
        f_src = cond(44)
        self.cards = []
        for i, s in enumerate(stories):
            card = Image.new("RGBA", (W - 280, 520), (0, 0, 0, 0))
            cd = ImageDraw.Draw(card)
            lines = wrap(clause_cut(clean(s["title"]), 150), f_head, W - 280)[:4]
            for j, line in enumerate(lines):
                cd.text((0, 40 + j * 82), line, font=f_head, fill=WHITE)
            y = 40 + len(lines) * 82 + 30
            source = clean(s.get("outlet") or s.get("source") or "").upper()
            cd.rectangle([0, y, 12, y + 50], fill=YELLOW + (255,))
            cd.text((30, y + 25), source, font=f_src, fill=YELLOW, anchor="lm")
            cd.text((W - 280, 0), f"{i + 1} / {len(stories)}", font=cond(40), fill=(180, 190, 210), anchor="ra")
            self.cards.append(card)

    def render(self, t: float) -> Image.Image:
        frame = self.bg.copy()
        phase = max(i for i, s in enumerate(self.starts) if t >= s)
        if phase == 0:
            return frame
        card = self.cards[min(phase - 1, len(self.cards) - 1)]
        p = ease_out(prog(t, self.starts[phase], 0.35))
        put(frame, card, 140 + 120 * (1 - p), 330, alpha=p)
        d = ImageDraw.Draw(frame)
        total = len(self.cards)
        for i in range(total):                                  # progress dots
            x = W / 2 - total * 22 + i * 44
            d.ellipse([x, 960, x + 18, 978], fill=RED if i < phase else (60, 72, 100))
        return frame


def make_roundup(stories: list[dict], out_path: str, voice_key: str) -> float:
    from renderer import compute_phase_durations
    from voice_engine import generate_segmented_speech

    segments = ["In brief, here are more of today's technology headlines."] + [roundup_line(s) for s in stories]
    audio, duration, timings = generate_segmented_speech(segments, "bulletin_roundup.mp3", voice_key=voice_key)
    try:
        durs = on_air_durations(compute_phase_durations(duration, timings, len(segments)))
        encode_scene(RoundupScene(stories, durs), (W, H), audio, sum(durs), out_path, "bulletin_roundup")
    finally:
        if os.path.exists(audio):
            os.remove(audio)
    return _duration(out_path)


# ------------------------------------------------------------------ thumbnail + metadata

def bulletin_thumbnail(items: list[dict], date_label: str, out_path: str, extra: int = 0) -> str:
    """BBC-style: lead story photo, 'Tech News Today' kicker, lead headline, '+N more stories'."""
    tw, th, pad = 1280, 720, 56
    photos = story_photos(items[0]["story"]) if items else []
    img = ImageOps.fit(photos[0], (tw, th), Image.LANCZOS, centering=(0.5, 0.4)) if photos else \
        Image.new("RGB", (tw, th), NAVY)
    img = ImageEnhance.Contrast(img).enhance(1.05).convert("RGBA")
    a = (np.linspace(0, 1, 560) ** 0.55 * 225).astype(np.uint8)
    shade = Image.new("RGBA", (tw, 560), BLACK + (0,))
    shade.putalpha(Image.fromarray(np.repeat(a[:, None], tw, axis=1)))
    img.alpha_composite(shade, (0, th - 560))
    d = ImageDraw.Draw(img)
    f_logo, f_news = font("Montserrat.ttf", 34, "ExtraBold"), font("Montserrat.ttf", 34, "Bold")
    mw, nw = int(f_logo.getlength("AIT")) + 28, int(f_news.getlength("NEWS")) + 28
    d.rectangle([pad, 44, pad + mw, 96], fill=RED)
    d.rectangle([pad + mw, 44, pad + mw + nw, 96], fill=(15, 15, 18))
    d.text((pad + mw // 2, 70), "AIT", font=f_logo, fill=WHITE, anchor="mm")
    d.text((pad + mw + nw // 2, 70), "NEWS", font=f_news, fill=WHITE, anchor="mm")

    lead = short_headline(items[0]["story"]["title"], 60) if items else "Today's top tech stories"
    f = font("Montserrat.ttf", 64, "ExtraBold")
    lines = wrap(lead, f, tw - pad * 2)[:2]
    more = f"+ {len(items) - 1 + extra} more stories" if len(items) + extra > 1 else ""
    y = th - pad - 76 * len(lines) - (56 if more else 0)
    kicker = f"TECH NEWS TODAY  •  {date_label}"
    f_k = font("Montserrat.ttf", 30, "Bold")
    kw = int(f_k.getlength(kicker)) + 32
    d.rectangle([pad, y - 64, pad + kw, y - 18], fill=RED)
    d.text((pad + kw // 2, y - 41), kicker, font=f_k, fill=WHITE, anchor="mm")
    for i, line in enumerate(lines):
        d.text((pad, y + i * 76), line, font=f, fill=WHITE)
    if more:
        d.text((pad, y + 76 * len(lines) + 12), more, font=font("Montserrat.ttf", 36, "SemiBold"), fill=YELLOW)
    img.convert("RGB").save(out_path, "JPEG", quality=92)
    return out_path


def _stamp(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{(s // 60) % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def bulletin_metadata(items: list[dict], roundup: list[dict], chapters: list[tuple[float, str]], date_label: str) -> dict:
    from youtube_uploader import BRAND_TAGS, build_tags

    lead = short_headline(items[0]["story"]["title"], 55)
    title = f"Tech News Today: {lead} & more | {date_label}"
    if len(title) > 100:
        title = f"Tech News Today | {date_label} | AIT News"
    lines = [f"Today's top technology stories from AIT News — {date_label}.", "", "Chapters:"]
    lines += [f"{_stamp(t)} {name}" for t, name in chapters]
    lines += ["", "Sources:"]
    for it in items:
        s = it["story"]
        lines.append(f"• {clean(s['title'])[:90]} — {s.get('outlet', '')}: {s.get('link', '')}")
    if roundup:
        lines += ["", "In brief:"]
        lines += [f"• {clean(s['title'])[:90]} — {s.get('outlet', '')}: {s.get('link', '')}" for s in roundup]
    lines += ["", "Subscribe for daily tech news.", "", "#AITNews #TechNews #TechNewsToday"]
    description = "\n".join(lines).replace("<", "").replace(">", "")
    while len(description) > 4900 and "Sources:" in description:          # trim sources, never chapters
        description = description[: description.rfind("\n• ")] + "\n" + description[description.rfind("\n\nSubscribe"):]
    tags, seen = [], set()
    for it in items:
        for t in build_tags(it["story"]):
            if t not in BRAND_TAGS and t.lower() not in seen:
                tags.append(t)
                seen.add(t.lower())
    tags = ["AIT News", "Tech News Today", "Tech News", "Technology News"] + tags
    out, total = [], 0
    for t in tags:
        cost = len(t) + (2 if " " in t else 0) + 1
        if total + cost <= 480:
            out.append(t)
            total += cost
    return {"title": title, "description": description[:4900], "tags": out}


# ------------------------------------------------------------------ build

def build_bulletin(out_path: str, voice_key: str = DEFAULT_VOICE) -> dict:
    items = pick_clips()
    if len(items) < 3:
        raise RuntimeError(f"Only {len(items)} eligible stories in the last 24 h; need at least 3")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    date_label = datetime.now(timezone.utc).strftime("%d %b %Y").upper()
    base = out_path[:-4]
    intro, outro = base + "_intro.mp4", base + "_outro.mp4"
    headlines = [clean(i["story"]["title"]) for i in items]
    intro_dur = make_card("intro", date_label, headlines, intro, voice_key)
    make_card("outro", date_label, headlines, outro, voice_key)
    roundup = pick_roundup({i["story"]["id"] for i in items})
    roundup_clip = base + "_roundup.mp4"
    roundup_dur = make_roundup(roundup, roundup_clip, voice_key) if len(roundup) >= 3 else 0.0
    if not roundup_dur:
        roundup = []

    chapters, t = [(0.0, "Intro")], intro_dur
    for it in items:
        chapters.append((t, short_headline(it["story"]["title"], 70)))
        t += it["duration"]
    if roundup_dur:
        chapters.append((t, "In brief: more tech headlines"))
        t += roundup_dur
    chapters.append((t, "Outro"))

    parts = [intro] + [i["clip"] for i in items] + ([roundup_clip] if roundup_dur else []) + [outro]
    concat = base + "_concat.txt"
    with open(concat, "w", encoding="utf-8") as f:
        for p in parts:
            f.write(f"file '{os.path.abspath(p).replace(chr(92), '/')}'\n")
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", concat, "-c", "copy", "-movflags", "+faststart", out_path], check=True)
    for p in (intro, outro, concat, roundup_clip):
        if os.path.exists(p):
            os.remove(p)

    thumb = bulletin_thumbnail(items, date_label, base + "_thumb.jpg", extra=len(roundup))
    meta = bulletin_metadata(items, roundup, chapters, date_label)
    meta.update({"video": out_path, "thumbnail": thumb, "duration": _duration(out_path),
                 "stories": [i["story"]["id"] for i in items], "roundup": [s["id"] for s in roundup]})
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    log(f"Built {os.path.basename(out_path)}: {len(items)} stories + {len(roundup)} in brief, "
        f"{meta['duration'] / 60:.1f} min")
    return meta


def main():
    ap = argparse.ArgumentParser(description="Build today's Tech News Today bulletin")
    ap.add_argument("--out", required=True)
    ap.add_argument("--voice", default=DEFAULT_VOICE)
    args = ap.parse_args()
    build_bulletin(args.out, args.voice)


if __name__ == "__main__":
    main()
