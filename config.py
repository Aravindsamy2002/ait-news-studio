import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
STATIC_DIR = os.path.join(BASE_DIR, "static")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(ASSETS_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

# Branding & Studio
CHANNEL_NAME = "AIT NEWS"
CHANNEL_TAGLINE = "AI & TECHNOLOGY GLOBAL BROADCAST"
NETWORK_LABEL = "AIT 24/7 LIVE DESK"

# Video Settings
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
VIDEO_FPS = 30

# Colors (Hex & RGB)
COLOR_PRIMARY_RED = "#DC2626"       # Crimson BBC Red
COLOR_BG_DARK = "#0B0F19"           # Deep Studio Navy
COLOR_CARD_DARK = "#111827"         # Glassmorphism Slate
COLOR_BORDER = "#1E293B"
COLOR_ACCENT_BLUE = "#2563EB"       # Cyber Tech Blue
COLOR_ACCENT_GOLD = "#F59E0B"       # Bloomberg Gold Ticker
COLOR_TEXT_MAIN = "#F8FAFC"
COLOR_TEXT_MUTED = "#94A3B8"

# News Feeds (Real-time Silicon Valley & Global Wire)
RSS_FEEDS = [
    {
        "name": "Techmeme Live Wire",
        "url": "https://www.techmeme.com/feed.xml",
        "default_category": "SILICON VALLEY BREAKING"
    },
    {
        "name": "Google News Tech",
        "url": "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-US&gl=US&ceid=US:en",
        "default_category": "GLOBAL TECH WIRE"
    },
    {
        "name": "TechCrunch AI",
        "url": "https://techcrunch.com/category/artificial-intelligence/feed/",
        "default_category": "AI BREAKTHROUGH"
    },
    {
        "name": "The Verge",
        "url": "https://www.theverge.com/rss/index.xml",
        "default_category": "TECH INDUSTRY"
    },
    {
        "name": "Ars Technica",
        "url": "https://feeds.arstechnica.com/arstechnica/index",
        "default_category": "CYBERSECURITY & DEV"
    }
]

# AI Anchor Voice Profiles
VOICE_PROFILES = {
    "christopher": {
        "name": "Christopher (BBC / CNN International Anchor)",
        "voice_id": "en-US-ChristopherNeural",
        "rate": "+0%",
        "pitch": "+0Hz"
    },
    "jenny": {
        "name": "Jenny (Fast & Clear Tech Anchor)",
        "voice_id": "en-US-JennyNeural",
        "rate": "+2%",
        "pitch": "+0Hz"
    },
    "guy": {
        "name": "Guy (Deep Broadcast Anchor)",
        "voice_id": "en-US-GuyNeural",
        "rate": "+0%",
        "pitch": "-2Hz"
    }
}
DEFAULT_VOICE = "christopher"

# YouTube Streaming RTMP Default
YOUTUBE_RTMP_URL = "rtmp://a.rtmp.youtube.com/live2"
DEFAULT_STREAM_KEY = os.environ.get("YOUTUBE_STREAM_KEY", "")
