# ==============================================================
# agent_engine.py
#
# REPLACES: AgenticChatEngineV2.ts, OpenClawOrchestrator.ts,
#           ToolRegistry.ts, BuiltinTools.ts, SafetyLayer.ts
#
# Updated for LangGraph API (langchain v1.2.x+)
# create_react_agent moved to langgraph.prebuilt
# ==============================================================

import os
import time
import asyncio
import logging
import subprocess
from typing import Optional, AsyncIterator, ClassVar

# ── LangGraph agent (replaces langchain.agents) ──────────────────────────────
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver

# ── LangChain core ────────────────────────────────────────────────────────────
from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.tools import tool as lc_tool
from langchain_core.messages import HumanMessage, SystemMessage

# ── LangChain built-in tools ──────────────────────────────────────────────────
from langchain_community.tools.file_management import (
    ReadFileTool, WriteFileTool, ListDirectoryTool,
    CopyFileTool, MoveFileTool, DeleteFileTool,
)
from langchain_experimental.tools.python.tool import PythonREPLTool

# ── Our LLM router ────────────────────────────────────────────────────────────
from llm_router import build_llm

logger = logging.getLogger('openclaw.agent')


def _to_str(content) -> str:
    """Coerce LangChain message content to a plain string.
    Gemini 2.5 models can return content as a list of dicts
    (e.g. [{'type': 'text', 'text': '...'}]) instead of a string.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and 'text' in item:
                parts.append(item['text'])
            else:
                parts.append(str(item))
        return ''.join(parts)
    return str(content)


# ==============================================================
# Rate-limit pacer — prevents burning through free-tier RPM
# Adds a configurable delay between consecutive LLM API calls.
# ==============================================================

class RateLimitPacer(BaseCallbackHandler):
    """Inserts a delay between LLM calls to stay under RPM limits."""

    def __init__(self, delay_seconds: float = 3.0):
        super().__init__()
        self._delay = delay_seconds
        self._last_call = 0.0

    def on_llm_start(self, *args, **kwargs):
        now = time.time()
        elapsed = now - self._last_call
        if self._last_call > 0 and elapsed < self._delay:
            wait = self._delay - elapsed
            logger.info(f"Rate-limit pacer: waiting {wait:.1f}s before next LLM call")
            time.sleep(wait)
        self._last_call = time.time()


# ==============================================================
# Error message cleaner — converts raw LangChain exception blobs
# into short, human-readable strings shown in the chat UI.
# ==============================================================

import re as _re
import json as _json

def _clean_error(exc: Exception) -> tuple[str, str]:
    """
    LangChain exceptions often contain the full API response JSON as their
    string representation.  Returns (human_message, error_type).
    error_type is one of: rate_limit, auth, forbidden, server, unavailable, unknown
    """
    raw = str(exc)
    error_type = "unknown"

    # 1) Try to find a JSON object embedded in the string and extract "message"
    try:
        json_match = _re.search(r"'message':\s*'(\{.*)\'\s*,\s*'status'", raw, _re.DOTALL)
        if json_match:
            inner = _json.loads(json_match.group(1))
            msg = inner.get("error", {}).get("message", "")
            code = inner.get("error", {}).get("code", "")
            if code == 429: error_type = "rate_limit"
            elif code == 401: error_type = "auth"
            elif code == 403: error_type = "forbidden"
            elif code >= 500: error_type = "server"
            if msg:
                msg = msg.split("For more information")[0].strip().rstrip(".")
                return (f"[{code}] {msg}" if code else msg, error_type)
    except Exception:
        pass

    # 2) Detect common HTTP status codes and map to friendly prefixes
    for code, friendly, etype in [
        ("429", "⏳ Rate limit / quota exceeded", "rate_limit"),
        ("401", "🔑 Invalid API key", "auth"),
        ("403", "🔒 Access forbidden", "forbidden"),
        ("500", "🔥 Server error", "server"),
        ("503", "🔥 Service unavailable", "unavailable"),
    ]:
        if f": {code} " in raw or f"code: {code}" in raw or f'"code": {code}' in raw:
            error_type = etype
            m = _re.search(r'"message":\s*"([^"]+)"', raw)
            detail = m.group(1) if m else raw[:120]
            detail = detail.split("\\n")[0].strip()
            return (f"{friendly}: {detail}", error_type)

    # 3) Fallback — first non-empty line, cap at 200 chars
    first_line = raw.split("\n")[0].strip()
    return (first_line[:200] if first_line else raw[:200], error_type)



# ==============================================================
# SafeShellTool: restricted shell (blocks destructive cmds)
# ==============================================================

from langchain_community.tools.shell.tool import ShellTool

class SafeShellTool(ShellTool):
    """
    Shell tool with a blocklist for destructive commands.
    Prevents the LLM from running rm -rf, sudo, curl to external
    IPs, etc. even if it hallucinates or is prompt-injected.
    """
    BLOCKED_PATTERNS: ClassVar[list[str]] = [
        # Unix
        "rm -rf /", "rm -rf ~", "sudo rm", "sudo dd",
        "dd if=/dev/zero", "dd if=/dev/random",
        "> /dev/sda", "mkfs", "fdisk",
        "shutdown", "reboot", "halt", "poweroff",
        "chmod 777 /", "chown -R root",
        ":(){:|:&};:",           # fork bomb
        "curl | bash", "wget | bash", "curl | sh", "wget | sh",
        # Windows
        "format c:", "format d:", "del /s /q", "rd /s /q",
        "rmdir /s /q", "del /f /s /q",
    ]

    def _run(self, commands: str) -> str:
        lower = commands.lower()
        for pattern in self.BLOCKED_PATTERNS:
            if pattern in lower:
                return f"❌ Blocked: '{pattern}' is not permitted by SafeShellTool."
        return super()._run(commands)

    async def _arun(self, commands: str) -> str:
        return self._run(commands)


# ==============================================================
# Custom dev tools — git, linting, testing, code search
# ==============================================================

@lc_tool
def git_status() -> str:
    """Get git repository status: current branch, staged and unstaged changes."""
    r = subprocess.run(
        "git status --short && echo '---' && git branch --show-current",
        shell=True, capture_output=True, text=True, cwd=os.getcwd()
    )
    return r.stdout.strip() or "Not a git repo or clean working tree"


@lc_tool
def git_diff(staged: bool = False) -> str:
    """Get git diff of current changes. Set staged=True for staged diff."""
    flag = "--cached" if staged else ""
    r = subprocess.run(f"git diff {flag} | head -300", shell=True, capture_output=True, text=True)
    return r.stdout.strip() or "No changes to diff"


@lc_tool
def git_log(limit: int = 10) -> str:
    """Get recent git commit history as a compact graph."""
    r = subprocess.run(f"git log --oneline --graph -{limit}", shell=True, capture_output=True, text=True)
    return r.stdout.strip() or "No git history"


@lc_tool
def git_suggest_commit() -> str:
    """Analyze staged changes and suggest a conventional commit message."""
    r = subprocess.run("git diff --cached", shell=True, capture_output=True, text=True)
    diff = r.stdout.strip()
    if not diff:
        return "No staged changes. Stage your changes with 'git add' first."
    return f"Staged diff (write a conventional commit message for this):\n\n{diff[:3000]}"


@lc_tool
def run_linter(file_path: str) -> str:
    """Run appropriate linter on a file. Auto-detects: eslint (.js/.ts), pylint (.py), mypy (.py), tsc."""
    ext = os.path.splitext(file_path)[1].lower()
    cmds = {
        ".py":  f"pylint '{file_path}' --score=no 2>&1 | head -50",
        ".ts":  "npx tsc --noEmit 2>&1 | head -50",
        ".tsx": "npx tsc --noEmit 2>&1 | head -50",
        ".js":  f"npx eslint '{file_path}' --format compact 2>&1 | head -50",
        ".jsx": f"npx eslint '{file_path}' --format compact 2>&1 | head -50",
    }
    cmd = cmds.get(ext, f"npx eslint '{file_path}' --format compact 2>&1 | head -50")
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
    out = (r.stdout + r.stderr).strip()
    return out or f"✅ No issues found in {file_path}"


@lc_tool
def run_tests(file_path: str = "", runner: str = "auto") -> str:
    """Run test suite. Supports jest, vitest, pytest. Set runner='auto' to detect automatically."""
    if runner == "auto":
        if os.path.exists("pytest.ini") or os.path.exists("pyproject.toml"):
            runner = "pytest"
        elif os.path.exists("package.json"):
            with open("package.json") as f:
                runner = "vitest" if "vitest" in f.read() else "jest"
        else:
            runner = "pytest"
    file_arg = f"'{file_path}'" if file_path else ""
    cmds = {
        "jest":   f"npx jest {file_arg} 2>&1 | tail -50",
        "vitest": f"npx vitest run {file_arg} 2>&1 | tail -50",
        "pytest": f"python -m pytest {file_arg} -v 2>&1 | tail -60",
    }
    cmd = cmds.get(runner, cmds["pytest"])
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
    return (r.stdout + r.stderr).strip() or f"No output from {runner}"


@lc_tool
def search_code(query: str, directory: str = ".", regex: bool = False) -> str:
    """Search for a string or pattern across all code files in a directory."""
    from pathlib import Path
    import re as _search_re

    EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".cs", ".cpp", ".c", ".rb"}
    results = []
    pattern = _search_re.compile(query) if regex else None
    root = Path(directory).resolve()

    try:
        for fpath in root.rglob("*"):
            if not fpath.is_file() or fpath.suffix.lower() not in EXTENSIONS:
                continue
            # Skip common non-source directories
            parts_lower = [p.lower() for p in fpath.parts]
            if any(skip in parts_lower for skip in ("node_modules", ".git", "venv", "__pycache__", ".venv")):
                continue
            try:
                lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
                for i, line in enumerate(lines, 1):
                    matched = (pattern.search(line) if pattern else query in line)
                    if matched:
                        rel = fpath.relative_to(root)
                        results.append(f"{rel}:{i}: {line.rstrip()}")
                        if len(results) >= 40:
                            return "\n".join(results)
            except Exception:
                continue
    except Exception as e:
        return f"Search error: {e}"

    return "\n".join(results) if results else f"No matches for '{query}' in {directory}"


@lc_tool
def find_symbol_definition(symbol: str) -> str:
    """Find where a function, class, or variable is defined in the codebase."""
    from pathlib import Path
    import re as _sym_re

    EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs"}
    pat = _sym_re.compile(
        r"(?:def|class|function|const|let|var|type|interface)\s+" + _sym_re.escape(symbol) + r"\b"
    )
    results = []
    root = Path(".").resolve()

    try:
        for fpath in root.rglob("*"):
            if not fpath.is_file() or fpath.suffix.lower() not in EXTENSIONS:
                continue
            parts_lower = [p.lower() for p in fpath.parts]
            if any(skip in parts_lower for skip in ("node_modules", ".git", "venv", "__pycache__", ".venv")):
                continue
            try:
                lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
                for i, line in enumerate(lines, 1):
                    if pat.search(line):
                        rel = fpath.relative_to(root)
                        results.append(f"{rel}:{i}: {line.rstrip()}")
                        if len(results) >= 20:
                            return "\n".join(results)
            except Exception:
                continue
    except Exception as e:
        return f"Search error: {e}"

    return "\n".join(results) if results else f"No definition found for '{symbol}'"


@lc_tool
def apply_patch(file_path: str, patch_content: str) -> str:
    """Apply a unified diff patch to a file safely."""
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False) as f:
        f.write(patch_content)
        patch_file = f.name
    try:
        r = subprocess.run(
            f"patch '{file_path}' < '{patch_file}'",
            shell=True, capture_output=True, text=True, timeout=15
        )
        if r.returncode == 0:
            return f"✅ Patch applied successfully to {file_path}"
        return f"❌ Patch failed:\n{r.stdout}\n{r.stderr}"
    finally:
        os.unlink(patch_file)


# ==============================================================
# Tool catalogue
# ==============================================================

def get_tools(workspace: str = ".") -> list:
    return [
        ReadFileTool(root_dir=workspace),
        WriteFileTool(root_dir=workspace),
        ListDirectoryTool(root_dir=workspace),
        CopyFileTool(root_dir=workspace),
        MoveFileTool(root_dir=workspace),
        DeleteFileTool(root_dir=workspace),
        SafeShellTool(),
        PythonREPLTool(),
        git_status, git_diff, git_log, git_suggest_commit,
        run_linter, run_tests,
        search_code, find_symbol_definition,
        apply_patch,
    ]


# ==============================================================
# System prompt (simplified for LangGraph — no ReAct template
# variables needed, LangGraph handles tool descriptions internally)
# ==============================================================

SYSTEM_PROMPT = """You are OpenClaw, an expert AI coding assistant embedded in VS Code.

