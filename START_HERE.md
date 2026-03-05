# OpenClaw AI Dev Platform — Quick Start

## Project structure
```
openclaw-complete/
├── backend/    → Python FastAPI server  (start this first)
└── frontend/   → VS Code Extension      (install and press F5)
```

---

## Step 1 — Start the Backend

```bash
cd backend

# Create virtual environment
python -m venv venv

# Activate it
source venv/bin/activate          # Mac / Linux
# venv\Scripts\activate           # Windows

# Install dependencies
pip install -r requirements.txt

# Configure — add at least one API key
cp .env.example .env
# Open .env and set OPENAI_API_KEY=sk-...  (or GEMINI_API_KEY for Gemini)
# For local models: make sure Ollama is running (ollama pull llama3.2)

# Start the server
python server.py
```

You should see:
```
🦾 OpenClaw Python Backend running on http://localhost:3579
```

---

## Step 2 — Install and Run the Extension

```bash
cd frontend
npm install
npm run compile
```

Then in VS Code:
1. Open the `frontend/` folder in VS Code
2. Press **F5** → this opens a new VS Code window (Extension Development Host)
3. In the new window, look for the **🦾 OpenClaw** icon in the Activity Bar (left sidebar)
4. Click it → the chat panel opens

---

## Step 3 — Use it

- **Chat:** Type in the panel, press Enter
- **Tools on selected code:** Select code → right-click → **🦾 OpenClaw AI** → pick a tool
- **Switch LLM:** Use the Provider/Model dropdowns at the top of the chat panel
- **New session:** Click the `+` icon in the panel title bar
- **Local models:** Make sure Ollama is running, select "Ollama (local)" in the dropdown

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "Cannot reach backend" warning | Make sure `python server.py` is running |
| No providers in dropdown | Backend is not running or API keys not set in `.env` |
| Ollama shows ⚠ | Run `ollama serve` and `ollama pull llama3.2` |
| Extension not showing | Run `npm run compile` first, then F5 |
| Tools not appearing in right-click | Select some code first — menu only shows when code is selected |
