# ==============================================================
# custom_tool_manager.py
#
# REPLACES: backend/src/tools/custom/CustomToolManager.ts
#
# How: YAML loading via pyyaml, hot-reload via watchfiles.
# Custom tools dropped as .yaml files → auto-appear in the UI.
# ==============================================================

import os
import yaml
import asyncio
import threading
from typing import Optional
from pathlib import Path

from langchain.tools import StructuredTool
from pydantic import BaseModel, Field, ConfigDict


# ── Custom tool schema ────────────────────────────────────────────────────────

class CustomToolDef(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    display_name: str = Field(alias="displayName", default="")
    description: str = ""
    category: str = "custom"
    system_prompt: str = Field(alias="systemPrompt", default="")
    prompt_template: str = Field(alias="promptTemplate", default="")
    author: str = ""
    version: str = "1.0.0"
    enabled: bool = True
    parameters: dict = Field(default_factory=dict)


# ── Manager ───────────────────────────────────────────────────────────────────

class CustomToolManager:
    """
    Loads custom tools from YAML files in a directory.
    REPLACES: CustomToolManager.ts watchForChanges() + loadTool() + getAllTools()
    Uses:
      - pyyaml for YAML parsing (replaces js-yaml)
      - watchfiles for hot-reload (replaces chokidar)
    """

    def __init__(self, tools_dir: str = "./custom_tools"):
        self.tools_dir = Path(tools_dir)
        self.tools_dir.mkdir(parents=True, exist_ok=True)
        self._tools: dict[str, CustomToolDef] = {}
        self._reload_callbacks: list = []
        self._load_all()

    def _load_all(self):
        """Load all .yaml and .json tool definitions from the tools directory."""
        self._tools.clear()
        for f in self.tools_dir.glob("*.yaml"):
            self._load_file(f)
        for f in self.tools_dir.glob("*.yml"):
            self._load_file(f)
        for f in self.tools_dir.glob("*.json"):
            self._load_file(f)

    def _load_file(self, path: Path):
        try:
            with open(path, "r") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict) and "name" in data:
                tool = CustomToolDef(**data)
                if tool.enabled:
                    self._tools[tool.name] = tool
                    print(f"[CustomTools] Loaded: {tool.name}")
        except Exception as e:
            print(f"[CustomTools] Failed to load {path.name}: {e}")

    def get_all(self) -> list[dict]:
        """Return all custom tools as dicts (for API responses)."""
        return [
            {
                "name": t.name,
                "displayName": t.display_name or t.name,
                "description": t.description,
                "category": t.category,
                "enabled": t.enabled,
                "author": t.author,
                "version": t.version,
            }
            for t in self._tools.values()
        ]

    def get(self, name: str) -> Optional[CustomToolDef]:
        return self._tools.get(name)

    def save(self, tool_data: dict):
        """Save a new custom tool as a YAML file."""
        name = tool_data.get("name", "")
        if not name:
            raise ValueError("Tool name is required")
        path = self.tools_dir / f"{name}.yaml"
        with open(path, "w") as f:
            yaml.dump(tool_data, f, default_flow_style=False, allow_unicode=True)
        self._load_file(path)
        self._notify()

    def delete(self, name: str) -> bool:
        """Delete a custom tool YAML file."""
        for ext in [".yaml", ".yml", ".json"]:
            path = self.tools_dir / f"{name}{ext}"
            if path.exists():
                path.unlink()
                self._tools.pop(name, None)
                self._notify()
                return True
        return False

    def build_langchain_tool(
        self, tool_def: CustomToolDef, provider: str = "openai", model_id: Optional[str] = None
    ) -> StructuredTool:
        """
        Convert a YAML custom tool definition into a LangChain StructuredTool.
        The tool calls the LLM with the custom system + prompt template.
        """
        from llm_router import build_llm

        class CodeInput(BaseModel):
            code: str = Field(description="The code to process")
            language: str = Field(default="", description="Programming language")
            file_path: str = Field(default="", alias="filePath", description="File path")

        def execute(code: str, language: str = "", file_path: str = "") -> str:
            llm = build_llm(provider, model_id)
            prompt = tool_def.prompt_template.replace("{{args.code}}", code)
            prompt = prompt.replace("{{ctx.language}}", language)
            prompt = prompt.replace("{{ctx.filePath}}", file_path)
            msgs = []
            if tool_def.system_prompt:
                from langchain_core.messages import SystemMessage, HumanMessage
                msgs = [SystemMessage(content=tool_def.system_prompt), HumanMessage(content=prompt)]
            else:
                from langchain_core.messages import HumanMessage
                msgs = [HumanMessage(content=prompt)]
            response = llm.invoke(msgs)
            return response.content if hasattr(response, "content") else str(response)

        return StructuredTool.from_function(
            func=execute,
            name=tool_def.name,
            description=tool_def.description or f"Custom tool: {tool_def.display_name}",
            args_schema=CodeInput,
        )

    def watch_for_changes(self, callback=None):
        """
        Watch the tools directory for YAML file changes and hot-reload.
        REPLACES: chokidar watch in CustomToolManager.ts
        Uses: watchfiles (pip install watchfiles)
        """
        if callback:
            self._reload_callbacks.append(callback)

        def _watch():
            try:
                from watchfiles import watch as wf_watch
                for _ in wf_watch(str(self.tools_dir)):
                    print("[CustomTools] Change detected — reloading tools")
                    self._load_all()
                    self._notify()
            except Exception as e:
                print(f"[CustomTools] Watcher error: {e}")

        t = threading.Thread(target=_watch, daemon=True)
        t.start()

    def _notify(self):
        for cb in self._reload_callbacks:
            try:
                cb()
            except Exception:
                pass


# Singleton
custom_tool_manager = CustomToolManager(
    os.getenv("CUSTOM_TOOLS_DIR", "./custom_tools")
)
