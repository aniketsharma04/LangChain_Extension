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
from openclaw_bridge import get_openclaw_tools

# ── Our LLM router ────────────────────────────────────────────────────────────
from llm_router import build_llm

logger = logging.getLogger('navyug.agent')

# Module-level workspace — set by get_tools() so custom @lc_tool functions
# automatically resolve "." to the user's opened project, not the backend CWD.
_current_workspace: str = "."


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



@lc_tool
def terminal(commands: str) -> str:
    """
    Execute shell commands or common workspace shortcuts.
    The tool automatically handles blocked commands for safety.
    
    Shortcuts:
      'short:test'        - Run the project test suite
      'short:lint'        - Lint the active file path
      'short:git-status'  - Show git status
      'short:git-diff'    - Show git diff
      'short:git-log'     - Show compact git history
      'short:summary'    - Summarize tech stack config
      'short:overview'   - Show project's key files/directories
    
    Examples:
      'ls -la'
      'pip install requests'
      'short:test'
    """
    # 1) Robust input coercion (fixes list object has no attribute 'lower')
    if isinstance(commands, list):
        cmd_str = " && ".join(str(c) for c in commands)
    elif isinstance(commands, dict):
        # Some LLMs wrap arguments in a dict even when not asked
        cmd_str = str(commands.get("commands") or commands.get("input") or str(commands))
    else:
        cmd_str = str(commands)

    # 2) Handle shortcuts (FIX: call logic functions, not @lc_tool objects)
    if cmd_str.startswith("short:"):
        s = cmd_str.replace("short:", "").strip().lower()
        if s == "test":       return _run_tests_logic()
        if s == "git-status": return _git_status_logic()
        if s == "git-diff":   return _git_diff_logic()
        if s == "git-log":    return _git_log_logic()
        if s == "summary":    return _get_project_summary_logic()
        if s == "overview":   return _project_overview_logic()
        # Note: linting requires a path, so we can't easily auto-shortcut it without context
        if s == "lint":       return "Shortcut error: 'short:lint' requires a file path. Use 'run_linter(path)' instead."
        return f"Unknown shortcut: {s}"

    # 3) Blocklist check
    BLOCKED = [
        "rm -rf /", "rm -rf ~", "sudo rm", "sudo dd", "mkfs", "fdisk",
        "shutdown", "reboot", "format c:", "del /s /q", "rd /s /q"
    ]
    lower_cmd = cmd_str.lower()
    for pattern in BLOCKED:
        if pattern in lower_cmd:
            return f"❌ Blocked: '{pattern}' is not permitted for safety."

    # 4) Safe execution
    try:
        r = subprocess.run(
            cmd_str,
            shell=True,
            capture_output=True,
            text=True,
            cwd=_current_workspace,
            timeout=60
        )
        out = (r.stdout + r.stderr).strip()
        return out or f"Command executed (no output). Status code: {r.returncode}"
    except subprocess.TimeoutExpired:
        return "❌ Error: Command timed out after 60 seconds."
    except Exception as e:
        return f"❌ Execution error: {str(e)}"


# --- Internal Logic Functions (to avoid 'StructuredTool' object is not callable) ---

def _git_status_logic() -> str:
    r = subprocess.run(
        "git status --short && echo '---' && git branch --show-current",
        shell=True, capture_output=True, text=True, cwd=_current_workspace
    )
    return r.stdout.strip() or "Not a git repo or clean working tree"

def _git_diff_logic(staged: bool = False) -> str:
    flag = "--cached" if staged else ""
    r = subprocess.run(f"git diff {flag} | head -300", shell=True, capture_output=True, text=True, cwd=_current_workspace)
    return r.stdout.strip() or "No changes to diff"

def _git_log_logic(limit: int = 10) -> str:
    r = subprocess.run(f"git log --oneline --graph -{limit}", shell=True, capture_output=True, text=True, cwd=_current_workspace)
    return r.stdout.strip() or "No git history"

