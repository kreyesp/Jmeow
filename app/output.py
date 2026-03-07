import os
import json
from dotenv import load_dotenv
import openai

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

dummy_data = {"temperature": 33, "touch": True}

prompt = f"""
You are an emotion inference system for a wearable device.

Input signals:
Temperature: {dummy_data['temperature']}°C
Touch detected: {dummy_data['touch']}

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