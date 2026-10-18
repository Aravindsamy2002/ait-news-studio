# 📡 AIT NEWS STUDIO (24/7 AI & Tech Broadcast Automation)

An automated, television-grade news broadcast generation and 24/7 YouTube live streaming studio designed to run on local machines or free cloud instances (e.g., Oracle Cloud Free Tier).

![AIT News Studio Banner](assets/broll/broll_ai_processor.jpg)

---

## ⚡ Key Capabilities

- **📰 Automated Tech & AI RSS Scraper:** Continuously aggregates breaking stories from TechCrunch AI, The Verge, Ars Technica, and Hacker News.
- **🎙️ Neural News Anchor Voice Engine:** Uses Edge-TTS (100% free, zero-cost broadcast neural voices such as `en-US-ChristopherNeural` and `en-US-JennyNeural`).
- **⏱️ Voice-Synchronized Text & Point Animations:** Automatically extracts millisecond sentence boundaries to dynamically highlight bullet points and update lower-third banners in lockstep with the anchor's speech.
- **🎥 Multi-Image Camera Cutting with Ken Burns Motion:** Switches between multiple high-resolution article photos and category-tailored B-roll footage (Cyber Defense Center, AI Synapse Core, High-Density Server Racks) using smooth documentary-style zoom and pan motions.
- **📊 Real-Time Audio Spectrum Waveform:** Animated cyan audio waveform reacting to the news anchor's voice.
- **🎞️ Bloomberg/BBC Style Graphics:** 1080p 30fps layout featuring a live UTC/IST clock, pulsing red LIVE badge, category pill, and continuous scrolling marquee headline ticker.
- **🚀 YouTube Automation & 24/7 RTMP Streaming:**
  - Auto-generated 1280x720 high-CTR YouTube thumbnails.
  - Auto-generated SEO titles, descriptions with chapter timestamps, and tags.
  - 1-click 24/7 YouTube Live RTMP streaming powered by FFmpeg.

---

## 🛠️ Architecture

```
ait_news_studio/
├── app.py                 # FastAPI web control dashboard server
├── config.py              # Feeds, voices, branding, video & RTMP configuration
├── fetcher.py             # RSS scraper, article image extractor & script formatter
├── voice_engine.py        # Neural TTS engine with sentence boundary timing extraction
├── renderer.py            # FFmpeg & PIL broadcast renderer (multi-image, Ken Burns, waveform)
├── studio_manager.py      # High-level coordinator for single clips, bulletins & metadata
├── streamer.py            # Continuous 24/7 YouTube Live RTMP streaming controller
├── assets_builder.py      # Ambient broadcast background bed & asset generator
├── templates/
│   └── index.html         # Modern BBC/Cyberpunk dashboard UI
├── assets/
│   ├── broll/             # High-res B-roll footage (AI chip, cyber defense, datacenter)
│   ├── images/            # Cached article images
│   └── news_ambient_bed.wav
└── output/                # Rendered broadcast MP4s, thumbnails, and metadata
```

---

## 🚀 Quick Start (Local Setup)

### 1. Clone the repository
```bash
git clone https://github.com/Aravindsamy2002/ait-news-studio.git
cd ait-news-studio
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Launch the Studio Dashboard
```bash
python app.py
```
Open your browser at **`http://127.0.0.1:8765`**.

---

## ☁️ Deploying on Oracle Cloud Free Tier (24/7 Streaming)

Target: **Ampere A1 (ARM64), 4 OCPU / 24 GB, Ubuntu 22.04 or 24.04**. Everything runs on the free tier:
Kokoro TTS and the Ollama analysis model run locally on the CPU, and the stream uses about 1.5 TB/month
of the 10 TB free egress.

1. Clone the repository on the VM, then run the one-time setup:
   ```bash
   bash deploy/setup_oracle.sh
   ```
   It installs FFmpeg, a Python venv, Ollama (`qwen2.5:3b`), the Kokoro voice model and an `ait-news` systemd service.
2. Put your stream key in `/etc/ait-news/env` (`YOUTUBE_STREAM_KEY=...`).
3. `sudo systemctl start ait-news` and follow the log with `journalctl -u ait-news -f`.

How the autopilot (`autopilot.py`) keeps the stream alive:
- **Scheduler**: refreshes the feeds every 15 minutes and picks the on-air rotation (breaking stories first, then newest; stories without a real article image are skipped).
- **Render queue**: 3 worker processes render missing clips in the background. Each story version is rendered once and cached in `output/clips/`. A story that stops being "breaking" after 2 hours is re-rendered without the BREAKING graphics.
- **Streamer**: one FFmpeg process pushes to YouTube with `-c copy` (no re-encoding), splicing clips from the rotation. A standby slate plays until the first clip is ready, so there is never dead air.

Dry run without YouTube: `python autopilot.py --output test.flv --minutes 5`

### YouTube uploads and live title (optional, free API quota)

Once a token exists, the autopilot also uploads each new story as its own video (title, description with
source link, story-wise tags, News category, BBC-style thumbnail; paced: max 4/day, 2 hours apart) and keeps the 24/7
stream titled after the top story ("AIT News LIVE: ...").

1. Google Cloud Console → new project → enable **YouTube Data API v3**.
2. OAuth consent screen: External, add your Google account as a user, then set publishing status to
   **In production** (in "Testing", refresh tokens expire after 7 days).
3. Credentials → Create OAuth client ID → **Desktop app** → download `client_secret.json`.
4. On your PC: `python youtube_uploader.py auth --client-secret client_secret.json` (sign in as the AIT News channel).
5. Copy `secrets/youtube_token.json` to the same path on the VM, then check: `python youtube_uploader.py whoami`.

Preview what would be uploaded: `python youtube_uploader.py preview`.
Settings (env): `YOUTUBE_UPLOADS`, `YOUTUBE_LIVE_TITLE`, `YOUTUBE_PRIVACY`, `YOUTUBE_MAX_UPLOADS_PER_DAY`.

---

## 📜 License
MIT License
