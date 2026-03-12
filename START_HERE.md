# Navyug AI Dev Platform — Quick Start

## Project structure
```
navyug-ai/
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
# Mac / Linux: source venv/bin/activate
# Windows:     venv\Scripts\activate

# Install dependencies  (Note: langgraph is required)
pip install -r requirements.txt
pip install langgraph

# IMPORTANT: If you get "ModuleNotFoundError: ... TimeoutError" when starting:
# This is a known bug in the openclaw package. 
# Open 'backend/venv/Lib/site-packages/openclaw/__init__.py' 
# Change 'from cmdop.exceptions import ..., TimeoutError' 
# To 'from cmdop.exceptions import ..., ConnectionTimeoutError as TimeoutError'

# Configure — add at least one API key
cp .env.example .env
# Open .env and set OPENAI_API_KEY=sk-...  (or GEMINI_API_KEY for Gemini)
# For local models: make sure Ollama is running (ollama pull llama3.2)

# Start the server
python server.py
```

You should see:
```
Navyug AI Python Backend running on http://localhost:3579
```

---

## Step 2 — Install and Run the Extension

```bash
cd frontend
npm install
npm run compile
```

Then in VS Code:
1. Open the `LangChain_Extension/frontend/` folder in VS Code
2. Press **F5** → this opens a new VS Code window (Extension Development Host)
3. In the new window, look for the **Navyug AI** icon in the Activity Bar (left sidebar)
- **Chat:** Type in the panel, press Enter
- **Tools on selected code:** Select code → right-click → ** Navyug AI** → pick a tool
- **Switch LLM:** Use the Provider/Model dropdowns at the top of the chat panel
- **New session:** Click the `+` icon in the panel title bar
- **Local models:** Make sure Ollama is running, select "Ollama (local)" in the dropdown
4. Click it → the chat panel opens

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "TimeoutError" on startup | See the `openclaw` patch mentioned in Step 1 above. |
| Red squiggles in server.py | Press `Ctrl+Shift+P` -> `Python: Select Interpreter` -> choose the one in `./backend/venv/`. |
| "Cannot reach backend" | Make sure `python server.py` is running in your terminal first. |
| F5 fails (cwd not found) | Ensure the `.vscode/launch.json` paths point correctly to `LangChain_Extension/frontend`. |
| Extension not showing | Run `npm run compile` first, then F5. |
