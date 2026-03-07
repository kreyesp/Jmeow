from fastapi import FastAPI, UploadFile, File
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

BRIDGE_URL = "http://192.168.1.42:5000/send"  # teammate laptop

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


# NEW ENDPOINT FOR TESTING
@app.post("/send_dummy")
def send_dummy():
    try:
        r = requests.post(
            BRIDGE_URL,
            json={"msg": "dummy_test"}
        )
        return {"status": "sent", "bridge_response": r.json()}
    except Exception as e:
        return {"status": "error", "message": str(e)}