def _run_tests_logic(file_path: str = "", runner: str = "auto") -> str:
    from pathlib import Path
    root = Path(_current_workspace).resolve()
    
    if runner == "auto":
        if (root / "pytest.ini").exists() or (root / "pyproject.toml").exists():
            runner = "pytest"
        elif (root / "package.json").exists():
            with open(root / "package.json") as f:
                content = f.read()
                runner = "vitest" if "vitest" in content else "jest"
        else:
            runner = "pytest"
            
    file_arg = f"'{file_path}'" if file_path else ""
    # Use python -m for pytest to ensure correct environment
    cmds = {
        "jest":   f"npx jest {file_arg} 2>&1 | tail -50",
        "vitest": f"npx vitest run {file_arg} 2>&1 | tail -50",
        "pytest": f"python -m pytest {file_arg} -v 2>&1 | tail -60",
    }
    cmd = cmds.get(runner, cmds["pytest"])
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120, cwd=str(root))
        return (r.stdout + r.stderr).strip() or f"No output from {runner}"
    except Exception as e:
        return f"Test error: {e}"

def _get_project_summary_logic(directory: str = ".") -> str:
    # Resolve relative to _current_workspace
    root = Path(_current_workspace).resolve()
    if directory != ".":
        root = (root / directory).resolve()
    
    if not root.exists():
        return f"Error: Directory {directory} not found in {_current_workspace}"

    indicators = {
        "package.json": "Node.js/NPM project",
        "tsconfig.json": "TypeScript project",
        "requirements.txt": "Python project (pip)",
        "pyproject.toml": "Python project (poetry/flit)",
        "venv": "Python virtual environment",
        ".venv": "Python virtual environment",
        "go.mod": "Go project",
        "Cargo.toml": "Cargo (Rust) project",
        "tailwind.config.js": "Tailwind CSS detected",
        "vite.config.ts": "Vite project detected",
        "vite.config.js": "Vite project detected",
        "next.config.js": "Next.js project detected",
        "next.config.mjs": "Next.js project detected",
        "Makefile": "C/C++ or build-script project",
        "CMakeLists.txt": "CMake (C/C++) project",
        "SOLUTION.sln": "Visual Studio Solution",
    }

    found = []
    for file, desc in indicators.items():
        if (root / file).exists():
            found.append(f"- {file}: {desc}")

    for folder in ["src", "backend", "frontend", "app", "lib", "components"]:
        if (root / folder).is_dir():
            found.append(f"- {folder}/ directory exists")

    return "Project tech stack indicators:\n" + "\n".join(found) if found else "No major tech stack indicators found."

