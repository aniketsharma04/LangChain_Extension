# ==============================================================
# agent_engine.py
#
# REPLACES: AgenticChatEngineV2.ts, OpenClawOrchestrator.ts,
#           ToolRegistry.ts, BuiltinTools.ts, SafetyLayer.ts
#
# Updated for OpenClaw Orchestration (local agent)
# ==============================================================

import asyncio
import time
import logging
from typing import Optional, AsyncIterator

# ── OpenClaw Orchestration ──────────────────────────────────────────────────
from openclaw import AsyncOpenClaw
from cmdop.models.agent import AgentEventType, AgentResult, AgentStreamEvent

# The client uses the .local() factory to connect to a local OpenClaw agent via IPC.
# Lazy-initialized so the module loads even if the agent isn't running yet.
_client: AsyncOpenClaw | None = None

def _get_client() -> AsyncOpenClaw:
    """Get or create the OpenClaw client (lazy init)."""
    global _client
    if _client is None:
        _client = AsyncOpenClaw.local()
        logger.info("OpenClaw client initialized (local IPC)")
    return _client

logger = logging.getLogger('navyug.agent')

# ==============================================================
# Utilities
# ==============================================================

def _clean_error(exc: Exception) -> tuple[str, str]:
    """Provides a human-readable error message and type."""
    raw = str(exc)
    error_type = "unknown"
    
    if "429" in raw:
        return "⏳ Rate limit / quota exceeded", "rate_limit"
    if "401" in raw or "invalid api key" in raw.lower():
        return "🔑 Invalid API key", "auth"
    
    return raw[:200], error_type


def clear_session(session_id: str):
    """Clear conversation memory for a specific session."""
    # OpenClaw manages sessions natively. 
    # Placeholder to maintain compatibility with server.py
    logger.info(f"Session cleared (placeholder): {session_id}")
    pass


# ==============================================================
# OpenClaw Engine - Orchestration
# ==============================================================

async def run_streaming(
    message: str,
    provider: str = "openai", # Legacy: Provider is now handled by the OpenClaw Agent
    model_id: Optional[str] = None,
    workspace: str = ".",
    session_id: Optional[str] = None,
) -> AsyncIterator[dict]:
    """
    Runs an AI agent using OpenClaw with real-time event streaming.
    Events are mapped to the format expected by the Navyug frontend.
    """
    start = time.time()
    tool_calls = 0
    sid = session_id or "default"

    try:
        # OpenClaw handles conversation history per session_id
        _get_client().agent.set_session_id(sid)
        
        async for event in _get_client().agent.run_stream(
            prompt=message,
        ):
            if isinstance(event, AgentResult):
                # Final result from OpenClaw
                yield {
                    "type": "done",
                    "durationMs": int((time.time() - start) * 1000),
                    "totalToolCalls": tool_calls,
                    "provider": provider,
                    "model": model_id or "openclaw-agent",
                }
            else:
                # Map OpenClaw event types to Navyug Frontend format
                if event.type == AgentEventType.TOKEN:
                    text = str(event.payload.get("token", ""))
                    yield {"type": "chunk", "content": text}
                
                elif event.type == AgentEventType.TOOL_START:
                    tool_calls += 1
                    yield {
                        "type": "step",
                        "step": {
                            "type": "tool_call",
                            "toolName": event.payload.get("tool_name", "unknown"),
                            "toolArgs": {"input": str(event.payload.get("args", ""))[:200]},
                            "timestamp": int(event.timestamp * 1000),
                        }
                    }
                
                elif event.type == AgentEventType.TOOL_END:
                    yield {
                        "type": "step",
                        "step": {
                            "type": "tool_result",
                            "result": str(event.payload.get("output", ""))[:2000],
                            "success": not event.payload.get("error"),
                            "timestamp": int(event.timestamp * 1000),
                        }
                    }
                
                elif event.type == AgentEventType.ERROR:
                    yield {
                        "type": "error",
                        "error": str(event.payload.get("message", "OpenClaw agent error")),
                        "errorType": "agent_error"
                    }

    except Exception as e:
        error_msg, error_type = _clean_error(e)
        logger.error(f"OpenClaw run_streaming error: {error_msg}")
        yield {"type": "error", "error": error_msg, "errorType": error_type}


