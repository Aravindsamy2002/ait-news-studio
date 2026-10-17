import re
import html
import json
import os
import urllib.request
from datetime import datetime, timezone
import feedparser
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
from config import RSS_FEEDS, OUTPUT_DIR, ASSETS_DIR

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

def infer_category(title: str, summary: str, default: str) -> str:
    """Infer high-impact broadcast category from keywords."""
    combined = (title + " " + summary).lower()
    if any(k in combined for k in ["hack", "breach", "vulnerability", "malware", "security", "exploit"]):
        return "CYBERSECURITY & DEFENSE"
    elif any(k in combined for k in ["openai", "gpt", "anthropic", "claude", "deepseek", "llm", "agent", "gemini", "model"]):
        return "ARTIFICIAL INTELLIGENCE"
    elif any(k in combined for k in ["nvidia", "chip", "semiconductor", "tsmc", "intel", "amd", "gpu"]):
        return "SILICON & HARDWARE"
    elif any(k in combined for k in ["crypto", "bitcoin", "blockchain", "ethereum", "solana"]):
        return "FINTECH & CRYPTO"
    elif any(k in combined for k in ["space", "nasa", "spacex", "satellite", "rocket"]):
        return "AEROSPACE & SCIENCE"
    elif any(k in combined for k in ["google", "apple", "meta", "microsoft", "amazon"]):
        return "BIG TECH RADAR"
    return default

def generate_bullet_points(title: str, summary: str) -> list[str]:
    """Break summary down into 2-3 punchy broadcast bullet points."""
    sentences = re.split(r"(?<=[.!?])\s+", summary)
    bullets = []
    for s in sentences:
        s = s.strip()
        if len(s) > 25:
            if len(s) > 120:
                s = s[:117] + "..."
            bullets.append(s)
            if len(bullets) >= 3:
                break
    
    if not bullets:
        bullets = [
            "Breaking development reported across international technology wires.",
            "Key industry stakeholders monitoring potential impacts on the AI ecosystem.",
            "AIT News desk continues tracking live updates as the story unfolds."
        ]
    elif len(bullets) == 1:
        bullets.append("Further technical analysis and developer responses are currently developing.")
        bullets.append("Market observers note this could accelerate regulatory discussions.")
    elif len(bullets) == 2:
        bullets.append("AIT 24/7 Live desk will provide continuous coverage as more details emerge.")

    return bullets

def generate_narration_script(title: str, summary: str, source: str) -> str:
    """Generate professional broadcast anchor narration text."""
    clean_title = title.replace("&", "and").replace('"', "").replace("'", "")
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", summary) if len(s.strip()) > 20]
    lead = sentences[0] if sentences else "Major developments are currently unfolding across the global tech sector."
    second = f" {sentences[1]}" if len(sentences) > 1 and len(sentences[1]) < 140 else ""

    script = (
        f"This is AIT News. In our top tech story today, {clean_title}. "
        f"{lead}{second} Reporting via {source}. We will bring you further updates as this develops."
    )
    return script

def extract_feed_image_url(entry) -> str:
    """Extract image URL directly from feed tags if present."""
    if "media_content" in entry:
        for m in entry.media_content:
            if "url" in m and m["url"].startswith("http"):
                return m["url"]
    if "enclosures" in entry:
        for enc in entry.enclosures:
            if "href" in enc and enc["href"].startswith("http"):
                return enc["href"]
    if "links" in entry:
        for l in entry.links:
            if l.get("type", "").startswith("image/") and l.get("href"):
                return l["href"]
    return ""

def fetch_article_og_image(article_url: str) -> str:
    """Fetch OpenGraph image from article page with quick timeout."""
    if not article_url or not article_url.startswith("http"):
        return ""
    try:
        req = urllib.request.Request(
            article_url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req, timeout=4) as resp:
            html_doc = resp.read(150000).decode("utf-8", errors="ignore")
            soup = BeautifulSoup(html_doc, "html.parser")
            og_img = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "twitter:image"})
            if og_img and og_img.get("content"):
                return og_img.get("content")
    except Exception:
        pass
    return ""

