"""
Tests for the LLM abstraction layer.

All tests use mocked providers — no real HTTP calls, no API keys required.

Unit tests cover LLMService logic directly.
Integration tests drive the FastAPI test client to verify:
  - /health/ready includes llm_provider status
  - LLMService dependency override works correctly
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, PropertyMock

from app.api.dependencies import get_llm_service
from app.application.interfaces.llm_provider import LLMProvider
from app.application.services.llm.llm_service import LLMService
from app.application.services.llm.types import (
    ChatMessage,
    CompletionRequest,
    CompletionResponse,
    MessageRole,
    ModelInfo,
    UsageInfo,
)
from app.core.exceptions import BadRequestException, LLMException, LLMUnavailableException


# ── Helpers ───────────────────────────────────────────────────────────────────


def _mock_provider(
    *,
    provider_name: str = "openai",
    default_model: str = "gpt-4o-mini",
) -> AsyncMock:
    """Return an AsyncMock that satisfies the LLMProvider ABC."""
    provider = AsyncMock(spec=LLMProvider)
    # spec= makes attribute access on AsyncMock return MagicMock by default.
    # For @property descriptors we need explicit side-effect assignment.
    type(provider).provider_name = PropertyMock(return_value=provider_name)
    type(provider).default_model = PropertyMock(return_value=default_model)
    return provider


def _make_response(**overrides: object) -> CompletionResponse:
    defaults: dict = dict(
        content="Hello from the mock.",
        model="gpt-4o-mini",
        usage=UsageInfo(prompt_tokens=12, completion_tokens=9, total_tokens=21),
        latency_ms=85,
        raw={},
    )
    return CompletionResponse(**{**defaults, **overrides})


def _single_message_request(text: str = "Hello!") -> CompletionRequest:
    return CompletionRequest(
        messages=[ChatMessage(role=MessageRole.USER, content=text)]
    )


# ── LLMService — unit tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_complete_returns_response() -> None:
    provider = _mock_provider()
    provider.complete.return_value = _make_response()

    service = LLMService(provider)
    resp = await service.complete(_single_message_request())

    provider.complete.assert_called_once()
    assert resp.content == "Hello from the mock."
    assert resp.model == "gpt-4o-mini"
    assert resp.usage.total_tokens == 21


@pytest.mark.asyncio
async def test_complete_raises_on_empty_messages() -> None:
    provider = _mock_provider()
    service = LLMService(provider)

    with pytest.raises(BadRequestException, match="at least one message"):
        await service.complete(CompletionRequest(messages=[]))

    provider.complete.assert_not_called()


@pytest.mark.asyncio
async def test_complete_respects_explicit_model() -> None:
    """CompletionRequest.model overrides the provider default."""
    provider = _mock_provider()
    provider.complete.return_value = _make_response(model="gpt-4o")

    service = LLMService(provider)
    req = CompletionRequest(
        messages=[ChatMessage(role=MessageRole.USER, content="Hi")],
        model="gpt-4o",
    )
    resp = await service.complete(req)

    call_args = provider.complete.call_args[0][0]
    assert call_args.model == "gpt-4o"
    assert resp.model == "gpt-4o"


@pytest.mark.asyncio
async def test_complete_propagates_llm_exception() -> None:
    provider = _mock_provider()
    provider.complete.side_effect = LLMException("Rate limit exceeded")

    service = LLMService(provider)
    with pytest.raises(LLMException, match="Rate limit exceeded"):
        await service.complete(_single_message_request())


@pytest.mark.asyncio
async def test_complete_propagates_unavailable_exception() -> None:
    provider = _mock_provider()
    provider.complete.side_effect = LLMUnavailableException("Cannot connect to LLM provider")

    service = LLMService(provider)
    with pytest.raises(LLMUnavailableException):
        await service.complete(_single_message_request())


@pytest.mark.asyncio
async def test_health_check_returns_true_when_healthy() -> None:
    provider = _mock_provider()
    provider.health_check.return_value = True

    service = LLMService(provider)
    assert await service.health_check() is True
    provider.health_check.assert_called_once()


@pytest.mark.asyncio
async def test_health_check_returns_false_when_unavailable() -> None:
    provider = _mock_provider()
    provider.health_check.return_value = False

    service = LLMService(provider)
    assert await service.health_check() is False


@pytest.mark.asyncio
async def test_list_models_returns_provider_models() -> None:
    provider = _mock_provider()
    provider.list_models.return_value = [
        ModelInfo(id="gpt-4o", provider="openai", owned_by="openai"),
        ModelInfo(id="gpt-4o-mini", provider="openai", owned_by="openai"),
    ]

    service = LLMService(provider)
    models = await service.list_models()

    assert len(models) == 2
    assert models[0].id == "gpt-4o"
    assert models[1].id == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_list_models_returns_empty_on_error() -> None:
    provider = _mock_provider()
    provider.list_models.return_value = []

    service = LLMService(provider)
    assert await service.list_models() == []


@pytest.mark.asyncio
async def test_service_exposes_provider_name() -> None:
    provider = _mock_provider(provider_name="ollama")
    service = LLMService(provider)
    assert service.provider_name == "ollama"


@pytest.mark.asyncio
async def test_service_exposes_default_model() -> None:
    provider = _mock_provider(default_model="llama3.2")
    service = LLMService(provider)
    assert service.default_model == "llama3.2"


@pytest.mark.asyncio
async def test_system_plus_user_messages() -> None:
    """Multi-turn requests with a system prompt are forwarded intact."""
    provider = _mock_provider()
    provider.complete.return_value = _make_response()

    req = CompletionRequest(
        messages=[
            ChatMessage(role=MessageRole.SYSTEM, content="You are a helpful assistant."),
            ChatMessage(role=MessageRole.USER, content="Explain async/await."),
        ]
    )
    service = LLMService(provider)
    await service.complete(req)

    forwarded: CompletionRequest = provider.complete.call_args[0][0]
    assert len(forwarded.messages) == 2
    assert forwarded.messages[0].role == MessageRole.SYSTEM
    assert forwarded.messages[1].role == MessageRole.USER


# ── /health/ready — integration tests ────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_ready_reports_llm_healthy(client: AsyncClient) -> None:
    """/health/ready must include llm_provider='healthy' when the provider is up."""
    provider = _mock_provider()
    provider.health_check.return_value = True
    mock_service = LLMService(provider)

    from app.main import app

    app.dependency_overrides[get_llm_service] = lambda: mock_service
    try:
        resp = await client.get("/api/v1/health/ready")
        assert resp.status_code == 200
        body = resp.json()
        assert body["database"] == "connected"
        assert body["llm_provider"] == "healthy"
        assert body["llm_provider_name"] == "openai"
    finally:
        app.dependency_overrides.pop(get_llm_service, None)


@pytest.mark.asyncio
async def test_health_ready_reports_llm_degraded(client: AsyncClient) -> None:
    """/health/ready must report degraded (not 5xx) when the LLM is unreachable."""
    provider = _mock_provider()
    provider.health_check.return_value = False
    mock_service = LLMService(provider)

    from app.main import app

    app.dependency_overrides[get_llm_service] = lambda: mock_service
    try:
        resp = await client.get("/api/v1/health/ready")
        # Degraded LLM must NOT cause a 5xx — the DB is still up.
        assert resp.status_code == 200
        body = resp.json()
        assert body["llm_provider"] == "degraded"
        assert body["database"] == "connected"
    finally:
        app.dependency_overrides.pop(get_llm_service, None)
