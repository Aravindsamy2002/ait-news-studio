import os
import subprocess
from datetime import datetime, timezone
from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg
from config import (
    VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_FPS,
    OUTPUT_DIR, ASSETS_DIR, CHANNEL_NAME, CHANNEL_TAGLINE
)
from assets_builder import ensure_ambient_bed

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
    """Gather multiple relevant images for the story including article photos and themed B-roll."""
    pool = []
    # Primary article photo
    primary = story.get("image_path")
    if primary and os.path.exists(primary):
        pool.append(primary)

    # Category-tailored B-roll footage
    cat = story.get("category", "").upper()
    broll_ai = os.path.join(BROLL_DIR, "broll_ai_processor.jpg")
    broll_cyber = os.path.join(BROLL_DIR, "broll_cyber_defense.jpg")
    broll_data = os.path.join(BROLL_DIR, "broll_datacenter_servers.jpg")

    if "CYBER" in cat or "DEFENSE" in cat:
        order = [broll_cyber, broll_ai, broll_data]
    elif "SILICON" in cat or "HARDWARE" in cat or "CHIP" in cat:
        order = [broll_ai, broll_data, broll_cyber]
    else:
        order = [broll_ai, broll_cyber, broll_data]

    for b in order:
        if os.path.exists(b) and b not in pool:
            pool.append(b)

    # Fallback to preview_slide if pool is still empty
    if not pool:
        fallback = os.path.join(OUTPUT_DIR, "preview_slide.png")
        if os.path.exists(fallback):
            pool.append(fallback)

    return pool

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

def compute_phase_durations(total_duration: float, timings: list[dict] = None) -> list[float]:
    """Calculate exact voice-synced durations for Phase 0 (Intro), Phase 1, Phase 2, Phase 3."""
    if timings and len(timings) >= 4:
        # Use exact sentence boundaries
        t_intro = max(4.0, timings[1]["end"])
        t_p1 = max(t_intro + 3.0, timings[2]["end"])
        t_p2 = max(t_p1 + 3.0, timings[3]["end"])
        
        d0 = t_intro
        d1 = t_p1 - t_intro
        d2 = t_p2 - t_p1
        d3 = max(3.0, total_duration - t_p2)
        return [d0, d1, d2, d3]
    else:
        # Fallback to 4 balanced phases
        seg = total_duration / 4.0
        return [seg, seg, seg, total_duration - (seg * 3)]

def render_story_video(
    story: dict,
    audio_path: str,
    duration: float,
    ticker_text: str,
    output_video_path: str,
    timings: list[dict] = None
) -> str:
    """Render full voice-synchronized broadcast with multiple camera images and text highlights."""
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    ambient_bed = ensure_ambient_bed()

    # 1. Get multiple images
    image_pool = get_story_image_pool(story)
    # Ensure at least 4 items in pool by wrapping around
    while len(image_pool) < 4:
        image_pool.extend(image_pool)

    # 2. Compute phase durations
    durations = compute_phase_durations(duration, timings)

    # 3. Render 4 individual video segments (each with its own slide state & image)
    segment_files = []
    temp_files = []

    clean_ticker = ticker_text.replace(":", "\\:").replace("'", "").replace("%", "\\%")
    font_path = "C\\:/Windows/Fonts/segoeuib.ttf"

    for i in range(4):
        active_idx = -1 if i == 0 else (i - 1)
        phase_slide = os.path.join(OUTPUT_DIR, f"temp_phase_{story['id']}_{i}.png")
        render_phase_slide(story, active_idx, phase_slide)
        temp_files.append(phase_slide)

        phase_img = image_pool[i % len(image_pool)]
        seg_video = os.path.join(OUTPUT_DIR, f"temp_seg_{story['id']}_{i}.mp4")
        temp_files.append(seg_video)

        seg_dur = durations[i]
        frames = int(seg_dur * VIDEO_FPS) + 20

        # Alternate Ken Burns zoom in vs zoom out across cameras
        if i % 2 == 0:
            z_expr = "min(zoom+0.0007,1.15)"
        else:
            z_expr = "max(1.15-zoom*0.0006,1.0)"

        vf = (
            f"[1:v]scale=1200:800,zoompan=z='{z_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=760x730:fps=30[zoomed_img];"
            f"[0:v][zoomed_img]overlay=1080:130[vout]"
        )

        cmd_seg = [
            ffmpeg_exe, "-y",
            "-loop", "1", "-i", phase_slide,
            "-loop", "1", "-i", phase_img,
            "-filter_complex", vf,
            "-map", "[vout]",
            "-t", f"{seg_dur:.2f}",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p",
            seg_video
        ]
        subprocess.run(cmd_seg, check=True)
        segment_files.append(seg_video)

    # 4. Concatenate visual segments
    concat_txt = os.path.join(OUTPUT_DIR, f"temp_concat_{story['id']}.txt")
    temp_files.append(concat_txt)
    with open(concat_txt, "w") as f:
        for s in segment_files:
            p_esc = os.path.abspath(s).replace("\\", "/")
            f.write(f"file '{p_esc}'\n")

    joined_video = os.path.join(OUTPUT_DIR, f"temp_joined_{story['id']}.mp4")
    temp_files.append(joined_video)
    cmd_join = [
        ffmpeg_exe, "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_txt,
        "-c", "copy",
        joined_video
    ]
    subprocess.run(cmd_join, check=True)

    # 5. Composite Joined Video + Live Audio Waveform + Scrolling Ticker + Ambient Bed Mix
    final_filter = (
        f"[1:a]showwaves=s=550x45:mode=line:colors=0x38BDF8[waveform];"
        f"[0:v][waveform]overlay=440:795[v_wave];"
        f"[v_wave]drawtext=fontfile='{font_path}':text='{clean_ticker}':x=w-t*200:y=1025:fontsize=28:fontcolor=0xFEF08A:shadowcolor=black@0.8:shadowx=2:shadowy=2[vout];"
        f"[2:a]volume=0.18[bg];[1:a][bg]amix=inputs=2:duration=first[aout]"
    )

    cmd_final = [
        ffmpeg_exe, "-y",
        "-i", joined_video,
        "-i", audio_path,
        "-stream_loop", "-1", "-i", ambient_bed,
        "-filter_complex", final_filter,
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "veryfast",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        output_video_path
    ]
    subprocess.run(cmd_final, check=True)

    # Clean up temporary files
    for tf in temp_files:
        if os.path.exists(tf):
            try:
                os.remove(tf)
            except Exception:
                pass

    return output_video_path

