"""
clean.py — Parse and normalize the giver Arduino stream into input_data.json.

Writes input_data.json only when a trigger condition is met:
  - touch is detected (touch == 1)
  - voice data exists (voice_data.json written by /upload_audio endpoint)
  - speed or temperature signal pattern/magnitude changes meaningfully
    (evaluated after collecting SPEED_SAMPLE_SIZE=10 / TEMP_SAMPLE_SIZE=25 samples via softmax characterization)

Speed/temp are no longer threshold-based. Instead, 10 samples are collected and
softmax-weighted to produce a magnitude + pattern ("constant", "increasing",
"decreasing", "variable"). A write is only triggered when that characterization
changes — preventing constant re-firing when a signal is stable above any fixed
threshold.

Usage:
    Pipe the serial/WebSocket stream to stdin:
        python clean.py < raw_stream.txt
    Or live:
        some_reader | python clean.py
"""

import sys
import json
import math
import re
import os
from collections import deque
from typing import Optional


SPEED_SAMPLE_SIZE = 10   # samples to collect before characterizing speed
TEMP_SAMPLE_SIZE  = 25   # larger window for temperature (gradual changes)
WINDOW_SIZE = 5          # legacy smoothing window (kept for process_stream compat)
SPEED_MIN_MAGNITUDE = 300  # below this mean speed, movement is resting — no speed trigger

# Rolling sample buffers for softmax characterization
speed_samples: deque = deque(maxlen=SPEED_SAMPLE_SIZE)
temp_samples: deque = deque(maxlen=TEMP_SAMPLE_SIZE)

# Last written characterization — used to detect meaningful change
_last_speed_char: Optional[dict] = None
_last_temp_char: Optional[dict] = None

BASE_DIR = os.path.dirname(__file__)
input_path = os.path.join(BASE_DIR, "input_data.json")
voice_path = os.path.join(BASE_DIR, "..", "voice_data.json")  # written by server.py


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Softmax signal characterization
# ---------------------------------------------------------------------------

def softmax(values: list) -> list:
    """Numerically stable softmax over a list of floats."""
    if not values:
        return []
    max_v = max(values)
    exps = [math.exp(v - max_v) for v in values]
    total = sum(exps)
    return [e / total for e in exps]


def analyze_signal(samples: deque) -> dict:
    """
    Characterize a signal buffer using softmax-weighted statistics.

    Returns:
        magnitude  — softmax-weighted average of the raw samples
        pattern    — "constant" | "increasing" | "decreasing" | "variable"
    """
    values = list(samples)
    if len(values) == 1:
        return {"magnitude": round(values[0], 2), "pattern": "unknown"}

    # Trimmed mean: drop highest and lowest value to suppress outlier pull
    sorted_v = sorted(values)
    trimmed = sorted_v[1:-1] if len(sorted_v) > 2 else sorted_v
    mean = sum(trimmed) / len(trimmed)

    variance = sum((v - mean) ** 2 for v in trimmed) / len(trimmed)
    std = math.sqrt(variance) if variance > 0 else 0.0
    relative_std = std / (abs(mean) + 1e-6)

    first, last = values[0], values[-1]
    relative_change = abs(last - first) / (abs(first) + 1e-6)

    if relative_std < 0.05:
        pattern = "constant"
    elif last > first and relative_change > 0.50:
        pattern = "increasing"
    elif last < first and relative_change > 0.50:
        pattern = "decreasing"
    else:
        pattern = "variable"

    return {"magnitude": round(mean, 2), "pattern": pattern}


def signal_changed(prev: Optional[dict], curr: Optional[dict]) -> bool:
    """True if the pattern changed or magnitude shifted by more than 20%."""
    if prev is None or curr is None:
        return True
    if prev["pattern"] != curr["pattern"]:
        return True
    prev_mag, curr_mag = prev["magnitude"], curr["magnitude"]
    if prev_mag == 0 and curr_mag == 0:
        return False
    return abs(curr_mag - prev_mag) / (abs(prev_mag) + 1e-6) > 0.20


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def write_input(output: dict) -> None:
    with open(input_path, "w") as f:
        json.dump(output, f, indent=2)


# ---------------------------------------------------------------------------
# Packet processing (called from server.py)
# ---------------------------------------------------------------------------

def process_packet(raw: dict) -> None:
    """Process a single already-parsed packet — called directly from server.py.

    Triggers a write to input_data.json when:
      - touch == 1  (immediate)
      - voice data present  (immediate)
      - speed buffer has >= SPEED_SAMPLE_SIZE samples AND characterization changed
      - temp buffer has >= TEMP_SAMPLE_SIZE samples AND characterization changed
    """
    global _last_speed_char, _last_temp_char

    if raw.get("type") == "hello" or "speed" not in raw:
        return

    touch = bool(raw.get("touch", 0))
    voice = load_voice()
    has_voice = bool(voice and (voice.get("transcript") or voice.get("sentiment")))

    # Touch fires immediately — no buffer needed
    if touch:
        write_input({
            "voice": voice if voice else {"transcript": "", "sentiment": ""},
            "speed": None,
            "temperature": None,
            "touch": True,
        })
        print("[clean] WRITE — triggers=['touch']")
        return

    raw_speed = raw.get("speed", 0.0)
    raw_temp = extract_temp(raw.get("temps", []))

    # Accumulate samples — reject outliers (> 5x current buffer median)
    if speed_samples:
        sorted_s = sorted(speed_samples)
        median_s = sorted_s[len(sorted_s) // 2]
        if median_s > 0 and raw_speed > median_s * 5:
            print(f"[clean] outlier rejected: speed={raw_speed:.1f} (median={median_s:.1f})")
            raw_speed = None
    if raw_speed is not None:
        speed_samples.append(raw_speed)
    if raw_temp is not None:
        temp_samples.append(raw_temp)

    speed_char = analyze_signal(speed_samples) if speed_samples else None
    temp_char = analyze_signal(temp_samples) if temp_samples else None

    speed_ready = len(speed_samples) >= SPEED_SAMPLE_SIZE
    temp_ready = len(temp_samples) >= TEMP_SAMPLE_SIZE
    speed_above_min = speed_char is not None and speed_char["magnitude"] >= SPEED_MIN_MAGNITUDE
    speed_trigger = speed_ready and speed_above_min and signal_changed(_last_speed_char, speed_char)
    temp_trigger = temp_ready and signal_changed(_last_temp_char, temp_char)

    if not has_voice and not speed_trigger and not temp_trigger:
        return

    # Commit characterization only when writing
    if speed_trigger:
        _last_speed_char = speed_char
    if temp_trigger:
        _last_temp_char = temp_char

    output = {
        "voice": voice if voice else {"transcript": "", "sentiment": ""},
        "speed": speed_char,
        "temperature": temp_char,
        "touch": touch,
    }
    write_input(output)

    reasons = []
    if has_voice:
        reasons.append("voice")
    if speed_trigger:
        reasons.append(f"speed-{speed_char['pattern']}@{speed_char['magnitude']:.0f}")
    if temp_trigger and temp_char:
        reasons.append(f"temp-{temp_char['pattern']}@{temp_char['magnitude']:.1f}C")
    print(f"[clean] WRITE — triggers={reasons}")


# ---------------------------------------------------------------------------
# Stream processing (used by test_clean.py and CLI)
# ---------------------------------------------------------------------------

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

        process_packet(raw)


if __name__ == "__main__":
    print("clean.py: reading giver stream from stdin → input_data.json")
    process_stream(sys.stdin)