def _project_overview_logic(directory: str = ".", max_depth: int = 2) -> str:
    """Generate a tree-like overview of the project structure."""
    from pathlib import Path
    
    # Resolve relative to _current_workspace
    root = Path(_current_workspace).resolve()
    if directory != ".":
        root = (root / directory).resolve()
    
    if not root.exists():
        return f"Error: Directory {directory} not found in {_current_workspace}"

    IGNORE = {
        "node_modules", ".git", "venv", ".venv", "__pycache__",
        "build", "dist", ".next", ".cache", "obj", "bin"
    }

    lines = [f"Project Overview: {root.name}"]
    
    def walk(curr: Path, depth: int, prefix: str):
        if depth > max_depth:
            return
        
        try:
            items = sorted(curr.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        except PermissionError:
            return

        for i, item in enumerate(items):
            if item.name in IGNORE:
                continue
                
            is_last = (i == len(items) - 1)
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{item.name}{'/' if item.is_dir() else ''}")
            
            if item.is_dir():
                walk(item, depth + 1, prefix + ("    " if is_last else "│   "))

    walk(root, 1, "")
    return "\n".join(lines)


# ==============================================================
# Custom dev tools — git, linting, testing, code search
# ==============================================================

@lc_tool
def git_status() -> str:
    """Get git repository status: current branch, staged and unstaged changes."""
    return _git_status_logic()


@lc_tool
def git_diff(staged: bool = False) -> str:
    """Get git diff of current changes. Set staged=True for staged diff."""
    return _git_diff_logic(staged)


@lc_tool
def git_log(limit: int = 10) -> str:
    """Get recent git commit history as a compact graph."""
    return _git_log_logic(limit)


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
    """Run appropriate linter on a file. Auto-detects Ruff, Pylint, ESLint, ShellCheck, etc."""
    from pathlib import Path
    root = Path(_current_workspace).resolve()
    abs_path = (root / file_path).resolve()
    ext = abs_path.suffix.lower()

    if not abs_path.exists():
        return f"Error: File {file_path} not found in {_current_workspace}"

    # Python logic
    if ext == ".py":
        # Check for ruff first (faster/modern)
        if (root / "ruff.toml").exists() or (root / ".ruff.toml").exists() or \
           ("ruff" in (root / "pyproject.toml").read_text() if (root / "pyproject.toml").exists() else False):
            cmd = f"ruff check '{abs_path}'"
        else:
            cmd = f"pylint '{abs_path}' --score=no"

    # JS/TS logic
    elif ext in (".js", ".jsx", ".ts", ".tsx"):
        if ext in (".ts", ".tsx") and (root / "tsconfig.json").exists():
            cmd = f"npx tsc --noEmit --project '{root}/tsconfig.json'"
        else:
            cmd = f"npx eslint '{abs_path}' --format compact"

    # Shell logic
    elif ext in (".sh", ".bash"):
        cmd = f"shellcheck '{abs_path}'"

    # Default/Unknown
    else:
        return f"No specialized linter configured for {ext} files."

    try:
        r = subprocess.run(
            cmd + " 2>&1 | head -50",
            shell=True, capture_output=True, text=True, timeout=30, cwd=str(root)
        )
        out = (r.stdout + r.stderr).strip()
        return out or f"✅ No issues found in {file_path}"
    except Exception as e:
        return f"Linter error: {e}"


@lc_tool
def run_tests(file_path: str = "", runner: str = "auto") -> str:
    """Run test suite. Supports jest, vitest, pytest. Set runner='auto' to detect automatically."""
    return _run_tests_logic(file_path, runner)


@lc_tool
def search_code(query: str, directory: str = ".", regex: bool = False) -> str:
    """Search for a string or pattern across all project files in a directory.
    Searches code, styles, config, documentation, and markup files."""
    from pathlib import Path
    import re as _search_re

    EXTENSIONS = {
        # Code
        ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".cs", ".cpp", ".c", ".rb",
        # Web / styles
        ".html", ".htm", ".css", ".scss", ".sass", ".less", ".svg",
        # Config / data
        ".json", ".yaml", ".yml", ".toml", ".xml", ".env", ".ini", ".cfg",
        # Documentation
        ".md", ".txt", ".rst",
        # Shell / misc
        ".sh", ".bat", ".ps1", ".dockerfile",
    }
    results = []
    pattern = _search_re.compile(query) if regex else None
    
    # Resolve relative to _current_workspace
    root = Path(_current_workspace).resolve()
    if directory != ".":
        root = (root / directory).resolve()
    
    if not root.exists():
        return f"Error: Directory {directory} not found in {_current_workspace}"

    try:
        for fpath in root.rglob("*"):
            if not fpath.is_file() or fpath.suffix.lower() not in EXTENSIONS:
                continue
            # Skip common non-source directories
            parts_lower = [p.lower() for p in fpath.parts]
            if any(skip in parts_lower for skip in ("node_modules", ".git", "venv", "__pycache__", ".venv", "build", "dist")):
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
def find_symbol_definition(symbol: str, directory: str = ".") -> str:
    """Find where a function, class, or variable is defined in the codebase."""
    from pathlib import Path
    import re as _sym_re

    EXTENSIONS = {
        ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs",
        ".java", ".cs", ".cpp", ".c", ".rb",
        ".html", ".css", ".scss",
    }
    pat = _sym_re.compile(
        r"(?:def|class|function|const|let|var|type|interface)\s+" + _sym_re.escape(symbol) + r"\b"
    )
    results = []
    root = Path(_current_workspace).resolve()
    if directory != ".":
        root = (root / directory).resolve()
    
    if not root.exists():
        return f"Error: Directory {directory} not found in {_current_workspace}"

    try:
        for fpath in root.rglob("*"):
            if not fpath.is_file() or fpath.suffix.lower() not in EXTENSIONS:
                continue
            parts_lower = [p.lower() for p in fpath.parts]
            if any(skip in parts_lower for skip in ("node_modules", ".git", "venv", "__pycache__", ".venv", "build", "dist")):
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
def find_file(pattern: str, directory: str = ".") -> str:
    """Find files by name or glob pattern in the project directory.
    Use this to locate a file by its name. Examples:
      find_file('App.css')       — find a specific file
      find_file('*.test.js')     — find all test files
      find_file('*.py')          — find all Python files
      find_file('package.json')  — find package.json files
    """
    from pathlib import Path

    # Resolve relative to _current_workspace
    root = Path(_current_workspace).resolve()
    if directory != ".":
        root = (root / directory).resolve()
    
    if not root.exists():
        return f"Error: Directory {directory} not found in {_current_workspace}"

    try:
        for fpath in root.rglob(pattern):
            if not fpath.is_file():
                continue
            parts_lower = [p.lower() for p in fpath.parts]
            if any(skip in parts_lower for skip in (
                "node_modules", ".git", "venv", "__pycache__", ".venv",
                "build", "dist", ".next", ".cache",
            )):
                continue
            try:
                rel = fpath.relative_to(root)
                size = fpath.stat().st_size
                results.append(f"{rel}  ({size} bytes)")
            except Exception:
                continue
            if len(results) >= 30:
                break
    except Exception as e:
        return f"Search error: {e}"

    return "\n".join(results) if results else f"No files matching '{pattern}' found in {directory}"


@lc_tool
def get_project_summary(directory: str = ".") -> str:
    """Summarizes the project's tech stack by looking for config files.
    Identifies if it's a React, Python, Node.js, or other type of project."""
    return _get_project_summary_logic(directory)


@lc_tool
def project_overview(directory: str = ".", max_depth: int = 2) -> str:
    """Get a tree-like overview of the project's key files and directories.
    Use this to understand the project structure and organization."""
    return _project_overview_logic(directory, max_depth)


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


def _read_key_files_logic() -> str:
    from pathlib import Path
    root = Path(_current_workspace).resolve()
    FILES = [
        "package.json", "requirements.txt", "pyproject.toml", "setup.py",
        "Cargo.toml", "go.mod", "docker-compose.yml", "Makefile"
    ]
    results = []
    for fname in FILES:
        fpath = root / fname
        if fpath.exists():
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")[:2000]
                results.append(f"--- {fname} ---\n{content}")
            except Exception as e:
                results.append(f"--- {fname} ---\nError reading: {e}")
    
    return "\n\n".join(results) if results else "No core config files found."


def _extract_existing_docs_logic() -> str:
    from pathlib import Path
    root = Path(_current_workspace).resolve()
    results = []
    
    # Check for README
    readme_files = list(root.glob("README*"))
    for r in readme_files:
        if r.is_file():
            try:
                content = r.read_text(encoding="utf-8", errors="replace")[:3000]
                results.append(f"--- Existing {r.name} ---\n{content}")
            except Exception: pass

    # Check for docs/ folder
    docs_dir = root / "docs"
    if docs_dir.is_dir():
        try:
            for f in list(docs_dir.glob("*.md"))[:5]:
                content = f.read_text(encoding="utf-8", errors="replace")[:1000]
                results.append(f"--- Doc: {f.name} ---\n{content}")
        except Exception: pass

    # Detect main entry points for docstrings
    entries = ["main.py", "app.py", "index.ts", "server.py", "agent_engine.py"]
    for e in entries:
        fpath = root / e
        if fpath.exists():
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
                import re
                match = re.search(r'^["\']{3}(.*?)["\']{3}', text, re.DOTALL)
                if match:
                    results.append(f"--- Docstring from {e} ---\n{match.group(1).strip()}")
            except Exception: pass

    return "\n\n".join(results) if results else "No existing documentation found."


def _write_readme_to_file_logic(readme_content: str, mode: str = "create") -> str:
    from pathlib import Path
    root = Path(_current_workspace).resolve()
    target = root / "README.md"
    
    try:
        if mode == "create" and target.exists():
            target = root / "README_generated.md"
            target.write_text(readme_content, encoding="utf-8")
            return f"✅ README.md already existed. Generated new one at: {target.name}"
        
        target.write_text(readme_content, encoding="utf-8")
        verb = "created" if mode == "create" else "updated"
        return f"✅ README.md {verb} successfully at: {target.absolute()}"
    except Exception as e:
        return f"❌ Error writing README: {str(e)}"


@lc_tool
def read_key_files() -> str:
    """Read core project configuration files to detect tech stack and project metadata.
    Reads package.json, requirements.txt, pyproject.toml, setup.py, Cargo.toml,
    go.mod, docker-compose.yml, and Makefile if they exist.
    Truncates each file to 2000 characters."""
    return _read_key_files_logic()


@lc_tool
def extract_existing_docs() -> str:
    """Extract existing documentation hints from README, docs/ folder, and module docstrings.
    Helps understand the project's purpose and existing documentation style."""
    return _extract_existing_docs_logic()


@lc_tool
def write_readme_to_file(readme_content: str, mode: str = "create") -> str:
    """Write or update the README.md file in the project root.
    Use mode='create' for new projects or mode='update' for existing ones.
    In 'create' mode, if README.md exists, it saves as README_generated.md to avoid overwriting."""
    return _write_readme_to_file_logic(readme_content, mode)


def _readme_creation_agent_logic(user_request: str) -> str:
    try:
        # 1. Build a local toolset for the sub-agent
        # We filter out the agent tool itself to prevent infinite recursion
        all_tools = get_tools(_current_workspace)
        sub_tools = [t for t in all_tools if getattr(t, "name", "") != "readme_creation_agent"]
        
        # 2. Get the LLM (same provider as main brain if possible)
        from llm_router import build_llm, list_providers
        
        # Try to find an active provider
        available = [p.name for p in list_providers()]
        provider = "gemini" if "gemini" in available else ("openai" if "openai" in available else (available[0] if available else "openai"))
        
        llm = build_llm(provider=provider)
        
        # 3. Create the specialized agent
        agent = create_react_agent(
            llm,
            sub_tools,
            prompt=README_SYSTEM_PROMPT,
        )
        
        logger.info(f"README Agent activated for request: {user_request}")
        
        # 4. Run the sub-agent loop
        # We need a dedicated event loop if one isn't already running, 
        # or use the existing one. For safety in a multi-threaded/async environment:
        try:
            loop = asyncio.get_running_loop()
            import threading
            from concurrent.futures import ThreadPoolExecutor
            
            def _run_sync():
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    return new_loop.run_until_complete(agent.ainvoke(
                        {"messages": [HumanMessage(content=user_request)]}
                    ))
                finally:
                    new_loop.close()
            
            with ThreadPoolExecutor(max_workers=1) as executor:
                result = executor.submit(_run_sync).result(timeout=120)
        except RuntimeError:
            # No loop running, fine to create one
            result = asyncio.run(agent.ainvoke(
                {"messages": [HumanMessage(content=user_request)]}
            ))
        except Exception as e:
            return f"❌ Sub-agent execution failed: {e}"
        
        # 5. Extract the final answer
        final_msg = result["messages"][-1].content
        return _to_str(final_msg)
        
    except Exception as e:
        logger.error(f"README Agent Error: {e}")
        return f"❌ README Agent failed: {str(e)}"


@lc_tool
def readme_creation_agent(user_request: str) -> str:
    """Specialized documentation agent. Call this whenever the user wants to CREATE, 
    UPDATE, IMPROVE, or FIX a README or project documentation.
    
    Input: The user's specific request about documentation.
    Output: Result of the documentation task (e.g., success message and file path).
    """
    return _readme_creation_agent_logic(user_request)


# ==============================================================
# Web search tool — DuckDuckGo (free) or Tavily (if key set)
# ==============================================================

def _build_web_search_tool():
    """
    Returns a web search LangChain tool.
    Uses Tavily if TAVILY_API_KEY is set (better quality),
    otherwise falls back to DuckDuckGo (free, no key needed).
    """
    tavily_key = os.getenv("TAVILY_API_KEY")
    if tavily_key:
        try:
            from langchain_community.tools.tavily_search import TavilySearchResults
            logger.info("Web search: using Tavily (API key detected)")
            return TavilySearchResults(
                max_results=5,
                search_depth="advanced",
                name="web_search",
                description=(
                    "Search the web for current information, news, facts, "
                    "people, events, or any real-time data. Returns top results "
                    "with titles, snippets, and URLs. Use this whenever the user "
                    "asks about recent events, live data, or anything outside "
                    "the local codebase."
                ),
            )
        except Exception as e:
            logger.warning(f"Tavily import failed, falling back to DuckDuckGo: {e}")

    # Fallback: DuckDuckGo (free, no API key)
    @lc_tool
    def web_search(query: str, max_results: int = 5) -> str:
        """Search the web for current information, news, facts, people, events,
        or any real-time data. Returns top results with titles, snippets, and URLs.
        Use this whenever the user asks about recent events, live data, or anything
        outside the local codebase."""
        try:
            from ddgs import DDGS
        except ImportError:
            return ("\u274c ddgs package not installed. "
                    "Run: pip install ddgs")

        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))

            if not results:
                return f"No web results found for: {query}"

            formatted = []
            for i, r in enumerate(results, 1):
                title = r.get("title", "No title")
                body = r.get("body", r.get("snippet", "No snippet"))
                href = r.get("href", r.get("link", ""))
                formatted.append(f"{i}. **{title}**\n   {body}\n   URL: {href}")

            return f"Web search results for '{query}':\n\n" + "\n\n".join(formatted)
        except Exception as e:
            return f"Web search error: {e}"

    logger.info("Web search: using DuckDuckGo (free, no API key)")
    return web_search


