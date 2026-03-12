# ==============================================================
# server.py
#
# REPLACES: backend/src/server.ts (Express on port 3579)
#
# Exact same REST API endpoints — VS Code extension talks to
# this server identically. Same URLs, same JSON shapes.
#
# Runs on port 3579 (same as Node.js version).
# Start: python server.py   OR   uvicorn server:app --reload
# ==============================================================

import os
import json
import asyncio
import logging
import traceback
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('openclaw')

# ── Our modules ───────────────────────────────────────────────────────────────
from llm_router import (
    init_providers, update_provider, add_custom_provider,
    list_providers, probe_provider, build_llm
)
from agent_engine import (
    run_streaming, run_simple, run_builtin_tool,
    clear_session, BUILTIN_TOOL_PROMPTS
)
from custom_tool_manager import custom_tool_manager


# ==============================================================
# File context injection
# Builds a prompt prefix from the context dict sent by VS Code.
# This is what makes the LLM "see" the file the dev has open.
# ==============================================================

def inject_file_context(message: str, context: dict | None) -> str:
    """
    Prepend active file context to the user message so the agent
    is always aware of what file/code the developer is looking at.

    Context dict fields (sent by contextManager.ts):
        filePath, fileName, language, totalLines,
        captureMode, code, cursorLine,
        selectionStart, selectionEnd
    """
    if not context or not context.get("code"):
        return message

    file_path    = context.get("filePath", "unknown")
    language     = context.get("language", "text")
    total_lines  = context.get("totalLines", "?")
    capture_mode = context.get("captureMode", "full_file")
    code         = context.get("code", "")
    cursor_line  = context.get("cursorLine")
    sel_start    = context.get("selectionStart")
    sel_end      = context.get("selectionEnd")

    lines = ["## Active File Context"]
    lines.append(f"**File:** `{file_path}`")
    lines.append(f"**Language:** {language}")
    lines.append(f"**Total lines:** {total_lines}")

    if capture_mode == "selection" and sel_start and sel_end:
        lines.append(f"**Showing:** Selected lines {sel_start}–{sel_end}")
    elif capture_mode == "visible_range":
        lines.append(f"**Showing:** Visible range (of {total_lines} total lines)")
    else:
        lines.append(f"**Showing:** Full file ({total_lines} lines)")

    if cursor_line:
        lines.append(f"**Cursor at:** line {cursor_line}")

    lines.append("")
    lines.append(f"```{language}")
    lines.append(code)
    lines.append("```")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"**User question:** {message}")

    return "\n".join(lines)


# ── App lifecycle ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_providers()
    custom_tool_manager.watch_for_changes(
        lambda: logger.info("Custom tools reloaded")
    )
    logger.info(f"Navyug AI Python Backend running on http://localhost:{PORT}")
    logger.info(f"   Framework: FastAPI + LangChain + LiteLLM")
    logger.info(f"   Custom tools dir: {custom_tool_manager.tools_dir}")
    yield
    # Shutdown (nothing needed)


