"""LLM provider abstraction module."""

from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.providers.logging_provider import LLMLoggingProvider

try:
    from nanobot.providers.litellm_provider import LiteLLMProvider
except ModuleNotFoundError:  # pragma: no cover - optional dependency at import time.
    LiteLLMProvider = None  # type: ignore[assignment]

try:
    from nanobot.providers.openai_codex_provider import OpenAICodexProvider
except ModuleNotFoundError:  # pragma: no cover - optional dependency at import time.
    OpenAICodexProvider = None  # type: ignore[assignment]

__all__ = [
    "LLMProvider",
    "LLMResponse",
    "LiteLLMProvider",
    "LLMLoggingProvider",
    "OpenAICodexProvider",
]