# ==============================================================
# Tool catalogue
# ==============================================================

def get_tools(workspace: str = ".") -> list:
    global _current_workspace
    _current_workspace = workspace
    logger.info(f"Tools workspace set to: {workspace}")
    tools = [
        ReadFileTool(root_dir=workspace),
        WriteFileTool(root_dir=workspace),
        ListDirectoryTool(root_dir=workspace),
        CopyFileTool(root_dir=workspace),
        MoveFileTool(root_dir=workspace),
        DeleteFileTool(root_dir=workspace),
        terminal,
        PythonREPLTool(),
        git_status, git_diff, git_log, git_suggest_commit,
        run_linter, run_tests,
        search_code, find_symbol_definition, find_file, get_project_summary,
        project_overview,
        read_key_files, extract_existing_docs, write_readme_to_file,
        readme_creation_agent,
        apply_patch,
        _build_web_search_tool(),
    ]
    # Add OpenClaw Ecosystem Tools
    try:
        oc_tools = get_openclaw_tools()
        tools.extend(oc_tools)
    except Exception as e:
        print(f"Warning: Failed to load OpenClaw tools: {e}")

    return tools


# ==============================================================
# System prompt (simplified for LangGraph — no ReAct template
# variables needed, LangGraph handles tool descriptions internally)
# ==============================================================

