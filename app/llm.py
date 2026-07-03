"""
Multi-provider LLM client.

Supported providers (all via OpenAI-compatible SDK except Claude):
  ollama, openai, claude, qwen, gemini, deepseek, glm, copilot
"""

import os
import httpx
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

PROVIDERS = {
    "ollama": {
        "label": "Ollama (本地部署)",
        "base_url": "http://localhost:11434/v1",
        "default_model": "llama3:8b",
        "default_key": "ollama",
        "needs_key": False,
        "sdk": "openai",
        "models": [],
    },
    "openai": {
        "label": "ChatGPT (OpenAI)",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
        "default_key": "",
        "needs_key": True,
        "sdk": "openai",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4", "gpt-3.5-turbo", "o1", "o1-mini", "o3-mini"],
    },
    "claude": {
        "label": "Claude (Anthropic)",
        "base_url": "https://api.anthropic.com",
        "default_model": "claude-sonnet-4-20250514",
        "default_key": "",
        "needs_key": True,
        "sdk": "anthropic",
        "models": ["claude-sonnet-4-20250514", "claude-opus-4-20250514", "claude-3-5-haiku-20241022", "claude-3-5-sonnet-20241022", "claude-3-opus-20240229"],
    },
    "qwen": {
        "label": "通义千问 (Qwen)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
        "default_key": "",
        "needs_key": True,
        "sdk": "openai",
        "models": ["qwen-max", "qwen-plus", "qwen-turbo", "qwen-long", "qwen2.5-72b-instruct", "qwen2.5-32b-instruct", "qwen2.5-14b-instruct", "qwen2.5-7b-instruct"],
    },
    "copilot": {
        "label": "Copilot (Azure OpenAI)",
        "base_url": "https://models.inference.ai.azure.com",
        "default_model": "gpt-4o",
        "default_key": "",
        "needs_key": True,
        "sdk": "openai",
        "models": ["gpt-4o", "gpt-4o-mini", "o1", "o1-mini", "o3-mini"],
    },
    "gemini": {
        "label": "Gemini (Google)",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "default_model": "gemini-2.0-flash",
        "default_key": "",
        "needs_key": True,
        "sdk": "openai",
        "models": ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-pro", "gemini-1.5-flash", "gemini-1.5-flash-8b"],
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
        "default_key": "",
        "needs_key": True,
        "sdk": "openai",
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
    "glm": {
        "label": "智谱 GLM (ChatGLM)",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4-flash",
        "default_key": "",
        "needs_key": True,
        "sdk": "openai",
        "models": ["glm-4-plus", "glm-4-flash", "glm-4-long", "glm-4-flashx", "glm-4", "glm-4-air", "glm-4-airx", "glm-4-0520"],
    },
}


async def list_models(provider: str | None = None, base_url: str | None = None) -> list[str]:
    """Return available models. For Ollama, query the server; others use static lists."""
    p = provider or get_config().get("provider", "ollama")
    meta = PROVIDERS.get(p, PROVIDERS["ollama"])

    if p == "ollama":
        url = base_url or get_config().get("base_url", meta["base_url"])
        api_url = url.rstrip("/")
        if api_url.endswith("/v1"):
            api_url = api_url[:-3].rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{api_url}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception:
            return meta.get("models", [])

    return meta.get("models", [])

_openai_client: AsyncOpenAI | None = None
_anthropic_client = None
_active_cfg: dict | None = None


def _env_config() -> dict:
    """Build config from environment variables (legacy fallback)."""
    provider = os.getenv("LLM_PROVIDER", "ollama")
    meta = PROVIDERS.get(provider, PROVIDERS["ollama"])
    base_url = os.getenv("LLM_BASE_URL", meta["base_url"])
    if provider == "ollama" and not base_url.rstrip("/").endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"
    return {
        "provider": provider,
        "base_url": base_url,
        "api_key": os.getenv("LLM_API_KEY", meta["default_key"]),
        "model": os.getenv("LLM_MODEL", meta["default_model"]),
        "context_window": int(os.getenv("LLM_CONTEXT_WINDOW", "20000")),
        "timeout": int(os.getenv("LLM_REQUEST_TIMEOUT", "3600")),
    }


def get_config() -> dict:
    global _active_cfg
    if _active_cfg is None:
        _active_cfg = _env_config()
    return _active_cfg


def set_config(cfg: dict):
    """Hot-swap the active LLM config (called from admin API)."""
    global _active_cfg, _openai_client, _anthropic_client
    _active_cfg = cfg
    _openai_client = None
    _anthropic_client = None


def _get_openai_client(cfg: dict) -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        timeout = cfg.get("timeout", 3600)
        _openai_client = AsyncOpenAI(
            api_key=cfg["api_key"] or "no-key",
            base_url=cfg["base_url"],
            timeout=httpx.Timeout(timeout, connect=30.0),
        )
    return _openai_client


def _get_anthropic_client(cfg: dict):
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic
        _anthropic_client = anthropic.AsyncAnthropic(
            api_key=cfg["api_key"],
            timeout=cfg.get("timeout", 3600),
        )
    return _anthropic_client


async def _chat_openai(cfg: dict, messages: list[dict], temperature: float, max_tokens: int) -> str:
    client = _get_openai_client(cfg)
    response = await client.chat.completions.create(
        model=cfg["model"],
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""


async def _chat_anthropic(cfg: dict, messages: list[dict], temperature: float, max_tokens: int) -> str:
    client = _get_anthropic_client(cfg)
    system_parts = [m["content"] for m in messages if m["role"] == "system"]
    chat_msgs = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]
    if not chat_msgs:
        chat_msgs = [{"role": "user", "content": "请开始。"}]
    response = await client.messages.create(
        model=cfg["model"],
        max_tokens=max_tokens,
        system="\n\n".join(system_parts) if system_parts else "",
        messages=chat_msgs,
        temperature=temperature,
    )
    return response.content[0].text if response.content else ""


async def chat_completion(
    messages: list[dict],
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> str:
    cfg = get_config()
    ctx = cfg.get("context_window", 20000)
    if max_tokens > ctx:
        max_tokens = ctx

    provider = cfg.get("provider", "ollama")
    meta = PROVIDERS.get(provider, PROVIDERS["ollama"])

    if meta["sdk"] == "anthropic":
        return await _chat_anthropic(cfg, messages, temperature, max_tokens)
    return await _chat_openai(cfg, messages, temperature, max_tokens)
