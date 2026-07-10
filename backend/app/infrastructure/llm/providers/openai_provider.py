"""
OpenAI-compatible LLM provider.

A single implementation that drives every OpenAI-compatible endpoint:

  Provider    | LLM_PROVIDER | LLM_BASE_URL (example)
  ------------|--------------|------------------------------------
  OpenAI      | openai       | (omit — SDK default)
  LM Studio   | lmstudio     | http://localhost:1234/v1
  Ollama      | ollama       | http://localhost:11434/v1
  vLLM        | vllm         | http://localhost:8000/v1
  Azure OAI   | azure        | https://<resource>.openai.azure.com

All five share the same OpenAI SDK wire format.  Azure uses the SDK's
AzureOpenAI client (same interface, different auth + versioning).

Defaults optimised for local CPU inference (LM Studio / Ollama):
  temperature = 0.2   (set via CompletionRequest default)
  top_p       = 0.9   (set via CompletionRequest default)
  max_tokens  = 500   (set via CompletionRequest default)
  timeout     = 600 s (set via LLM_TIMEOUT config)
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncAzureOpenAI,
    AsyncOpenAI,
)

from app.application.interfaces.llm_provider import LLMProvider
from app.application.services.llm.types import (
    CompletionRequest,
    CompletionResponse,
    ModelInfo,
    UsageInfo,
)
from app.core.config import Settings
from app.core.exceptions import LLMException, LLMUnavailableException

logger = structlog.get_logger(__name__)

# Providers that use a local server and don't need a real API key.
_LOCAL_PROVIDERS: frozenset[str] = frozenset({"lmstudio", "ollama", "vllm"})

# Sensible default base URLs for well-known local providers.
_DEFAULT_BASE_URLS: dict[str, str] = {
    "lmstudio": "http://localhost:1234/v1",
    "ollama": "http://localhost:11434/v1",
    "vllm": "http://localhost:8000/v1",
}

# Placeholder API keys accepted by local servers that require a non-empty value.
_DEFAULT_API_KEYS: dict[str, str] = {
    "lmstudio": "lm-studio",
    "ollama": "ollama",
    "vllm": "EMPTY",
}

# Seconds to wait before the single reconnect attempt on a connection error.
_RETRY_DELAY_S: float = 2.0


class OpenAICompatibleProvider(LLMProvider):
    """Concrete adapter for OpenAI and any OpenAI-compatible endpoint."""

    def __init__(self, cfg: Settings) -> None:
        self._provider = cfg.LLM_PROVIDER.lower()
        self._model = cfg.LLM_MODEL
        self._timeout = cfg.LLM_TIMEOUT

        if self._provider == "azure":
            if not cfg.LLM_BASE_URL:
                raise ValueError(
                    "LLM_BASE_URL must be set to the Azure endpoint "
                    "(e.g. https://<resource>.openai.azure.com) when LLM_PROVIDER=azure"
                )
            self._client: AsyncOpenAI = AsyncAzureOpenAI(
                azure_endpoint=cfg.LLM_BASE_URL,
                api_key=cfg.LLM_API_KEY,
                api_version=cfg.LLM_AZURE_API_VERSION,
                timeout=self._timeout,
            )
        else:
            base_url = cfg.LLM_BASE_URL or _DEFAULT_BASE_URLS.get(self._provider)
            api_key = cfg.LLM_API_KEY or _DEFAULT_API_KEYS.get(self._provider)
            self._client = AsyncOpenAI(
                base_url=base_url,
                api_key=api_key,
                timeout=self._timeout,
            )

        logger.info(
            "llm_provider_initialised",
            provider=self._provider,
            model=self._model,
            base_url=cfg.LLM_BASE_URL or "(sdk default)",
            timeout=self._timeout,
        )

    # ── LLMProvider properties ───────────────────────────────────────────────

    @property
    def provider_name(self) -> str:
        return self._provider

    @property
    def default_model(self) -> str:
        return self._model

    # ── Core operations ──────────────────────────────────────────────────────

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Execute a chat completion with one automatic retry on connection errors.

        If the response is truncated (finish_reason="length"), the partial
        content is returned rather than raising — the workflow continues with
        whatever the model produced.
        """
        model = request.model or self._model
        messages: list[dict[str, str]] = [
            {"role": msg.role.value, "content": msg.content}
            for msg in request.messages
        ]

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": request.temperature,
            "top_p": request.top_p,
            "max_tokens": request.max_tokens,
        }

        t0 = time.monotonic()
        response = await self._call_with_retry(model, kwargs)
        latency_ms = int((time.monotonic() - t0) * 1000)

        choice = response.choices[0]
        finish_reason = getattr(choice, "finish_reason", None)
        usage = response.usage

        if finish_reason == "length":
            logger.warning(
                "llm_output_truncated",
                provider=self._provider,
                model=model,
                max_tokens=request.max_tokens,
                completion_tokens=usage.completion_tokens if usage else 0,
            )
            # Return partial content — do not raise.  Downstream nodes handle
            # incomplete output gracefully via their existing error paths.

        logger.info(
            "llm_completion",
            provider=self._provider,
            model=response.model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            finish_reason=finish_reason,
            latency_ms=latency_ms,
        )

        return CompletionResponse(
            content=choice.message.content or "",
            model=response.model,
            usage=UsageInfo(
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                total_tokens=usage.total_tokens if usage else 0,
            ),
            latency_ms=latency_ms,
            raw=response.model_dump(),
        )

    async def _call_with_retry(self, model: str, kwargs: dict[str, Any]) -> Any:
        """
        Call the completion endpoint once; on APIConnectionError or
        APITimeoutError wait _RETRY_DELAY_S seconds and try exactly once more.

        Re-raises as LLMUnavailableException if both attempts fail, or as
        LLMException for HTTP-level errors.
        """
        for attempt in range(2):
            try:
                return await self._client.chat.completions.create(**kwargs)
            except (APIConnectionError, APITimeoutError) as exc:
                if attempt == 0:
                    logger.warning(
                        "llm_connection_error_retrying",
                        provider=self._provider,
                        model=model,
                        attempt=attempt + 1,
                        retry_delay_s=_RETRY_DELAY_S,
                    )
                    await asyncio.sleep(_RETRY_DELAY_S)
                    continue
                # Second failure — give up.
                logger.warning(
                    "llm_connection_error_final",
                    provider=self._provider,
                    model=model,
                )
                raise LLMUnavailableException(
                    "LLM provider unreachable after retry"
                ) from exc
            except APIStatusError as exc:
                logger.warning(
                    "llm_status_error",
                    provider=self._provider,
                    model=model,
                    status_code=exc.status_code,
                )
                raise LLMException(
                    f"LLM provider returned HTTP {exc.status_code}: {exc.message}"
                ) from exc
        # Should never reach here, but satisfies the type checker.
        raise LLMUnavailableException("LLM provider unreachable")  # pragma: no cover

    async def health_check(self) -> bool:
        """Probe the /models endpoint.  A 401 still means the server is up."""
        try:
            await self._client.models.list()
            return True
        except (APIConnectionError, APITimeoutError):
            return False
        except APIStatusError as exc:
            # 401 Unauthorized: server is reachable but the key is wrong.
            # We still consider the provider *reachable* (it responded).
            return exc.status_code == 401

    async def list_models(self) -> list[ModelInfo]:
        try:
            page = await self._client.models.list()
            return [
                ModelInfo(
                    id=m.id,
                    provider=self._provider,
                    owned_by=getattr(m, "owned_by", None),
                )
                for m in page.data
            ]
        except (APIConnectionError, APITimeoutError, APIStatusError):
            return []
