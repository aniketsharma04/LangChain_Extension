"""
Direct test of the Gemini API key - bypasses all LangChain/LiteLLM layers
to get the raw HTTP response from Google's API.
"""
import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
print(f"API Key: {api_key[:12]}...{api_key[-4:]}" if api_key else "NO API KEY FOUND")
print(f"Key length: {len(api_key) if api_key else 0}")
print()

# Test 1: List models (to check if key is valid at all)
print("=" * 60)
print("TEST 1: List available models")
print("=" * 60)
url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
try:
    resp = requests.get(url, timeout=10)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        models = resp.json().get("models", [])
        gemini_models = [m["name"] for m in models if "gemini" in m["name"].lower()]
        print(f"Found {len(gemini_models)} Gemini models:")
        for m in gemini_models[:5]:
            print(f"  - {m}")
    else:
        print(f"Response: {resp.text[:500]}")
except Exception as e:
    print(f"Error: {e}")

print()

# Test 2: Generate content with gemini-2.0-flash (the model being used)
print("=" * 60)
print("TEST 2: generateContent with gemini-2.0-flash")
print("=" * 60)
url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
payload = {
    "contents": [{"parts": [{"text": "Say hello in one word"}]}]
}
try:
    resp = requests.post(url, json=payload, timeout=15)
    print(f"Status: {resp.status_code}")
    print(f"Headers: {dict(resp.headers)}")
    if resp.status_code == 200:
        data = resp.json()
        content = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        print(f"Response: {content}")
    else:
        print(f"Error response:")
        print(json.dumps(resp.json(), indent=2))
except Exception as e:
    print(f"Error: {e}")

print()

# Test 3: Try streaming endpoint (which is what the extension uses)
print("=" * 60)
print("TEST 3: streamGenerateContent with gemini-2.0-flash")
print("=" * 60)
url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:streamGenerateContent?key={api_key}"
payload = {
    "contents": [{"parts": [{"text": "Say hi"}]}]
}
try:
    resp = requests.post(url, json=payload, timeout=15, stream=True)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        # Read first chunk
        for i, chunk in enumerate(resp.iter_content(chunk_size=1024)):
            if i == 0:
                print(f"First chunk (stream works): {chunk[:200]}")
                break
    else:
        print(f"Error response:")
        print(resp.text[:500])
except Exception as e:
    print(f"Error: {e}")

print()

# Test 4: Test via LangChain (the actual path used by the extension)
print("=" * 60)
print("TEST 4: Via LangChain ChatGoogleGenerativeAI")
print("=" * 60)
try:
    from langchain_google_genai import ChatGoogleGenerativeAI
    
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        google_api_key=api_key,
        temperature=0.2,
    )
    
    result = llm.invoke("Say hello in one word")
    print(f"Success! Response: {result.content}")
except Exception as e:
    print(f"LangChain Error Type: {type(e).__name__}")
    print(f"LangChain Error: {e}")
    # Print the full raw exception string to see what _clean_error would see
    print(f"\nRaw str(e):")
    print(str(e)[:1000])

print()
print("=" * 60)
print("DONE")
print("=" * 60)