You have full access to the developer's workspace. Use your tools proactively.

## Tools available
- **ReadFileTool / WriteFileTool / ListDirectoryTool** — read, write, list files
- **CopyFileTool / MoveFileTool / DeleteFileTool** — manage files
- **SafeShellTool** — run shell commands (destructive commands are blocked)
- **PythonREPLTool** — write and execute Python code
- **git_status / git_diff / git_log / git_suggest_commit** — git operations
- **run_linter** — lint a file (pylint / eslint / tsc / mypy)
- **run_tests** — run tests (pytest / jest / vitest)
- **search_code** — grep across the codebase
- **find_symbol_definition** — find where a function/class is defined
- **apply_patch** — apply a unified diff patch to a file

## Rules
1. Always **read before editing** — use ReadFileTool first
2. **Verify after changes** — run_linter or run_tests after edits
3. Show **git diff** after making file changes
4. For code blocks, always include the language identifier in markdown"""


# ==============================================================
# Session memory using LangGraph MemorySaver checkpointer
# ==============================================================

_checkpointer = MemorySaver()
_session_timestamps: dict[str, float] = {}
SESSION_TTL = 3600  # 1 hour


def _evict_expired_sessions():
    """Remove sessions older than SESSION_TTL."""
    now = time.time()
    expired = [sid for sid, t in _session_timestamps.items() if now - t > SESSION_TTL]
    for sid in expired:
        # Clear from checkpointer storage
        keys_to_remove = [k for k in _checkpointer.storage if k[0] == sid]
        for k in keys_to_remove:
            del _checkpointer.storage[k]
        _session_timestamps.pop(sid, None)
        logger.info(f"Session evicted: {sid}")


def clear_session(session_id: str):
    """Clear conversation memory for a specific session."""
    keys_to_remove = [k for k in _checkpointer.storage if k[0] == session_id]
    for k in keys_to_remove:
        del _checkpointer.storage[k]
    _session_timestamps.pop(session_id, None)


# ==============================================================
# Agent builder — uses LangGraph create_react_agent
# ==============================================================

def build_agent(
    provider: str = "openai",
    model_id: Optional[str] = None,
    workspace: str = ".",
):
    """Build a LangGraph ReAct agent with all tools."""
    logger.info(f"Building agent: provider={provider}, model={model_id or 'default'}, workspace={workspace}")
    llm = build_llm(provider, model_id)

    # Attach rate-limit pacer to prevent free-tier RPM exhaustion
    pacer = RateLimitPacer(delay_seconds=3.0)
    llm.callbacks = [pacer]

    tools = get_tools(workspace)
    agent = create_react_agent(
        llm,
        tools,
        prompt=SYSTEM_PROMPT,
        checkpointer=_checkpointer,
    )
    return agent


# ==============================================================
# Streaming agentic run — yields SSE-compatible dicts
# Uses LangGraph's native astream_events for real-time streaming
# ==============================================================

async def run_streaming(
    message: str,
    provider: str = "openai",
    model_id: Optional[str] = None,
    workspace: str = ".",
    session_id: Optional[str] = None,
) -> AsyncIterator[dict]:
    start = time.time()
    tool_calls = 0
    sid = session_id or "default"

    _evict_expired_sessions()
    _session_timestamps[sid] = time.time()

    try:
        agent = build_agent(provider, model_id, workspace)
        config = {"configurable": {"thread_id": sid}}

        final_output = ""

        async for event in agent.astream_events(
            {"messages": [HumanMessage(content=message)]},
            config=config,
            version="v2",
        ):
            kind = event.get("event", "")

            if kind == "on_tool_start":
                tool_calls += 1
                yield {
                    "type": "step",
                    "step": {
                        "type": "tool_call",
                        "toolName": event.get("name", "unknown"),
                        "toolArgs": {"input": str(event.get("data", {}).get("input", ""))[:200]},
                        "timestamp": int(time.time() * 1000),
                    }
                }

            elif kind == "on_tool_end":
                yield {
                    "type": "step",
                    "step": {
                        "type": "tool_result",
                        "result": str(event.get("data", {}).get("output", ""))[:2000],
                        "success": True,
                        "timestamp": int(time.time() * 1000),
                    }
                }

            elif kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    # Only yield content from the final response (not tool-calling steps)
                    if event.get("metadata", {}).get("langgraph_node") == "agent":
                        text = _to_str(chunk.content)
                        final_output += text
                        yield {"type": "chunk", "content": text}

    except Exception as e:
        error_msg, error_type = _clean_error(e)
        logger.error(f"Streaming run error [{error_type}]: {error_msg}")
        logger.debug(f"Full exception: {e}", exc_info=True)
        yield {"type": "error", "error": error_msg, "errorType": error_type}
        return

    yield {
        "type": "done",
        "durationMs": int((time.time() - start) * 1000),
        "totalToolCalls": tool_calls,
        "provider": provider,
        "model": model_id or "",
    }


# ==============================================================
# Simple (non-streaming) run
# ==============================================================

async def run_simple(
    message: str,
    provider: str = "openai",
    model_id: Optional[str] = None,
    workspace: str = ".",
    session_id: Optional[str] = None,
) -> dict:
    start = time.time()
    sid = session_id or "default"

    _evict_expired_sessions()
    _session_timestamps[sid] = time.time()

    try:
        agent = build_agent(provider, model_id, workspace)
        config = {"configurable": {"thread_id": sid}}

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: agent.invoke(
                {"messages": [HumanMessage(content=message)]},
                config=config,
            )
        )

        # Extract the final AI message
        messages = result.get("messages", [])
        output = ""
        tool_call_count = 0
        for msg in messages:
            if hasattr(msg, "content") and msg.type == "ai" and not getattr(msg, "tool_calls", None):
                output = _to_str(msg.content)
            if msg.type == "tool":
                tool_call_count += 1

        return {
            "output": output,
            "provider": provider,
            "model": model_id or "",
            "durationMs": int((time.time() - start) * 1000),
            "totalToolCalls": tool_call_count,
            "error": None,
        }
    except Exception as e:
        error_msg, error_type = _clean_error(e)
        logger.error(f"Simple run error [{error_type}]: {error_msg}")
        logger.debug(f"Full exception: {e}", exc_info=True)
        return {
            "output": "",
            "provider": provider,
            "model": model_id or "",
            "durationMs": int((time.time() - start) * 1000),
            "totalToolCalls": 0,
            "error": error_msg,
            "errorType": error_type,
        }


# ==============================================================
# Builtin LLM tools (direct prompt calls, no agent loop)
# ==============================================================

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
        output = _to_str(response.content) if hasattr(response, "content") else str(response)
        return {
            "output": output,
            "toolName": tool_name,
            "provider": provider,
            "model": model_id or "",
            "durationMs": int((time.time() - start) * 1000),
            "error": None,
        }
    except Exception as e:
        error_msg, error_type = _clean_error(e)
        logger.error(f"Builtin tool error [{error_type}]: {tool_name} — {error_msg}")
        logger.debug(f"Full exception: {e}", exc_info=True)
        return {
            "output": "",
            "toolName": tool_name,
            "provider": provider,
            "model": model_id or "",
            "durationMs": int((time.time() - start) * 1000),
            "error": error_msg,
            "errorType": error_type,
        }
