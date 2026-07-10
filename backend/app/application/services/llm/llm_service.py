"""
LLMService — application-layer facade over the LLMProvider ABC.

Responsibilities:
  - Validate CompletionRequests before forwarding to the provider
  - Emit structured log events for every completion (latency, tokens)
  - Expose provider health and model introspection to API routes
  - Provider-level exceptions propagate as-is (already mapped to AppExceptions
    in the concrete provider implementations)
"""
import structlog

from app.application.interfaces.llm_provider import LLMProvider
from app.application.services.llm.types import (
    CompletionRequest,
    CompletionResponse,
    ModelInfo,
)
from app.core.exceptions import BadRequestException

logger = structlog.get_logger(__name__)


class LLMService:
    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    # ── Core ────────────────────────────────────────────────────────────────

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Execute a chat completion via the configured provider.

        Raises:
            BadRequestException:     request has no messages.
            LLMUnavailableException: provider is unreachable / timed out.
            LLMException:            provider returned an API error.
        """
        if not request.messages:
            raise BadRequestException("CompletionRequest must contain at least one message")

        logger.debug(
            "llm_complete_start",
            provider=self._provider.provider_name,
            model=request.model or self._provider.default_model,
            message_count=len(request.messages),
        )

        response = await self._provider.complete(request)

        logger.info(
            "llm_complete_done",
            provider=self._provider.provider_name,
            model=response.model,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            latency_ms=response.latency_ms,
        )
        return response

    # ── Introspection ────────────────────────────────────────────────────────

    async def health_check(self) -> bool:
        """True when the underlying provider endpoint is reachable."""
        return await self._provider.health_check()

    async def list_models(self) -> list[ModelInfo]:
        """Models advertised by the provider, or [] on any transport error."""
        return await self._provider.list_models()

    # ── Properties forwarded from the provider ───────────────────────────────

    @property
    def provider_name(self) -> str:
        return self._provider.provider_name

    @property
    def default_model(self) -> str:
        return self._provider.default_model