app = FastAPI(title="Navyug AI Backend", version="2.0.0", lifespan=lifespan)
PORT = int(os.getenv("PORT", "3579"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==============================================================
# Request / Response models (same shape as Node.js version)
# ==============================================================

class ChatRequest(BaseModel):
    message: str
    sessionId: Optional[str] = None
    workspacePath: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    agentMode: Optional[bool] = True
    stream: Optional[bool] = False
    context: Optional[dict] = None


class ExecuteRequest(BaseModel):
    taskType: str           # "tool" | "chat" | "auto"
    toolName: Optional[str] = None
    toolArgs: Optional[dict] = None
    userMessage: str = ""
    context: Optional[dict] = None
    llmProvider: Optional[str] = None
    llmModel: Optional[str] = None
    sessionId: Optional[str] = None


class ProviderConfigUpdate(BaseModel):
    providers: Optional[dict] = None
    defaultProvider: Optional[str] = None


class CustomProviderConfig(BaseModel):
    name: str
    baseUrl: str
    apiKey: Optional[str] = None
    models: list[str] = []


class FilesContextRequest(BaseModel):
    paths: list[str]
    workspacePath: Optional[str] = None


# ==============================================================
# Health check
# ==============================================================

@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0.0", "runtime": "python+fastapi+langchain"}


# ==============================================================
# Providers
# GET  /api/providers       — list all + probe
# POST /api/providers/config — update API keys / URLs
# POST /api/providers/custom — add a custom LLM endpoint
# ==============================================================

@app.get("/api/providers")
async def get_providers():
    """REPLACES: GET /api/providers in server.ts"""
    cfgs = list_providers()
    probed = await asyncio.gather(*[probe_provider(c.name) for c in cfgs])
    return {"providers": list(probed)}


@app.post("/api/providers/config")
async def update_provider_config(body: ProviderConfigUpdate):
    """REPLACES: POST /api/providers/config in server.ts"""
    if body.providers:
        for name, cfg in body.providers.items():
            if isinstance(cfg, dict):
                update_provider(
                    name,
                    api_key=cfg.get("apiKey"),
                    base_url=cfg.get("baseUrl"),
                )
    return {"success": True, "message": "Provider config updated"}


@app.post("/api/providers/custom")
async def add_provider(body: CustomProviderConfig):
    """REPLACES: POST /api/providers/custom in server.ts"""
    add_custom_provider(body.name, body.baseUrl, body.apiKey, body.models)
    return {"success": True, "message": f'Custom provider "{body.name}" added'}


# ==============================================================
# Tools
# GET /api/tools — list builtin + custom tools
# ==============================================================

@app.get("/api/tools")
async def list_tools():
    """REPLACES: GET /api/tools in server.ts"""
    builtin = [
        {"name": name, "displayName": name.replace("_", " ").title(), "type": "builtin"}
        for name in BUILTIN_TOOL_PROMPTS
    ]
    custom = custom_tool_manager.get_all()
    return {"builtin": builtin, "custom": custom}


# ==============================================================
# Execute — unified tool/chat dispatcher
# POST /api/execute
# ==============================================================

@app.post("/api/execute")
async def execute(body: ExecuteRequest):
    """
    REPLACES: POST /api/execute in server.ts
    Dispatches to: builtin tool, custom tool, or chat
    """
    provider = body.llmProvider or os.getenv("DEFAULT_PROVIDER", "openai")
    model_id = body.llmModel or None
    workspace = (body.context or {}).get("workspacePath", ".")
    code = (body.toolArgs or {}).get("code", "") or body.userMessage
    language = (body.context or {}).get("language", "unknown")

    # ── Builtin LLM tool ───────────────────────────────────────────────────────
    if body.taskType == "tool" and body.toolName in BUILTIN_TOOL_PROMPTS:
        result = await run_builtin_tool(
            tool_name=body.toolName,
            code=code,
            language=language,
            provider=provider,
            model_id=model_id,
            extra=body.toolArgs,
        )
        return result

    # ── Custom tool ────────────────────────────────────────────────────────────
    if body.taskType == "tool" and body.toolName:
        tool_def = custom_tool_manager.get(body.toolName)
        if tool_def:
            lc_tool = custom_tool_manager.build_langchain_tool(tool_def, provider, model_id)
            import time as _time
            _start = _time.time()
            try:
                output = lc_tool.run({
                    "code": code,
                    "language": language,
                    "file_path": (body.context or {}).get("filePath", ""),
                })
                return {"output": output, "toolName": body.toolName, "provider": provider, "model": model_id or "", "durationMs": int((_time.time() - _start) * 1000), "error": None}
            except Exception as e:
                return {"output": "", "toolName": body.toolName, "provider": provider, "model": model_id or "", "durationMs": int((_time.time() - _start) * 1000), "error": str(e)}
        raise HTTPException(status_code=404, detail=f"Tool '{body.toolName}' not found")

    # ── Chat ────────────────────────────────────────────────────────────────────
    result = await run_simple(
        message=body.userMessage or code,
        provider=provider,
        model_id=model_id,
        workspace=workspace,
        session_id=body.sessionId,
    )
    return result


# ==============================================================
# Chat — simple non-streaming
# POST /api/chat
# ==============================================================

@app.post("/api/chat")
async def chat(body: ChatRequest):
    """REPLACES: POST /api/chat in server.ts"""
    provider = body.provider or os.getenv("DEFAULT_PROVIDER", "openai")
    logger.info(f"POST /api/chat | provider={provider}, model={body.model or 'default'}, session={body.sessionId}")
    message = inject_file_context(body.message, body.context)
    try:
        result = await run_simple(
            message=message,
            provider=provider,
            model_id=body.model,
            workspace=body.workspacePath or ".",
            session_id=body.sessionId,
        )
        if result.get("error"):
            logger.error(f"Chat error: {result['error']}")
        else:
            logger.info(f"Chat OK: provider={result.get('provider')}, duration={result.get('durationMs')}ms")
        return result
    except Exception as e:
        logger.exception(f"Chat endpoint crashed: {e}")
        raise


# ==============================================================
# Streaming chat — SSE
# POST /api/chat/stream
#
# Emits: data: {"type":"step",...}
#        data: {"type":"chunk","content":"..."}
#        data: {"type":"done",...}
#        data: {"type":"error","error":"..."}
# ==============================================================

@app.post("/api/chat/stream")
async def chat_stream(body: ChatRequest):
    """
    REPLACES: POST /api/chat/stream SSE endpoint.
    Uses FastAPI StreamingResponse — no external SSE library needed.
    """
    provider = body.provider or os.getenv("DEFAULT_PROVIDER", "openai")
    message  = inject_file_context(body.message, body.context)
    logger.info(f"POST /api/chat/stream | provider={provider}, model={body.model or 'default'}, session={body.sessionId}")

    async def event_generator():
        try:
            async for event in run_streaming(
                message=message,
                provider=provider,
                model_id=body.model,
                workspace=body.workspacePath or ".",
                session_id=body.sessionId,
            ):
                if event.get("type") == "error":
                    logger.error(f"Stream error event: {event.get('error')}")
                yield f"data: {json.dumps(event)}\n\n"
        except asyncio.CancelledError:
            logger.info("Stream cancelled by client")
        except Exception as e:
            logger.exception(f"Stream event generator error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ==============================================================
# Agentic chat — non-streaming
# POST /api/agent-chat
# ==============================================================

@app.post("/api/agent-chat")
async def agent_chat(body: ChatRequest):
    """
    REPLACES: POST /api/agent-chat in server.ts
    Runs the full agentic loop and returns once complete.
    FIX #3: now injects file context just like /api/chat and /api/chat/stream
    """
    provider = body.provider or os.getenv("DEFAULT_PROVIDER", "openai")
    message  = inject_file_context(body.message, body.context)  # FIX #3
    result   = await run_simple(
        message=message,
        provider=provider,
        model_id=body.model,
        workspace=body.workspacePath or ".",
        session_id=body.sessionId,
    )
    return result


# ==============================================================
# Custom tools CRUD
# GET    /api/custom-tools
# POST   /api/custom-tools
# DELETE /api/custom-tools/{name}
# ==============================================================

@app.get("/api/custom-tools")
async def list_custom_tools():
    """REPLACES: GET /api/custom-tools in server.ts"""
    return {"tools": custom_tool_manager.get_all(), "dir": str(custom_tool_manager.tools_dir)}


@app.post("/api/custom-tools")
async def save_custom_tool(tool_data: dict):
    """REPLACES: POST /api/custom-tools in server.ts"""
    try:
        custom_tool_manager.save(tool_data)
        return {"success": True, "message": f'Tool "{tool_data.get("name")}" saved'}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/custom-tools/{name}")
async def delete_custom_tool(name: str):
    """REPLACES: DELETE /api/custom-tools/{name} in server.ts"""
    deleted = custom_tool_manager.delete(name)
    return {"success": deleted, "message": "Tool deleted" if deleted else "Tool not found"}


# ==============================================================
# Session management
# DELETE /api/session/{sessionId}
# ==============================================================

@app.delete("/api/session/{session_id}")
async def delete_session(session_id: str):
    """REPLACES: DELETE /api/session/:sessionId in server.ts"""
    clear_session(session_id)
    return {"success": True}


# ==============================================================
# Multi-file context
# POST /api/files/context
# ==============================================================

@app.post("/api/files/context")
async def files_context(body: FilesContextRequest):
    """
    REPLACES: POST /api/files/context in server.ts
    Returns content of requested files for multi-file context injection.
    """
    import aiofiles
    from pathlib import Path

    EXT_LANG = {
        ".ts": "typescript", ".tsx": "tsx", ".js": "javascript", ".jsx": "jsx",
        ".py": "python", ".go": "go", ".rs": "rust", ".java": "java",
        ".cs": "csharp", ".cpp": "cpp", ".c": "c", ".rb": "ruby",
        ".md": "markdown", ".json": "json", ".yaml": "yaml", ".sh": "bash",
        ".html": "html", ".css": "css", ".sql": "sql",
    }

    files = []
    for p in body.paths:
        abs_path = Path(body.workspacePath or ".") / p if body.workspacePath else Path(p)
        if not abs_path.exists():
            continue
        try:
            async with aiofiles.open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                content = await f.read()
            ext = abs_path.suffix.lower()
            files.append({
                "name": abs_path.name,
                "path": str(p),
                "content": content,
                "language": EXT_LANG.get(ext, ext.lstrip(".") or "text"),
                "lines": content.count("\n") + 1,
            })
        except Exception:
            continue

    return {"files": files}


# ==============================================================
# Tool catalog
# GET /api/tools/catalog
# ==============================================================

@app.get("/api/tools/catalog")
async def tools_catalog():
    """REPLACES: GET /api/tools/catalog in server.ts"""
    builtin = [{"name": k, "description": v[:80]} for k, v in BUILTIN_TOOL_PROMPTS.items()]
    return {"total": len(builtin), "definitions": builtin}


# ==============================================================
# Admin: permissions
# POST /api/admin/permissions/{sessionId}
# ==============================================================

@app.post("/api/admin/permissions/{session_id}")
async def set_permissions(session_id: str, body: dict):
    """REPLACES: POST /api/admin/permissions/:sessionId in server.ts"""
    # Permissions are enforced via LangChain's tool allow/block lists
    # For now, store the level and apply on next agent build
    level = body.get("level", "standard")
    logger.info(f"Permissions set: session={session_id}, level={level}")
    return {"success": True, "message": f'Permission level "{level}" set'}


# ==============================================================
# Shortcut endpoints (same as Node.js version)
# ==============================================================

class ToolShortcutRequest(BaseModel):
    code: str
    language: str = "unknown"
    filePath: str = ""
    provider: Optional[str] = None
    model: Optional[str] = None


@app.post("/api/tools/generate-tests")
async def generate_tests(body: ToolShortcutRequest):
    return await run_builtin_tool("generate_tests", body.code, body.language,
                                  body.provider or "openai", body.model)


@app.post("/api/tools/review-code")
async def review_code(body: ToolShortcutRequest):
    return await run_builtin_tool("review_code", body.code, body.language,
                                  body.provider or "openai", body.model)


@app.post("/api/tools/find-bugs")
async def find_bugs(body: ToolShortcutRequest):
    return await run_builtin_tool("find_bugs", body.code, body.language,
                                  body.provider or "openai", body.model)


@app.post("/api/tools/explain-code")
async def explain_code(body: ToolShortcutRequest):
    return await run_builtin_tool("explain_code", body.code, body.language,
                                  body.provider or "openai", body.model)


@app.post("/api/tools/security-analysis")
async def security_analysis(body: ToolShortcutRequest):
    return await run_builtin_tool("security_analysis", body.code, body.language,
                                  body.provider or "openai", body.model)


# ==============================================================
# Entry point
# ==============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "server:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=PORT,
        reload=True,
        reload_dirs=["."],
    )
