# Navyug AI — AI Developer Assistant for VS Code
### Complete Project Documentation · v4.0

> **VS Code Extension + Python FastAPI Backend**  
> TypeScript · Python · LangGraph · LangChain · LiteLLM · OpenAI / Gemini / Ollama / vLLM

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Repository Structure](#2-repository-structure)
3. [Backend — Python FastAPI Server](#3-backend--python-fastapi-server)
4. [Frontend — VS Code Extension](#4-frontend--vs-code-extension-typescript)
5. [End-to-End Data Flow](#5-end-to-end-data-flow)
6. [Configuration](#6-configuration)
7. [Setup & Running the Project](#7-setup--running-the-project)
8. [Bug Fix History (v1 → v3)](#8-bug-fix-history-v1--v3)
9. [VS Code Commands & Menus](#9-vs-code-commands--menus)
10. [Security Considerations](#10-security-considerations)
11. [Adding Custom Tools](#11-adding-custom-tools)
12. [Extending the Project](#12-extending-the-project)
13. [Dependency Reference](#13-dependency-reference)

---

## 1. Project Overview

**Navyug AI** is a fully local, self-hosted AI coding assistant that runs as a VS Code extension. It provides a GitHub Copilot-style sidebar panel connected to a Python backend that routes requests to any LLM — cloud (OpenAI, Gemini) or local (Ollama, vLLM). The developer never sends code to a third-party SaaS product; everything flows through your own backend server.

### 1.1 Purpose & Goals

| Goal | Description |
|---|---|
| **AI Chat Panel** | Persistent sidebar chat, aware of the file and code you have open |
| **Code Tools** | 10 built-in one-click actions: generate tests, review code, find bugs, explain, refactor, generate docs, security audit, performance optimisation, complexity analysis, translate code |
| **Custom Tools** | Drop a YAML file into a folder; it hot-reloads as a new tool automatically |
| **Multi-LLM routing** | Switch provider and model from a dropdown in the sidebar |
| **Agent mode** | The backend runs a ReAct agent with file system, git, shell, linting, and test runner tools (21 tools total) |

### 1.2 High-Level Architecture

The project has two independent layers that communicate over HTTP on `localhost:3579`:

| Component | Role |
|---|---|
| VS Code Extension (TypeScript) | Sidebar webview UI + command palette commands |
| Python Backend (FastAPI) | LLM routing, agent orchestration, tool execution |
| Communication protocol | REST (JSON) + SSE streaming on `localhost:3579` |
| LLM providers | OpenAI, Google Gemini, Ollama, vLLM, or any OpenAI-compatible URL |
| Agent framework | LangGraph ReAct agent (via `langgraph.prebuilt`) with 21 tools |
| Custom tools | YAML files hot-loaded from `./custom_tools/` |

**Data flow:**  
User types in sidebar → Extension posts to `/api/chat/stream` → Backend injects file context → LangChain agent decides which tools to call → SSE chunks stream back → UI renders in real time.

---

## 2. Repository Structure

The project root contains two completely independent sub-projects:

### 2.1 Top-level Layout

```
openclaw-extension/
├── backend/          # Python FastAPI server — start this first
├── frontend/         # VS Code extension (TypeScript) — open in VS Code and press F5
│   ├── .vscode/      # launch.json + tasks.json for F5 debug
│   ├── media/        # SVG icon for Activity Bar
│   ├── src/          # TypeScript source
│   ├── out/          # Compiled JS (generated)
│   ├── package.json  # Extension manifest (must be here, not at root)
│   └── tsconfig.json # TypeScript config
└── START_HERE.md     # Quick-start guide
```

### 2.2 Backend File Inventory

| File | Purpose | Size |
|---|---|---|
| `server.py` | FastAPI application entry point, all HTTP endpoints | ~560 lines |
| `agent_engine.py` | LangGraph ReAct agent, all tool definitions, streaming logic | ~850 lines |
| `llm_router.py` | LLM provider registry, `build_llm()` factory, health probing | ~160 lines |
| `custom_tool_manager.py` | YAML tool loader, hot-reload watcher, LangChain tool builder | ~140 lines |
| `requirements.txt` | Python package list (FastAPI, LangChain, LiteLLM, etc.) | — |
| `.env.example` | Template for API keys and config variables | — |
| `custom_tools/` | Drop `.yaml` files here to add new tools at runtime | directory |

### 2.3 Frontend File Inventory

| File | Purpose | Size |
|---|---|---|
| `src/extension.ts` | Extension entry point, registers all commands and the sidebar provider | ~80 lines |
| `src/chatViewProvider.ts` | WebviewViewProvider — owns the sidebar panel lifecycle | ~270 lines |
| `src/chatHtml.ts` | Returns the full single-file HTML/CSS/JS string for the webview | ~900 lines |
| `src/backendClient.ts` | Axios HTTP client — all backend API calls in one place | ~215 lines |
| `src/toolsProvider.ts` | Right-click tool commands, QuickPick picker | ~145 lines |
| `src/contextManager.ts` | Reads active editor state and builds FileContext for each request | ~175 lines |
| `src/utils.ts` | `generateSessionId()` utility function | ~5 lines |
| `package.json` | Extension manifest: commands, menus, config schema, dependencies | ~120 lines |
| `tsconfig.json` | TypeScript compiler config | ~10 lines |
| `.vscode/launch.json` | F5 debug config — launches Extension Development Host | — |
| `.vscode/tasks.json` | npm compile task wired to F5 | — |

---

## 3. Backend — Python FastAPI Server

The backend replaces what was originally a Node.js/Express server. It runs on port `3579` and exposes a REST + SSE API. The VS Code extension talks to this server identically regardless of which LLM is selected.

### 3.1 server.py — API Endpoints

Every endpoint mirrors the shape of the original Node.js version so the frontend needs no changes when the backend is swapped:

| Endpoint | Type | Description |
|---|---|---|
| `GET  /health` | Health check | Returns `{status:"ok"}`. Used by the extension on startup to update the status bar icon. |
| `GET  /api/providers` | Provider list | Probes all registered LLM providers. Returns name, type (cloud/local), and available models. |
| `POST /api/providers/config` | Config update | Update an existing provider's API key or base URL at runtime. |
| `POST /api/providers/custom` | Custom provider | Register a new OpenAI-compatible endpoint (e.g. LM Studio, Llama.cpp). |
| `GET  /api/tools` | Tool catalog | Returns all builtin + custom tool definitions. Used by the Tools tab in the sidebar. |
| `GET  /api/tools/catalog` | Tool catalog | Returns builtin tool names and first 80 chars of their prompts for inspection. |
| `POST /api/execute` | Tool execution | Unified dispatcher: runs a named builtin tool, custom YAML tool, or falls back to chat. |
| `POST /api/chat` | Chat (sync) | Non-streaming chat. Returns the full response as one JSON object. |
| `POST /api/chat/stream` | Chat (stream) | Streaming chat over SSE. Emits `step` / `chunk` / `done` / `error` events. |
| `POST /api/agent-chat` | Agent chat | Alias for `/api/chat` but always uses the agent loop. Same payload shape. |
| `GET  /api/custom-tools` | Custom tools | List all loaded custom YAML tools and their storage directory. |
| `POST /api/custom-tools` | Create tool | Save a new tool definition as a YAML file (triggers hot-reload). |
| `DELETE /api/custom-tools/{name}` | Delete tool | Delete a custom tool YAML file and evict it from memory. |
| `DELETE /api/session/{id}` | Session clear | Clear conversation memory for a session. Called on "New Session" button. |
| `POST /api/files/context` | File reader | Read file contents from the workspace for multi-file context injection. |
| `POST /api/admin/permissions/{id}` | Permissions | Set permission level for a session (standard/elevated). Reserved for future sandboxing. |
| `POST /api/tools/generate-tests` | Tool shortcut | Shortcut — calls `run_builtin_tool("generate_tests")` directly. |
| `POST /api/tools/review-code` | Tool shortcut | Shortcut — calls `run_builtin_tool("review_code")` directly. |
| `POST /api/tools/find-bugs` | Tool shortcut | Shortcut — calls `run_builtin_tool("find_bugs")` directly. |
| `POST /api/tools/explain-code` | Tool shortcut | Shortcut — calls `run_builtin_tool("explain_code")` directly. |
| `POST /api/tools/security-analysis` | Tool shortcut | Shortcut — calls `run_builtin_tool("security_analysis")` directly. |

---

### 3.2 agent_engine.py — The AI Brain

This file is the core of Navyug AI. It uses `langgraph.prebuilt.create_react_agent` to build a ReAct agent with all tool definitions. Session memory is handled by `MemorySaver` checkpointer, and streaming uses LangGraph's native `astream_events()` API. It also integrates specialized tools and agents from the **OpenClaw Ecosystem** via a custom bridge.

#### 3.2.1 Built-in Agent Tools (22 tools)

These tools are available to the LangChain agent on every request. The agent autonomously decides when to call them:

| Tool Name | What It Does | Source |
|---|---|---|
| `ReadFileTool` | Read any file in the workspace root directory | LangChain community |
| `WriteFileTool` | Write or overwrite a file in the workspace | LangChain community |
| `ListDirectoryTool` | List files and directories | LangChain community |
| `CopyFileTool` | Copy a file to a new path | LangChain community |
| `MoveFileTool` | Move or rename a file | LangChain community |
| `DeleteFileTool` | Delete a file from the workspace | LangChain community |
| `SafeShellTool` | Run shell commands. Blocks: `rm -rf /`, `sudo dd`, fork bomb, `curl\|bash`, etc. | Custom (extends ShellTool) |
| `PythonREPLTool` | Execute arbitrary Python code and return stdout | LangChain experimental |
| `git_status` | Show current branch + staged/unstaged changes summary | Custom `@lc_tool` |
| `git_diff` | Show diff of current or staged changes (first 300 lines) | Custom `@lc_tool` |
| `git_log` | Compact graph of last N commits | Custom `@lc_tool` |
| `git_suggest_commit` | Analyse staged diff and return it for commit message generation | Custom `@lc_tool` |
| `run_linter` | Auto-detect and run pylint, eslint, tsc, or mypy on a file | Custom `@lc_tool` |
| `run_tests` | Auto-detect and run pytest, jest, or vitest. Supports `file_path` arg | Custom `@lc_tool` |
| `search_code` | grep across all project files (py/ts/js/go/rs/css/html/json/md) | Custom `@lc_tool` |
| `find_symbol_definition` | Locate where a function, class, or variable is defined | Custom `@lc_tool` |
| `find_file` | Find files by name or glob pattern (e.g. 'App.css', '*.test.js') | Custom `@lc_tool` |
| `get_project_summary` | Identify project tech stack and key indicators (metadata) | Custom `@lc_tool` |
| `project_overview` | Generate a tree-like overview of the project structure | Custom `@lc_tool` |
| `apply_patch` | Apply a unified diff patch to a file safely using a temp file | Custom `@lc_tool` |
| `web_search` | Search the web via DuckDuckGo (free, no API key needed) | Custom `@lc_tool` |
| `openclaw_proactive_agent` | specialized OpenClaw Proactive Agent for high-level, complex goals | OpenClaw Bridge Tool |

#### 3.2.2 Built-in LLM Tools (10 prompt templates)

These are direct LLM calls — no agent loop. Each is a formatted prompt that the LLM answers directly. Invoked via `/api/execute` or the right-click menu:

| Tool Name | Description |
|---|---|
| `generate_tests` | Generate comprehensive unit tests with edge cases for selected code |
| `review_code` | Review for bugs, style issues, and best practices — actionable feedback |
| `find_bugs` | Identify all bugs and logic errors with line numbers and explanations |
| `explain_code` | Plain-language explanation of what the code does and how it works |
| `refactor_code` | Improve readability and maintainability — shows improved version with explanations |
| `generate_docs` | Write JSDoc / docstrings, parameter descriptions, and usage examples |
| `security_analysis` | OWASP vulnerability scan: injection, auth issues, data exposure |
| `optimize_performance` | Identify bottlenecks and suggest optimisations with code examples |
| `analyze_complexity` | Cyclomatic + Big-O complexity analysis with simplification suggestions |
| `translate_code` | Translate to any target language while preserving all logic |

#### 3.2.3 Session Memory

| Property | Detail |
|---|---|
| **Storage** | `MemorySaver` checkpointer from `langgraph.checkpoint.memory`. Conversation history stored by `thread_id` (= `session_id`). |
| **TTL** | Sessions expire after 1 hour of inactivity. Expiry is checked on every new request via `_evict_expired_sessions()`. Prevents memory leaks. |
| **Clear** | `DELETE /api/session/{id}` removes the session's checkpointer storage immediately. The frontend calls this when the user presses the New Session (+) button. |

#### 3.2.4 Streaming Architecture

Streaming uses LangGraph's native `astream_events()` API — no thread pool, no `asyncio.Queue`, no callback handler needed.

```
run_streaming() called
    │
    ├─ build_agent() → create_react_agent(llm, tools, prompt, checkpointer)
    ├─ agent.astream_events({messages: [user_msg]}, config={thread_id})
    │
    │   [Async event stream]
    │   ├─ on_tool_start  → yield step event {type:"tool_call", toolName}
    │   ├─ on_tool_end    → yield step event {type:"tool_result", result}
    │   └─ on_chat_model_stream → yield chunk event {content} (from agent node only)
    │
    └─ Yields done event with durationMs + totalToolCalls
```

---

### 3.3 llm_router.py — Provider Registry

`build_llm(provider, model_id)` is the single factory function that constructs LangChain chat models. It is the **only** place LLM objects are ever created.

| Provider key | Implementation | Notes |
|---|---|---|
| `openai` | `ChatOpenAI` | Uses `OPENAI_API_KEY`. Default model: `gpt-4o`. Models: gpt-4o, gpt-4o-mini, gpt-4-turbo, o3-mini |
| `gemini` | `ChatGoogleGenerativeAI` | Uses `GEMINI_API_KEY`. Default model: `gemini-2.0-flash` |
| `ollama` | `ChatOllama` | No API key needed. Connects to `OLLAMA_URL` (default `localhost:11434`). Dynamic model list probed at startup |
| `vllm` | `ChatOpenAI` → `VLLM_URL/v1` | Treats vLLM as OpenAI-compatible endpoint. `api_key="none"` |
| `custom` | `ChatOpenAI` → custom `base_url` | Any registered provider with a `base_url`. Covers LM Studio, Llama.cpp server, etc. |
| fallback | `ChatLiteLLM` | Handles any other provider string via LiteLLM unified routing |

---

### 3.4 custom_tool_manager.py — Hot-Reload YAML Tools

`CustomToolManager` watches the `custom_tools/` directory using the `watchfiles` library. When a `.yaml` or `.json` file is added, changed, or deleted, it automatically reloads without restarting the server.

| Method | What It Does |
|---|---|
| `get_all()` | Returns list of all enabled tools as dicts for the `/api/tools` endpoint |
| `get(name)` | Look up one tool definition by name |
| `save(tool_data)` | Write a new `.yaml` file and immediately load it into memory |
| `delete(name)` | Delete the `.yaml` file and evict from memory |
| `build_langchain_tool(def, ...)` | Convert a YAML `CustomToolDef` into a callable LangChain `StructuredTool` |
| `watch_for_changes(callback)` | Starts a daemon thread watching the directory via `watchfiles` |

#### 3.4.1 Custom Tool YAML Schema

| Field | Required | Meaning |
|---|---|---|
| `name` | ✅ | Machine-readable identifier (no spaces). Used as the tool slug in API calls |
| `displayName` | — | Human-readable label shown in the Tools tab UI |
| `description` | — | One-line description shown below the name in the UI |
| `category` | — | Optional grouping label (e.g. `"documentation"`, `"testing"`) |
| `systemPrompt` | — | System-level context injected before the user prompt |
| `promptTemplate` | ✅ | The actual prompt. Use `{{args.code}}`, `{{ctx.language}}`, `{{ctx.filePath}}` |
| `enabled` | — | `true`/`false` — disabled tools are silently skipped on load. Default: `true` |
| `author` | — | Optional author name for display in the UI |
| `version` | — | Optional version string for display |
| `parameters` | — | JSON Schema definition of inputs (informational only, not yet validated) |

---

## 4. Frontend — VS Code Extension (TypeScript)

The frontend is a standard VS Code extension that registers a sidebar `WebviewView`, a set of commands, and a right-click context menu. It has zero runtime dependencies beyond `axios`.

### 4.1 extension.ts — Entry Point

This file runs when VS Code activates the extension (`onStartupFinished`). It:

1. Creates a `BackendClient` pointing at the configured backend URL (default `http://localhost:3579`)
2. Creates `Navyug AI ChatViewProvider` and `ToolsProvider`
3. Calls `chatProvider.setToolsProvider(toolsProvider)` to wire the two together (avoids circular dependency)
4. Registers the sidebar `WebviewViewProvider` for the `"openclawChatView"` view ID
5. Registers all 10 tool commands + 3 chat commands + 1 tool-picker command
6. Creates a status bar item (`🦾 Navyug AI`) that pings `/health` on startup
7. Shows a warning notification if the backend cannot be reached

---

### 4.2 chatViewProvider.ts — Sidebar Panel Lifecycle

This is the most complex file in the frontend. It implements the VS Code `WebviewViewProvider` interface and owns the entire chat session.

#### 4.2.1 Key Responsibilities

| Method | Responsibility |
|---|---|
| `resolveWebviewView()` | Called once when the sidebar becomes visible. Sets up the webview HTML, registers the message listener, and starts listening for editor/selection changes to keep the context pill live. |
| `_handleUserMessage()` | Reads provider/model from config, captures file context, then calls either `_streamResponse()` or `_simpleResponse()` based on the `streamResponses` setting. |
| `_streamResponse()` | Creates an `AbortController`, iterates the `chatStream()` async generator, and dispatches `chunk`/`toolCall`/`done` events to the webview. |
| `_sendProviders()` | Calls `backendClient.getProviders()` and posts the result to the webview so the dropdown stays in sync. |
| `_sendTools()` | Calls `backendClient.getTools()` and posts `{builtin, custom}` to the webview for the Tools tab. |
| `clearChat()` | Public — called by command. Posts `clearChat` to webview. |
| `newSession()` | Public — saves old session ID, generates new one, clears old session on backend, posts `newSession` to webview. |
| `pushUserMessage()` | Public — called by `ToolsProvider` to inject a user-triggered tool message into chat. |
| `pushFullResponse()` | Public — called by `ToolsProvider` with the completed tool result. |
| `pushError()` | Public — called by `ToolsProvider` if a tool execution fails. |

#### 4.2.2 Message Protocol (Extension ↔ Webview)

All communication between the TypeScript extension and the HTML webview uses VS Code's `postMessage` API:

| Message type | Direction | Payload / Purpose |
|---|---|---|
| `sendMessage` | Webview → Extension | User pressed Send. Carries `text`, `provider`, `model`, `contextEnabled` |
| `getProviders` | Webview → Extension | Request provider list on load or tab focus |
| `getTools` | Webview → Extension | User switched to Tools tab |
| `runCustomTool` | Webview → Extension | User clicked ▶ Run on a tool card. Carries `toolName` |
| `clearChat` | Webview → Extension | Webview-side clear chat button |
| `newSession` | Webview → Extension | Webview-side new session button |
| `cancelStream` | Webview → Extension | User pressed the ⏹ stop button |
| `providers` | Extension → Webview | Updated provider list for the dropdown |
| `tools` | Extension → Webview | Builtin + custom tool list for the Tools tab |
| `startAssistant` | Extension → Webview | Begin typing indicator |
| `chunk` | Extension → Webview | A piece of streaming text content |
| `done` | Extension → Webview | Stream complete. Carries `durationMs`, `totalToolCalls` |
| `fullResponse` | Extension → Webview | Non-streaming complete response |
| `toolCall` | Extension → Webview | An agent tool was invoked (shows progress badge) |
| `error` | Extension → Webview | Backend or network error to display |
| `cancelled` | Extension → Webview | Stream was aborted by user |
| `contextAttached` | Extension → Webview | Active file context summary for the context pill |
| `clearChat` | Extension → Webview | Clear all messages from UI |
| `newSession` | Extension → Webview | Clear messages and reset session ID |
| `pushUserMessage` | Extension → Webview | Inject a user message from a right-click tool run |

---

### 4.3 backendClient.ts — HTTP Client

Single source of truth for all HTTP calls. Uses `axios` for REST calls and native `fetch` for the SSE stream (`axios` does not support async generators).

| Method | Description |
|---|---|
| `healthCheck()` | `GET /health` — returns `true`/`false`. Times out after 3 seconds. |
| `executeTool(req)` | `POST /api/execute` — dispatches a named tool or chat request |
| `chat(...)` | `POST /api/chat` — non-streaming chat. Returns `ChatResponse` |
| `chatStream(...)` | `POST /api/chat/stream` — returns `AsyncGenerator<StreamEvent>` over SSE. Accepts `AbortSignal`. |
| `getProviders()` | `GET /api/providers` — returns `Provider[]` with models and availability |
| `getTools()` | `GET /api/tools` — returns `{builtin, custom}` tool arrays |
| `clearSession(sessionId)` | `DELETE /api/session/{id}` — frees backend memory for a session |

---

### 4.4 toolsProvider.ts — Right-Click Tool Commands

`ToolsProvider` bridges VS Code editor commands and the backend. When a user selects code and right-clicks → **Navyug AI** → picks a tool, this class:

1. Reads the selection (or full file if nothing selected) from the active editor
2. For `translate_code`: shows an input box asking for the target language
3. Calls `pushUserMessage()` on the chat panel so the user sees what triggered
4. POSTs to `/api/execute` with `taskType="tool"`, the selected code, and language
5. Calls `pushFullResponse()` or `pushError()` depending on the result
6. Focuses the chat panel so the result is immediately visible

**`showToolPicker()`** shows a VS Code QuickPick menu with all 10 built-in tools, their icons and descriptions. Works from the command palette without needing a selection.

---

### 4.5 contextManager.ts — File Context Injection

Every chat message automatically includes context about the file the developer has open. `ContextManager.capture()` reads the active editor and returns a `FileContext` object plus a summary string for the UI pill.

#### 4.5.1 Capture Priority

| Priority | Mode | Condition | What's sent |
|---|---|---|---|
| 1 | `selection` | User has text selected | Only the selected lines |
| 2 | `full_file` | File is ≤ 500 lines | Entire file contents |
| 3 | `visible_range` | File is > 500 lines | Visible viewport ± 30-line buffer |

**Hard truncation:** Content is always capped at **40,000 characters** regardless of mode, with a `[truncated]` marker appended.

#### 4.5.2 Live Context Pill

The context pill in the sidebar updates in real time — not just when a message is sent. `chatViewProvider` subscribes to `onDidChangeActiveTextEditor` and `onDidChangeTextEditorSelection` and calls `_sendCurrentFileContext()` on every change, so the pill always shows exactly what will be sent with the next message.

---

### 4.6 chatHtml.ts — Webview UI

A single TypeScript function `getChatHtml()` returns a complete ~900-line HTML string. There are no external CSS files, no external JS scripts, and no CDN imports — everything is inline to comply with VS Code's Content Security Policy.

#### 4.6.1 UI Structure

| Section | Content |
|---|---|
| Header bar | Navyug AI logo and title |
| Provider row | Provider dropdown + Model dropdown — populated from `/api/providers` |
| Context bar | Real-time file/selection pill + toggle checkbox to enable/disable context injection |
| Tab strip | 💬 Chat tab \| 🔧 Tools tab |
| Messages area | Chat bubbles with markdown rendering, code blocks, tool call indicators, typing animation |
| Tools panel | Two sections: **Custom Tools** (green badge) + **Built-in Tools** (grey badge). Each has a ▶ Run button |
| Input area | Auto-growing textarea, Send button, Cancel (⏹) button, hint text |

#### 4.6.2 Markdown Rendering

The UI renders markdown in assistant responses using a lightweight inline renderer. Supported features: fenced code blocks with language label, inline code, bold, italics, headers (h1–h4), unordered and ordered lists, horizontal rules, and blockquotes.

#### 4.6.3 Security — Content Security Policy

The HTML includes a strict CSP meta tag generated with a per-load nonce:

```
default-src 'none'; style-src 'nonce-{nonce}'; script-src 'nonce-{nonce}'
```

This means no inline event handlers, no external resources, and no eval(). All styles and scripts must carry the nonce attribute. VS Code's webview sandbox is respected.

---

## 5. End-to-End Data Flow

### 5.1 Chat Message (Streaming)

| Step | Action | Location |
|---|---|---|
| 1 | User types a message and presses Enter in the sidebar | `chatHtml.ts` — `sendMessage()` |
| 2 | Webview posts `{type:"sendMessage", text, provider, model, contextEnabled}` | `postMessage` API |
| 3 | `chatViewProvider` receives message, calls `ContextManager.capture()` | `chatViewProvider.ts` |
| 4 | `FileContext` built from active editor (selection / full file / visible range) | `contextManager.ts` |
| 5 | `chatStream()` called with message + context + `AbortSignal` | `backendClient.ts` |
| 6 | `POST /api/chat/stream` with full JSON payload including context dict | HTTP fetch + SSE |
| 7 | `server.py` calls `inject_file_context()` to prepend code context to the message | `server.py` |
| 8 | `run_streaming()` builds LangGraph agent, uses `astream_events()` to fire tool + chunk events | `agent_engine.py` |
| 9 | SSE events yielded: `step` → `chunk` (×N) → `done` | `AsyncGenerator` |
| 10 | Extension receives each event and `postMessage`s `{type:"chunk"}` etc. to webview | `chatViewProvider.ts` |
| 11 | Webview appends text to the current assistant bubble in real time | `chatHtml.ts` |
| 12 | `done` event fires; `finalizeMessage()` renders metadata footer | `chatHtml.ts` |

### 5.2 Right-Click Tool (e.g. Generate Tests)

| Step | Action | Location |
|---|---|---|
| 1 | Developer selects code in editor, right-clicks → Navyug AI → Generate Tests | VS Code context menu |
| 2 | `openclaw.tool.generate_tests` command fires | `package.json` menus |
| 3 | `ToolsProvider.runFromEditor("generate_tests")` reads selection and `languageId` | `toolsProvider.ts` |
| 4 | `pushUserMessage()` injects a "🧪 Generate Tests on filename" bubble into chat | `chatViewProvider.ts` |
| 5 | `POST /api/execute {taskType:"tool", toolName:"generate_tests", toolArgs:{code, language}}` | `backendClient.ts` |
| 6 | `server.py` routes to `run_builtin_tool()` — direct LLM call with formatted prompt | `server.py` + `agent_engine.py` |
| 7 | LLM generates test cases and returns full text response | `llm_router.py` |
| 8 | `ToolResponse` returned: `{output, toolName, provider, model, durationMs, error}` | `server.py` |
| 9 | `pushFullResponse()` renders the result in the chat panel + focuses chat | `chatViewProvider.ts` |

### 5.3 Custom Tool Execution (Tools Tab)

| Step | Action | Location |
|---|---|---|
| 1 | User clicks Tools tab in sidebar | `chatHtml.ts` — `switchTab()` |
| 2 | Webview posts `{type:"getTools"}` | `postMessage` |
| 3 | Extension calls `backendClient.getTools()` → `GET /api/tools` | `chatViewProvider.ts` |
| 4 | Backend returns `{builtin:[...], custom:[...]}` from `BUILTIN_TOOL_PROMPTS` + YAML files | `server.py` |
| 5 | Webview calls `renderTools()` — builds tool cards with ▶ Run buttons | `chatHtml.ts` |
| 6 | User clicks ▶ Run on a custom tool card | `chatHtml.ts` |
| 7 | Webview posts `{type:"runCustomTool", toolName:"explain_for_junior"}` | `postMessage` |
| 8 | Extension calls `toolsProvider.runFromEditor(toolName)` — reads code from editor | `chatViewProvider.ts` |
| 9 | `POST /api/execute` — `server.py` routes to `custom_tool_manager.build_langchain_tool()` | `server.py` |
| 10 | `StructuredTool` runs: substitutes `{{args.code}}` and `{{ctx.language}}` in prompt template | `custom_tool_manager.py` |
| 11 | LLM called via `build_llm()`, result returned. Tab switches back to Chat. | `llm_router.py` |

---

## 6. Configuration

### 6.1 Backend — .env File

Copy `.env.example` to `.env` and fill in at least one API key before starting the server:

| Variable | Description |
|---|---|
| `PORT` | Port the FastAPI server listens on. Default: `3579`. Must match `openclaw.backendUrl` in VS Code. |
| `HOST` | Bind address. Default: `0.0.0.0`. Use `127.0.0.1` to restrict to localhost only. |
| `DEFAULT_PROVIDER` | Fallback LLM provider when none is specified in the request. Default: `openai`. |
| `OPENAI_API_KEY` | Your OpenAI API key. Required for the OpenAI provider. Format: `sk-...` |
| `GEMINI_API_KEY` | Your Google Gemini API key. Required for the Gemini provider. Format: `AIza...` |
| `OLLAMA_URL` | Base URL for Ollama. Default: `http://localhost:11434`. Only change if non-standard port. |
| `VLLM_URL` | Base URL for a running vLLM server. Uncomment to enable the vLLM provider. |
| `CUSTOM_TOOLS_DIR` | Directory to watch for custom YAML tool files. Default: `./custom_tools` |

### 6.2 Frontend — VS Code Settings

These settings appear in VS Code's settings UI under **"Navyug AI"** and can also be set in `.vscode/settings.json`:

| Setting | Type | Default | Description |
|---|---|---|---|
| `openclaw.backendUrl` | string | `"http://localhost:3579"` | URL of the Python backend. Change if running on a different port or host. |
| `openclaw.defaultProvider` | enum | `"openai"` | Default LLM provider. Options: `openai`, `gemini`, `ollama`, `vllm`. |
| `openclaw.defaultModel` | string | `""` | Default model name. Leave empty to use each provider's built-in default. |
| `openclaw.streamResponses` | boolean | `true` | Stream responses word-by-word (`true`) or wait for the full response (`false`). |

---

## 7. Setup & Running the Project

### 7.1 Prerequisites

- **Python 3.10+** (3.12 recommended — `asyncio.get_running_loop()` behaviour is correct from 3.10)
- **Node.js 18+** + npm (for TypeScript compilation)
- **VS Code 1.85+** (extension engine requirement set in `package.json`)
- **At least one of:** OpenAI API key, Gemini API key, or Ollama running locally

### 7.2 Step-by-Step Start

#### Step 1 — Start the Backend

```bash
cd backend

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate          # Mac/Linux
# venv\Scripts\activate           # Windows

# Install dependencies
pip install -r requirements.txt

# Create config file and set at least one API key
cp .env.example .env
# Edit .env → set OPENAI_API_KEY=sk-...  or  GEMINI_API_KEY=AIza...
# For local models: make sure Ollama is running (ollama pull llama3.2)

# Start the server
python server.py
```

You should see:
```
🦾 Navyug AI Python Backend running on http://localhost:3579
```

#### Step 2 — Run the Extension

```bash
cd frontend
npm install           # installs @types/vscode, axios — also clears the red underline error
npm run compile       # compiles TypeScript → out/ folder
```

Then in VS Code:

1. **File → Open Folder** → select the `frontend/` directory (or if your workspace is the parent folder, ensure `.vscode/launch.json` has `--extensionDevelopmentPath` pointing to `frontend/`)
2. Press **F5** → VS Code opens a new **Extension Development Host** window
3. In the new window, look for the **Navyug AI** icon in the Activity Bar (left sidebar)
4. Click it → the chat panel opens

#### Step 3 — Use It

- **Chat:** Type in the panel, press Enter
- **Tools on selected code:** Select code → right-click → **🦾 Navyug AI** → pick a tool
- **Tools tab:** Click the 🔧 Tools tab in the sidebar to browse and run all tools
- **Switch LLM:** Use the Provider/Model dropdowns at the top of the chat panel
- **New session:** Click the `+` icon in the panel title bar
- **Cancel stream:** Click the ⏹ button while a response is streaming

### 7.3 Troubleshooting

| Problem | Fix |
|---|---|
| "Cannot reach backend" warning | Run `python server.py` in the `backend/` directory first |
| No providers in dropdown | Backend is not running, or no API keys set in `.env` |
| Ollama shows ⚠ in dropdown | Run `ollama serve` and `ollama pull llama3.2` |
| Red underline on `import vscode` | Run `npm install` in `frontend/`. The `@types/vscode` package is missing |
| F5 does nothing useful | Confirm `.vscode/launch.json` exists with `"type": "extensionHost"` |
| Extension not in Activity Bar | Run `npm run compile` first so the `out/` folder exists |
| Tools right-click not appearing | Select some code first — the menu only shows when `editorHasSelection` is true |
| `translate_code` returns error | Fixed in v3. Ensure you are using the v3 codebase. |

---

## 8. Bug Fix History (v1 → v4)

All fixes are present in the v4 codebase.

| ID | Severity | Short Description | Detail |
|---|---|---|---|
| #1 | 🔴 CRITICAL | `translate_code` KeyError crash | The prompt template used `{target_language}` / `{source_language}` but the frontend sends `targetLanguage` / `language` (camelCase). Every Translate Code request threw `KeyError`. **Fix:** Renamed template placeholders to match what the frontend actually sends. |
| #2 | 🔴 HIGH | Custom tool response missing `durationMs` | `server.py` custom tool path returned `{output, toolName, provider, model, error}` — missing `durationMs`. Frontend showed "undefined ms". **Fix:** Added timing around execution and included `durationMs` in both success and error paths. |
| #3 | 🟠 HIGH | `AbortController` signal not passed to `fetch` | `AbortController` was created and `.abort()` was called on cancel, but `signal` was never passed to `fetch()`. The HTTP stream kept the server connection open indefinitely — a resource leak. **Fix:** Added `signal` parameter to `chatStream()` and passed `_streamAbortController.signal` into the fetch options. |
| #4 | 🟡 MEDIUM | `asyncio.get_event_loop()` deprecated | Used inside async functions in 3 places. Deprecated since Python 3.10, raises `DeprecationWarning`, can fail entirely in Python 3.12. **Fix:** Replaced all 3 instances with `asyncio.get_running_loop()`. |
| #5 | 🟡 MEDIUM | Pydantic v2 deprecated `class Config` | `CustomToolDef` used `class Config: populate_by_name = True` — deprecated in Pydantic v2. Flooded logs with warnings on every tool load. **Fix:** Replaced with `model_config = ConfigDict(populate_by_name=True)`. |
| #6 | 🔴 HIGH | `newSession()` cleared wrong session ID | Code did `this._sessionId = generateSessionId()` first, then `clearSession(this._sessionId)` — clearing the brand new (non-existent) ID. The old session's memory was never freed and accumulated until the 1-hour TTL. **Fix:** Saved `oldSessionId` before reassigning, then cleared the old one. |
| #7 | 🟠 MEDIUM | Unknown tool early return missing fields | `run_builtin_tool` returned `{output, error, durationMs:0}` for unknown tool names — missing `provider`, `model`, `toolName`, `totalToolCalls`. Frontend showed `undefined` in chat bubble metadata. **Fix:** Added all missing fields to the early return dict. |
| #8 | ℹ️ INFO | Deprecated LangChain import path | `from langchain.tools import tool as lc_tool` was the old import path. **Fix:** Changed to `from langchain_core.tools import tool as lc_tool`. |
| #9 | 🟠 GAP | Custom tools never shown in UI | `backendClient.getTools()` was defined but never called anywhere. Custom YAML tools were completely invisible to users — no way to see or run them. **Fix:** Added a full **Tools tab** to the sidebar with builtin + custom tool listing, badges, and ▶ Run buttons for each tool. |
| #10 | 🔴 CRITICAL | LangChain v1.2.x broke agent imports | `from langchain.agents import create_react_agent, AgentExecutor` removed in langchain v1.2.x. **Fix:** Migrated to `from langgraph.prebuilt import create_react_agent` + `MemorySaver` checkpointer. Rewrote `agent_engine.py` streaming to use `astream_events()`. |
| #11 | 🟡 MEDIUM | `SafeShellTool.BLOCKED_PATTERNS` Pydantic v2 error | Class attribute without type annotation caused `PydanticUserError: model-field-missing-annotation`. **Fix:** Added `ClassVar[list[str]]` annotation. |
| #12 | 🟡 MEDIUM | `StructuredTool` import path moved | `from langchain.tools import StructuredTool` removed. **Fix:** Changed to `from langchain_core.tools import StructuredTool` in `custom_tool_manager.py`. |
| #13 | 🟡 MEDIUM | Activity Bar icon used codicon instead of file path | `package.json` used `$(hubot)` codicon for `viewsContainers.activitybar.icon` — requires file path. **Fix:** Created `media/openclaw-icon.svg` and updated manifest. |
| #14 | 🔴 HIGH | Path Resolution (WinError 3) | Tools were resolving paths relative to backend CWD instead of the active workspace. **Fix:** Implemented `_current_workspace` tracking in `agent_engine.py`. |
| #15 | 🔴 HIGH | Tool Error Handling | LangGraph agent crashed on tool failures, corrupting state. **Fix:** Enabled `handle_tool_errors=True` in `create_react_agent`. |
| #16 | ℹ️ INFO | Rebranding to Navyug AI | Full migration from OpenClaw to Navyug AI across UI, backend, and documentation. |

---

## 9. VS Code Commands & Menus

### 9.1 Command Palette Commands

| Command ID | Description |
|---|---|
| `openclaw.openChat` | Focus and open the Navyug AI chat panel in the sidebar |
| `openclaw.clearChat` | Clear all messages from the chat panel (keeps session alive) |
| `openclaw.newSession` | Start a fresh conversation session (clears backend memory) |
| `openclaw.runTool` | Open QuickPick tool selector — shows all 10 built-in tools |
| `openclaw.tool.generate_tests` | Run Generate Tests on selected code or full active file |
| `openclaw.tool.review_code` | Run Code Review on selected code or full active file |
| `openclaw.tool.find_bugs` | Run Find Bugs on selected code or full active file |
| `openclaw.tool.explain_code` | Run Explain Code on selected code or full active file |
| `openclaw.tool.refactor_code` | Run Refactor Code on selected code or full active file |
| `openclaw.tool.generate_docs` | Run Generate Docs on selected code or full active file |
| `openclaw.tool.security_analysis` | Run Security Analysis on selected code or full active file |
| `openclaw.tool.optimize_performance` | Run Performance Optimisation on selected code or full active file |
| `openclaw.tool.analyze_complexity` | Run Complexity Analysis on selected code or full active file |
| `openclaw.tool.translate_code` | Translate selected code — prompts for target language |

### 9.2 Right-Click Context Menu

All 10 tool commands appear under a submenu called **🦾 Navyug AI** in the editor context menu. The submenu is only shown when `editorHasSelection` is true (user has selected code). Tools are grouped into three sub-groups:

| Group | Tools |
|---|---|
| `1_analyze` | Generate Tests, Review Code, Find Bugs, Explain Code |
| `2_transform` | Refactor Code, Generate Docs, Translate Code |
| `3_audit` | Security Analysis, Optimise Performance, Analyse Complexity |

---

## 10. Security Considerations

### 10.1 SafeShellTool Blocklist

The agent's shell access is wrapped in `SafeShellTool` which checks all commands against a blocklist before execution:

| Blocked pattern | Risk prevented |
|---|---|
| `rm -rf /`, `rm -rf ~` | Recursive filesystem deletion |
| `sudo rm`, `sudo dd` | Privileged destructive operations |
| `dd if=/dev/zero`, `dd if=/dev/random` | Disk write attacks |
| `> /dev/sda`, `mkfs`, `fdisk` | Partition and format operations |
| `shutdown`, `reboot`, `halt`, `poweroff` | System state changes |
| `chmod 777 /`, `chown -R root` | Mass permission changes |
| `:(){:\|:&};:` | Fork bomb |
| `curl \| bash`, `wget \| bash`, `curl \| sh`, `wget \| sh` | Remote code execution via pipe |

### 10.2 Content Security Policy (Webview)

The webview uses a strict CSP with a per-request nonce. It blocks: all external resource loads, all inline scripts without the nonce, `eval()`, and all cross-origin requests. The webview communicates with the extension only through the `postMessage` API — it cannot directly call any VS Code API or access the file system.

### 10.3 CORS

The FastAPI backend has `allow_origins=["*"]` for local development convenience. In a team/shared server deployment this should be restricted to the VS Code webview origin only.

### 10.4 API Key Handling

API keys are stored only in the `.env` file on the machine running the backend server. They are never sent to the frontend, never stored in VS Code settings, and never included in any log output. The `.env` file should be added to `.gitignore` if the project is version-controlled.

---

## 11. Adding Custom Tools

Adding a custom tool requires no code changes and no server restart. Simply create a YAML file in `backend/custom_tools/` and it appears in the Tools tab within seconds.

### 11.1 Example: Code Smell Detector

Create the file `backend/custom_tools/detect_smells.yaml`:

```yaml
name: detect_smells
displayName: Detect Code Smells
description: Identify design smells and anti-patterns in code
category: analysis
enabled: true
author: Your Name
version: 1.0.0

systemPrompt: |
  You are an expert software architect specialising in clean code principles.

promptTemplate: |
  Identify all code smells in this {{ctx.language}} code.
  Reference well-known smells: long methods, god classes, feature envy,
  primitive obsession, data clumps, shotgun surgery, etc.

  For each smell found: name it, quote the relevant lines, and explain the fix.

  File: {{ctx.filePath}}

  ```{{ctx.language}}
  {{args.code}}
  ```

parameters:
  type: object
  properties:
    code:
      type: string
      description: The code to analyse
  required:
    - code
```

The tool appears in the sidebar Tools tab with a green "custom" badge. Clicking ▶ Run reads the selected code from the editor and sends it to the backend.

### 11.2 Template Variable Reference

| Variable | Value injected at runtime |
|---|---|
| `{{args.code}}` | The code selected in the editor (or full file if nothing selected) |
| `{{ctx.language}}` | The VS Code `languageId` of the active file (e.g. `"python"`, `"typescript"`) |
| `{{ctx.filePath}}` | Relative file path within the workspace |

### 11.3 Via the API (Programmatic)

You can also create tools by POSTing to `/api/custom-tools`:

```bash
# Create a tool
curl -X POST http://localhost:3579/api/custom-tools \
  -H "Content-Type: application/json" \
  -d '{"name":"my_tool","displayName":"My Tool","promptTemplate":"Analyse: {{args.code}}"}'

# Delete a tool
curl -X DELETE http://localhost:3579/api/custom-tools/my_tool

# List all custom tools
curl http://localhost:3579/api/custom-tools
```

---

## 12. Extending the Project

### 12.1 Adding a New LLM Provider

1. **`backend/llm_router.py` — `build_llm()`:** Add an `elif` branch for the new provider name, returning the appropriate LangChain chat model.
2. **`backend/llm_router.py` — `probe_provider()`:** Add an `elif` to check availability and return the model list.
3. **`backend/llm_router.py` — `init_providers()`:** Add a conditional block to register the provider from environment variables on startup.
4. **`backend/.env.example`:** Add the API key / base URL variable.
5. **`frontend/package.json`:** Add the new provider name to the `openclaw.defaultProvider` enum array. The dropdown is populated dynamically from the backend so no HTML change is needed.

### 12.2 Adding a New Built-in LLM Tool

1. **`backend/agent_engine.py` — `BUILTIN_TOOL_PROMPTS`:** Add an entry with the tool name as key and a prompt template as value. Use `{code}`, `{language}`, and any extra params as placeholders.
2. **`frontend/src/toolsProvider.ts` — `BUILTIN_TOOLS`:** Add an entry with `name`, `label`, `icon`, and `description`.
3. **`frontend/package.json`:** Add a command entry for `openclaw.tool.your_tool_name` in both the `"commands"` and `"openclaw.submenu"` arrays.

### 12.3 Adding a New Agent Tool

1. **`backend/agent_engine.py`:** Define a new Python function decorated with `@lc_tool`. The docstring becomes the tool's description seen by the LLM.
2. **`backend/agent_engine.py` — `get_tools()`:** Add the function to the return list.
3. **`backend/agent_engine.py` — `SYSTEM_PROMPT`:** Add a bullet point describing the tool so the LLM knows when to use it.

### 12.4 Packaging the Extension for Distribution

```bash
# Install packaging tool
npm install -g @vscode/vsce

# Compile and package
cd frontend
npm run compile
vsce package
# → creates openclaw-0.1.0.vsix

# Install locally
code --install-extension openclaw-0.1.0.vsix

# Publish to VS Code Marketplace (requires publisher account)
vsce publish
```

> **Note:** `.vscodeignore` already excludes `src/`, `.vscode/`, `node_modules/`, and all `.ts` source files from the packaged extension.

---

## 13. Dependency Reference

### 13.1 Python Backend Dependencies

| Package | Purpose | Category |
|---|---|---|
| `fastapi>=0.111.0` | Web framework — replaces Node.js/Express | Core |
| `uvicorn[standard]>=0.29.0` | ASGI server with WebSocket and HTTP/2 support | Core |
| `python-dotenv>=1.0.0` | Loads `.env` file into `os.environ` on startup | Core |
| `pydantic>=2.7.0` | Request/response model validation | Core |
| `langchain>=0.2.0` | Agent orchestration framework (v1.2.x installed) | AI |
| `langchain-core>=0.2.0` | Callbacks, prompts, base chat model interface | AI |
| `langchain-community>=0.2.0` | File tools, shell tool, `ChatLiteLLM` | AI |
| `langchain-experimental>=0.0.60` | `PythonREPLTool` | AI |
| `langchain-openai>=0.1.0` | `ChatOpenAI` — wraps OpenAI + vLLM endpoints | AI |
| `langchain-google-genai>=1.0.0` | `ChatGoogleGenerativeAI` — wraps Gemini | AI |
| `langchain-ollama>=0.1.0` | `ChatOllama` — wraps local Ollama models | AI |
| `litellm>=1.40.0` | Universal LLM router — fallback for any provider | AI |
| `openai>=1.30.0` | OpenAI SDK (required by `langchain-openai`) | AI |
| `google-generativeai>=0.7.0` | Google AI SDK (required by `langchain-google-genai`) | AI |
| `pyyaml>=6.0.1` | YAML parsing for custom tool definitions | Tools |
| `watchfiles>=0.21.0` | File system watcher for hot-reload | Tools |
| `httpx>=0.27.0` | Async HTTP client for provider health probes | Tools |
| `aiofiles>=23.2.1` | Async file reading for `/api/files/context` | Tools |
| `gitpython>=3.1.43` | Available for git tooling extensions | Tools |
| `langgraph` | LangGraph ReAct agent framework (`create_react_agent`, `MemorySaver`) | AI |

### 13.2 Frontend (npm) Dependencies

| Package | Type | Purpose |
|---|---|---|
| `axios ^1.6.0` | dependency | HTTP client for REST calls to the backend |
| `@types/vscode ^1.85.0` | devDependency | TypeScript type definitions for the VS Code API |
| `@types/node ^20.0.0` | devDependency | TypeScript type definitions for Node.js built-ins |
| `typescript ^5.3.0` | devDependency | TypeScript compiler |

---

*OpenClaw v4.0 — Complete Project Documentation*
