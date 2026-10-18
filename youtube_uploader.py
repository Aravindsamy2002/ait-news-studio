"""
YouTube publishing for AIT News (YouTube Data API v3, free quota).

  * one video per new story: title, description with source attribution, story-wise tags,
    News category and the BBC-style thumbnail;
  * the 24/7 live stream's title follows the top story ("AIT News LIVE: ...").

One-time setup on your PC (opens a browser to sign in to the AIT News channel):
    python youtube_uploader.py auth --client-secret client_secret.json
Copy secrets/youtube_token.json to the same path on the VM, then check it:
    python youtube_uploader.py whoami
"""
import argparse
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

from config import (
    BULLETIN_ENABLED, BULLETIN_HOUR_UTC, BULLETINS_DIR, LIVE_TITLE_MINUTES, OUTPUT_DIR,
    YOUTUBE_LIVE_TITLE, YOUTUBE_MAX_UPLOADS_PER_DAY,
    YOUTUBE_MIN_UPLOAD_GAP_MINUTES, YOUTUBE_UPLOAD_MAX_AGE_HOURS,
    YOUTUBE_PRIVACY, YOUTUBE_SHORTS, YOUTUBE_TOKEN_FILE, YOUTUBE_UPLOADS,
)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube"]
NEWS_CATEGORY_ID = "25"                       # YouTube category "News & Politics"
STATE_FILE = os.path.join(OUTPUT_DIR, "youtube_uploads.json")
THUMBS_DIR = os.path.join(OUTPUT_DIR, "thumbs")
BRAND_TAGS = ["AIT News", "Tech News", "Technology News", "Latest News"]

# Capitalised words that are ordinary English, not names
_COMMON = {
    "a", "an", "the", "this", "that", "these", "those", "it", "its", "in", "on", "at", "of", "for", "to", "and",
    "or", "but", "as", "by", "with", "from", "after", "before", "over", "how", "why", "what", "who", "when",
    "where", "here", "there", "now", "new", "says", "said", "report", "reports", "ceo", "cto", "according",
    "today", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "while", "also",
    "just", "more", "most", "his", "her", "their", "our", "we", "they", "he", "she", "you", "i", "my",
    "january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
    "november", "december", "move", "comes", "update", "breaking", "exclusive", "live",
}


def log(msg: str):
    print(time.strftime("[%H:%M:%S] ") + f"[youtube] {msg}", flush=True)


# ------------------------------------------------------------------ auth

def is_configured() -> bool:
    return os.path.exists(YOUTUBE_TOKEN_FILE)


def _save_token(creds):
    """The token controls the channel: write it readable by this user only (dir 700, file 600)."""
    os.makedirs(os.path.dirname(YOUTUBE_TOKEN_FILE), mode=0o700, exist_ok=True)
    fd = os.open(YOUTUBE_TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    os.chmod(YOUTUBE_TOKEN_FILE, 0o600)          # in case it already existed with looser permissions


def _credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file(YOUTUBE_TOKEN_FILE, SCOPES)
    if not creds.valid:
        if not creds.refresh_token:
            raise RuntimeError("YouTube token has no refresh token; run `python youtube_uploader.py auth` again")
        creds.refresh(Request())
        _save_token(creds)
    return creds


def youtube_client():
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=_credentials(), cache_discovery=False)


