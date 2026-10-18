import os
from datetime import datetime, timezone
from PIL import Image, ImageDraw, ImageFont
from config import (
    VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_FPS,
    OUTPUT_DIR, ASSETS_DIR, CHANNEL_NAME, CHANNEL_TAGLINE
)
from motion_renderer import render_animated_story, render_thumbnail, story_phase_count

BROLL_DIR = os.path.join(ASSETS_DIR, "broll")

def get_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    """Safely load Windows system font with fallbacks."""
    win_fonts = r"C:\Windows\Fonts"
    candidates = [
        os.path.join(win_fonts, name),
        os.path.join(win_fonts, "segoeuib.ttf"),
        os.path.join(win_fonts, "arialbd.ttf"),
        os.path.join(win_fonts, "calibrib.ttf"),
        os.path.join(win_fonts, "arial.ttf"),
    ]
    for c in candidates:
        if os.path.exists(c):
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                pass
    return ImageFont.load_default()

def get_story_image_pool(story: dict) -> list[str]:
    """Gather ONLY genuine images and camera angles from the article itself."""
    article_imgs = story.get("article_images", [])
    valid = [p for p in article_imgs if p and os.path.exists(p) and os.path.getsize(p) > 2000]

    if not valid:
        primary = story.get("image_path")
        if primary and os.path.exists(primary) and os.path.getsize(primary) > 2000:
            valid.append(primary)

    if not valid:
        fallback = os.path.join(OUTPUT_DIR, "preview_slide.png")
        if os.path.exists(fallback):
            valid.append(fallback)

    return valid

