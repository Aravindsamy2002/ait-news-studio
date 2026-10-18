import io
import re
import html
import random
import json
import os
import urllib.request
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta, timezone
import feedparser
from bs4 import BeautifulSoup
from PIL import Image
from config import (
    RSS_FEEDS, OUTPUT_DIR, ASSETS_DIR,
    MAX_STORY_AGE_HOURS, BREAKING_WINDOW_HOURS, NEWS_REFRESH_MINUTES
)

CACHE_FILE = os.path.join(OUTPUT_DIR, "latest_news.json")
IMAGES_DIR = os.path.join(ASSETS_DIR, "images")
os.makedirs(IMAGES_DIR, exist_ok=True)

def clean_html(raw_html: str) -> str:
    """Strip HTML tags and clean up whitespace."""
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    text = soup.get_text(separator=" ")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

_CATEGORY_RULES = [(c, re.compile(p, re.I)) for c, p in [
    ("CYBERSECURITY & DEFENSE", r"\b(hack(ed|er|ers|ing)?|breach(es|ed)?|vulnerabilit(y|ies)|malware|ransomware|"
                                r"cyber ?attacks?|cybersecurity|exploit(ed|s)?|phishing|zero-day|spyware)\b"),
    ("ARTIFICIAL INTELLIGENCE", r"\b(openai|chatgpt|gpt-?\d\w*|anthropic|claude|deepseek|llms?|gemini|copilot|"
                                r"artificial intelligence|generative ai|ai (model|models|agent|agents|chatbot|safety)|"
                                r"language models?|machine learning|ai)\b"),
    ("SILICON & HARDWARE", r"\b(nvidia|chips?|chipmakers?|semiconductors?|tsmc|intel|amd|gpus?|qualcomm|arm holdings)\b"),
    ("FINTECH & CRYPTO", r"\b(crypto\w*|bitcoin|blockchain|ethereum|solana|stablecoins?)\b"),
    ("AEROSPACE & SCIENCE", r"\b(nasa|spacex|satellites?|rockets?|orbit\w*|astronauts?|space ?station|moon|mars)\b"),
    ("BIG TECH RADAR", r"\b(google|apple|iphone|meta|microsoft|amazon|samsung|tiktok)\b"),
]]


def infer_category(title: str, summary: str, default: str) -> str:
    """Infer the broadcast category from whole-word keywords (headline weighs more than the summary)."""
    for text in (title, f"{title} {summary}"):
        for category, pattern in _CATEGORY_RULES:
            if pattern.search(text):
                return category
    return default

FEED_OUTLETS = {
    "Techmeme Live Wire": "Techmeme",
    "Google News Tech": "Google News",
    "TechCrunch AI": "TechCrunch",
    "The Verge": "The Verge",
    "Ars Technica": "Ars Technica",
    "Engadget": "Engadget",
    "The Next Web": "The Next Web",
    "Wired": "Wired",
    "9to5Mac": "9to5Mac",
    "The Register": "The Register",
    "BBC Technology": "BBC News",
}
AGGREGATORS = {"Techmeme", "Google News"}

BREAKING_OPENERS = [
    "Breaking news this hour.",
    "This just in.",
    "We are getting breaking news from the world of technology.",
]
NEWS_OPENERS = [
    "Big news from the world of technology.",
    "We begin with this developing story.",
    "Now to a major story from the tech world.",
    "Turning now to a story that is making headlines.",
]
NEWS_SIGNOFFS = [
    "We will keep you updated as more details come in.",
    "Stay with AIT News for more on this story.",
    "We will continue to track this story as it develops.",
]
# Lines written to the reader (site boilerplate, calls to action) are not news facts
_READER_CTA = re.compile(
    r"\b(if you('re| are)? (a developer|interested|looking)|would like your|get in (touch|contact)|let us know|"
    r"reach out to us|subscribe|sign up|newsletter|follow us|click here|tap here|read more|learn more|"
    r"stay tuned|we may earn|affiliate|sponsored|what you can do|here'?s (why|how|what))\b", re.I)
