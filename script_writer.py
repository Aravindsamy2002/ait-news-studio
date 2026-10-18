"""
Engaging anchor scripts written by Gemini (free API tier) and fact-checked before they air.

The on-screen text stays the verbatim source (headline + key points). Only the anchor's spoken
lines are rewritten into a natural broadcast style, one spoken segment per on-screen phase, so
the graphics still flip in sync. Every rewritten line must pass:
  1. a local guard: no number, name or hedged/speculative word that the source doesn't contain;
  2. a second Gemini call acting as a fact checker against the source text.
Any line that fails falls back to the verbatim source line. Any API error -> fully verbatim.
"""
import hashlib
import json
import os
import re
import threading
import urllib.error
import urllib.request

from bs4 import BeautifulSoup

from config import GEMINI_API_KEY, GEMINI_MODEL, OUTPUT_DIR, SCRIPT_WRITER_ENABLED
from fetcher import BREAKING_OPENERS, summary_sentences

CACHE_FILE = os.path.join(OUTPUT_DIR, "script_cache.json")
_lock = threading.Lock()
_warned = False

WRITER_PROMPT = """You are the script writer for a TV technology news bulletin. Rewrite the facts below into lines an anchor reads aloud.

Return JSON: {{"headline": "...", "points": ["...", ...]}} with exactly {n} items in "points".
- "headline": one or two short spoken sentences that introduce the story with a light hook. Start with the news itself.
- "points": item i retells key point i in a natural spoken way (max 35 words each). You may add context ONLY if it is stated in the source text.

Rules:
- Use only facts stated in the source. No outside knowledge, no predictions, no opinions, no guesses.
- Keep every name, number, date and quantity exactly as in the source, but write symbols the way an anchor
  says them: "~$180M" -> "about 180 million dollars", "60+" -> "more than 60", "40%" -> "40 percent".
- Attribute claims the way the source does ("the company said", "according to ...").
- Never use: could, might, may, likely, potentially, reportedly, breaking, shocking, massive, huge.
- No first person, no questions to the viewer, no greetings, no sign-off, no emojis.

Headline: {title}
Outlet: {outlet}
Key points:
{points}
Source text:
{source}
"""

CHECKER_PROMPT = """You are a strict fact checker for a news broadcast. For each numbered script line, decide whether every factual claim in it is directly supported by the source text. Wording may differ; meaning, numbers, names and certainty must not. A line that adds any fact, makes a claim stronger or more certain than the source, or changes who did what is NOT supported.

Return JSON: {{"results": [{{"line": 1, "supported": true}}, ...]}} covering every line.

Source text:
{source}

Script lines:
{lines}
"""

_SPECULATION = re.compile(r"\b(could|might|may|likely|potentially|possibly|reportedly|rumou?red|expected to|"
                          r"set to|poised|breaking|shocking|massive|huge)\b", re.I)
_ALLOWED_CAPS = {"The", "This", "That", "It", "Its", "A", "An", "In", "On", "For", "And", "But", "As", "With",
                 "Now", "Today", "Meanwhile", "According", "So", "Also", "Here", "These", "Those", "Their",
                 "They", "He", "She", "His", "Her", "After", "Before", "While", "AI", "CEO", "US", "UK"}


def log(msg: str):
    print(f"[script] {msg}", flush=True)


def _gemini(prompt: str, temperature: float) -> dict:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    body = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "responseMimeType": "application/json",
                             "maxOutputTokens": 2048},
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json",
                                                          "x-goog-api-key": GEMINI_API_KEY})
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read())
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


def article_text(url: str, limit: int = 3500) -> str:
    """Paragraphs from the article body (context for the writer and the checker; never read verbatim on air)."""
    if not url or not url.startswith("http") or "news.google" in url:
        return ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            soup = BeautifulSoup(resp.read(), "html.parser")
        body = soup.find("article") or soup
        for junk in body.find_all(["aside", "nav", "footer", "figure", "script", "style"]):
            junk.decompose()
        paras = [p.get_text(" ", strip=True) for p in body.find_all("p")]
        paras = [p for p in paras if len(p) > 60 and not re.search(r"(subscribe|newsletter|sign up|cookie)", p, re.I)]
        return " ".join(paras)[:limit]
    except Exception:
        return ""