SYSTEM_PROMPT = """You are Navyug AI, the primary Orchestrator and 'Brain' for this VS Code workspace.

You have full access to the developer's workspace and tools.

## DELEGATION RULES
1. **README / Documentation**: If the user asks to create, update, improve, or fix a README or any project documentation, you MUST delegate the entire task to the `readme_creation_agent` tool. Send the user's full request to it and return its final response. Do NOT attempt to do documentation tasks yourself.

## Tools available
- **readme_creation_agent** — Specialized agent for documentation (Delegate ALL README tasks here)
- **ReadFileTool / WriteFileTool / ListDirectoryTool** — read, write, list files
- **CopyFileTool / MoveFileTool / DeleteFileTool** — manage files
- **terminal** — execute shell commands and common shortcuts (test, lint, git)
- **PythonREPLTool** — write and execute Python code
- **git_status / git_diff / git_log / git_suggest_commit** — git operations
- **run_linter** — lint a file (pylint / eslint / tsc / mypy)
- **run_tests** — run tests (pytest / jest / vitest)
- **search_code** — grep across all project files (code, CSS, HTML, JSON, config, docs)
- **project_overview** — get a tree-like overview of the project structure
- **find_file** — find files by name or glob pattern (e.g. 'App.css', '*.test.js')
- **find_symbol_definition** — find where a function/class is defined
- **apply_patch** — apply a unified diff patch to a file
- **web_search** — search the web for current news, facts, people, events, real-time data

## Rules
1. Always **read before editing** — use ReadFileTool first
2. **Verify after changes** — run_linter or run_tests after edits
3. Show **git diff** after making file changes
4. For code blocks, always include the language identifier in markdown
5. When the user asks about current events, news, people, or anything outside the codebase, use **web_search** proactively
6. Cite sources with URLs when presenting web search results
7. When asked to find or locate a file, use **find_file** first — it is faster and more accurate than listing directories one by one
8. When asked to search for text content, use **search_code** — it searches ALL file types including CSS, HTML, JSON, Markdown, and config files
9. **File Extensions**: ALWAYS use appropriate file extensions (e.g., `.py` for Python, `.ts`/`.tsx` for TypeScript, `.c` for C, `.cpp` for C++, `.md` for Markdown, `.json` for JSON). NEVER create extensionless files for code or data.
10. **Tech Stack Consistency**: Before creating new files, check the project's tech stack using `get_project_summary` or by looking at existing files. Match the project's language and style (e.g., use C if the project is C-based).
11. **README Generation**: This task is handled by the specialized `readme_creation_agent`. Always delegate to it for anything related to READMEs or docs."""


