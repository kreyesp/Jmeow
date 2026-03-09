from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from openai import OpenAI
import asyncio
import subprocess
import shutil
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
import clean

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    asyncio.create_task(input_watcher())
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

AUDIO_DIR = "received_audio"
os.makedirs(AUDIO_DIR, exist_ok=True)

BASE_DIR = os.path.dirname(__file__)
input_path = os.path.join(BASE_DIR, "input_data.json")
output_path = os.path.join(BASE_DIR, "output.json")

# Track connected Arduinos by name
connected_arduinos: dict[str, WebSocket] = {}

_last_pipeline_time: float = 0.0
PIPELINE_COOLDOWN = 2.0  # seconds between pipeline runs


async def run_pipeline(priority: bool = False):
    """Run output.py then send output.json to the receiver Arduino.

    priority=True bypasses the cooldown (used for touch and voice triggers).
    """
    global _last_pipeline_time
    now = time.time()
    if not priority and now - _last_pipeline_time < PIPELINE_COOLDOWN:
        print(f"[pipeline] cooldown active, skipping ({PIPELINE_COOLDOWN}s between runs)")
        return
    _last_pipeline_time = now
    print("[pipeline] running output.py...")
    result = subprocess.run(
        ["python", os.path.join(BASE_DIR, "output.py")],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"[pipeline] output.py error:\n{result.stderr}")
        return
    print(f"[pipeline] output.py done: {result.stdout.strip()}")

    if not os.path.exists(output_path):
        print("[pipeline] output.json not found, skipping send")
        return

    with open(output_path) as f:
        payload = json.load(f)

    receiver = connected_arduinos.get("receiver")
    if receiver:
        await receiver.send_text(json.dumps(payload))
        print(f"[pipeline] sent to receiver: {payload}")
    else:
        print(f"[pipeline] receiver not connected, output.json ready but not sent")


async def input_watcher():
    """Watch input_data.json for changes and auto-trigger the pipeline."""
    async def watcher():
        last_mtime = None
        while True:
            try:
                mtime = os.path.getmtime(input_path)
                if last_mtime is not None and mtime != last_mtime:
                    print("[watcher] input_data.json changed — triggering pipeline")
                    await run_pipeline()
                last_mtime = mtime
            except FileNotFoundError:
                pass
            await asyncio.sleep(1)

    asyncio.create_task(watcher())


@app.get("/")
def index():
    return FileResponse("index.html")




# --- WebSocket: Arduinos connect with ?name=receiver ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, name: str = Query("unknown")):
    await websocket.accept()
    connected_arduinos[name] = websocket
    print(f"Arduino '{name}' connected. Total: {len(connected_arduinos)}")
    try:
        while True:
            data = await websocket.receive_text()
            print(f"[{name}] received: {data}")
            try:
                raw = json.loads(data)
                if "speed" in raw and (name == "giver" or raw.get("device") == "giver"):
                    clean.process_packet(raw)
                    if raw.get("touch"):
                        asyncio.create_task(run_pipeline(priority=True))
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        connected_arduinos.pop(name, None)
        print(f"Arduino '{name}' disconnected. Total: {len(connected_arduinos)}")


# --- Send output.json to the receiver Arduino ---
@app.post("/send_output")
async def send_output():
    if not os.path.exists(output_path):
        return {"status": "error", "message": "output.json not found"}

    with open(output_path) as f:
        result = json.load(f)

    receiver = connected_arduinos.get("receiver")
    if receiver:
        await receiver.send_text(json.dumps(result))
        return {"status": "sent", "result": result}
    else:
        return {"status": "receiver_not_connected", "result": result}


# --- Audio upload from index.html ---
@app.post("/upload_audio")
async def upload_audio(file: UploadFile = File(...)):
    filename = f"{AUDIO_DIR}/{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.webm"
    with open(filename, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    print(f"Saved: {filename}")

    with open(filename, "rb") as audio_file:
        transcription = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
        )
    transcript = transcription.text
    print(f"Transcript: {transcript}")

    sentiment_response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": f"Classify the sentiment of this text into exactly one word from this list: happy, sad, mad, love, anxious, neutral. Reply with only the one word.\n\nText: \"{transcript}\""}],
        temperature=0,
    )
    sentiment = sentiment_response.choices[0].message.content.strip().lower()
    print(f"Sentiment: {sentiment}")

    with open("voice_data.json", "w") as f:
        json.dump({"transcript": transcript, "sentiment": sentiment}, f, indent=2)

    try:
        with open(input_path) as f:
            existing = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        existing = {"speed": 0.0, "temperature": None, "touch": False}

    output = {
        "voice": {"transcript": transcript, "sentiment": sentiment},
        "speed": existing.get("speed", 0.0),
        "temperature": existing.get("temperature"),
        "touch": existing.get("touch", False),
    }
    with open(input_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"[upload_audio] wrote input_data.json — triggering pipeline (priority)")
    asyncio.create_task(run_pipeline(priority=True))

    return {"status": "received", "filename": filename, "transcript": transcript, "sentiment": sentiment}
