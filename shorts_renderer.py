"""
Vertical (9:16) YouTube Shorts version of a story.

Built from the same anchor voice track and phase timings as the 16:9 broadcast clip, so the
on-screen points flip exactly when the anchor moves on. Text stays clear of the Shorts UI
(the caption/button area at the bottom and the action buttons on the right).

    python shorts_renderer.py --meta output/clips/<clip>.json --out short.mp4
"""
import argparse
import json
import math
import os
from datetime import datetime

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from motion_renderer import (
    AMBER, BLACK, DARK_RED, DISPLAY_TZ, FLIP, FPS, RED, WHITE, XFADE, YELLOW,
    clamp, clean, clause_cut, cond, ease_back, ease_in, ease_in_out, ease_out, encode_scene, fit_line,
    font, gloss, gradient, heavy, ken_burns, lerp, make_hashtag, make_plate, on_air_durations,
    placeholder_plate, prog, put, rrect, screen_points, shine_sprite, story_photos, text_layer, wrap,
)

SW, SH = 1080, 1920
MEDIA_Y, MEDIA_H = 230, 840
TAB_Y, TAB_H = 1092, 58
SUPER_Y, SUPER_H = 1150, 330
STRAP_Y, STRAP_H = 1480, 64
TEXT_X, TEXT_W = 48, 860          # keep text left of the Shorts action buttons


