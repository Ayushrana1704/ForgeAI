"""
Provider-agnostic data types for LLM interactions.

These dataclasses form the shared language between the Application layer
(LLMService, future agents) and Infrastructure layer (concrete providers).
Nothing here imports from Infrastructure — this file has zero external deps.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class ChatMessage:
    """A single turn in a conversation."""

    role: MessageRole
    content: str


@dataclass
class CompletionRequest:
    """Everything a provider needs to execute a chat completion."""

    messages: list[ChatMessage]
    # None → provider uses its configured default model
    model: str | None = None
    # Low temperature for deterministic, structured output suited to local CPU inference.
    temperature: float = 0.2
    # Global default of 500 tokens keeps local inference fast on 8 GB RAM / CPU.
    # Nodes that need more output must pass an explicit override.
    max_tokens: int = 500
    # Nucleus sampling; 0.9 keeps output focused without over-greedy sampling.
    top_p: float = 0.9
    # Caller-supplied key/value pairs forwarded in structured logs (not sent
    # to the provider).  Useful for tracing agent_run_id, step_id, etc.
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class UsageInfo:
    """Token consumption reported by the provider."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass
class CompletionResponse:
    """Normalised response returned by every provider implementation."""

    content: str
    model: str
    usage: UsageInfo
    latency_ms: int
    # Raw provider payload, kept for debugging / audit logging.
    # Agents should never depend on this field's structure.
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelInfo:
    """Lightweight descriptor for a model advertised by a provider."""

    id: str
    provider: str
    owned_by: str | None = None