async def run_simple(
    message: str,
    provider: str = "openai",
    model_id: Optional[str] = None,
    workspace: str = ".",
    session_id: Optional[str] = None,
) -> dict:
    """
    Non-streaming agent execution.
    """
    start = time.time()
    sid = session_id or "default"

    try:
        _get_client().agent.set_session_id(sid)
        result = await _get_client().agent.run(prompt=message)

        return {
            "output": result.text,
            "provider": provider,
            "model": model_id or "openclaw-agent",
            "durationMs": int((time.time() - start) * 1000),
            "totalToolCalls": 0,
            "error": None,
        }
    except Exception as e:
        error_msg, error_type = _clean_error(e)
        logger.error(f"OpenClaw run_simple error: {error_msg}")
        return {
            "output": "",
            "provider": provider,
            "model": model_id or "openclaw-agent",
            "durationMs": int((time.time() - start) * 1000),
            "totalToolCalls": 0,
            "error": error_msg,
            "errorType": error_type,
        }


# ==============================================================
# Builtin LLM tools (direct prompt calls)
# ==============================================================
# These remain powered by the local LLM router for now.

from llm_router import build_llm

BUILTIN_TOOL_PROMPTS: dict[str, str] = {
    "review_code":          "You are an expert code reviewer. Review the following {language} code for bugs, style issues, and best practices. Be specific and actionable.\n\nCode:\n```{language}\n{code}\n```",
    "generate_tests":       "You are an expert in test-driven development. Generate comprehensive unit tests for the following {language} code. Include edge cases.\n\nCode:\n```{language}\n{code}\n```",
    "find_bugs":            "You are a debugging expert. Identify all bugs, logic errors, and potential runtime issues in this {language} code. List each with line number and explanation.\n\nCode:\n```{language}\n{code}\n```",
    "explain_code":         "Explain the following {language} code in plain language. Describe what it does, how it works, and any important patterns used.\n\nCode:\n```{language}\n{code}\n```",
    "refactor_code":        "Refactor the following {language} code for better readability, maintainability, and performance. Show the improved version with explanations.\n\nCode:\n```{language}\n{code}\n```",
    "generate_docs":        "Generate comprehensive documentation for the following {language} code. Include JSDoc/docstrings, parameter descriptions, return values, and usage examples.\n\nCode:\n```{language}\n{code}\n```",
    "security_analysis":    "Perform a security analysis of the following {language} code. Identify OWASP vulnerabilities, injection risks, authentication issues, and other security concerns.\n\nCode:\n```{language}\n{code}\n```",
    "optimize_performance": "Analyze the following {language} code for performance issues. Identify bottlenecks and suggest optimizations with code examples.\n\nCode:\n```{language}\n{code}\n```",
    "analyze_complexity":   "Analyze the cyclomatic complexity and Big-O complexity of the following {language} code. Identify complex areas and suggest simplifications.\n\nCode:\n```{language}\n{code}\n```",
    "translate_code":       "Translate the following code to {targetLanguage}. Preserve all logic and add appropriate idiomatic patterns for the target language.\n\nCode:\n```{language}\n{code}\n```",
}

async def run_builtin_tool(
    tool_name: str,
    code: str,
    language: str = "unknown",
    provider: str = "openai",
    model_id: Optional[str] = None,
    extra: Optional[dict] = None,
) -> dict:
    start = time.time()
    prompt_template = BUILTIN_TOOL_PROMPTS.get(tool_name)
    if not prompt_template:
        return {"output": "", "toolName": tool_name, "provider": provider, "model": model_id or "", "durationMs": 0, "totalToolCalls": 0, "error": f"Unknown tool: {tool_name}"}

    try:
        params = {"code": code, "language": language, **(extra or {})}
        prompt = prompt_template.format(**params)
        llm    = build_llm(provider, model_id)
        loop   = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, lambda: llm.invoke(prompt))
        return {
            "output": response.content if hasattr(response, "content") else str(response),
            "toolName": tool_name,
            "provider": provider,
            "model": model_id or "",
            "durationMs": int((time.time() - start) * 1000),
            "error": None,
        }
    except Exception as e:
        error_msg, error_type = _clean_error(e)
        logger.error(f"Builtin tool error [{error_type}]: {tool_name} — {error_msg}")
        return {
            "output": "",
            "toolName": tool_name,
            "provider": provider,
            "model": model_id or "",
            "durationMs": int((time.time() - start) * 1000),
            "error": error_msg,
            "errorType": error_type,
        }
