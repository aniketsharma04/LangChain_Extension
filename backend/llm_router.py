# ==============================================================
# llm_router.py
#
# REPLACES: backend/src/router/LLMRouter.ts
#
# How: Instead of building our own multi-provider router from
# scratch, we import LiteLLM and LangChain provider wrappers
# directly. Zero custom routing logic written by us.
#
# Imports doing the heavy lifting:
#   from langchain_openai import ChatOpenAI
#   from langchain_google_genai import ChatGoogleGenerativeAI
#   from langchain_ollama import ChatOllama
#   from langchain_openai import ChatOpenAI  ← also handles vLLM
#   from litellm import completion            ← unified fallback
# ==============================================================

import os
from typing import Optional
from dataclasses import dataclass, field

# ── LangChain provider wrappers (pip install langchain-openai etc.) ──────────
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama

# ── LiteLLM — unified fallback router for anything else ─────────────────────
from langchain_community.chat_models import ChatLiteLLM


# ── Provider config store ─────────────────────────────────────────────────────
@dataclass
class ProviderConfig:
    name: str
    provider_type: str          # "cloud" | "local"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    default_model: Optional[str] = None
    models: list[str] = field(default_factory=list)


_providers: dict[str, ProviderConfig] = {}


def init_providers():
    """Populate provider registry from environment variables on startup."""
    global _providers

    if os.getenv("OPENAI_API_KEY"):
        _providers["openai"] = ProviderConfig(
            name="openai",
            provider_type="cloud",
            api_key=os.getenv("OPENAI_API_KEY"),
            default_model="gpt-4o",
            models=["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o3-mini"],
        )

    if os.getenv("GEMINI_API_KEY"):
        _providers["gemini"] = ProviderConfig(
            name="gemini",
            provider_type="cloud",
            api_key=os.getenv("GEMINI_API_KEY"),
            default_model="gemini-2.0-flash",
            models=["gemini-2.5-pro", "gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
        )

    # Ollama — always registered, no key needed
    _providers["ollama"] = ProviderConfig(
        name="ollama",
        provider_type="local",
        base_url=os.getenv("OLLAMA_URL", "http://localhost:11434"),
        default_model="llama3.2",
        models=[],  # populated dynamically when probed
    )

    if os.getenv("VLLM_URL"):
        _providers["vllm"] = ProviderConfig(
            name="vllm",
            provider_type="local",
            base_url=os.getenv("VLLM_URL"),
            models=[],
        )


def update_provider(name: str, api_key: Optional[str] = None,
                    base_url: Optional[str] = None, models: Optional[list] = None):
    cfg = _providers.get(name)
    if cfg:
        if api_key:    cfg.api_key    = api_key
        if base_url:   cfg.base_url   = base_url
        if models:     cfg.models     = models
    else:
        _providers[name] = ProviderConfig(
            name=name, provider_type="custom",
            api_key=api_key, base_url=base_url, models=models or [],
        )


def add_custom_provider(name: str, base_url: str,
                        api_key: Optional[str], models: list[str]):
    _providers[name] = ProviderConfig(
        name=name, provider_type="local",
        api_key=api_key, base_url=base_url, models=models,
    )


def list_providers() -> list[ProviderConfig]:
    return list(_providers.values())


def get_provider(name: str) -> Optional[ProviderConfig]:
    return _providers.get(name)


# ── Core: build a LangChain chat model for any provider ──────────────────────

def build_llm(provider: str, model_id: Optional[str] = None, temperature: float = 0.2):
    """
    Returns a LangChain BaseChatModel for the requested provider.

    This is the ONLY function that constructs LLM objects.
    All construction delegates to LangChain provider packages or LiteLLM.
    No custom HTTP calls, no custom token counting, no custom retry logic —
    LangChain and LiteLLM handle all of that.
    """
    cfg = _providers.get(provider)

    # ── OpenAI ────────────────────────────────────────────────────────────────
    if provider == "openai":
        return ChatOpenAI(
            model=model_id or (cfg.default_model if cfg else "gpt-4o"),
            api_key=cfg.api_key if cfg else os.getenv("OPENAI_API_KEY", ""),
            temperature=temperature,
            streaming=True,        # enables token-by-token streaming
        )

    # ── Gemini ────────────────────────────────────────────────────────────────
    elif provider == "gemini":
        return ChatGoogleGenerativeAI(
            model=model_id or (cfg.default_model if cfg else "gemini-2.0-flash"),
            google_api_key=cfg.api_key if cfg else os.getenv("GEMINI_API_KEY", ""),
            temperature=temperature,
        )

    # ── Ollama (local) ────────────────────────────────────────────────────────
    elif provider == "ollama":
        base = cfg.base_url if cfg else os.getenv("OLLAMA_URL", "http://localhost:11434")
        return ChatOllama(
            model=model_id or (cfg.default_model if cfg else "llama3.2"),
            base_url=base,
            temperature=temperature,
        )

    # ── vLLM — OpenAI-compatible endpoint ─────────────────────────────────────
    elif provider == "vllm":
        base = cfg.base_url if cfg else os.getenv("VLLM_URL", "http://localhost:8000")
        return ChatOpenAI(
            model=model_id or "default",
            base_url=f"{base}/v1",
            api_key="none",         # vLLM doesn't need a real key
            temperature=temperature,
            streaming=True,
        )

    # ── Custom provider (OpenAI-compatible) ───────────────────────────────────
    elif cfg and cfg.base_url:
        return ChatOpenAI(
            model=model_id or (cfg.models[0] if cfg.models else "default"),
            base_url=f"{cfg.base_url}/v1",
            api_key=cfg.api_key or "none",
            temperature=temperature,
            streaming=True,
        )

    # ── Fallback: LiteLLM handles anything else ───────────────────────────────
    else:
        return ChatLiteLLM(
            model=f"{provider}/{model_id}" if model_id else provider,
            temperature=temperature,
        )


# ── Provider health probe ─────────────────────────────────────────────────────

async def probe_provider(name: str) -> dict:
    """Check if a provider is reachable and return its available models."""
    cfg = _providers.get(name)
    try:
        if name == "ollama":
            import httpx
            base = cfg.base_url if cfg else "http://localhost:11434"
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get(f"{base}/api/tags")
                if r.status_code == 200:
                    models = [m["name"] for m in r.json().get("models", [])]
                    return {"provider": name, "type": "local", "models": models}
            return {"provider": name, "type": "local", "models": [], "error": "unreachable"}

        elif name == "vllm":
            import httpx
            base = cfg.base_url if cfg else "http://localhost:8000"
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get(f"{base}/v1/models")
                if r.status_code == 200:
                    models = [m["id"] for m in r.json().get("data", [])]
                    return {"provider": name, "type": "local", "models": models}
            return {"provider": name, "type": "local", "models": [], "error": "unreachable"}

        else:
            # Cloud providers — just return configured model list
            return {
                "provider": name,
                "type": cfg.provider_type if cfg else "cloud",
                "models": cfg.models if cfg else [],
            }
    except Exception as e:
        return {"provider": name, "type": "unknown", "models": [], "error": str(e)}
