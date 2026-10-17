import re
import html
import json
import os
import urllib.request
from datetime import datetime, timezone
import feedparser
from bs4 import BeautifulSoup
from PIL import Image
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

            # Images in article content
            for container in soup.find_all(["article", "main", "figure", "div"]):
                c_class = " ".join(container.get("class", []))
                if any(k in c_class for k in ["content", "article", "post", "body", "entry"]):
                    for im in container.find_all("img"):
                        src = im.get("src") or im.get("data-src") or ""
                        if src.startswith("http"):
                            # Filter out non-article visuals (avatars, headshots, icons, logos, svgs)
                            is_junk = any(k in src.lower() for k in [
                                "author", "headshot", "avatar", "profile", "logo",
                                "icon", "pixel", "advert", "sponsor", ".svg", "button"
                            ])
                            if not is_junk and src not in found_urls:
                                found_urls.append(src)
        except Exception as e:
            print(f"Error scraping article images from {article_url}: {e}")

    # Remove duplicates and clean
    unique = []
    for u in found_urls:
        if u not in unique and not u.endswith(".svg"):
            unique.append(u)

    return unique

def generate_cinematic_crops_from_image(base_img_path: str, story_id: str) -> list[str]:
    """When an article has 1 image, generate 4 cinematic camera angles strictly from that article image."""
    paths = [base_img_path]
    try:
        img = Image.open(base_img_path).convert("RGB")
        W, H = img.size

        # CAM 2: Tight Close-up (center-top 65% of the photo)
        cw, ch = int(W * 0.65), int(H * 0.65)
        x0 = (W - cw) // 2
        y0 = int(H * 0.08)
        c2 = img.crop((x0, y0, x0 + cw, y0 + ch))
        p2 = os.path.join(IMAGES_DIR, f"{story_id}_cam2_tight.jpg")
        c2.save(p2, "JPEG", quality=90)
        paths.append(p2)

        # CAM 3: Medium Left / Action Focus
        x0 = int(W * 0.05)
        y0 = int(H * 0.12)
        c3 = img.crop((x0, y0, x0 + cw, y0 + ch))
        p3 = os.path.join(IMAGES_DIR, f"{story_id}_cam3_left.jpg")
        c3.save(p3, "JPEG", quality=90)
        paths.append(p3)

        # CAM 4: Medium Right Focus
        x0 = max(0, W - cw - int(W * 0.05))
        y0 = int(H * 0.12)
        c4 = img.crop((x0, y0, x0 + cw, y0 + ch))
        p4 = os.path.join(IMAGES_DIR, f"{story_id}_cam4_right.jpg")
        c4.save(p4, "JPEG", quality=90)
        paths.append(p4)

    except Exception as e:
        print(f"Error generating angle crops: {e}")

    return paths

def fetch_and_cache_article_images(story_id: str, article_url: str, feed_entry) -> list[str]:
    """Download and cache ONLY images used in the article itself."""
    # Check if already cached
    primary_path = os.path.join(IMAGES_DIR, f"{story_id}_img0.jpg")
    if os.path.exists(primary_path) and os.path.getsize(primary_path) > 3000:
        # Check existing angles/images
        existing = [p for p in [
            primary_path,
            os.path.join(IMAGES_DIR, f"{story_id}_cam2_tight.jpg"),
            os.path.join(IMAGES_DIR, f"{story_id}_cam3_left.jpg"),
            os.path.join(IMAGES_DIR, f"{story_id}_cam4_right.jpg"),
        ] if os.path.exists(p)]
        if len(existing) >= 2:
            return existing

    image_urls = scrape_article_image_urls(article_url, feed_entry)
    downloaded_paths = []

    for idx, url in enumerate(image_urls[:4]):
        out_p = os.path.join(IMAGES_DIR, f"{story_id}_img{idx}.jpg")
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = resp.read()
                if len(data) > 3000:
                    with open(out_p, "wb") as f:
                        f.write(data)
                    downloaded_paths.append(out_p)
        except Exception as e:
            print(f"Failed to download article image {url}: {e}")

    # If only 1 image found in article, create 4 cinematic camera angles strictly from that photo
    if len(downloaded_paths) == 1:
        return generate_cinematic_crops_from_image(downloaded_paths[0], story_id)
    elif len(downloaded_paths) > 1:
        return downloaded_paths

    # Fallback to existing image if any
    old_p = os.path.join(IMAGES_DIR, f"{story_id}.jpg")
    if os.path.exists(old_p) and os.path.getsize(old_p) > 3000:
        return generate_cinematic_crops_from_image(old_p, story_id)

    return []

def fetch_all_news(limit_per_feed: int = 4) -> list[dict]:
    """Fetch stories from all configured RSS feeds with genuine article images."""
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

                # Extract and download ONLY article's own images
                article_images = fetch_and_cache_article_images(story_id, link, entry)
                primary_image = article_images[0] if article_images else ""

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
                    "image_path": primary_image,
                    "article_images": article_images,
                    "image_url": f"/assets/images/{os.path.basename(primary_image)}" if primary_image else ""
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
    print(f"Fetched {len(news)} stories.")
    for s in news[:3]:
        print(f"Story: {s['title'][:40]} | Article Images: {len(s.get('article_images', []))}")
