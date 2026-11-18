from google import genai

client = genai.Client()
candidates = [
    "gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash",
    "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite",
    "gemini-2.5-pro", "gemini-2.5-flash-lite",
]

for model in candidates:
    try:
        r = client.models.generate_content(model=model, contents="say hi")
        print(f"OK   {model:<24} {r.text.strip()[:30]}")
    except Exception as e:
        print(f"ERRO {model:<24} {str(e)[:70]}")