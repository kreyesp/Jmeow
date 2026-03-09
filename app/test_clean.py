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

def _patched_write(output):
    global write_count
    _original_write(output)
    with open(clean.input_path) as f:
        entry = json.load(f)
    test_log.append(entry)
    with open(test_json_path, "w") as f:
        json.dump(test_log, f, indent=2)
    write_count += 1
    print(f"  → appended to test.json (write #{write_count})\n")

clean.write_input = _patched_write

# Fake stream:
#   - 10 constant-speed packets (speed ~120, no touch) to fill the sample buffer
#   - 1 touch=1 packet (immediate trigger regardless of buffer)
#   - 10 high-speed packets (speed ~800, increasing) to trigger a speed pattern change
FAKE_STREAM = """\
{"touch": 0, "speed": 118.00, "temps": [{"addr": "0x48", "tempC": 22.5}], "device": "giver"}
{"touch": 0, "speed": 119.50, "temps": [{"addr": "0x48", "tempC": 22.6}], "device": "giver"}
{"touch": 0, "speed": 120.10, "temps": [{"addr": "0x48", "tempC": 22.5}], "device": "giver"}
{"touch": 0, "speed": 118.80, "temps": [{"addr": "0x48", "tempC": 22.7}], "device": "giver"}
{"touch": 0, "speed": 121.00, "temps": [{"addr": "0x48", "tempC": 22.5}], "device": "giver"}
{"touch": 0, "speed": 119.20, "temps": [{"addr": "0x48", "tempC": 22.6}], "device": "giver"}
{"touch": 0, "speed": 120.50, "temps": [{"addr": "0x48", "tempC": 22.5}], "device": "giver"}
{"touch": 0, "speed": 118.60, "temps": [{"addr": "0x48", "tempC": 22.6}], "device": "giver"}
{"touch": 0, "speed": 120.00, "temps": [{"addr": "0x48", "tempC": 22.5}], "device": "giver"}
{"touch": 0, "speed": 119.70, "temps": [{"addr": "0x48", "tempC": 22.6}], "device": "giver"}
{"touch": 1, "speed": 118.95, "temps": [{"addr": "0x48", "tempC": 22.875}], "device": "giver"}
{"touch": 0, "speed": 500.00, "temps": [{"addr": "0x48", "tempC": 23.0}], "device": "giver"}
{"touch": 0, "speed": 580.00, "temps": [{"addr": "0x48", "tempC": 23.2}], "device": "giver"}
{"touch": 0, "speed": 650.00, "temps": [{"addr": "0x48", "tempC": 23.5}], "device": "giver"}
{"touch": 0, "speed": 700.00, "temps": [{"addr": "0x48", "tempC": 23.8}], "device": "giver"}
{"touch": 0, "speed": 730.00, "temps": [{"addr": "0x48", "tempC": 24.0}], "device": "giver"}
{"touch": 0, "speed": 760.00, "temps": [{"addr": "0x48", "tempC": 24.1}], "device": "giver"}
{"touch": 0, "speed": 780.00, "temps": [{"addr": "0x48", "tempC": 24.2}], "device": "giver"}
{"touch": 0, "speed": 800.00, "temps": [{"addr": "0x48", "tempC": 24.3}], "device": "giver"}
{"touch": 0, "speed": 810.00, "temps": [{"addr": "0x48", "tempC": 24.4}], "device": "giver"}
{"touch": 0, "speed": 820.00, "temps": [{"addr": "0x48", "tempC": 24.5}], "device": "giver"}
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
