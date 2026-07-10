"""
LLMProvider — Abstract Base Class for all LLM backend implementations.

Agents and services code against this interface exclusively.  Swapping
providers (OpenAI → Ollama → Azure) requires zero changes to caller code.
"""
from abc import ABC, abstractmethod

from app.application.services.llm.types import (
    CompletionRequest,
    CompletionResponse,
    ModelInfo,
)


class LLMProvider(ABC):
    """Port (in Hexagonal Architecture terms) that every concrete LLM
    adapter must implement."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider identifier, e.g. 'openai', 'ollama'."""
        ...

    @property
    @abstractmethod
    def default_model(self) -> str:
        """Model used when CompletionRequest.model is None."""
        ...

    @abstractmethod
    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Send a chat-completion request and return the normalised response.

        Raises:
            LLMUnavailableException: provider is unreachable or timed out.
            LLMException:            provider returned a non-2xx error.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True when the provider endpoint is reachable.

        Must never raise — swallow all transport/protocol errors and return
        False instead so that callers can degrade gracefully.
        """
        ...

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]:
        """Return models available on this provider.

        Returns an empty list (not raises) on any error.
        """
        ...