def local_guard(line: str, source: str) -> bool:
    """No new numbers, names or hedged/speculative words."""
    src = source.lower().replace(",", "")
    if _SPECULATION.search(line) and not _SPECULATION.search(source):
        return False
    for num in re.findall(r"\d[\d,.]*\d|\d", line):
        if num.replace(",", "").rstrip(".") not in src:
            return False
    for sentence in re.split(r"(?<=[.!?])\s+", line):
        for w in re.findall(r"[A-Za-z][A-Za-z'’\-]*", sentence)[1:]:
            base = re.sub(r"['’]s$", "", w)
            if base[0].isupper() and base not in _ALLOWED_CAPS and base.lower() not in src:
                return False
    return True


def _load_cache() -> dict:
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def with_engaging_script(story: dict) -> dict:
    """Replace the anchor's spoken lines with checked, engaging ones. Falls back to verbatim per line."""
    global _warned
    if not SCRIPT_WRITER_ENABLED:
        return story
    points = list(story.get("bullets") or [])
    segments = list(story.get("narration_segments") or [])
    if len(segments) != len(points) + 2:                 # [intro+headline, points..., sign-off]; analysis adds more
        return story
    key = hashlib.sha1(json.dumps([GEMINI_MODEL, story["title"], points]).encode()).hexdigest()[:16]
    with _lock:
        cached = _load_cache().get(key)
    if cached is None:
        summary = "" if "Google" in story.get("source", "") else story.get("summary", "")
        source = " ".join([story["title"] + "."] + summary_sentences(summary, story["title"], limit=8)
                          + [article_text(story.get("link", ""))]).strip()
        try:
            draft = _gemini(WRITER_PROMPT.format(
                n=len(points), title=story["title"], outlet=story.get("outlet", ""),
                points="\n".join(f"{i + 1}. {p}" for i, p in enumerate(points)) or "(none)", source=source), 0.5)
            lines = [str(draft.get("headline", "")).strip()] + [str(x).strip() for x in draft.get("points", [])]
            if len(lines) != len(points) + 1 or not all(lines):
                raise ValueError("writer returned the wrong shape")
            checked = _gemini(CHECKER_PROMPT.format(
                source=source, lines="\n".join(f"{i + 1}. {l}" for i, l in enumerate(lines))), 0.0)
            ok = {int(r["line"]): bool(r["supported"]) for r in checked.get("results", [])}
            cached = [l if ok.get(i + 1) and local_guard(l, source) else None for i, l in enumerate(lines)]
            rejected = [i for i, l in enumerate(cached) if l is None]
            if rejected:
                log(f"{story['id']}: {len(rejected)} line(s) failed fact check -> verbatim for those")
        except Exception as e:
            if not _warned:
                log(f"Gemini unavailable, using verbatim script ({e})")
                _warned = True
            return story                                  # don't cache failures; try again next render
        with _lock:
            cache = _load_cache()
            cache[key] = cached
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=2, ensure_ascii=False)

    s = dict(story)
    new_segments = list(segments)
    if cached[0]:
        # Keep the honest "breaking" opener for genuinely fresh stories; otherwise the hook replaces it
        opener = next((o for o in BREAKING_OPENERS if segments[0].startswith(o)), "") if story.get("is_breaking") else ""
        new_segments[0] = f"{opener} {cached[0]}".strip()
    for i, line in enumerate(cached[1:], start=1):
        if line:
            new_segments[i] = line
    s["narration_segments"] = new_segments
    s["narration"] = " ".join(new_segments)
    s["script_source"] = "gemini"
    return s
