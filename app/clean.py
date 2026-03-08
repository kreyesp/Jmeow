"""
clean.py — Parse and normalize the giver Arduino stream into input_data.json.

Writes input_data.json only when a trigger condition is met:
  - touch is detected (touch == 1)
  - raw speed > 500
  - temperature > 22°C
  - voice data exists (voice_data.json written by /upload_audio endpoint)

Usage:
    Pipe the serial/WebSocket stream to stdin:
        python clean.py < raw_stream.txt
    Or live:
        some_reader | python clean.py
"""

import sys
import json
import re
import os
from collections import deque
from typing import Optional


SPEED_MAX = 5000.0   # raw speed cap for 0–1 normalization
SPEED_TRIGGER = 500  # raw speed threshold to trigger a write
TEMP_TRIGGER = 22    # °C threshold to trigger a write
WINDOW_SIZE = 5      # readings to smooth over

window = deque(maxlen=WINDOW_SIZE)

BASE_DIR = os.path.dirname(__file__)
input_path = os.path.join(BASE_DIR, "input_data.json")
voice_path = os.path.join(BASE_DIR, "..", "voice_data.json")  # written by server.py


def parse_line(line: str) -> Optional[dict]:
    """Extract JSON from '[unknown] received: {...}' or plain JSON lines."""
    match = re.search(r"received:\s*(\{.*\})", line)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
    try:
        return json.loads(line.strip())
    except json.JSONDecodeError:
        return None


def normalize_speed(raw: float) -> float:
    return min(raw / SPEED_MAX, 1.0)


def extract_temp(temps: list) -> Optional[float]:
    if temps and isinstance(temps, list) and len(temps) > 0:
        return temps[0].get("tempC")
    return None


def load_voice() -> Optional[dict]:
    """Read voice_data.json if it exists (written by /upload_audio in server.py)."""
    try:
        with open(voice_path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def should_trigger(raw: dict, voice: Optional[dict]) -> bool:
    """Return True if any condition warrants writing input_data.json."""
    if bool(raw.get("touch", 0)):
        return True
    if raw.get("speed", 0) > SPEED_TRIGGER:
        return True
    temp = extract_temp(raw.get("temps", []))
    if temp is not None and temp > TEMP_TRIGGER:
        return True
    if voice:
        return True
    return False


def clean_reading(raw: dict) -> dict:
    return {
        "touch": bool(raw.get("touch", 0)),
        "speed": normalize_speed(raw.get("speed", 0.0)),
        "temperature": extract_temp(raw.get("temps", [])),
        "imu": {
            "gx": raw.get("gx"),
            "gy": raw.get("gy"),
            "gz": raw.get("gz"),
            "led": raw.get("imu_led"),
            "ok": raw.get("imu_ok"),
        },
        "mpu_time": raw.get("mpu_time"),
    }


def average_window(readings: deque) -> dict:
    speeds = [r["speed"] for r in readings]
    temps = [r["temperature"] for r in readings if r["temperature"] is not None]
    touches = [r["touch"] for r in readings]

    return {
        "speed": round(sum(speeds) / len(speeds), 4),
        "temperature": round(sum(temps) / len(temps), 4) if temps else None,
        "touch": any(touches),
        "imu": readings[-1]["imu"],
        "mpu_time": readings[-1]["mpu_time"],
    }


def write_input(averaged: dict, voice: Optional[dict]) -> None:
    averaged["voice"] = voice if voice else {"transcript": "", "sentiment": ""}
    output = {
        "voice": averaged["voice"],
        "speed": averaged["speed"],
        "temperature": averaged["temperature"],
        "touch": averaged["touch"],
    }
    with open(input_path, "w") as f:
        json.dump(output, f, indent=2)


def process_stream(stream) -> None:
    for line in stream:
        line = line.strip()
        if not line:
            continue

        raw = parse_line(line)
        if raw is None:
            continue

        if raw.get("type") == "hello" or "speed" not in raw:
            continue

        voice = load_voice()

        if not should_trigger(raw, voice):
            print(
                f"[clean] skip — speed={raw.get('speed', 0):.0f}  "
                f"touch={raw.get('touch', 0)}  "
                f"temp={extract_temp(raw.get('temps', []))}°C"
            )
            continue

        cleaned = clean_reading(raw)
        window.append(cleaned)
        averaged = average_window(window)
        averaged.pop("imu", None)
        averaged.pop("mpu_time", None)
        write_input(averaged, voice)

        reasons = []
        if averaged["touch"]:
            reasons.append("touch")
        if raw.get("speed", 0) > SPEED_TRIGGER:
            reasons.append(f"speed>{SPEED_TRIGGER}")
        if averaged["temperature"] is not None and averaged["temperature"] > TEMP_TRIGGER:
            reasons.append(f"temp>{TEMP_TRIGGER}")
        if voice:
            reasons.append("voice")

        print(
            f"[clean] WRITE — speed={averaged['speed']:.3f}  "
            f"temp={averaged['temperature']}°C  "
            f"touch={averaged['touch']}  "
            f"triggers={reasons}"
        )


def process_packet(raw: dict) -> None:
    """Process a single already-parsed packet — called directly from server.py.

    Triggers write when:
      - touch == 1
      - speed > 500
      - temperature > 23
      - /upload_audio was hit (voice_data.json exists with content)
    """
    if raw.get("type") == "hello" or "speed" not in raw:
        return

    touch = bool(raw.get("touch", 0))
    speed = raw.get("speed", 0)
    temp = extract_temp(raw.get("temps", []))
    voice = load_voice()
    has_voice = bool(voice and (voice.get("transcript") or voice.get("sentiment")))

    if not touch and speed <= 500 and (temp is None or temp <= 23) and not has_voice:
        return

    cleaned = clean_reading(raw)
    window.append(cleaned)
    averaged = average_window(window)
    averaged.pop("imu", None)
    averaged.pop("mpu_time", None)
    write_input(averaged, voice)

    reasons = []
    if touch: reasons.append("touch")
    if speed > 500: reasons.append(f"speed>{speed:.0f}")
    if temp is not None and temp > 23: reasons.append(f"temp>{temp}")
    if has_voice: reasons.append("voice")
    print(f"[clean] WRITE — triggers={reasons}")


if __name__ == "__main__":
    print("clean.py: reading giver stream from stdin → input_data.json")
    process_stream(sys.stdin)