def generate_fallback_themed_image(output_path: str, category: str, title: str):
    """Generate a modern cyber/tech graphic if no article photo is found."""
    W, H = 1200, 800
    img = Image.new("RGBA", (W, H), (15, 23, 42, 255))
    draw = ImageDraw.Draw(img)

    # Cyber grid
    for x in range(0, W, 60):
        draw.line([(x, 0), (x, H)], fill=(30, 41, 59, 120), width=1)
    for y in range(0, H, 60):
        draw.line([(0, y), (W, y)], fill=(30, 41, 59, 120), width=1)

    # Radial glow
    for r in range(350, 50, -40):
        alpha = int((1 - r / 350) * 50)
        draw.ellipse([(W//2 - r, H//2 - r), (W//2 + r, H//2 + r)], fill=(37, 99, 235, alpha))

    font_path = "C:\\Windows\\Fonts\\segoeuib.ttf"
    try:
        font_cat = ImageFont.truetype(font_path, 40)
        font_sub = ImageFont.truetype(font_path, 28)
    except Exception:
        font_cat = ImageFont.load_default()
        font_sub = font_cat

    draw.rounded_rectangle([(100, 100), (W - 100, H - 100)], radius=20, outline=(56, 189, 248, 180), width=3)
    draw.text((140, 140), f"⚡ {category}", font=font_cat, fill=(248, 113, 113, 255))
    draw.text((140, 220), "AIT NEWS LIVE REPORT FOOTAGE", font=font_sub, fill=(56, 189, 248, 255))

    img.convert("RGB").save(output_path, "JPEG", quality=85)

def cache_story_image(story_id: str, feed_img_url: str, article_link: str, category: str, title: str) -> str:
    """Download and cache relevant story photo, or create fallback."""
    local_path = os.path.join(IMAGES_DIR, f"{story_id}.jpg")
    if os.path.exists(local_path) and os.path.getsize(local_path) > 3000:
        return local_path

    img_url = feed_img_url or fetch_article_og_image(article_link)
    if img_url:
        try:
            req = urllib.request.Request(
                img_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = resp.read()
                if len(data) > 3000:
                    with open(local_path, "wb") as f:
                        f.write(data)
                    return local_path
        except Exception as e:
            print(f"Failed to download image {img_url}: {e}")

    # Fallback graphic
    generate_fallback_themed_image(local_path, category, title)
    return local_path

def fetch_all_news(limit_per_feed: int = 4) -> list[dict]:
    """Fetch stories from all configured RSS feeds with images and scripts."""
    all_stories = []

    for feed_info in RSS_FEEDS:
        name = feed_info["name"]
        url = feed_info["url"]
        default_cat = feed_info["default_category"]

        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:limit_per_feed]:
                title = clean_html(entry.get("title", ""))
                if not title or len(title) < 15:
                    continue

                raw_summary = entry.get("summary", "") or entry.get("description", "")
                summary = clean_html(raw_summary)

                link = entry.get("link", "")
                published = entry.get("published", "") or entry.get("updated", "") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

                category = infer_category(title, summary, default_cat)
                bullets = generate_bullet_points(title, summary)
                narration = generate_narration_script(title, summary, name)

                story_id = re.sub(r"[^a-zA-Z0-9]+", "_", title[:35]).strip("_").lower()

                # Get image URL & cache photo
                feed_img = extract_feed_image_url(entry)
                image_path = cache_story_image(story_id, feed_img, link, category, title)

                all_stories.append({
                    "id": story_id,
                    "title": title,
                    "summary": summary[:400],
                    "category": category,
                    "source": name,
                    "link": link,
                    "published": published,
                    "bullets": bullets,
                    "narration": narration,
                    "image_path": image_path,
                    "image_url": f"/assets/images/{os.path.basename(image_path)}"
                })
        except Exception as e:
            print(f"Error fetching feed {name}: {e}")

    # Save to cache
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(all_stories, f, indent=2, ensure_ascii=False)

    return all_stories

def get_cached_news() -> list[dict]:
    """Retrieve news from cache or fetch fresh if cache missing."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return fetch_all_news()

def build_ticker_string(stories: list[dict], max_items: int = 12) -> str:
    """Format marquee ticker string with bullet separators."""
    items = [f"⚡ {s['category']}: {s['title']}" for s in stories[:max_items]]
    return "   •   ".join(items)

if __name__ == "__main__":
    news = fetch_all_news(limit_per_feed=2)
    print(f"Fetched {len(news)} stories with cached images!")
    for s in news[:3]:
        print(f"Story: {s['title'][:40]} | Img: {s['image_path']}")
