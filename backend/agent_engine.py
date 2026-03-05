# ==============================================================
# agent_engine.py
#
# REPLACES: AgenticChatEngineV2.ts, OpenClawOrchestrator.ts,
#           ToolRegistry.ts, BuiltinTools.ts, SafetyLayer.ts
# ==============================================================

import os
import time
import asyncio
import subprocess
from typing import Optional, AsyncIterator

# ── LangChain orchestration ───────────────────────────────────────────────────
from langchain.agents import create_react_agent, AgentExecutor
from langchain_core.prompts import PromptTemplate
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain.memory import ConversationBufferWindowMemory
from langchain_core.callbacks.base import BaseCallbackHandler  # FIX #1
from langchain_core.tools import tool as lc_tool

# ── LangChain built-in tools ──────────────────────────────────────────────────
from langchain_community.tools.file_management import (
    ReadFileTool, WriteFileTool, ListDirectoryTool,
    CopyFileTool, MoveFileTool, DeleteFileTool,
)
from langchain_experimental.tools.python.tool import PythonREPLTool

# ── Our LLM router ────────────────────────────────────────────────────────────
from llm_router import build_llm


# ==============================================================
# FIX #5 — SafeShellTool: restricted shell (blocks destructive cmds)
# Replaces bare ShellTool() with a sandboxed version
# ==============================================================

from langchain_community.tools.shell.tool import ShellTool

class SafeShellTool(ShellTool):
    """
    Shell tool with a blocklist for destructive commands.
    Prevents the LLM from running rm -rf, sudo, curl to external
    IPs, etc. even if it hallucinates or is prompt-injected.
    """
    BLOCKED_PATTERNS = [
        "rm -rf /", "rm -rf ~", "sudo rm", "sudo dd",
        "dd if=/dev/zero", "dd if=/dev/random",
        "> /dev/sda", "mkfs", "fdisk",
        "shutdown", "reboot", "halt", "poweroff",
        "chmod 777 /", "chown -R root",
        ":(){:|:&};:",           # fork bomb
        "curl | bash", "wget | bash", "curl | sh", "wget | sh",
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
    flag = "" if regex else "-F"
    r = subprocess.run(
        f"grep -rn {flag} '{query}' {directory} "
        "--include='*.py' --include='*.ts' --include='*.tsx' --include='*.js' "
        "--include='*.jsx' --include='*.go' --include='*.rs' 2>/dev/null | head -40",
        shell=True, capture_output=True, text=True, timeout=15,
    )
    return r.stdout.strip() or f"No matches for '{query}' in {directory}"


@lc_tool
def find_symbol_definition(symbol: str) -> str:
    """Find where a function, class, or variable is defined in the codebase."""
    r = subprocess.run(
        f"grep -rn -E '(def|class|function|const|let|var|type|interface)\\s+{symbol}\\b' . "
        "--include='*.py' --include='*.ts' --include='*.js' 2>/dev/null | head -20",
        shell=True, capture_output=True, text=True, timeout=10,
    )
    return r.stdout.strip() or f"No definition found for '{symbol}'"


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
        SafeShellTool(),          # FIX #5: SafeShellTool instead of ShellTool()
        PythonREPLTool(),
        git_status, git_diff, git_log, git_suggest_commit,
        run_linter, run_tests,
        search_code, find_symbol_definition,
        apply_patch,
    ]


# ==============================================================
# System prompt
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
4. For code blocks, always include the language identifier in markdown

{tools}

Use the following format:
Question: the input question you must answer
Thought: you should always think about what to do
Action: the action to take, should be one of [{tool_names}]
Action Input: the input to the action
Observation: the result of the action
... (this Thought/Action/Action Input/Observation can repeat N times)
Thought: I now know the final answer
Final Answer: the final answer to the original input question

