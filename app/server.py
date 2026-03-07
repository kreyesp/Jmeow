from fastapi import FastAPI, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import shutil
import uuid
import os
import requests

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

AUDIO_DIR = "received_audio"
os.makedirs(AUDIO_DIR, exist_ok=True)

BRIDGE_URL = "http://10.29.154.85:8000"

# Track connected Arduinos
connected_arduinos: list[WebSocket] = []

@app.get("/")
def index():
    return FileResponse("index.html")

@app.post("/upload_audio")
async def upload_audio(file: UploadFile = File(...)):
    filename = f"{AUDIO_DIR}/audio_{uuid.uuid4()}.webm"
    with open(filename, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    print(f"Saved: {filename}")
    return {"status": "received", "filename": filename}

# --- WebSocket: Arduino connects here and listens ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_arduinos.append(websocket)
    print(f"Arduino connected! Total: {len(connected_arduinos)}")
    try:
        while True:
            await websocket.receive_text()  # keep connection alive
    except WebSocketDisconnect:
        connected_arduinos.remove(websocket)
        print("Arduino disconnected")

# --- Teammate POSTs here to send data to Arduino ---
@app.post("/send_to_arduino")
async def send_to_arduino(payload: dict):
    if not connected_arduinos:
        return {"status": "error", "message": "No Arduino connected"}
    
    message = payload.get("msg", "")
    print(f"Sending to Arduino: {message}")
    
    for arduino in connected_arduinos:
        await arduino.send_text(message)
    
    return {"status": "sent", "message": message, "recipients": len(connected_arduinos)}

# --- Original test endpoint ---
@app.post("/send_dummy")
def send_dummy():
    try:
        r = requests.post(BRIDGE_URL, json={"msg": "dummy_test"})
        return {"status": "sent", "bridge_response": r.json()}
    except Exception as e:
        return {"status": "error", "message": str(e)}