import os
import json
from dotenv import load_dotenv
import openai

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

dummy_data = {"temperature": 33.89, "touch": True}

voice_data_path = os.path.join(os.path.dirname(__file__), "voice_data.json")
if os.path.exists(voice_data_path):
    with open(voice_data_path) as f:
        voice_data = json.load(f)
    voice_input = voice_data.get("transcript")
    voice_sentiment = voice_data.get("sentiment")
else:
    voice_input = None
    voice_sentiment = None

prompt = f"""
You are an emotion inference system for a wearable device.

Input signals:
Temperature: {dummy_data['temperature']}°C
Touch detected: {dummy_data['touch']}
{f"Voice input: {voice_input}" if voice_input else ""}
{f"Voice sentiment: {voice_sentiment}" if voice_sentiment else ""}

Respond ONLY in JSON with this structure:
{{
  "emotion": "",
  "confidence": 0.0
}}
"""

response = openai.ChatCompletion.create(
    model="gpt-4.1-mini",
    messages=[{"role": "user", "content": prompt}],
    temperature=0.2
)

output_text = response.choices[0].message.content
emotion_json = json.loads(output_text)
print("AI output:", emotion_json)