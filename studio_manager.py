import os
import json
import subprocess
import imageio_ffmpeg
from config import OUTPUT_DIR, DEFAULT_VOICE, CHANNEL_NAME
from fetcher import get_cached_news, build_ticker_string
from voice_engine import generate_speech
from renderer import render_story_video, render_youtube_thumbnail

METADATA_FILE = os.path.join(OUTPUT_DIR, "broadcast_metadata.json")

def generate_youtube_metadata(story: dict, duration: float) -> dict:
    """Generate high-CTR, SEO-optimized title, description, and tags."""
    title = f"{story['title']} | AIT NEWS 24/7 Global Tech Broadcast"
    if len(title) > 95:
        title = f"{story['title'][:70]}... | AIT NEWS"

    cat = story.get("category", "TECH")
    source = story.get("source", "AIT Global Desk")

    description = f"""⚡ {story['title']}
Category: {cat}
Source: {source}

Welcome to AIT NEWS — your 24/7 autonomous source for artificial intelligence, frontier technology, cybersecurity disclosures, and global silicon developments.

📌 KEY HIGHLIGHTS:
• {story['bullets'][0] if len(story['bullets']) > 0 else ''}
• {story['bullets'][1] if len(story['bullets']) > 1 else ''}
• {story['bullets'][2] if len(story['bullets']) > 2 else ''}

🕒 Broadcast Duration: {int(duration)}s
📡 Streamed 24/7 via AIT News Cloud Desk

#AITNews #ArtificialIntelligence #TechNews #OpenAI #CyberSecurity #Silicon #BreakingNews #AI
"""

    tags = [
        "AIT News", "Tech News", "Artificial Intelligence", "AI News",
        "OpenAI", "Claude", "DeepSeek", "Nvidia", "Silicon",
        "Cybersecurity", "Breaking Tech News", "24/7 Live Stream",
        "Tech Wire", "Technology Updates", "Autonomous News"
    ]

    return {
        "title": title,
        "description": description,
        "tags": tags
    }

def create_single_story_broadcast(story: dict, voice_key: str = DEFAULT_VOICE) -> dict:
    """Render a single breaking news broadcast video clip + thumbnail + metadata."""
    story_id = story["id"]
    audio_file = f"audio_{story_id}.mp3"
    video_file = f"broadcast_{story_id}.mp4"
    thumb_file = f"thumb_{story_id}.jpg"

    audio_path = os.path.join(OUTPUT_DIR, audio_file)
    video_path = os.path.join(OUTPUT_DIR, video_file)
    thumb_path = os.path.join(OUTPUT_DIR, thumb_file)

    # 1. Voice generation with sentence boundary timings
    print(f"Generating voice for: {story['title'][:40]}...")
    audio_path, duration, timings = generate_speech(story["narration"], audio_file, voice_key=voice_key)

    # 2. News ticker
    all_news = get_cached_news()
    ticker = build_ticker_string(all_news)

    # 3. Video rendering (Voice-synced points & multi-image Ken Burns)
    print(f"Rendering video (Duration: {duration:.1f}s, Timings: {len(timings)})...")
    render_story_video(story, audio_path, duration, ticker, video_path, timings=timings)

    # 4. Thumbnail
    render_youtube_thumbnail(story, thumb_path)

    # 5. Metadata
    metadata = generate_youtube_metadata(story, duration)
    metadata["video_file"] = video_file
    metadata["audio_file"] = audio_file
    metadata["thumb_file"] = thumb_file
    metadata["duration"] = duration
    metadata["story_id"] = story_id

    # Save metadata
    with open(METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    return metadata

def create_multi_story_bulletin(stories: list[dict], voice_key: str = DEFAULT_VOICE) -> dict:
    """Stitch multiple stories into a full continuous broadcast bulletin."""
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    rendered_clips = []
    chapters = []
    total_time = 0.0

    all_news = get_cached_news()
    ticker = build_ticker_string(all_news)

    for i, s in enumerate(stories):
        story_id = s["id"]
        audio_file = f"b_audio_{i}_{story_id}.mp3"
        video_file = f"b_clip_{i}_{story_id}.mp4"
        video_path = os.path.join(OUTPUT_DIR, video_file)

        audio_path, duration, timings = generate_speech(s["narration"], audio_file, voice_key=voice_key)
        render_story_video(s, audio_path, duration, ticker, video_path, timings=timings)

        rendered_clips.append(video_path)
        mins = int(total_time // 60)
        secs = int(total_time % 60)
        chapters.append(f"{mins:02d}:{secs:02d} - {s['title']}")
        total_time += duration

    # Concat file
    concat_txt_path = os.path.join(OUTPUT_DIR, "concat_list.txt")
    with open(concat_txt_path, "w", encoding="utf-8") as f:
        for clip in rendered_clips:
            # Escape path for FFmpeg concat
            p_esc = clip.replace("\\", "/")
            f.write(f"file '{p_esc}'\n")

    bulletin_video_name = "ait_full_bulletin.mp4"
    bulletin_video_path = os.path.join(OUTPUT_DIR, bulletin_video_name)

    # Run FFmpeg concat demuxer
    cmd = [
        ffmpeg_exe, "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_txt_path,
        "-c", "copy",
        bulletin_video_path
    ]
    subprocess.run(cmd, check=True)

    # Thumbnail from lead story
    lead = stories[0]
    thumb_path = os.path.join(OUTPUT_DIR, "bulletin_thumb.jpg")
    render_youtube_thumbnail(lead, thumb_path)

    # Chapters description
    chapter_text = "\n".join(chapters)
    description = f"""🔥 AIT NEWS DAILY BULLETIN — TOP TECH & AI STORIES

Chapters:
{chapter_text}

Welcome to AIT NEWS, broadcasting continuous 24/7 AI and technology intelligence.

#AITNews #AINews #TechNews #OpenAI #TechRecap #DailyTech
"""

    metadata = {
        "title": f"AIT NEWS BULLETIN: {lead['title'][:60]} + More Tech Stories",
        "description": description,
        "video_file": bulletin_video_name,
        "thumb_file": "bulletin_thumb.jpg",
        "total_duration": total_time,
        "chapters": chapters
    }

    return metadata

if __name__ == "__main__":
    news = get_cached_news()
    if news:
        print("Testing single broadcast creation...")
        res = create_single_story_broadcast(news[0])
        print("Broadcast created successfully:", res["video_file"])
