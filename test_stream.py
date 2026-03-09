"""
test_stream.py — Send a fake giver Arduino stream to the running server via WebSocket.

Sends packets in labeled phases so you can observe exactly when triggers fire
(watch server terminal for [clean] WRITE and [pipeline] lines).

Usage:
    python test_stream.py [--host localhost] [--port 8000]

Phases:
  1. NOISE        — low speed, no touch  (should NOT trigger)
  2. CONSTANT     — 10 packets at steady ~120 speed  (triggers once on buffer fill)
  3. TOUCH        — single touch=1 packet  (triggers immediately)
  4. INCREASING   — speed ramps 500→900  (triggers as characterization shifts)
  5. DECREASING   — speed drops 900→100  (triggers as pattern flips)
  6. CONSTANT HI  — 10 more packets at steady ~900  (should NOT re-trigger)
"""

import asyncio
import json
import argparse
import websockets

INTERVAL = 0.3   # seconds between packets — adjust to taste

PHASES = [
    {
        "name": "NOISE — low speed, no touch (should NOT trigger speed/temp)",
        "packets": [
            {"touch": 0, "speed": 30.0,  "temps": [{"addr": "0x48", "tempC": 22.4}], "device": "giver"},
            {"touch": 0, "speed": 28.5,  "temps": [{"addr": "0x48", "tempC": 22.5}], "device": "giver"},
            {"touch": 0, "speed": 31.0,  "temps": [{"addr": "0x48", "tempC": 22.4}], "device": "giver"},
            {"touch": 0, "speed": 29.0,  "temps": [{"addr": "0x48", "tempC": 22.5}], "device": "giver"},
            {"touch": 0, "speed": 30.5,  "temps": [{"addr": "0x48", "tempC": 22.4}], "device": "giver"},
        ],
    },
    {
        "name": "CONSTANT SPEED ~120 — fills 10-sample buffer (triggers once)",
        "packets": [
            {"touch": 0, "speed": 118.0, "temps": [{"addr": "0x48", "tempC": 22.5}], "device": "giver"},
            {"touch": 0, "speed": 119.5, "temps": [{"addr": "0x48", "tempC": 22.6}], "device": "giver"},
            {"touch": 0, "speed": 120.1, "temps": [{"addr": "0x48", "tempC": 22.5}], "device": "giver"},
            {"touch": 0, "speed": 118.8, "temps": [{"addr": "0x48", "tempC": 22.6}], "device": "giver"},
            {"touch": 0, "speed": 121.0, "temps": [{"addr": "0x48", "tempC": 22.5}], "device": "giver"},
            {"touch": 0, "speed": 119.2, "temps": [{"addr": "0x48", "tempC": 22.6}], "device": "giver"},
            {"touch": 0, "speed": 120.5, "temps": [{"addr": "0x48", "tempC": 22.5}], "device": "giver"},
            {"touch": 0, "speed": 118.6, "temps": [{"addr": "0x48", "tempC": 22.6}], "device": "giver"},
            {"touch": 0, "speed": 120.0, "temps": [{"addr": "0x48", "tempC": 22.5}], "device": "giver"},
            {"touch": 0, "speed": 119.7, "temps": [{"addr": "0x48", "tempC": 22.6}], "device": "giver"},
        ],
    },
    {
        "name": "CONSTANT SPEED REPEATED — same range, should NOT re-trigger",
        "packets": [
            {"touch": 0, "speed": 120.3, "temps": [{"addr": "0x48", "tempC": 22.5}], "device": "giver"},
            {"touch": 0, "speed": 119.1, "temps": [{"addr": "0x48", "tempC": 22.6}], "device": "giver"},
            {"touch": 0, "speed": 121.2, "temps": [{"addr": "0x48", "tempC": 22.5}], "device": "giver"},
            {"touch": 0, "speed": 118.9, "temps": [{"addr": "0x48", "tempC": 22.6}], "device": "giver"},
            {"touch": 0, "speed": 120.7, "temps": [{"addr": "0x48", "tempC": 22.5}], "device": "giver"},
        ],
    },
    {
        "name": "TOUCH=1 — immediate trigger regardless of buffers",
        "packets": [
            {"touch": 1, "speed": 119.0, "temps": [{"addr": "0x48", "tempC": 22.5}], "device": "giver"},
        ],
    },
    {
        "name": "INCREASING SPEED 500→900 — should trigger as pattern/magnitude shifts",
        "packets": [
            {"touch": 0, "speed": 500.0, "temps": [{"addr": "0x48", "tempC": 23.0}], "device": "giver"},
            {"touch": 0, "speed": 580.0, "temps": [{"addr": "0x48", "tempC": 23.1}], "device": "giver"},
            {"touch": 0, "speed": 650.0, "temps": [{"addr": "0x48", "tempC": 23.2}], "device": "giver"},
            {"touch": 0, "speed": 700.0, "temps": [{"addr": "0x48", "tempC": 23.4}], "device": "giver"},
            {"touch": 0, "speed": 750.0, "temps": [{"addr": "0x48", "tempC": 23.5}], "device": "giver"},
            {"touch": 0, "speed": 800.0, "temps": [{"addr": "0x48", "tempC": 23.7}], "device": "giver"},
            {"touch": 0, "speed": 840.0, "temps": [{"addr": "0x48", "tempC": 23.8}], "device": "giver"},
            {"touch": 0, "speed": 870.0, "temps": [{"addr": "0x48", "tempC": 23.9}], "device": "giver"},
            {"touch": 0, "speed": 890.0, "temps": [{"addr": "0x48", "tempC": 24.0}], "device": "giver"},
            {"touch": 0, "speed": 900.0, "temps": [{"addr": "0x48", "tempC": 24.1}], "device": "giver"},
        ],
    },
    {
        "name": "CONSTANT HIGH SPEED ~900 — should NOT re-trigger after settling",
        "packets": [
            {"touch": 0, "speed": 898.0, "temps": [{"addr": "0x48", "tempC": 24.1}], "device": "giver"},
            {"touch": 0, "speed": 901.0, "temps": [{"addr": "0x48", "tempC": 24.1}], "device": "giver"},
            {"touch": 0, "speed": 899.5, "temps": [{"addr": "0x48", "tempC": 24.2}], "device": "giver"},
            {"touch": 0, "speed": 900.5, "temps": [{"addr": "0x48", "tempC": 24.1}], "device": "giver"},
            {"touch": 0, "speed": 897.0, "temps": [{"addr": "0x48", "tempC": 24.1}], "device": "giver"},
            {"touch": 0, "speed": 902.0, "temps": [{"addr": "0x48", "tempC": 24.2}], "device": "giver"},
            {"touch": 0, "speed": 900.0, "temps": [{"addr": "0x48", "tempC": 24.1}], "device": "giver"},
            {"touch": 0, "speed": 899.0, "temps": [{"addr": "0x48", "tempC": 24.1}], "device": "giver"},
            {"touch": 0, "speed": 901.5, "temps": [{"addr": "0x48", "tempC": 24.2}], "device": "giver"},
            {"touch": 0, "speed": 900.0, "temps": [{"addr": "0x48", "tempC": 24.1}], "device": "giver"},
        ],
    },
    {
        "name": "DECREASING SPEED 900→100 — should trigger as pattern flips to decreasing",
        "packets": [
            {"touch": 0, "speed": 800.0, "temps": [{"addr": "0x48", "tempC": 24.0}], "device": "giver"},
            {"touch": 0, "speed": 700.0, "temps": [{"addr": "0x48", "tempC": 23.8}], "device": "giver"},
            {"touch": 0, "speed": 580.0, "temps": [{"addr": "0x48", "tempC": 23.5}], "device": "giver"},
            {"touch": 0, "speed": 450.0, "temps": [{"addr": "0x48", "tempC": 23.2}], "device": "giver"},
            {"touch": 0, "speed": 320.0, "temps": [{"addr": "0x48", "tempC": 23.0}], "device": "giver"},
            {"touch": 0, "speed": 220.0, "temps": [{"addr": "0x48", "tempC": 22.8}], "device": "giver"},
            {"touch": 0, "speed": 150.0, "temps": [{"addr": "0x48", "tempC": 22.6}], "device": "giver"},
            {"touch": 0, "speed": 120.0, "temps": [{"addr": "0x48", "tempC": 22.5}], "device": "giver"},
            {"touch": 0, "speed": 105.0, "temps": [{"addr": "0x48", "tempC": 22.5}], "device": "giver"},
            {"touch": 0, "speed": 100.0, "temps": [{"addr": "0x48", "tempC": 22.4}], "device": "giver"},
        ],
    },
]


async def run(host: str, port: int):
    uri = f"ws://{host}:{port}/ws?name=giver"
    print(f"Connecting to {uri} ...")

    async with websockets.connect(uri) as ws:
        print(f"Connected.\n")

        total_sent = 0
        for phase in PHASES:
            print(f"{'─' * 60}")
            print(f"PHASE: {phase['name']}")
            print(f"{'─' * 60}")

            for i, packet in enumerate(phase["packets"]):
                payload = json.dumps(packet)
                await ws.send(payload)
                total_sent += 1
                print(f"  [{total_sent:3d}] sent: speed={packet['speed']:6.1f}  "
                      f"touch={packet['touch']}  "
                      f"temp={packet['temps'][0]['tempC']:.1f}°C")
                await asyncio.sleep(INTERVAL)

            # Pause between phases so server logs are easier to read
            print(f"       ↳ phase done — pausing 1s\n")
            await asyncio.sleep(1.0)

        print(f"{'─' * 60}")
        print(f"Done. {total_sent} packets sent total.")
        print(f"Check server terminal for [clean] WRITE and [pipeline] lines.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    asyncio.run(run(args.host, args.port))
