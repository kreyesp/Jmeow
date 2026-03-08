"""
test_clean.py — Run clean.py against a fake Arduino stream.
Each time a write is triggered, also saves a copy to test.json.

Usage:
    python app/test_clean.py
"""

import json
import os
import io
import clean

# Override write_input to also copy to test.json
_original_write = clean.write_input
test_json_path = os.path.join(os.path.dirname(__file__), "test.json")
write_count = 0
test_log = []

def _patched_write(averaged, voice):
    global write_count
    _original_write(averaged, voice)
    with open(clean.input_path) as f:
        entry = json.load(f)
    test_log.append(entry)
    with open(test_json_path, "w") as f:
        json.dump(test_log, f, indent=2)
    write_count += 1
    print(f"  → appended to test.json (write #{write_count})\n")

clean.write_input = _patched_write

# Fake stream: idle readings, then a single touch=1 trigger
FAKE_STREAM = """\
[unknown] received: {"touch": 1, "imu_ok": true, "gx": -64, "gy": -63, "gz": -78, "speed": 118.95, "imu_led": 1, "temps": [{"addr": "0x48", "tempC": 22.875}], "device": "giver", "mpu_time": "2026-03-08T03:41:37"}
"""

# Simulate voice_data.json being present for one window of readings
# (uncomment to test voice trigger)
# with open(os.path.join(os.path.dirname(__file__), "..", "voice_data.json"), "w") as f:
#     json.dump({"transcript": "I feel really anxious right now.", "sentiment": "anxious"}, f)

print("=" * 55)
print("test_clean.py: running fake stream through clean.py")
print("=" * 55 + "\n")

clean.process_stream(io.StringIO(FAKE_STREAM))

print("\n" + "=" * 55)
print(f"Done. {write_count} write(s) triggered.")
if write_count:
    print(f"test.json contents ({write_count} entries):")
    print(json.dumps(test_log, indent=2))
print("=" * 55)