# ==============================================================
# Specialized Agent Prompts
# ==============================================================

README_SYSTEM_PROMPT = """You are the specialized README Creation Agent. Your sole purpose is to create, update, and improve project documentation.

HOW TO DECIDE CREATE vs UPDATE MODE:
- Scan the project first using `project_overview`. If README.md already exists, AND the user said 'update', 'improve', 'fix', or 'add to' → UPDATE mode.
- If no README.md exists OR user said 'create', 'generate', 'write' → CREATE mode.
- If user says 'rewrite completely' → CREATE mode even if file exists.

CREATE MODE — follow this sequence:
1. Scan the project structure (`project_overview`) to understand what exists.
2. Read key config files (`read_key_files`) to detect tech stack and metadata.
3. Extract existing documentation (`extract_existing_docs`) to find code docstrings.
4. Compose a complete, professional README.md from scratch.
5. Save it to disk using `write_readme_to_file(mode='create')`.

UPDATE MODE — follow this sequence:
1. Read the EXISTING README.md first (`ReadFileTool`) — this is mandatory.
2. Scan the project structure (`project_overview`).
3. Read key config files (`read_key_files`).
4. Identify what is outdated, missing, or incorrect in the existing README.
5. Compose an improved version that KEEPS good content and fixes the rest.
6. Save it back to README.md using `write_readme_to_file(mode='update')`.
7. Tell the user exactly what you changed and why.

README STRUCTURE TO FOLLOW:
# Project Title
> One-line description
## 🚀 Overview
## ✨ Features  
## 🛠️ Tech Stack
## 📦 Installation
## 🔧 Usage
## 🏗️ Project Structure (paste the scanned folder tree here)
## 🤝 Contributing
## 📄 License

For UPDATE mode, respect the user's existing structure unless it is broken."""


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