class ShortScene:
    def __init__(self, story: dict, phase_durations: list[float]):
        self.durs = list(phase_durations)
        self.starts = [sum(self.durs[:i]) for i in range(len(self.durs))]
        self.total = sum(self.durs)
        self.title = clean(story.get("title", ""))
        self.points = screen_points(story)[: len(self.durs) - 1]
        self.breaking = bool(story.get("is_breaking"))
        self.tag_words = ("BREAKING", "NEWS") if self.breaking else ("BIG", "STORY")
        self.outlet = clean(story.get("outlet") or story.get("source") or "").upper()
        try:
            self.published = datetime.fromisoformat(story.get("published_ts", "")).astimezone(DISPLAY_TZ)
        except ValueError:
            self.published = None

        photos = story_photos(story)
        self.plates = [make_plate(p, SW, MEDIA_H) for p in photos[:4]] or [placeholder_plate(SW, MEDIA_H)]
        self._build_backdrop(photos[0] if photos else None)
        self._build_graphics(story)
        self._build_sting()

    # ---- static assets

    def _build_backdrop(self, photo):
        bw, bh = SW + 140, SH + 140
        if photo is not None:
            base = ImageOps.fit(photo, (bw // 10, bh // 10)).filter(ImageFilter.GaussianBlur(2))
            base = ImageEnhance.Brightness(base.resize((bw, bh), Image.BICUBIC)).enhance(0.32)
        else:
            base = Image.new("RGB", (bw, bh), (12, 16, 30))
        self.backdrop = base
        self.media_fade = gradient(SW, 160, BLACK, BLACK, 0, 190)

    def _build_graphics(self, story):
        # Brand mark: red AIT block + white NEWS block
        logo = Image.new("RGBA", (330, 84), (0, 0, 0, 0))
        logo.alpha_composite(gloss(150, 84, (236, 30, 40), (150, 0, 12)), (0, 0))
        logo.alpha_composite(gloss(180, 84, WHITE, (225, 225, 230)), (150, 0))
        d = ImageDraw.Draw(logo)
        d.text((75, 44), "AIT", font=heavy(54), fill=WHITE, anchor="mm")
        d.text((240, 44), "NEWS", font=cond(52), fill=RED, anchor="mm")
        self.logo = logo

        f_tab = cond(38)
        label = " ".join(self.tag_words)
        tw = int(f_tab.getlength(label)) + 48
        self.tabs = []
        for bg in (((255, 224, 40), AMBER, DARK_RED), ((236, 30, 40), (150, 0, 12), WHITE)):
            spr = gloss(tw, TAB_H, bg[0], bg[1])
            ImageDraw.Draw(spr).text((tw // 2, TAB_H // 2 + 2), label, font=f_tab, fill=bg[2], anchor="mm")
            self.tabs.append(spr)

        band = gloss(SW, SUPER_H, (226, 24, 36), DARK_RED)
        ImageDraw.Draw(band).rectangle([0, 0, 14, SUPER_H], fill=YELLOW + (255,))
        self.super_band = band
        self.super_texts = [self._super_sprite(t) for t in [self.title] + self.points]
        self.shine = shine_sprite(SUPER_H)

        strap = gloss(SW, STRAP_H, (255, 226, 50), AMBER)
        stamp = self.published.strftime("%d %b, %H:%M UTC").upper() if self.published else ""
        info = "  •  ".join(x for x in (self.outlet, stamp) if x)
        f_strap = cond(36)
        ImageDraw.Draw(strap).text((TEXT_X, STRAP_H // 2 + 1), fit_line(info, f_strap, TEXT_W), font=f_strap,
                                   fill=BLACK, anchor="lm")
        self.strap = strap

        self.hashtag = text_layer([make_hashtag(self.title)], cond(48), WHITE, 48, (TEXT_W, 70))
        f_follow = font("Montserrat.ttf", 40, "ExtraBold")
        msg = "FOLLOW AIT FOR DAILY TECH NEWS"
        fw = int(f_follow.getlength(msg)) + 80
        follow = rrect((fw, 92), 46, fill=(236, 30, 40, 245))
        ImageDraw.Draw(follow).text((fw // 2, 47), msg, font=f_follow, fill=WHITE, anchor="mm")
        self.follow = follow

    def _super_sprite(self, text: str) -> Image.Image:
        text = clean(text).upper()
        size = (TEXT_W, SUPER_H - 30)
        for s in (78, 70, 62, 56, 50, 45):
            f = cond(s)
            lines = wrap(text, f, TEXT_W)
            if len(lines) * s * 1.16 <= SUPER_H - 40:
                return text_layer(lines, f, WHITE, int(s * 1.16), size)
        f = cond(45)
        lines = wrap(clause_cut(text, 170), f, TEXT_W)[:5]
        lines[-1] = fit_line(lines[-1], f, TEXT_W)
        return text_layer(lines, f, WHITE, 52, size)

    def _build_sting(self):
        yy, xx = np.mgrid[0:SH, 0:SW]
        r = np.clip(np.hypot((xx - SW / 2) / SW, (yy - SH / 2) / SH) * 1.7, 0, 1)[..., None]
        arr = np.array((236, 34, 30), float) * (1 - r) + np.array((58, 0, 6), float) * r
        self.sting_bg = Image.fromarray(arr.astype(np.uint8), "RGB")
        s = 2300
        rays = Image.new("L", (s, s), 0)
        d = ImageDraw.Draw(rays)
        for k in range(24):
            d.pieslice([0, 0, s, s], k * 15, k * 15 + 6, fill=34)
        self.sting_rays = rays.filter(ImageFilter.GaussianBlur(5))
        word, box_word = self.tag_words
        f = heavy(150 if len(word) > 4 else 210)
        ww = int(f.getlength(word)) + 60
        wsp = Image.new("RGBA", (ww, 260), (0, 0, 0, 0))
        ImageDraw.Draw(wsp).text((30, 20), word, font=f, fill=WHITE, stroke_width=5, stroke_fill=(110, 0, 8))
        self.sting_word = wsp
        nf = heavy(140)
        nw = int(nf.getlength(box_word)) + 90
        box = gloss(nw, 180, (255, 228, 50), AMBER)
        ImageDraw.Draw(box).text((nw // 2, 88), box_word, font=nf, fill=(150, 0, 12), anchor="mm")
        self.sting_box = box

    # ---- per-frame

    def phase_at(self, t: float) -> int:
        return max(i for i, s in enumerate(self.starts) if t >= s)

    def _shot(self, phase: int, t: float) -> Image.Image:
        p = clamp((t - self.starts[phase]) / max(0.1, self.durs[phase]), 0, 1.15)
        return ken_burns(self.plates[phase % len(self.plates)], SW, MEDIA_H, p, phase)

    def _sting(self, t: float) -> Image.Image:
        img = self.sting_bg.copy()
        s = self.sting_rays.size[0]
        rays = self.sting_rays.rotate(t * 28, resample=Image.BILINEAR)
        ox, oy = (s - SW) // 2, (s - SH) // 2
        img.paste((255, 190, 170), (0, 0, SW, SH), rays.crop((ox, oy, ox + SW, oy + SH)))
        scale = lerp(2.4, 1.0, ease_out(prog(t, 0.0, 0.33))) * (1 + 0.035 * t)
        w = self.sting_word
        sw_, sh_ = int(w.width * scale), int(w.height * scale)
        put(img, w.resize((sw_, sh_), Image.BILINEAR), SW / 2 - sw_ / 2, SH / 2 - 230 - sh_ / 2 + 40,
            alpha=prog(t, 0, 0.1), clip=(0, 0, SW, SH))
        b = self.sting_box
        put(img, b, lerp(SW + 40, SW / 2 - b.width / 2, ease_back(prog(t, 0.28, 0.32))), SH / 2 + 30, clip=(0, 0, SW, SH))
        flash = 1 - prog(t, 0.33, 0.25)
        if t >= 0.33 and flash > 0:
            img = Image.blend(img, Image.new("RGB", (SW, SH), WHITE), 0.65 * flash)
        return img

    def render(self, t: float) -> Image.Image:
        if t < 1.0:
            return self._sting(t)
        ox = int(70 + 60 * math.sin(t * 0.12))
        oy = int(70 + 50 * math.cos(t * 0.09))
        frame = self.backdrop.crop((ox, oy, ox + SW, oy + SH))
        d = ImageDraw.Draw(frame)
        clip = (0, 0, SW, SH)
        phase = self.phase_at(t)

        shot = self._shot(phase, t)
        if phase > 0 and t - self.starts[phase] < XFADE:
            shot = Image.blend(self._shot(phase - 1, t), shot, ease_in_out((t - self.starts[phase]) / XFADE))
        frame.paste(shot, (0, MEDIA_Y))
        put(frame, self.media_fade, 0, MEDIA_Y + MEDIA_H - 160, clip=clip)

        # Progress bar across the very top: viewers see how short the story is
        d.rectangle([0, 0, SW, 10], fill=(60, 10, 14))
        d.rectangle([0, 0, SW * clamp(t / self.total), 10], fill=RED)
        e_logo = ease_out(prog(t, 1.1, 0.4))
        put(frame, self.logo, TEXT_X - 380 * (1 - e_logo), 96, clip=clip)

        e_tab = ease_back(prog(t, 1.35, 0.4))
        flashing = self.breaking and (t < self.starts[1] if len(self.starts) > 1 else True)
        tab = self.tabs[int(t / 0.42) % 2] if flashing and t > 1.8 else self.tabs[1]
        put(frame, tab, TEXT_X - (tab.width + 60) * (1 - e_tab), TAB_Y, clip=clip)

        reveal = ease_out(prog(t, 1.2, 0.5))
        put(frame, self.super_band, 0, SUPER_Y, clip=(0, SUPER_Y, int(SW * reveal), SUPER_Y + SUPER_H))
        idx = min(phase, len(self.super_texts) - 1)
        prev = min(phase - 1, len(self.super_texts) - 1)
        flip = prog(t, self.starts[phase], FLIP) if phase > 0 and prev != idx else 1.0
        if flip < 1.0:
            spr, s = (self.super_texts[prev], 1 - ease_in(flip * 2)) if flip < 0.5 else \
                     (self.super_texts[idx], ease_out((flip - 0.5) * 2))
        else:
            spr, s = self.super_texts[idx], ease_out(prog(t, 1.5, 0.3))
        if s > 0.02:
            h = max(1, int(spr.height * s))
            put(frame, spr.resize((spr.width, h), Image.BILINEAR), TEXT_X, SUPER_Y + 15 + (spr.height - h) / 2, clip=clip)
        shine_t = (t - 2.6) % 5.5
        if t > 2.6 and shine_t < 0.9:
            put(frame, self.shine, lerp(-120, SW + 40, shine_t / 0.9), SUPER_Y, clip=(0, SUPER_Y, SW, SUPER_Y + SUPER_H))

        e_strap = ease_out(prog(t, 1.3, 0.4))
        put(frame, self.strap, -SW * (1 - e_strap), STRAP_Y, clip=clip)
        put(frame, self.hashtag, TEXT_X, STRAP_Y + STRAP_H + 18, alpha=ease_out(prog(t, 1.7, 0.4)), clip=clip)

        # Closing call to action over the picture
        e_f = ease_back(prog(t, self.total - 2.4, 0.45))
        if e_f > 0:
            fw, fh = int(self.follow.width * e_f), int(self.follow.height * e_f)
            if fw > 4 and fh > 4:
                put(frame, self.follow.resize((fw, fh), Image.BILINEAR), SW / 2 - fw / 2,
                    MEDIA_Y + MEDIA_H - 150 - fh / 2, clip=clip)

        if t < 1.45:                                   # stinger wipes away
            sting = self._sting(t)
            edge = lerp(SH + 300, -300, ease_in(prog(t, 1.0, 0.45)))
            mask = Image.new("L", (SW, SH), 0)
            ImageDraw.Draw(mask).polygon([(0, 0), (SW, 0), (SW, edge - 180), (0, edge + 180)], fill=255)
            frame.paste(sting, (0, 0), mask)
            d = ImageDraw.Draw(frame)
            d.polygon([(0, edge + 180), (SW, edge - 180), (SW, edge - 130), (0, edge + 230)], fill=YELLOW)
        return frame


def render_short(story: dict, audio_path: str, phase_durations: list[float], output_path: str) -> str:
    durs = on_air_durations(phase_durations)
    scene = ShortScene(story, durs)
    return encode_scene(scene, (SW, SH), audio_path, sum(durs), output_path, story.get("id", "short"))


def main():
    ap = argparse.ArgumentParser(description="Render the vertical Shorts version of a rendered clip")
    ap.add_argument("--meta", required=True, help="clip .json written by the autopilot")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    with open(args.meta, "r", encoding="utf-8") as f:
        meta = json.load(f)
    render_short(meta["story"], meta["audio"], meta["phase_durations"], args.out)
    print(args.out)


if __name__ == "__main__":
    main()
