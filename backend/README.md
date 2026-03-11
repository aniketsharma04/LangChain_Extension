# Navyug AI — Python Backend

FastAPI + LangChain backend. Runs on port 3579, identical API to the old Node.js version.

## What replaces what

| Old Node.js file | Python replacement | How |
|---|---|---|
| `server.ts` (Express) | `server.py` (FastAPI) | `pip install fastapi uvicorn` |
| `LLMRouter.ts` | `llm_router.py` | `from langchain_openai import ChatOpenAI` etc. |
| `AgenticChatEngineV2.ts` | `agent_engine.py` | `from langchain.agents import create_react_agent, AgentExecutor` |
| `ToolRegistry.ts` (custom tools) | `agent_engine.py` | `from langchain_community.tools.shell.tool import ShellTool` etc. |
| `BuiltinTools.ts` | `agent_engine.py` (BUILTIN_TOOL_PROMPTS) | Simple LLM prompt calls |
| `CustomToolManager.ts` | `custom_tool_manager.py` | `import yaml` + `from watchfiles import watch` |
| Session management | `agent_engine.py` | `from langchain.memory import ConversationBufferWindowMemory` |
| OrchestrationHelpers.ts | LangChain's AgentExecutor | `max_iterations=25, handle_parsing_errors=True` |
| SafetyLayer.ts | LangChain's AgentExecutor | Built-in iteration + error handling |

## Install and run

```bash
# 1. Create virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
# Edit .env — add your API keys
# Optional but recommended for web search quality:
# set TAVILY_API_KEY=tvly-... (free tier: 1000 searches/month)

# 4. Start the server
python server.py
# OR with hot-reload:
uvicorn server:app --reload --port 3579
```

## API endpoints (identical to Node.js version)

| Method | URL | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/api/providers` | List all LLM providers + status |
| POST | `/api/providers/config` | Update API keys / URLs |
| POST | `/api/providers/custom` | Add custom LLM endpoint |
| GET | `/api/tools` | List all tools (builtin + custom) |
| POST | `/api/execute` | Run a tool or chat |
| POST | `/api/chat` | Simple chat |
| POST | `/api/chat/stream` | Streaming chat (SSE) |
| POST | `/api/agent-chat` | Agentic chat with tools |
| GET | `/api/custom-tools` | List custom tools |
| POST | `/api/custom-tools` | Save custom tool |
| DELETE | `/api/custom-tools/{name}` | Delete custom tool |
| DELETE | `/api/session/{id}` | Clear session memory |
| POST | `/api/files/context` | Get multi-file content |

## Custom tools

Drop a `.yaml` file into `./custom_tools/` — the server hot-reloads it automatically:

```yaml
name: my_tool
displayName: My Tool
description: What it does
systemPrompt: You are an expert in...
promptTemplate: |
  Analyze this {{ctx.language}} code:
  {{args.code}}
```

## VS Code extension

The extension connects to `http://localhost:3579` (same as before).
Change `openclaw.backendUrl` in VS Code settings if you use a different port.