def render_youtube_thumbnail(story: dict, output_thumb_path: str) -> str:
    """Render high-CTR 1280x720 YouTube thumbnail featuring the story image."""
    W, H = 1280, 720
    img = Image.new("RGBA", (W, H), (11, 15, 25, 255))

    image_pool = get_story_image_pool(story)
    if image_pool and os.path.exists(image_pool[0]):
        try:
            photo = Image.open(image_pool[0]).convert("RGBA")
            photo = photo.resize((W, H), Image.Resampling.LANCZOS)
            img.paste(photo, (0, 0))
        except Exception:
            pass

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d_over = ImageDraw.Draw(overlay)
    for x in range(0, W):
        alpha = int(255 * (1.0 - (x / (W * 0.85)))) if x < (W * 0.85) else 0
        d_over.line([(x, 0), (x, H)], fill=(7, 10, 19, min(255, alpha + 60)))
    img = Image.alpha_composite(img, overlay)

    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, 0), (W, 25)], fill=(220, 38, 38, 255))

    font_logo = get_font("arialbd.ttf", 36)
    font_badge = get_font("segoeuib.ttf", 26)
    font_title = get_font("segoeuib.ttf", 46)
    font_sub = get_font("segoeuib.ttf", 28)

    draw.rectangle([(40, 50), (140, 105)], fill=(220, 38, 38, 255))
    draw.text((55, 55), "AIT", font=font_logo, fill=(255, 255, 255, 255))
    draw.text((155, 58), "NEWS", font=font_logo, fill=(255, 255, 255, 255))

    draw.rounded_rectangle([(40, 135), (320, 185)], radius=10, fill=(220, 38, 38, 255))
    draw.text((55, 142), "🚨 BREAKING AI", font=font_badge, fill=(255, 255, 255, 255))

    headline = story.get("title", "")
    words = headline.split()
    lines = []
    cur = []
    for w in words:
        cur.append(w)
        bbox = draw.textbbox((0, 0), " ".join(cur), font=font_title)
        if (bbox[2] - bbox[0]) > (W * 0.65):
            cur.pop()
            lines.append(" ".join(cur))
            cur = [w]
    if cur:
        lines.append(" ".join(cur))

    ty = 220
    for l in lines[:4]:
        draw.text((40, ty), l, font=font_title, fill=(255, 255, 255, 255))
        ty += 60

    draw.rectangle([(0, H - 75), (W, H)], fill=(15, 23, 42, 255))
    draw.line([(0, H - 75), (W, H - 75)], fill=(245, 158, 11, 255), width=3)
    draw.text((40, H - 55), f"24/7 AI GLOBAL DESK • SOURCE: {story.get('source', 'GLOBAL').upper()}", font=font_sub, fill=(254, 240, 138, 255))

    img.convert("RGB").save(output_thumb_path, "JPEG", quality=92)
    return output_thumb_path