_FIRST_PERSON = re.compile(r"\b(I|I['’]m|I['’]ve|I['’]d|I['’]ll|my|me|we['’]re|our)\b")

def split_title_outlet(title: str, feed_name: str) -> tuple[str, str]:
    """Strip '(Author/Outlet)' or ' - Outlet' credits from a headline and return the outlet."""
    t = clean_html(title).replace("�", "").strip()
    outlet = ""
    m = re.search(r"\s*\(([^()]*)\)\s*$", t)
    # Techmeme always ends headlines with the credit: "(Author/Outlet)" or just "(Outlet)"
    if m and ("/" in m.group(1) or ("Techmeme" in feed_name and len(m.group(1)) <= 40)):
        outlet = m.group(1).split("/")[-1].strip()
        t = t[:m.start()].strip()
    elif "Google" in feed_name and " - " in t:
        head, _, tail = t.rpartition(" - ")
        if len(tail) <= 40 and len(head) > 20:
            t, outlet = head.strip(), tail.strip()
    return t, outlet or FEED_OUTLETS.get(feed_name, feed_name)

def summary_sentences(summary: str, title: str, limit: int = 3) -> list[str]:
    """Complete, third-person sentences from the summary that a news anchor can read out."""
    s = clean_html(summary).replace("�", ". ")
    s = re.sub(r"^[^:]{2,60}\s:\s", "", s)                       # Techmeme "Author / Outlet : " byline
    if title and s.lower().startswith(title.lower()[:40]):
        s = s[len(title):].lstrip(" .:;-—")
    s = re.sub(r"The post .* appeared first on .*$", "", s)
    s = re.sub(r"\s*\[(?:…|\.\.\.)\]\s*$", "", s)
    sentences = []
    for sent in re.split(r"(?<=[.!?])\s+", s):
        sent = sent.strip()
        if len(sent) < 30 or sent[-1] not in ".!?" or sent.endswith("..."):
            continue                                              # fragments cut off by the feed
        if _READER_CTA.search(sent):
            continue                                              # "get in contact", "subscribe", "here's how"...
        if _FIRST_PERSON.search(sent):
            continue                                              # interviewer's own voice
        sentences.append(sent)
        if len(sentences) >= limit:
            break
    return sentences

def generate_bullet_points(title: str, summary: str) -> list[str]:
    """Key points for the on-screen flipper (only real sentences, no filler)."""
    return summary_sentences(summary, title)

# Wire-style headline prefixes, read the way an anchor would say them (same meaning, spoken form)
_SPOKEN_PREFIXES = {
    "sources": "according to sources", "source": "according to a source", "filing": "according to a filing",
    "memo": "according to a memo", "letter": "according to a letter", "documents": "according to documents",
    "survey": "according to a survey", "report": "according to a report", "study": "according to a study",
}


def spoken_headline(title: str, outlet: str = "") -> str:
    """Headline as a full spoken sentence: "Sources: X" -> "X, according to sources." plus the outlet credit."""
    text = title.replace("&", "and").strip()
    credit = ""
    m = re.match(r"^(\w+):\s+(.+)$", text)
    if m and m.group(1).lower() in _SPOKEN_PREFIXES:
        credit, text = _SPOKEN_PREFIXES[m.group(1).lower()], m.group(2)
    end = text[-1] if text and text[-1] in ".!?" else ""
    if end == "?":
        return text                                      # a question reads badly with a credit; the source is on screen
    text = text.rstrip(".!?;,")
    if credit:
        text += f", {credit}"
    if outlet and outlet not in AGGREGATORS and "." not in outlet:
        text += f", reports {outlet}"
    return text + (end or ".")


def build_narration_segments(title: str, points: list[str], outlet: str, seed: str = "", breaking: bool = False) -> list[str]:
    """Anchor script split by on-screen phase: [intro+headline, point 1..n, sign-off].

    Only genuinely fresh stories get a "breaking" opener.
    """
    rnd = random.Random(seed or title)
    openers = BREAKING_OPENERS if breaking else NEWS_OPENERS
    segments = [f"{rnd.choice(openers)} {spoken_headline(title, outlet)}"]
    segments += [p.replace("&", "and") for p in points]
    segments.append(rnd.choice(NEWS_SIGNOFFS))
    return segments

