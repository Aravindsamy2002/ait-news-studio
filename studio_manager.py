import os
import json
import subprocess
import imageio_ffmpeg
from config import OUTPUT_DIR, DEFAULT_VOICE, CHANNEL_NAME
from fetcher import get_cached_news, build_ticker_string, prepare_story
from voice_engine import generate_segmented_speech
from renderer import render_story_video, render_youtube_thumbnail
from motion_renderer import LEAD_IN, TAIL, story_phase_count
from analysis import with_analysis
from youtube_uploader import build_metadata

METADATA_FILE = os.path.join(OUTPUT_DIR, "broadcast_metadata.json")

def generate_youtube_metadata(story: dict, duration: float) -> dict:
    """Title, description and story-wise tags (same builder the YouTube uploader uses)."""
    return build_metadata(story)

def create_single_story_broadcast(story: dict, voice_key: str = DEFAULT_VOICE) -> dict:
    """Render a single breaking news broadcast video clip + thumbnail + metadata."""
    story_id = story["id"]
    audio_file = f"audio_{story_id}.mp3"
    video_file = f"broadcast_{story_id}.mp4"
    thumb_file = f"thumb_{story_id}.jpg"

    audio_path = os.path.join(OUTPUT_DIR, audio_file)
    video_path = os.path.join(OUTPUT_DIR, video_file)
    thumb_path = os.path.join(OUTPUT_DIR, thumb_file)

    # 1. Clean headline/script, then voice each segment for exact graphic sync
    story = with_analysis(prepare_story(story))
    print(f"Generating voice for: {story['title'][:40]}...")
    audio_path, duration, timings = generate_segmented_speech(story["narration_segments"], audio_file, voice_key=voice_key)
    timings = timings[:story_phase_count(story)]

    # 2. News ticker
    all_news = get_cached_news()
    ticker = build_ticker_string(all_news)

    # 3. Video rendering (Voice-synced points & multi-image Ken Burns)
    print(f"Rendering video (Duration: {duration:.1f}s, Timings: {len(timings)})...")
    render_story_video(story, audio_path, duration, ticker, video_path, timings=timings)

    # 4. Thumbnail
    render_youtube_thumbnail(story, thumb_path)

    # 5. Metadata
    duration += LEAD_IN + TAIL
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

        s = with_analysis(prepare_story(s))
        audio_path, duration, timings = generate_segmented_speech(s["narration_segments"], audio_file, voice_key=voice_key)
        timings = timings[:story_phase_count(s)]
        render_story_video(s, audio_path, duration, ticker, video_path, timings=timings)

        rendered_clips.append(video_path)
        mins = int(total_time // 60)
        secs = int(total_time % 60)
        chapters.append(f"{mins:02d}:{secs:02d} - {s['title']}")
        total_time += duration + LEAD_IN + TAIL

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
    lead = prepare_story(stories[0])
    thumb_path = os.path.join(OUTPUT_DIR, "bulletin_thumb.jpg")
    render_youtube_thumbnail(lead, thumb_path)

    # Chapters description
    chapter_text = "\n".join(chapters)
    description = f"""🔥 AIT NEWS DAILY BULLETIN — TOP TECH & AI STORIES

Chapters:
{chapter_text}

The day's biggest technology and AI stories from AIT NEWS.

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
