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

# "What it means" explainer via a local Ollama server (free, CPU/ARM).
# OFF by default: an LLM can subtly shift a story's meaning, and accuracy comes first.
# Turn on later (e.g. for monetization) with ANALYSIS_ENABLED=1.
ANALYSIS_ENABLED = os.environ.get("ANALYSIS_ENABLED", "0") == "1"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
ANALYSIS_MODEL = os.environ.get("ANALYSIS_MODEL", "qwen2.5:3b")

# Engaging anchor scripts via the Gemini API (free tier). On whenever GEMINI_API_KEY is set.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
SCRIPT_WRITER_ENABLED = bool(GEMINI_API_KEY) and os.environ.get("SCRIPT_WRITER", "1") == "1"

# 24/7 autopilot
RENDER_WORKERS = int(os.environ.get("RENDER_WORKERS", "3"))   # parallel render processes (4-core VM -> 3)
ROTATION_SIZE = 24                                            # stories kept in the on-air rotation (and rendered)
CLIPS_DIR = os.path.join(OUTPUT_DIR, "clips")
CLIP_RETENTION_HOURS = 26                                      # keep the day's clips for the daily bulletin

# Daily long-form "Tech News Today" bulletin (uses one of the daily upload slots)
BULLETIN_ENABLED = os.environ.get("BULLETIN_ENABLED", "1") == "1"
BULLETIN_HOUR_UTC = int(os.environ.get("BULLETIN_HOUR_UTC", "13"))   # 13:00 UTC = 18:30 IST = 9am US Eastern
BULLETIN_STORIES = 20                                          # full stories
BULLETIN_ROUNDUP = 10                                          # extra headlines in the "In brief" round-up
BULLETINS_DIR = os.path.join(OUTPUT_DIR, "bulletins")

# Freshness rules (no stale story is ever presented as new)
MAX_STORY_AGE_HOURS = 24       # stories older than this are dropped
BREAKING_WINDOW_HOURS = 2      # only stories published within this window get "BREAKING NEWS"
NEWS_REFRESH_MINUTES = 15      # cached feed data older than this is re-fetched

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
    },
    {
        "name": "Engadget",
        "url": "https://www.engadget.com/rss.xml",
        "default_category": "GADGETS & TECH"
    },
    {
        "name": "The Next Web",
        "url": "https://thenextweb.com/feed",
        "default_category": "TECH INDUSTRY"
    },
    {
        "name": "Wired",
        "url": "https://www.wired.com/feed/rss",
        "default_category": "TECH & SCIENCE"
    },
    {
        "name": "9to5Mac",
        "url": "https://9to5mac.com/feed/",
        "default_category": "BIG TECH RADAR"
    },
    {
        "name": "The Register",
        "url": "https://www.theregister.com/headlines.atom",
        "default_category": "ENTERPRISE TECH"
    },
    {
        "name": "BBC Technology",
        "url": "https://feeds.bbci.co.uk/news/technology/rss.xml",
        "default_category": "GLOBAL TECH WIRE",
        "require_tech": True          # this feed sometimes carries general news; keep only tech stories
    }
]

# Anchor Voice Profiles
# engine "kokoro" = free local TTS (runs on CPU, incl. ARM); anything else = edge-tts (online)
VOICE_PROFILES = {
    "heart": {
        "name": "Heart (Kokoro, natural US female anchor)",
        "engine": "kokoro",
        "voice_id": "af_heart",
        "speed": 1.05,
        "lang": "en-us"
    },
    "bella": {
        "name": "Bella (Kokoro, warm US female)",
        "engine": "kokoro",
        "voice_id": "af_bella",
        "speed": 1.05,
        "lang": "en-us"
    },
    "michael": {
        "name": "Michael (Kokoro, US male anchor)",
        "engine": "kokoro",
        "voice_id": "am_michael",
        "speed": 1.05,
        "lang": "en-us"
    },
    "emma": {
        "name": "Emma (Kokoro, British female anchor)",
        "engine": "kokoro",
        "voice_id": "bf_emma",
        "speed": 1.05,
        "lang": "en-gb"
    },
    "george": {
        "name": "George (Kokoro, British male anchor)",
        "engine": "kokoro",
        "voice_id": "bm_george",
        "speed": 1.05,
        "lang": "en-gb"
    },
    "neerja": {
        "name": "Neerja (Indian English News Anchor)",
        "voice_id": "en-IN-NeerjaExpressiveNeural",
        "rate": "+6%",
        "pitch": "+0Hz"
    },
    "prabhat": {
        "name": "Prabhat (Indian English News Anchor)",
        "voice_id": "en-IN-PrabhatNeural",
        "rate": "+6%",
        "pitch": "+0Hz"
    },
    "andrew": {
        "name": "Andrew (Warm US Presenter)",
        "voice_id": "en-US-AndrewMultilingualNeural",
        "rate": "+4%",
        "pitch": "+0Hz"
    },
    "ryan": {
        "name": "Ryan (British Presenter)",
        "voice_id": "en-GB-RyanNeural",
        "rate": "+4%",
        "pitch": "+0Hz"
    },
    "christopher": {
        "name": "Christopher (US News Anchor)",
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
DEFAULT_VOICE = "heart"

# YouTube uploads + live title (YouTube Data API, free quota). Active only once the OAuth token exists.
YOUTUBE_TOKEN_FILE = os.environ.get("YOUTUBE_TOKEN_FILE", os.path.join(BASE_DIR, "secrets", "youtube_token.json"))
YOUTUBE_UPLOADS = os.environ.get("YOUTUBE_UPLOADS", "1") == "1"            # one video per new story
YOUTUBE_LIVE_TITLE = os.environ.get("YOUTUBE_LIVE_TITLE", "1") == "1"      # keep the 24/7 stream title on the top story
YOUTUBE_PRIVACY = os.environ.get("YOUTUBE_PRIVACY", "public")              # public | unlisted | private
YOUTUBE_SHORTS = os.environ.get("YOUTUBE_SHORTS", "1") == "1"              # upload stories as vertical Shorts
YOUTUBE_MAX_UPLOADS_PER_DAY = int(os.environ.get("YOUTUBE_MAX_UPLOADS_PER_DAY", "4"))   # new channel: start very low
YOUTUBE_MIN_UPLOAD_GAP_MINUTES = int(os.environ.get("YOUTUBE_MIN_UPLOAD_GAP_MINUTES", "120"))  # never burst-upload
YOUTUBE_UPLOAD_MAX_AGE_HOURS = 12                                           # don't upload stories older than this
LIVE_TITLE_MINUTES = 30                                                     # at most one live-title change per 30 min

# YouTube Streaming RTMP Default
YOUTUBE_RTMP_URL = "rtmp://a.rtmp.youtube.com/live2"
DEFAULT_STREAM_KEY = os.environ.get("YOUTUBE_STREAM_KEY", "")