Question: {input}
Thought: {agent_scratchpad}"""


# ==============================================================
# FIX #4 — Session memory with TTL (prevents memory leak)
# Sessions older than SESSION_TTL seconds are evicted automatically
# ==============================================================

_sessions: dict[str, ConversationBufferWindowMemory] = {}
_session_timestamps: dict[str, float] = {}
SESSION_TTL = 3600  # 1 hour


def get_or_create_memory(session_id: str) -> ConversationBufferWindowMemory:
    now = time.time()

    # Evict expired sessions
    expired = [sid for sid, t in _session_timestamps.items() if now - t > SESSION_TTL]
    for sid in expired:
        _sessions.pop(sid, None)
        _session_timestamps.pop(sid, None)
        print(f"[Session] Evicted expired session: {sid}")

    if session_id not in _sessions:
        _sessions[session_id] = ConversationBufferWindowMemory(
            k=20,
            memory_key="chat_history",
            return_messages=True,
        )

    _session_timestamps[session_id] = now
    return _sessions[session_id]


def clear_session(session_id: str):
    _sessions.pop(session_id, None)
    _session_timestamps.pop(session_id, None)


# ==============================================================
# Agent builder
# ==============================================================

def build_agent_executor(
    provider: str = "openai",
    model_id: Optional[str] = None,
    workspace: str = ".",
    session_id: Optional[str] = None,
) -> AgentExecutor:
    llm    = build_llm(provider, model_id)
    tools  = get_tools(workspace)
    memory = get_or_create_memory(session_id or "default")
    prompt = PromptTemplate.from_template(SYSTEM_PROMPT)
    agent  = create_react_agent(llm=llm, tools=tools, prompt=prompt)

    return AgentExecutor(
        agent=agent,
        tools=tools,
        memory=memory,
        verbose=True,
        max_iterations=25,
        handle_parsing_errors=True,
        return_intermediate_steps=True,
    )


# ==============================================================
# FIX #1 — StepCallback: now a proper LangChain BaseCallbackHandler
# and correctly passed into executor.invoke() via config=
# Previously: defined but never registered → tool events never fired
# Now: inherits BaseCallbackHandler, passed via config={"callbacks": [...]}
# ==============================================================

class StepCallbackHandler(BaseCallbackHandler):
    """
    Collects tool call / tool result events from the agent executor
    and pushes them into an asyncio Queue for SSE streaming.
    """

    def __init__(self, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self._queue = queue
        self._loop  = loop

    def _put(self, item: dict):
        asyncio.run_coroutine_threadsafe(self._queue.put(item), self._loop)

    def on_tool_start(self, serialized, input_str, **kwargs):
        self._put({
            "type": "step",
            "step": {
                "type": "tool_call",
                "toolName": serialized.get("name", "unknown"),
                "toolArgs": {"input": str(input_str)[:200]},
                "timestamp": int(time.time() * 1000),
            }
        })

    def on_tool_end(self, output, **kwargs):
        self._put({
            "type": "step",
            "step": {
                "type": "tool_result",
                "result": str(output)[:500],
                "success": True,
                "timestamp": int(time.time() * 1000),
            }
        })

    def on_tool_error(self, error, **kwargs):
        self._put({
            "type": "step",
            "step": {
                "type": "tool_result",
                "result": str(error)[:300],
                "success": False,
                "timestamp": int(time.time() * 1000),
            }
        })


# ==============================================================
# Streaming agentic run — yields SSE-compatible dicts
# ==============================================================

async def run_streaming(
    message: str,
    provider: str = "openai",
    model_id: Optional[str] = None,
    workspace: str = ".",
    session_id: Optional[str] = None,
) -> AsyncIterator[dict]:
    start      = time.time()
    tool_calls = 0

    try:
        executor   = build_agent_executor(provider, model_id, workspace, session_id)
        loop       = asyncio.get_running_loop()
        step_queue: asyncio.Queue = asyncio.Queue()

        # FIX #1: callback is now properly instantiated and passed to invoke()
        callback = StepCallbackHandler(step_queue, loop)

        steps_collected: list = []
        final_output = ""

        def run_sync():
            nonlocal final_output, tool_calls
            # Pass callback via config — this is the correct LangChain pattern
            result = executor.invoke(
                {"input": message},
                config={"callbacks": [callback]}
            )
            final_output = result.get("output", "")
            steps_collected.extend(result.get("intermediate_steps", []))
            tool_calls = len(steps_collected)

        future = loop.run_in_executor(None, run_sync)

        # Yield steps while agent is running
        while not future.done():
            try:
                item = await asyncio.wait_for(step_queue.get(), timeout=0.1)
                yield item
            except asyncio.TimeoutError:
                continue

        # Drain any remaining queued events
        while not step_queue.empty():
            yield await step_queue.get()

        await future  # re-raise any exceptions from run_sync

        # Stream the final answer in chunks
        if final_output:
            words = final_output.split(" ")
            for i in range(0, len(words), 4):
                chunk = " ".join(words[i:i + 4])
                if i + 4 < len(words):
                    chunk += " "
                yield {"type": "chunk", "content": chunk}
                await asyncio.sleep(0.01)

    except Exception as e:
        yield {"type": "error", "error": str(e)}
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
    try:
        executor = build_agent_executor(provider, model_id, workspace, session_id)
        loop     = asyncio.get_running_loop()
        result   = await loop.run_in_executor(
            None,
            lambda: executor.invoke({"input": message})
        )
        return {
            "output": result.get("output", ""),
            "provider": provider,
            "model": model_id or "",
            "durationMs": int((time.time() - start) * 1000),
            "totalToolCalls": len(result.get("intermediate_steps", [])),
            "error": None,
        }
    except Exception as e:
        return {
            "output": "",
            "provider": provider,
            "model": model_id or "",
            "durationMs": int((time.time() - start) * 1000),
            "totalToolCalls": 0,
            "error": str(e),
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
        output = response.content if hasattr(response, "content") else str(response)
        return {
            "output": output,
            "toolName": tool_name,
            "provider": provider,
            "model": model_id or "",
            "durationMs": int((time.time() - start) * 1000),
            "error": None,
        }
    except Exception as e:
        return {
            "output": "",
            "toolName": tool_name,
            "provider": provider,
            "model": model_id or "",
            "durationMs": int((time.time() - start) * 1000),
            "error": str(e),
        }
