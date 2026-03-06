# OpenClaw — Changes Log

## Session: 2026-03-05

### 📁 Project Structure (committed)

| Action | Item | Reason |
|---|---|---|
| **Moved → `frontend/`** | `package.json` | Must be inside `frontend/` for VS Code extension to compile and F5 launch |
| **Moved → `frontend/`** | `package-lock.json` | Follows `package.json` |
| **Moved → `frontend/`** | `tsconfig.json` | Must be co-located with `package.json` |
| **Moved → `frontend/`** | `.gitignore` | Scoped to frontend build artifacts |
| **Moved → `frontend/`** | `node_modules/` | Follows `package.json` |
| **Deleted** | `.vscode-test.mjs` | `yo code` scaffold — unused |
| **Deleted** | `eslint.config.mjs` | `yo code` scaffold — unused |
| **Deleted** | `vsc-extension-quickstart.md` | `yo code` scaffold — unused |

---

### 📝 Backend Changes (uncommitted)

#### `backend/.env` — **Created**
- Copied from `.env.example`
- `DEFAULT_PROVIDER=gemini`
- `GEMINI_API_KEY` set
- `OPENAI_API_KEY` commented out

#### `backend/agent_engine.py` — **Rewritten**

> Migrated from deprecated `langchain.agents` to `langgraph.prebuilt` API (langchain v1.2.x+).

| What changed | Old | New |
|---|---|---|
| Agent builder | `from langchain.agents import create_react_agent, AgentExecutor` | `from langgraph.prebuilt import create_react_agent` |
| Session memory | `ConversationBufferWindowMemory` (k=20) | `MemorySaver` checkpointer (keyed by `thread_id`) |
| Streaming | Thread pool + `asyncio.Queue` + `StepCallbackHandler` | Native `astream_events()` async generator |
| System prompt | ReAct template with `{tools}`, `{tool_names}`, `{agent_scratchpad}` | Plain string (LangGraph handles tool injection) |
| `SafeShellTool.BLOCKED_PATTERNS` | No annotation | `ClassVar[list[str]]` (Pydantic v2 fix) |

**Preserved unchanged:** All 17 agent tools, all 10 builtin LLM tool prompts, `run_builtin_tool()` function.

#### `backend/custom_tool_manager.py` — **1-line fix**

```diff
-from langchain.tools import StructuredTool
+from langchain_core.tools import StructuredTool
```

Import moved in langchain v1.2.x.

#### `frontend/tsconfig.json` — **1-line fix**

```diff
-"rootDir": "frontend/src",
+"rootDir": "src",
```

Path updated because `tsconfig.json` moved from root into `frontend/`.

---

### ✅ Frontend Source — Zero Changes

No TypeScript files modified: `extension.ts`, `chatViewProvider.ts`, `backendClient.ts`, `toolsProvider.ts`, `contextManager.ts`, `chatHtml.ts`, `utils.ts`.

---

### 🛠 Environment Setup

- Created Python venv at `backend/venv/`
- Installed all dependencies from `requirements.txt` + `langgraph`
- Backend health check verified: `GET /health → 200 OK`
- Frontend compiled: `npm run compile → 0 errors`
