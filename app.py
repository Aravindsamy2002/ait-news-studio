import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

from config import OUTPUT_DIR, STATIC_DIR, BASE_DIR, ASSETS_DIR
from fetcher import get_cached_news, fetch_all_news
from voice_engine import generate_speech
from studio_manager import create_single_story_broadcast, create_multi_story_bulletin
from streamer import streamer_instance

app = FastAPI(title="AIT NEWS Studio")

# Mount output directory for video/audio streaming
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")
app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

class AuditionRequest(BaseModel):
    text: str
    id: str

class GenerateSingleRequest(BaseModel):
    story_id: str

class StreamRequest(BaseModel):
    stream_key: str

@app.get("/", response_class=HTMLResponse)
async def get_index():
    template_path = os.path.join(BASE_DIR, "templates", "index.html")
    with open(template_path, "r", encoding="utf-8") as f:
        return f.read()

@app.get("/api/news")
async def api_get_news():
    return get_cached_news()

@app.post("/api/refresh")
async def api_refresh_news():
    news = fetch_all_news()
    return news

@app.post("/api/audition-voice")
async def api_audition_voice(req: AuditionRequest):
    from voice_engine import generate_speech_async
    audio_filename = f"audition_{req.id}.mp3"
    path, duration, timings = await generate_speech_async(req.text, audio_filename)
    return {
        "audio_url": f"/output/{audio_filename}",
        "duration": duration
    }

@app.post("/api/generate-single")
async def api_generate_single(req: GenerateSingleRequest):
    import asyncio
    news = get_cached_news()
    selected = next((s for s in news if s["id"] == req.story_id), None)
    if not selected:
        raise HTTPException(status_code=404, detail="Story not found")

    meta = await asyncio.to_thread(create_single_story_broadcast, selected)
    return meta

@app.post("/api/generate-bulletin")
async def api_generate_bulletin():
    import asyncio
    news = get_cached_news()
    if not news:
        raise HTTPException(status_code=400, detail="No stories available")

    top_stories = news[:3]
    meta = await asyncio.to_thread(create_multi_story_bulletin, top_stories)
    return meta

@app.post("/api/stream/start")
async def api_stream_start(req: StreamRequest):
    # Find latest generated video in output
    videos = [f for f in os.listdir(OUTPUT_DIR) if f.endswith(".mp4")]
    if not videos:
        return {"success": False, "error": "No rendered video available to stream. Please render a clip first!"}

    # Pick the most recent video
    latest_video = max(videos, key=lambda f: os.path.getmtime(os.path.join(OUTPUT_DIR, f)))
    try:
        success = streamer_instance.start_youtube_stream(latest_video, req.stream_key)
        return {"success": success, "video": latest_video}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/stream/stop")
async def api_stream_stop():
    stopped = streamer_instance.stop_stream()
    return {"success": stopped}

@app.get("/api/stream/status")
async def api_stream_status():
    return streamer_instance.get_status()

if __name__ == "__main__":
    print("Starting AIT NEWS Studio on http://127.0.0.1:8765...")
    uvicorn.run("app:app", host="127.0.0.1", port=8765, reload=False)
