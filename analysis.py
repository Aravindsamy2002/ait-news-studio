"""
"What it means" explainer for each story, written by a local LLM and fact-checked.

Runs against a local Ollama server (free, CPU-only, works on ARM). The model may only
explain the significance of facts already in the source; any number or name that is not
in the source text gets the whole analysis rejected, so nothing invented reaches air.
If Ollama is not running, stories simply go out without the analysis segment.
"""
import json
import os
import re
import threading
import urllib.request

from config import ANALYSIS_ENABLED, ANALYSIS_MODEL, OLLAMA_URL, OUTPUT_DIR
from fetcher import summary_sentences

CACHE_FILE = os.path.join(OUTPUT_DIR, "analysis_cache.json")
_cache_lock = threading.Lock()
_warned = False

PROMPT = """You are a senior editor at a TV news channel. Write exactly two short sentences for the anchor that explain this story in plain words for an ordinary viewer: what has changed, and who it affects.

Rules:
- Use only information stated in the source. Reuse the source's own key words.
- No background knowledge, no predictions, no opinions, no guesses.
- Never use the words could, might, may, likely, potentially, suggests or indicates.
- No number, date, name, company or product that is not in the source.
- Start directly with the subject. Do not start with "This story", "It matters" or "This means".
- No first person, no questions, no quotation marks. Maximum 40 words in total.

Source headline: {title}
Source outlet: {outlet}
Source text: {text}

Explanation:"""

# Capitalised words that can appear in commentary without being facts
_ALLOWED_CAPS = {"AI", "This", "That", "The", "It", "For", "And", "But", "As", "If", "In", "On", "With",
                 "These", "Those", "Such", "While", "Its", "A", "An", "Here", "Why", "What", "Now"}

# Hedged or speculative wording = a guess, not a fact
_SPECULATION = re.compile(r"\b(could|might|may|likely|potentially|possibly|suggests?|indicat\w*|signal\w*|"
                          r"expected|predict\w*|crucial|significant(ly)?)\b", re.I)

# Plain connective words the explanation may use even if the source doesn't
_GENERIC = {
    "this", "that", "these", "those", "with", "from", "into", "about", "after", "before", "their", "there",
    "they", "them", "which", "while", "when", "what", "where", "will", "would", "have", "been", "being",
    "more", "most", "less", "also", "than", "then", "only", "just", "some", "such", "other", "over",
    "people", "users", "change", "changes", "changed", "means", "affect", "affects", "affected", "using",
    "make", "makes", "made", "part", "move", "moves", "plan", "plans", "now", "were", "does", "done",
}


def _source_text(story: dict) -> str:
    summary = "" if "Google" in story.get("source", "") else story.get("summary", "")
    return " ".join(summary_sentences(summary, story.get("title", ""), limit=6))


def _base(word: str) -> str:
    """Lowercase, possessive-stripped form: "Meta's" -> "meta"."""
    return re.sub(r"['’]s$", "", word.lower()).strip("'’-")


def passes_fact_guard(text: str, source: str) -> bool:
    """Reject commentary that adds names, numbers, guesses or ideas the source doesn't contain."""
    src = source.lower().replace(",", "")
    if _SPECULATION.search(text) and not _SPECULATION.search(source):
        return False
    for num in re.findall(r"\d[\d,.]*\d|\d", text):
        if num.replace(",", "").rstrip(".") not in src:
            return False
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        words = re.findall(r"[A-Za-z][A-Za-z'’\-]*", sentence)
        for w in words[1:]:                                   # skip the sentence-initial capital
            if (w[0].isupper() or w.isupper()) and w not in _ALLOWED_CAPS and _base(w) not in src:
                return False
    # Grounding: most meaningful words must come from the source (5-letter stems tolerate word forms)
    src_stems = {_base(w)[:5] for w in re.findall(r"[A-Za-z][A-Za-z'’\-]*", source) if len(w) >= 4}
    content = [_base(w) for w in re.findall(r"[A-Za-z][A-Za-z'’\-]*", text) if len(w) >= 4]
    content = [w for w in content if w not in _GENERIC]
    if content and sum(w[:5] in src_stems for w in content) / len(content) < 0.7:
        return False
    banned = ("as an ai", "i think", "we think", "according to reports", "experts say", "sources say")
    return not any(b in text.lower() for b in banned) or any(b in src for b in banned)


def _tidy(raw: str) -> str:
    text = re.sub(r"\s+", " ", raw.replace('"', "").replace("“", "").replace("”", "")).strip()
    text = re.sub(r"^((why it matters|explanation|what it means):?\s*)", "", text, flags=re.I)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    text = " ".join(sentences[:2])
    return text if text.endswith((".", "!")) and 40 <= len(text) <= 340 else ""


def _ask_ollama(prompt: str) -> str:
    payload = json.dumps({
        "model": ANALYSIS_MODEL,
        "prompt": prompt,
        "stream": False,
        # num_thread caps CPU use so the live stream and other services keep their share
        "options": {"temperature": 0.3, "num_predict": 110,
                    "num_thread": int(os.environ.get("ANALYSIS_THREADS", "2"))},
    }).encode()
    req = urllib.request.Request(f"{OLLAMA_URL}/api/generate", data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read()).get("response", "")


def _load_cache() -> dict:
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def get_analysis(story: dict) -> str:
    """Fact-checked 'why it matters' text for a story ('' when unavailable or rejected)."""
    global _warned
    source = _source_text(story)
    if len(source) < 60:
        return ""                                             # too little source to comment on honestly
    key = story.get("id", story.get("title", ""))
    with _cache_lock:
        cache = _load_cache()
        if key in cache:
            return cache[key]
    try:
        raw = _ask_ollama(PROMPT.format(title=story.get("title", ""), outlet=story.get("outlet", ""), text=source))
    except Exception as e:
        if not _warned:
            print(f"Analysis skipped (Ollama unavailable at {OLLAMA_URL}): {e}")
            _warned = True
        return ""
    text = _tidy(raw)
    if text and not passes_fact_guard(text, f"{story.get('title', '')} {story.get('outlet', '')} {source}"):
        print(f"Analysis rejected by fact guard for {key}: {text}")
        text = ""
    with _cache_lock:
        cache = _load_cache()
        cache[key] = text
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    return text


def with_analysis(story: dict) -> dict:
    """Add the analysis as its own on-air segment, just before the anchor's sign-off."""
    if not ANALYSIS_ENABLED:
        return story
    text = get_analysis(story)
    if not text:
        return story
    s = dict(story)
    s["analysis"] = text
    segments = list(s["narration_segments"])
    segments.insert(len(segments) - 1, f"So what does this mean? {text}")
    s["narration_segments"] = segments
    s["narration"] = " ".join(segments)
    return s
