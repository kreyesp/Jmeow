import os
import json
import re
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

input_path = os.path.join(os.path.dirname(__file__), "input_data.json")
with open(input_path) as f:
    data = json.load(f)

speed_data  = data.get("speed") or {}
temp_data   = data.get("temperature")
touch       = data.get("touch", False)
voice       = data.get("voice") or {}
transcript  = voice.get("transcript", "")
sentiment   = voice.get("sentiment", "")

# speed and temperature are now {"magnitude": float, "pattern": str} dicts
# (or None if not enough samples collected yet)
speed_mag     = speed_data.get("magnitude", 0.0) if isinstance(speed_data, dict) else float(speed_data or 0)
speed_pattern = speed_data.get("pattern", "unknown") if isinstance(speed_data, dict) else "unknown"
temp_mag      = temp_data.get("magnitude") if isinstance(temp_data, dict) else temp_data
temp_pattern  = temp_data.get("pattern", "unknown") if isinstance(temp_data, dict) else "unknown"

active_signals = ""

if speed_mag and speed_mag > 0:
    active_signals += f"- motion speed: {speed_pattern} at magnitude {speed_mag:.1f} (raw sensor units, range 0–5000; >500 is notable)\n"
if temp_mag is not None:
    active_signals += f"- ambient temperature: {temp_pattern} at {temp_mag:.1f}°C (baseline ~22°C; higher = warmer/more tense)\n"
if touch:
    active_signals += "- touch: detected\n"
if transcript and sentiment:
    active_signals += f'- voice transcript: "{transcript}"\n'
    active_signals += f"- voice sentiment: {sentiment}\n"

if not active_signals:
    active_signals = "- no strong signals detected\n"

prompt = f"""You are an emotion inference system for a wearable comfort device that controls micro servos.

Active sensor signals:
{active_signals}
Based on all active signals together, infer the user's emotional state and output a single micro servo speed in microseconds (us).
Valid us range: 500-2500 (500 = fast/intense, 1500 = neutral, 2500 = slow/gentle).

Guidelines:
- motion speed: "constant" at high magnitude means sustained agitation → lower us; "increasing" means escalating → lower us; "decreasing" means calming → higher us.
- ambient temperature: "constant" above baseline means ongoing tension → lower us; "increasing" means building stress → lower us.
- touch detected: lean toward gentle comforting movement → higher us.
- voice sentiment: anxious/sad/mad → lower us; happy/love/calm → higher us.
- If only one signal is present, let it fully determine the output.
- Combine all active signals into one unified emotion and one us value.

Respond ONLY with valid JSON and nothing else, no markdown, no explanation:
{{"emotion": "", "microseconds": 0}}"""

print(f"[output] sending to LLM...")

response = client.chat.completions.create(
    model="gpt-4.1-mini",
    messages=[{"role": "user", "content": prompt}],
    temperature=0.2,
)

choice = response.choices[0]
print(f"[output] finish_reason: {choice.finish_reason}")

raw = choice.message.content or ""
raw = raw.strip()
print(f"[output] raw response: {repr(raw)}")

# Strip markdown code fences if model ignores instructions
raw = re.sub(r"^```(?:json)?\s*", "", raw)
raw = re.sub(r"\s*```$", "", raw)
raw = raw.strip()

if not raw:
    print("[output] ERROR: empty response from model")
    exit(1)

try:
    result = json.loads(raw)
except json.JSONDecodeError as e:
    print(f"[output] ERROR: could not parse JSON: {e}")
    print(f"[output] content was: {repr(raw)}")
    exit(1)

result["microseconds"] = max(500, min(2500, int(result["microseconds"])))
result["touch"]       = bool(touch)
result["speed"]       = {"magnitude": round(speed_mag, 4), "pattern": speed_pattern}
result["temperature"] = {"magnitude": temp_mag, "pattern": temp_pattern} if temp_mag is not None else None

output_path = os.path.join(os.path.dirname(__file__), "output.json")
with open(output_path, "w") as f:
    json.dump(result, f, indent=2)

print(f"[output] wrote output.json:")
print(json.dumps(result, indent=2))