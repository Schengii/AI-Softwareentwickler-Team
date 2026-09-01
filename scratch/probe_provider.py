"""scratch/probe_provider.py - Minimaler Kontingent-Check gegen Gemini, ohne einen echten
Agenten-Lauf zu starten (spart Kontingent, waehrend wir NUR wissen wollen, ob wieder
Kapazitaet da ist)."""
import sys

sys.path.insert(0, ".")

from google import genai

from config import GEMINI_API_KEY

if not GEMINI_API_KEY:
    print("FAIL: kein GEMINI_API_KEY konfiguriert")
    sys.exit(1)

try:
    client = genai.Client(api_key=GEMINI_API_KEY)
    resp = client.models.generate_content(model="gemini-3.1-flash-lite", contents="ping")
    print("OK:", (resp.text or "")[:50])
except Exception as e:
    print(f"FAIL: {e}")
    sys.exit(1)
