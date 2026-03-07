from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import shutil
import uuid
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

AUDIO_DIR = "received_audio"
os.makedirs(AUDIO_DIR, exist_ok=True)

# Track connected Arduinos
connected_arduinos: list[WebSocket] = []

@app.get("/")
def index():
    return FileResponse("index.html")

# --- WebSocket: Arduinos connect here, messages broadcast to all others ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_arduinos.append(websocket)
    print(f"Arduino connected! Total: {len(connected_arduinos)}")
    try:
        while True:
            data = await websocket.receive_text()
            print(f"Relaying: {data}")
            for arduino in connected_arduinos:
                if arduino != websocket:
                    await arduino.send_text(data)
    except WebSocketDisconnect:
        connected_arduinos.remove(websocket)
        print(f"Arduino disconnected. Total: {len(connected_arduinos)}")

# --- Manually send a message to all connected Arduinos ---
@app.post("/send_to_arduino")
async def send_to_arduino(payload: dict):
    if not connected_arduinos:
        return {"status": "error", "message": "No Arduino connected"}

    message = payload.get("msg", "")
    print(f"Sending to all Arduinos: {message}")

    for arduino in connected_arduinos:
        await arduino.send_text(message)

    return {"status": "sent", "message": message, "recipients": len(connected_arduinos)}

# --- Audio upload from index.html ---
@app.post("/upload_audio")
async def upload_audio(file: UploadFile = File(...)):
    filename = f"{AUDIO_DIR}/audio_{uuid.uuid4()}.webm"
    with open(filename, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    print(f"Saved: {filename}")
    return {"status": "received", "filename": filename}