def run_auth(client_secret: str):
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(client_secret, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    _save_token(creds)
    print(f"Saved token to {YOUTUBE_TOKEN_FILE}. Copy this file to the same path on the VM.")


# ------------------------------------------------------------------ metadata

def _no_angle_brackets(text: str) -> str:
    return text.replace("<", "").replace(">", "")       # YouTube rejects < and > in titles/descriptions


def story_entities(story: dict, limit: int = 8) -> list[str]:
    """Company, product and people names mentioned in the story (no dictionary needed).

    Names are words capitalised in the middle of a normal sentence ("... with Bleecker Street"),
    or words with inner capitals/digits ("OpenAI", "iPhone", "GPT-5") anywhere.
    """
    title = story.get("title", "")
    title_words = [w for w in re.findall(r"[A-Za-z][\w'’\-]*", title) if len(w) > 3]
    title_case = bool(title_words) and sum(w[0].isupper() for w in title_words) / len(title_words) > 0.7
    texts = ([] if title_case else [title]) + list(story.get("bullets") or [])

    names, acronyms = [], []

    def add(name: str, bucket: list):
        name = re.sub(r"['’]s$", "", name.strip(" .,:;!?\"“”()[]"))
        if "'" in name or "’" in name or len(name) < 2 or name.lower() in _COMMON:
            return                                                 # contractions like "We've"
        if len(name) == 2 and name != "AI":
            return                                                 # "OS", "TV": too vague as tags
        if name.lower() not in [f.lower() for f in names + acronyms]:
            bucket.append(name)

    for text in texts:
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            run = []
            for raw in sentence.split() + [""]:
                w = re.sub(r"['’]s$", "", raw.strip(".,:;!?\"“”()[]"))
                if w and re.search(r"-[a-z]", w):                  # "Spark-powered" ends a name
                    w = ""
                if w and (w[0].isupper() or re.search(r"[a-z][A-Z]", w)) and w.lower() not in _COMMON and len(run) < 3:
                    run.append(w)                                  # consecutive capitals form one name
                    possessive = bool(re.search(r"['’]s[.,:;!?\"”)]*$", raw))
                    if raw.endswith((",", ":", ";", ")")) or possessive:   # "Google, Microsoft" / "Gibney's Musk"
                        add(" ".join(run), names)
                        run = []
                elif run:
                    add(" ".join(run), names)
                    run = [w] if w and w[0].isupper() and w.lower() not in _COMMON else []
    for word in re.findall(r"[A-Za-z0-9][\w\-]*", title):              # inner caps / digits anywhere: OpenAI, GPT-5
        if re.search(r"[a-z][A-Z]|[A-Za-z]\d", word):
            add(word, names)
        elif re.fullmatch(r"[A-Z]{2,5}", word):
            add(word, acronyms)
    return (names + acronyms)[:limit]


CATEGORY_TAGS = {
    "ARTIFICIAL INTELLIGENCE": ["Artificial Intelligence", "AI News"],
    "CYBERSECURITY & DEFENSE": ["Cybersecurity", "Data Breach"],
    "SILICON & HARDWARE": ["Semiconductors", "Hardware"],
    "FINTECH & CRYPTO": ["Crypto", "Fintech"],
    "AEROSPACE & SCIENCE": ["Space", "Science"],
    "BIG TECH RADAR": ["Big Tech"],
    "GADGETS & TECH": ["Gadgets", "Consumer Tech"],
    "TECH & SCIENCE": ["Science", "Technology"],
    "ENTERPRISE TECH": ["Enterprise Tech"],
    "TECH INDUSTRY": ["Tech Industry"],
}


def build_tags(story: dict) -> list[str]:
    tags = story_entities(story)
    tags += CATEGORY_TAGS.get(story.get("category", "").upper(), ["Technology"])
    if story.get("outlet") and "." not in story["outlet"]:     # outlet names, not bare domains
        tags.append(story["outlet"])
    if story.get("is_breaking"):
        tags.append("Breaking News")
    tags += BRAND_TAGS
    unique, seen, total = [], set(), 0
    for t in tags:
        t = _no_angle_brackets(t).strip()
        cost = len(t) + (2 if " " in t else 0) + 1          # YouTube counts quotes around multi-word tags
        if t and t.lower() not in seen and total + cost <= 480:
            unique.append(t)
            seen.add(t.lower())
            total += cost
    return unique


def build_title(story: dict) -> str:
    from motion_renderer import clause_cut

    title = _no_angle_brackets(story.get("title", "")).strip()
    suffix = " | AIT News"
    if len(title) + len(suffix) <= 100:
        return title + suffix
    room = 100 - len(suffix)
    cut = clause_cut(title, room).rstrip("…").rstrip(" ,;:-")
    if len(cut) < room * 0.8:                                   # a clause break that drops the news itself
        cut = title[:room - 1].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"
    return cut + suffix


def build_description(story: dict, short: bool = False) -> str:
    lines = [story.get("title", ""), ""]
    for b in story.get("bullets") or []:
        lines.append(f"• {b}")
    if story.get("bullets"):
        lines.append("")
    outlet = story.get("outlet") or story.get("source", "")
    if outlet or story.get("link"):
        lines.append(f"Source: {outlet}" + (f" — {story['link']}" if story.get("link") else ""))
    if story.get("published"):
        lines.append(f"Published: {story['published']}")
    lines += [
        "",
        "AIT NEWS brings you the biggest stories in technology, AI, cybersecurity and business, as they happen.",
        "Subscribe and turn on notifications for breaking tech news.",
        "",
    ]
    hashtags = ["#" + re.sub(r"[^A-Za-z0-9]", "", e) for e in story_entities(story, 3)]
    lines.append(" ".join([h for h in hashtags if len(h) > 2] + ["#AITNews", "#TechNews"] + (["#Shorts"] if short else [])))
    return _no_angle_brackets("\n".join(lines))[:4900]


def build_metadata(story: dict, short: bool = False) -> dict:
    return {"title": build_title(story), "description": build_description(story, short), "tags": build_tags(story)}


# ------------------------------------------------------------------ API calls

def upload_story(clip_path: str, story: dict, thumb_path: str = None, short: bool = False) -> str:
    return upload_video(clip_path, build_metadata(story, short), thumb_path)


def upload_video(clip_path: str, meta: dict, thumb_path: str = None) -> str:
    """Upload one video with title/description/tags (News category) and an optional custom thumbnail."""
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    yt = youtube_client()
    body = {
        "snippet": {
            "title": meta["title"], "description": meta["description"], "tags": meta["tags"],
            "categoryId": NEWS_CATEGORY_ID, "defaultLanguage": "en", "defaultAudioLanguage": "en",
        },
        "status": {"privacyStatus": YOUTUBE_PRIVACY, "selfDeclaredMadeForKids": False, "embeddable": True},
    }
    media = MediaFileUpload(clip_path, mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response, retries = None, 0
    while response is None:
        try:
            _, response = request.next_chunk()
        except HttpError as e:
            if e.resp.status in (500, 502, 503, 504) and retries < 5:
                time.sleep(2 ** retries)
                retries += 1
                continue
            raise
    video_id = response["id"]
    if thumb_path and os.path.exists(thumb_path):
        try:
            yt.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(thumb_path, mimetype="image/jpeg")).execute()
        except HttpError as e:
            log(f"Thumbnail not set for {video_id} (is the channel phone-verified?): {e}")
    return video_id


def update_live_title(headline: str) -> bool:
    """Retitle the active live broadcast after the top story. Returns False if nothing is live."""
    yt = youtube_client()
    items = yt.liveBroadcasts().list(part="id,snippet", broadcastStatus="active", broadcastType="all").execute().get("items", [])
    if not items:
        return False
    broadcast = items[0]
    prefix = "AIT News LIVE: "
    head = _no_angle_brackets(headline).strip()
    title = prefix + head if len(prefix + head) <= 100 else (prefix + head)[:99].rsplit(" ", 1)[0] + "…"
    snippet = broadcast["snippet"]
    if snippet.get("title") == title:
        return True
    yt.liveBroadcasts().update(part="snippet", body={"id": broadcast["id"], "snippet": {
        "title": title,
        "description": snippet.get("description", ""),
        "scheduledStartTime": snippet["scheduledStartTime"],
    }}).execute()
    log(f"Live title -> {title}")
    return True


# ------------------------------------------------------------------ background publisher

def _load_state() -> dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def uploads_today(state: dict) -> int:
    today = datetime.now(timezone.utc).date().isoformat()
    return sum(1 for v in state.values() if v.get("uploaded_at", "").startswith(today))


def render_short_for(clip_path: str) -> str:
    """Render the vertical Short for a clip in a separate lowest-priority process (never stalls the stream)."""
    out = clip_path.replace(".mp4", "_short.mp4")
    if os.path.exists(out):
        return out
    tmp = out.replace(".mp4", ".part.mp4")
    lower = (lambda: os.nice(19)) if hasattr(os, "nice") else None
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shorts_renderer.py")
    result = subprocess.run([sys.executable, script, "--meta", clip_path.replace(".mp4", ".json"), "--out", tmp],
                            preexec_fn=lower, capture_output=True, text=True, timeout=1800)
    if result.returncode != 0 or not os.path.exists(tmp):
        raise RuntimeError(f"Short render failed: {result.stderr.strip()[-400:]}")
    os.replace(tmp, out)
    return out


def build_bulletin_for_today() -> dict:
    """Build today's long-form bulletin in a lowest-priority process; returns its metadata."""
    os.makedirs(BULLETINS_DIR, exist_ok=True)
    for name in os.listdir(BULLETINS_DIR):                   # keep only the last few days on disk
        path = os.path.join(BULLETINS_DIR, name)
        if time.time() - os.path.getmtime(path) > 3 * 86400:
            os.remove(path)
    out = os.path.join(BULLETINS_DIR, datetime.now(timezone.utc).strftime("%Y-%m-%d") + ".mp4")
    lower = (lambda: os.nice(19)) if hasattr(os, "nice") else None
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bulletin.py")
    result = subprocess.run([sys.executable, script, "--out", out], preexec_fn=lower,
                            capture_output=True, text=True, timeout=3600)
    if result.returncode != 0:
        raise RuntimeError(f"Bulletin build failed: {result.stderr.strip()[-400:]}")
    with open(out[:-4] + ".json", "r", encoding="utf-8") as f:
        return json.load(f)


class Publisher(threading.Thread):
    """Uploads new story clips and keeps the live title current, without ever blocking the stream."""

    def __init__(self):
        super().__init__(daemon=True)
        self.jobs = queue.Queue()
        self.state = _load_state()
        self.backlog = {}            # story id -> (clip path, story), waiting for an upload slot
        self.paused_until = 0.0
        self.bulletin_retry_at = 0.0
        self.last_live_title = 0.0
        self.last_headline = None
        self.enabled = is_configured()
        if not self.enabled:
            log(f"No token at {YOUTUBE_TOKEN_FILE}; uploads and live-title updates are off")

    def submit_story(self, clip_path: str, story: dict):
        if self.enabled and YOUTUBE_UPLOADS and story["id"] not in self.state:
            self.jobs.put(("upload", clip_path, story))

    def _last_upload_time(self) -> float:
        times = [datetime.fromisoformat(v["uploaded_at"]).timestamp() for v in self.state.values() if v.get("uploaded_at")]
        return max(times, default=0.0)

    @staticmethod
    def _bulletin_key() -> str:
        return "bulletin-" + datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _slot_open(self) -> bool:
        """Pace uploads like a human newsroom: one at a time, a long gap between them, a low daily cap."""
        now = time.time()
        return (now >= self.paused_until and uploads_today(self.state) < YOUTUBE_MAX_UPLOADS_PER_DAY
                and now - self._last_upload_time() >= YOUTUBE_MIN_UPLOAD_GAP_MINUTES * 60)

    def _bulletin_due(self) -> bool:
        return (BULLETIN_ENABLED and self._bulletin_key() not in self.state
                and datetime.now(timezone.utc).hour >= BULLETIN_HOUR_UTC and time.time() >= self.bulletin_retry_at)

    def _next_upload(self):
        """Next Short to upload: only fresh stories, newest first. One daily slot stays reserved for the
        bulletin until it has gone out. Everything else simply stays on the live stream."""
        reserved = 1 if BULLETIN_ENABLED and self._bulletin_key() not in self.state else 0
        if not self._slot_open() or uploads_today(self.state) >= YOUTUBE_MAX_UPLOADS_PER_DAY - reserved:
            return None
        cutoff = datetime.now(timezone.utc).timestamp() - YOUTUBE_UPLOAD_MAX_AGE_HOURS * 3600
        for sid, (clip, story) in list(self.backlog.items()):
            published = story.get("published_ts")
            stale = not published or datetime.fromisoformat(published).timestamp() < cutoff
            if sid in self.state or stale or not os.path.exists(clip):
                del self.backlog[sid]
        if not self.backlog:
            return None
        sid = max(self.backlog, key=lambda k: self.backlog[k][1].get("published_ts", ""))   # newest first
        return self.backlog.pop(sid)

    def submit_headline(self, headline: str):
        due = time.time() - self.last_live_title > LIVE_TITLE_MINUTES * 60
        if self.enabled and YOUTUBE_LIVE_TITLE and headline and headline != self.last_headline and due:
            self.last_headline = headline
            self.last_live_title = time.time()
            self.jobs.put(("live_title", headline))

    def _publish_bulletin(self):
        try:
            meta = build_bulletin_for_today()
        except Exception as e:
            self.bulletin_retry_at = time.time() + 3600          # e.g. too few stories yet; try again in an hour
            log(f"{e}; retrying in 1 hour")
            return
        video_id = upload_video(meta["video"], meta, meta.get("thumbnail"))
        self.state[self._bulletin_key()] = {
            "video_id": video_id, "title": meta["title"], "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }
        _save_state(self.state)
        log(f"Uploaded bulletin https://youtu.be/{video_id}  ({meta['duration'] / 60:.1f} min, "
            f"{len(meta['stories'])} stories)")

    def run(self):
        from googleapiclient.errors import HttpError
        from motion_renderer import render_thumbnail

        os.makedirs(THUMBS_DIR, exist_ok=True)
        while True:
            try:
                job = self.jobs.get(timeout=60)
            except queue.Empty:
                job = None
            try:
                if job and job[0] == "live_title":
                    if time.time() >= self.paused_until and not update_live_title(job[1]):
                        log("No active live broadcast to retitle")
                    continue
                if job:
                    _, clip_path, story = job
                    self.backlog[story["id"]] = (clip_path, story)
                if self.enabled and YOUTUBE_UPLOADS and self._slot_open() and self._bulletin_due():
                    self._publish_bulletin()
                    continue
                nxt = self._next_upload()
                if not nxt:
                    continue
                clip_path, story = nxt
                if YOUTUBE_SHORTS:
                    video_path, thumb = render_short_for(clip_path), None     # Shorts use a frame, not a thumbnail
                else:
                    video_path, thumb = clip_path, os.path.join(THUMBS_DIR, f"{story['id']}.jpg")
                    render_thumbnail(story, thumb)
                video_id = upload_story(video_path, story, thumb, short=YOUTUBE_SHORTS)
                self.state[story["id"]] = {
                    "video_id": video_id, "title": story["title"],
                    "uploaded_at": datetime.now(timezone.utc).isoformat(),
                }
                _save_state(self.state)
                log(f"Uploaded https://youtu.be/{video_id}  {story['title'][:60]}")
            except HttpError as e:
                if "quotaExceeded" in str(e) or "uploadLimitExceeded" in str(e):
                    self.paused_until = time.time() + 6 * 3600
                    log("YouTube quota reached; pausing uploads for 6 hours")
                else:
                    log(f"API error: {e}")
            except Exception as e:
                if any(k in str(e) for k in ("disabled_client", "invalid_client", "invalid_grant")):
                    self.paused_until = time.time() + 24 * 3600     # stop calling Google until a human fixes auth
                    log(f"YouTube auth is not working ({e}); uploads paused for 24 hours")
                else:
                    log(f"Publish failed: {e}")


# ------------------------------------------------------------------ CLI

def main():
    ap = argparse.ArgumentParser(description="AIT News YouTube publishing")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("auth", help="sign in once (on a PC with a browser) and save the token")
    a.add_argument("--client-secret", required=True, help="OAuth client JSON from Google Cloud Console")
    sub.add_parser("whoami", help="show which channel the saved token publishes to")
    p = sub.add_parser("preview", help="print the title/description/tags the uploader would use")
    p.add_argument("--count", type=int, default=3)
    args = ap.parse_args()

    if args.cmd == "auth":
        run_auth(args.client_secret)
    elif args.cmd == "whoami":
        items = youtube_client().channels().list(part="snippet,statistics", mine=True).execute().get("items", [])
        for ch in items:
            print(f"Channel: {ch['snippet']['title']}  (id {ch['id']}, {ch['statistics'].get('subscriberCount', '?')} subscribers)")
        if not items:
            print("Token works, but no channel found for this account.")
    elif args.cmd == "preview":
        from fetcher import get_cached_news, prepare_story
        for s in [prepare_story(x) for x in get_cached_news() if x.get("article_images")][: args.count]:
            meta = build_metadata(s)
            print("=" * 80)
            print("TITLE:", meta["title"])
            print("TAGS: ", ", ".join(meta["tags"]))
            print(meta["description"])


if __name__ == "__main__":
    main()