def render_phase_slide(
    story: dict,
    active_bullet_idx: int,
    output_image_path: str,
    time_str: str = None
) -> str:
    """Render base 1920x1080 template with dynamic voice-synced highlighted points."""
    W, H = VIDEO_WIDTH, VIDEO_HEIGHT
    img = Image.new("RGBA", (W, H), (11, 15, 25, 255))
    draw = ImageDraw.Draw(img)

    # 1. Tech Cyber Grid Background
    for x in range(0, W, 80):
        draw.line([(x, 0), (x, H)], fill=(20, 30, 50, 100), width=1)
    for y in range(0, H, 80):
        draw.line([(0, y), (W, y)], fill=(20, 30, 50, 100), width=1)

    for r in range(450, 50, -50):
        alpha = int((1 - r / 450) * 35)
        draw.ellipse([(W//2 - r*2, H//2 - r), (W//2 + r*2, H//2 + r)], fill=(37, 99, 235, alpha))

    # Fonts
    font_logo = get_font("arialbd.ttf", 44)
    font_header_tag = get_font("segoeui.ttf", 22)
    font_time = get_font("segoeuib.ttf", 24)
    font_cat = get_font("segoeuib.ttf", 24)
    font_title = get_font("segoeuib.ttf", 44)
    font_body = get_font("segoeui.ttf", 27)
    font_source = get_font("segoeuib.ttf", 20)
    font_ticker_lbl = get_font("segoeuib.ttf", 26)
    font_breaking = get_font("segoeuib.ttf", 30)
    font_wave_lbl = get_font("segoeuib.ttf", 16)
    font_active_tag = get_font("segoeuib.ttf", 18)

    # 2. TOP HEADER BAR
    draw.rectangle([(0, 0), (W, 85)], fill=(15, 23, 42, 240))
    draw.line([(0, 85), (W, 85)], fill=(220, 38, 38, 255), width=3)

    draw.rectangle([(60, 12), (180, 72)], fill=(220, 38, 38, 255))
    draw.text((78, 16), "AIT", font=font_logo, fill=(255, 255, 255, 255))
    draw.text((200, 18), "NEWS", font=font_logo, fill=(255, 255, 255, 255))
    draw.text((345, 30), CHANNEL_TAGLINE, font=font_header_tag, fill=(148, 163, 184, 255))

    if not time_str:
        time_str = datetime.now(timezone.utc).strftime("%H:%M UTC") + " • LIVE"
    draw.ellipse([(W - 440, 32), (W - 420, 52)], fill=(239, 68, 68, 255))
    draw.text((W - 410, 28), "LIVE", font=font_time, fill=(239, 68, 68, 255))
    draw.text((W - 330, 28), f"|  {time_str}", font=font_time, fill=(241, 245, 249, 255))

    # 3. LEFT STORY CARD (54% width)
    card_x0, card_y0 = 80, 130
    card_x1, card_y1 = 1040, 860
    draw.rounded_rectangle([(card_x0+6, card_y0+6), (card_x1+6, card_y1+6)], radius=18, fill=(0, 0, 0, 120))
    draw.rounded_rectangle([(card_x0, card_y0), (card_x1, card_y1)], radius=18, fill=(17, 24, 39, 235), outline=(55, 65, 81, 255), width=2)

    cat_text = f"⚡ {story.get('category', 'TECH BREAKTHROUGH')}"
    draw.rounded_rectangle([(card_x0 + 40, card_y0 + 35), (card_x0 + 380, card_y0 + 80)], radius=10, fill=(220, 38, 38, 255))
    draw.text((card_x0 + 55, card_y0 + 44), cat_text, font=font_cat, fill=(255, 255, 255, 255))

    src_text = f"SOURCE: {story.get('source', 'GLOBAL').upper()} • VERIFIED"
    draw.text((card_x0 + 400, card_y0 + 50), src_text, font=font_source, fill=(156, 163, 175, 255))

    headline = story.get("title", "")
    words = headline.split()
    h_lines = []
    cur_line = []
    for w in words:
        cur_line.append(w)
        test_str = " ".join(cur_line)
        bbox = draw.textbbox((0, 0), test_str, font=font_title)
        if (bbox[2] - bbox[0]) > (card_x1 - card_x0 - 90):
            cur_line.pop()
            h_lines.append(" ".join(cur_line))
            cur_line = [w]
    if cur_line:
        h_lines.append(" ".join(cur_line))

    headline_y = card_y0 + 105
    for l in h_lines[:3]:
        draw.text((card_x0 + 40, headline_y), l, font=font_title, fill=(255, 255, 255, 255))
        headline_y += 54

    draw.line([(card_x0 + 40, headline_y + 12), (card_x1 - 40, headline_y + 12)], fill=(37, 99, 235, 180), width=3)

    # Dynamic Bullets
    bullets = story.get("bullets", [])
    body_y = headline_y + 35

    for b_idx, bullet in enumerate(bullets[:3]):
        is_active = (b_idx == active_bullet_idx)
        is_past = (b_idx < active_bullet_idx) or (active_bullet_idx >= 3)
        b_height = 80

        if is_active:
            # Highlight container with electric cyan border
            draw.rounded_rectangle(
                [(card_x0 + 25, body_y - 8), (card_x1 - 25, body_y + b_height)],
                radius=10,
                fill=(30, 58, 138, 160),
                outline=(56, 189, 248, 240),
                width=2
            )
            draw.rounded_rectangle([(card_x0 + 35, body_y - 20), (card_x0 + 185, body_y + 2)], radius=6, fill=(220, 38, 38, 255))
            draw.text((card_x0 + 45, body_y - 18), f"▶ POINT {b_idx + 1} LIVE", font=font_active_tag, fill=(255, 255, 255, 255))

            dot_color = (56, 189, 248, 255)
            text_color = (255, 255, 255, 255)
        elif is_past:
            dot_color = (16, 185, 129, 255) # Green
            text_color = (226, 232, 240, 220)
        else:
            dot_color = (75, 85, 99, 150)
            text_color = (100, 116, 139, 140)

        draw.ellipse([(card_x0 + 45, body_y + 12), (card_x0 + 61, body_y + 28)], fill=dot_color)

        b_words = bullet.split()
        b_lines = []
        b_cur = []
        for bw in b_words:
            b_cur.append(bw)
            b_test = " ".join(b_cur)
            bbox = draw.textbbox((0, 0), b_test, font=font_body)
            if (bbox[2] - bbox[0]) > (card_x1 - card_x0 - 140):
                b_cur.pop()
                b_lines.append(" ".join(b_cur))
                b_cur = [bw]
        if b_cur:
            b_lines.append(" ".join(b_cur))

        ty = body_y + 5
        for bl in b_lines[:2]:
            draw.text((card_x0 + 75, ty), bl, font=font_body, fill=text_color)
            ty += 34
        body_y += b_height + 15

    draw.text((card_x0 + 40, card_y1 - 65), "🎙️ LIVE ANCHOR AUDIO SPECTRUM", font=font_wave_lbl, fill=(148, 163, 184, 255))

    # 4. RIGHT MEDIA VIEWPORT
    frame_x0, frame_y0 = 1080, 130
    frame_x1, frame_y1 = 1840, 860
    draw.rounded_rectangle([(frame_x0-4, frame_y0-4), (frame_x1+4, frame_y1+4)], radius=18, outline=(56, 189, 248, 200), width=3)
    draw.rectangle([(frame_x0 + 20, frame_y0 - 20), (frame_x0 + 300, frame_y0 + 15)], fill=(15, 23, 42, 255))
    cam_num = max(1, active_bullet_idx + 2) if active_bullet_idx >= 0 else 1
    phase_label = f"LIVE REPORT FOOTAGE • CAM {cam_num}"
    draw.text((frame_x0 + 30, frame_y0 - 15), phase_label, font=font_source, fill=(56, 189, 248, 255))

    # 5. LOWER THIRD BANNER
    l3_y0, l3_y1 = 890, 980
    draw.rectangle([(0, l3_y0), (320, l3_y1)], fill=(220, 38, 38, 255))
    draw.text((50, l3_y0 + 24), "BREAKING", font=font_breaking, fill=(255, 255, 255, 255))

    draw.rectangle([(320, l3_y0), (W, l3_y1)], fill=(15, 23, 42, 255))
    draw.line([(320, l3_y0), (W, l3_y0)], fill=(220, 38, 38, 255), width=3)
    if active_bullet_idx >= 0 and active_bullet_idx < len(bullets):
        l3_text = f"POINT {active_bullet_idx + 1}: {bullets[active_bullet_idx]}"
    else:
        l3_text = headline
    short_l3 = l3_text[:80] + ("..." if len(l3_text) > 80 else "")
    draw.text((360, l3_y0 + 24), short_l3, font=font_breaking, fill=(255, 255, 255, 255))

    # 6. BOTTOM TICKER RUNWAY
    ticker_y0, ticker_y1 = 990, 1080
    draw.rectangle([(0, ticker_y0), (W, ticker_y1)], fill=(7, 10, 19, 255))
    draw.line([(0, ticker_y0), (W, ticker_y0)], fill=(245, 158, 11, 255), width=3)

    draw.rectangle([(0, ticker_y0), (220, ticker_y1)], fill=(245, 158, 11, 255))
    draw.text((30, ticker_y0 + 26), "AIT TICKER", font=font_ticker_lbl, fill=(0, 0, 0, 255))

    img.save(output_image_path, "PNG")
    return output_image_path

def compute_phase_durations(total_duration: float, timings: list[dict] = None, n_phases: int = 4) -> list[float]:
    """Voice-synced phase lengths: intro/headline, then one phase per key point.

    `timings` holds one {"start", "end"} entry per phase (from segmented narration);
    each phase runs until the next one starts, the last until the audio ends.
    """
    if timings:
        starts = [0.0] + [seg["start"] for seg in timings[1:]]
        ends = starts[1:] + [total_duration]
        return [max(0.5, e - s) for s, e in zip(starts, ends)]
    seg = total_duration / n_phases
    return [seg] * (n_phases - 1) + [total_duration - seg * (n_phases - 1)]

def render_story_video(
    story: dict,
    audio_path: str,
    duration: float,
    ticker_text: str,
    output_video_path: str,
    timings: list[dict] = None
) -> str:
    """Render the full voice-synchronized broadcast with news-channel motion graphics."""
    n_phases = story_phase_count(story)
    durations = compute_phase_durations(duration, timings, n_phases)
    return render_animated_story(story, audio_path, duration, ticker_text, output_video_path, durations)

def render_youtube_thumbnail(story: dict, output_thumb_path: str) -> str:
    """Render a 1280x720 YouTube thumbnail in the broadcast style."""
    return render_thumbnail(story, output_thumb_path)
