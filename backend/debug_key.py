"""
Deep diagnostic v2: ASCII-safe, checks everything.
"""
import os
import sys
import io

# Force UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

print("=" * 60)
print("STEP 1: System env BEFORE .env")
print("=" * 60)
sys_gemini = os.environ.get("GEMINI_API_KEY")
sys_google = os.environ.get("GOOGLE_API_KEY")
print(f"  System GEMINI_API_KEY: {sys_gemini}" if sys_gemini else "  System GEMINI_API_KEY: NOT SET")
print(f"  System GOOGLE_API_KEY: {sys_google}" if sys_google else "  System GOOGLE_API_KEY: NOT SET")

print()
print("=" * 60)
print("STEP 2: Raw .env file contents (API_KEY lines only)")
print("=" * 60)
with open(".env", "r", encoding="utf-8") as f:
    for line_num, line in enumerate(f, 1):
        if "API_KEY" in line and not line.strip().startswith("#"):
            raw = line.rstrip()
            print(f"  Line {line_num}: {raw}")
            if "=" in raw:
                key_name, key_val = raw.split("=", 1)
                print(f"    Name:   [{key_name.strip()}]")
                print(f"    Value:  [{key_val.strip()}]")
                print(f"    Length: {len(key_val.strip())}")

print()
print("=" * 60)
print("STEP 3: After load_dotenv(override=True)")
print("=" * 60)
from dotenv import load_dotenv
load_dotenv(override=True)
env_gemini = os.getenv("GEMINI_API_KEY")
env_google = os.getenv("GOOGLE_API_KEY")
print(f"  GEMINI_API_KEY: [{env_gemini}]")
print(f"  GOOGLE_API_KEY: [{env_google}]")

# Are they the same?
if env_gemini and env_google:
    if env_gemini == env_google:
        print("  Keys are IDENTICAL")
    else:
        print("  !!! KEYS ARE DIFFERENT !!!")
        print(f"    GEMINI: {env_gemini}")
        print(f"    GOOGLE: {env_google}")

print()
print("=" * 60)
print("STEP 4: Direct HTTP test of the key")
print("=" * 60)
import requests

key_to_test = env_gemini or env_google
print(f"  Testing key: {key_to_test}")

# Test: list models
url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key_to_test}"
resp = requests.get(url, timeout=10)
print(f"  List models: {resp.status_code}")

# Test: generate content
url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key_to_test}"
payload = {"contents": [{"parts": [{"text": "hi"}]}]}
resp = requests.post(url, json=payload, timeout=15)
print(f"  Generate content: {resp.status_code}")
if resp.status_code != 200:
    err = resp.json().get("error", {})
    msg = err.get("message", "")
    # Find quota metrics
    for line in msg.split("\n"):
        line = line.strip()
        if line.startswith("*"):
            print(f"    {line}")
    # Show retry delay
    details = err.get("details", [])
    for d in details:
        if "retryDelay" in str(d):
            print(f"    retryDelay: {d.get('retryDelay')}")
else:
    data = resp.json()
    text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
    print(f"  SUCCESS! Response: {text}")

print()
print("=" * 60)
print("STEP 5: Is the backend server using this SAME key?")
print("=" * 60)
try:
    resp = requests.get("http://localhost:3579/health", timeout=3)
    print(f"  Backend: RUNNING (status={resp.status_code})")
    
    # Send a minimal test message through the actual backend
    print("  Sending test message through backend...")
    resp = requests.post("http://localhost:3579/api/chat", json={
        "message": "say hi in one word",
        "provider": "gemini",
        "model": "gemini-2.0-flash",
        "sessionId": "debug-test-session",
    }, timeout=30)
    data = resp.json()
    if data.get("error"):
        print(f"  Backend error: {data['error']}")
    else:
        print(f"  Backend success: {data.get('output', '')[:100]}")
except requests.exceptions.ConnectionError:
    print("  Backend: NOT RUNNING")
except Exception as e:
    print(f"  Backend error: {e}")

print()
print("=" * 60)
print("STEP 6: Check ALL Google/Gemini related env vars")
print("=" * 60)
for key in sorted(os.environ.keys()):
    lower = key.lower()
    if any(kw in lower for kw in ["google", "gemini", "gcloud", "gcp", "genai", "palm"]):
        val = os.environ[key]
        print(f"  {key} = {val}")

print()
print("=" * 60)
print("STEP 7: Verify the PROJECT the key belongs to")
print("=" * 60)
# The API key itself tells us nothing about the project.
# But we can check if listing models returns different quotas info
url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash?key={key_to_test}"
resp = requests.get(url, timeout=10)
if resp.status_code == 200:
    model_info = resp.json()
    print(f"  Model: {model_info.get('name')}")
    print(f"  Display: {model_info.get('displayName')}")
    print(f"  Input token limit: {model_info.get('inputTokenLimit')}")
    print(f"  Output token limit: {model_info.get('outputTokenLimit')}")
else:
    print(f"  Could not get model info: {resp.status_code}")

# Check if a different model works (maybe gemini-2.0-flash specifically is blocked)
print()
print("  Testing gemini-1.5-flash instead...")
url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={key_to_test}"
payload = {"contents": [{"parts": [{"text": "hi"}]}]}
resp = requests.post(url, json=payload, timeout=15)
print(f"  gemini-1.5-flash status: {resp.status_code}")
if resp.status_code == 200:
    text = resp.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
    print(f"  SUCCESS: {text[:100]}")
else:
    err = resp.json().get("error", {})
    print(f"  Error: {err.get('status')} - {err.get('message', '')[:200]}")

print()
print("  Testing gemini-2.5-flash instead...")
url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key_to_test}"
payload = {"contents": [{"parts": [{"text": "hi"}]}]}
resp = requests.post(url, json=payload, timeout=15)
print(f"  gemini-2.5-flash status: {resp.status_code}")
if resp.status_code == 200:
    text = resp.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
    print(f"  SUCCESS: {text[:100]}")
else:
    err = resp.json().get("error", {})
    print(f"  Error: {err.get('status')} - {err.get('message', '')[:200]}")

print()
print("=" * 60)
print("ALL TESTS COMPLETE")
print("=" * 60)