def generate_narration_script(title: str, summary: str, source: str) -> str:
    """Generate the full anchor narration as one string."""
    clean_title, outlet = split_title_outlet(title, source)
    points = summary_sentences("" if "Google" in source else summary, clean_title)
    return " ".join(build_narration_segments(clean_title, points, outlet))

def story_published_at(story: dict) -> datetime | None:
    """Publication time from the stored ISO stamp or the feed's date string."""
    for value in (story.get("published_ts"), story.get("published")):
        if not value:
            continue
        for parse in (datetime.fromisoformat,
                      lambda v: datetime.strptime(v, "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc),
                      parsedate_to_datetime):
            try:
                dt = parse(value)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue
    return None

def prepare_story(story: dict) -> dict:
    """Re-derive clean headline, outlet, key points and anchor script for a (cached) story."""
    s = dict(story)
    title, outlet = split_title_outlet(story.get("title", ""), story.get("source", ""))
    # Google News "summaries" are just lists of related headlines, not readable copy
    summary = "" if "Google" in story.get("source", "") else story.get("summary", "")
    points = summary_sentences(summary, title)
    published = story_published_at(story)
    breaking = bool(published) and datetime.now(timezone.utc) - published <= timedelta(hours=BREAKING_WINDOW_HOURS)
    link = story.get("link", "")
    if outlet in AGGREGATORS and link.startswith("http") and not any(a in link for a in ("techmeme.com", "news.google")):
        outlet = link.split("/")[2].removeprefix("www.")          # credit the real publisher, not the aggregator
    feed_default = next((f["default_category"] for f in RSS_FEEDS if f["name"] == story.get("source")), "TECH NEWS")
    s["category"] = infer_category(title, summary, feed_default)
    s["title"] = title
    s["outlet"] = outlet
    s["bullets"] = points
    s["published_ts"] = published.isoformat() if published else ""
    s["is_breaking"] = breaking
    s["narration_segments"] = build_narration_segments(title, points, outlet, seed=story.get("id", ""), breaking=breaking)
    s["narration"] = " ".join(s["narration_segments"])
    return s

def scrape_article_image_urls(article_url: str, feed_entry) -> list[str]:
    """Scrape ONLY genuine images used inside the article itself."""
    found_urls = []

    # 1. From RSS entry
    if "media_content" in feed_entry:
        for m in feed_entry.media_content:
            if "url" in m and m["url"].startswith("http"):
                found_urls.append(m["url"])
    if "enclosures" in feed_entry:
        for enc in feed_entry.enclosures:
            if "href" in enc and enc["href"].startswith("http"):
                found_urls.append(enc["href"])

    # 2. Scrape article page
    if article_url and article_url.startswith("http"):
        try:
            req = urllib.request.Request(
                article_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                soup = BeautifulSoup(resp.read(), "html.parser")

            # Meta OG / Twitter image
            for prop in ["og:image", "twitter:image"]:
                m = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
                if m and m.get("content") and m.get("content").startswith("http"):
                    u = m.get("content")
                    if u not in found_urls:
                        found_urls.append(u)

            # Images inside the article body only: never sidebars, related-story cards or footers
            for junk in soup.find_all(["aside", "nav", "footer", "header"]):
                junk.decompose()
            for related in soup.find_all(class_=re.compile(r"related|recommend|more-stories|newsletter|promo", re.I)):
                related.decompose()
            body = soup.find("article")
            for im in (body.find_all("img") if body else []):
                src = im.get("src") or im.get("data-src") or ""
                if src.startswith("http") and not is_junk_image_url(src) and src not in found_urls:
                    found_urls.append(src)
        except Exception as e:
            print(f"Error scraping article images from {article_url}: {e}")

    # Remove duplicates and clean
    unique = []
    for u in found_urls:
        if u not in unique and not is_junk_image_url(u):
            unique.append(u)

    return unique

def is_junk_image_url(url: str) -> bool:
    """Avatars, logos, site default share images and trackers are not story images."""
    u = url.lower()
    return any(k in u for k in [
        "author", "headshot", "avatar", "profile", "logo", "icon", "pixel", "advert", "sponsor",
        ".svg", "button", "placeholder", "default", "fallback", "brand", "techmeme.com",
        "news.google", "gstatic.com",
    ])

def fetch_and_cache_article_images(story_id: str, article_url: str, feed_entry) -> list[str]:
    """Download and cache ONLY real images from the article itself (no generated crops)."""
    cached = [os.path.join(IMAGES_DIR, f"{story_id}_img{i}.jpg") for i in range(4)]
    cached = [p for p in cached if os.path.exists(p) and os.path.getsize(p) > 3000]
    if cached:
        return cached

    downloaded_paths = []
    for url in scrape_article_image_urls(article_url, feed_entry):
        if len(downloaded_paths) >= 4:
            break
        out_p = os.path.join(IMAGES_DIR, f"{story_id}_img{len(downloaded_paths)}.jpg")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = resp.read()
            img = Image.open(io.BytesIO(data))
            w, h = img.size
            # Thumbnails, icons and banner strips are not usable story pictures
            if w < 400 or h < 225 or not (0.5 <= w / h <= 2.6):
                continue
            img.convert("RGB").save(out_p, "JPEG", quality=92)
            downloaded_paths.append(out_p)
        except Exception as e:
            print(f"Failed to download article image {url}: {e}")
    return downloaded_paths

def parse_published(entry) -> datetime | None:
    """Real publication time of the feed item in UTC (None if the feed doesn't say)."""
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return datetime(*parsed[:6], tzinfo=timezone.utc)
    return None

def resolve_article_url(entry, feed_name: str) -> str:
    """Techmeme links point at Techmeme itself; the real article is the first link in its summary."""
    link = entry.get("link", "")
    if "techmeme.com" in link:
        soup = BeautifulSoup(entry.get("summary", ""), "html.parser")
        for a in soup.find_all("a", href=True):
            if a["href"].startswith("http") and "techmeme.com" not in a["href"]:
                return a["href"]
    if "news.google.com" in link:
        return ""        # Google News links are JS redirects; scraping them only yields Google's logo
    return link

# How-to guides, shopping deals, listicles and clickbait are not news; keep them off a news channel
_NOT_NEWS = re.compile(
    r"^(how to|how do|what to|why (your|you)|why it'?s (important|worth|time)|you (don'?t|do not) (have|need) to|"
    r"here's (how|why)|here are|don't|do this|should you|is it worth|what is|what are|everything you need|"
    r"what'?s actually|indie app spotlight|sponsored|giveaway|podcast|top stories|this week in|weekly roundup|"
    r"9to5mac (daily|overtime)|apple @ work|"
    r"the best|best\b|\d+ (best|ways|things|tips|reasons))"
    r"|[$£€₹]\d[\d,.]* off\b|\d+% off\b"
    r"|\b(best|weekend|holiday|early|black friday|cyber monday|prime day|top) deals?\b|\bdeals? on\b"
    r"|\b(on sale|sale price|discount code|coupon|ranked|worst to best|gift guide|"
    r"buying guide|tips and tricks|cheapest)\b",
    re.I,
)


_TECH = re.compile(
    r"\b(tech\w*|ai|artificial intelligence|chatbot|robot\w*|software|app|apps|online|internet|web|cyber\w*|"
    r"hack\w*|data|privacy|digital|computer\w*|chip\w*|semiconductor|smartphone|phone\w*|iphone|android|"
    r"social media|platform|algorithm|crypto\w*|bitcoin|blockchain|gaming|games?|console|streaming|satellite|"
    r"space|rocket|electric vehicle|ev|battery|broadband|5g|wi-?fi|cloud|startup|silicon|google|apple|meta|"
    r"microsoft|amazon|nvidia|openai|tesla|tiktok|youtube|facebook|instagram|whatsapp|x\.com|twitter|"
    r"samsung|ofcom|online safety)\b", re.I)


def is_tech(text: str) -> bool:
    """For general-purpose feeds: keep only stories that are actually about technology."""
    return bool(_TECH.search(text))


def is_news(title: str) -> bool:
    return not _NOT_NEWS.search(clean_html(title))


def _title_tokens(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", title.lower()) if len(w) > 2}

def is_duplicate(title: str, seen: list[set[str]]) -> bool:
    tokens = _title_tokens(title)
    for other in seen:
        if tokens and other and len(tokens & other) / len(tokens | other) >= 0.5:
            return True
    return False

def fetch_all_news(limit_per_feed: int = 12) -> list[dict]:
    """Fetch fresh stories from all feeds: real timestamps, real article images, no duplicates."""
    all_stories = []
    seen_titles = []
    now = datetime.now(timezone.utc)

    for feed_info in RSS_FEEDS:
        name = feed_info["name"]
        url = feed_info["url"]
        default_cat = feed_info["default_category"]

        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:limit_per_feed]:
                raw_title = clean_html(entry.get("title", ""))
                if not raw_title or len(raw_title) < 15:
                    continue
                published_dt = parse_published(entry)
                if published_dt is None or now - published_dt > timedelta(hours=MAX_STORY_AGE_HOURS):
                    continue                                   # undated or stale: never shown as news
                title, outlet = split_title_outlet(raw_title, name)
                summary_text = clean_html(entry.get("summary", "") or entry.get("description", ""))
                if is_duplicate(title, seen_titles) or not is_news(title):
                    continue
                if feed_info.get("require_tech") and not is_tech(f"{title} {summary_text}"):
                    continue
                seen_titles.append(_title_tokens(title))

                raw_summary = entry.get("summary", "") or entry.get("description", "")
                summary = clean_html(raw_summary)
                link = entry.get("link", "")
                article_url = resolve_article_url(entry, name)

                category = infer_category(title, summary, default_cat)
                story_id = re.sub(r"[^a-zA-Z0-9]+", "_", title[:35]).strip("_").lower()

                article_images = fetch_and_cache_article_images(story_id, article_url, entry) if article_url else []
                primary_image = article_images[0] if article_images else ""

                story = {
                    "id": story_id,
                    "title": raw_title,
                    "summary": summary[:1500],
                    "category": category,
                    "source": name,
                    "outlet": outlet,
                    "link": article_url or link,
                    "published": published_dt.strftime("%Y-%m-%d %H:%M UTC"),
                    "published_ts": published_dt.isoformat(),
                    "image_path": primary_image,
                    "article_images": article_images,
                    "image_url": f"/assets/images/{os.path.basename(primary_image)}" if primary_image else ""
                }
                all_stories.append(prepare_story(story))
        except Exception as e:
            print(f"Error fetching feed {name}: {e}")

    all_stories.sort(key=lambda s: s["published_ts"], reverse=True)
    if not all_stories:
        print("No fresh stories fetched; keeping the previous cache.")
        return _read_cache() or []

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(all_stories, f, indent=2, ensure_ascii=False)
    return all_stories

def _read_cache() -> list[dict] | None:
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def get_cached_news() -> list[dict]:
    """Return cached stories, re-fetching when the cache is older than NEWS_REFRESH_MINUTES."""
    if os.path.exists(CACHE_FILE):
        age_min = (datetime.now().timestamp() - os.path.getmtime(CACHE_FILE)) / 60
        if age_min < NEWS_REFRESH_MINUTES:
            cached = _read_cache()
            if cached:
                return cached
    return fetch_all_news()

def build_ticker_string(stories: list[dict], max_items: int = 12) -> str:
    """Format marquee ticker string with bullet separators."""
    items = []
    for s in stories[:max_items]:
        title, _ = split_title_outlet(s["title"], s.get("source", ""))
        items.append(f"{s['category']}: {title}")
    return "   •   ".join(items)

if __name__ == "__main__":
    news = fetch_all_news(limit_per_feed=2)
    print(f"Fetched {len(news)} stories.")
    for s in news[:3]:
        print(f"Story: {s['title'][:40]} | Article Images: {len(s.get('article_images', []))}")
