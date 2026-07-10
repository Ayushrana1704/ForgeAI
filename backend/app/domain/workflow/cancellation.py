"""
In-process run cancellation registry.

Maps run_id → asyncio.Event.  The cancel endpoint sets the event;
WorkflowService.stream_run polls it between agent completions.

Design for extension
--------------------
When background workers are introduced, replace CancellationRegistry with a
shared signal store (e.g. Redis SETNX / DB row flag).  The WorkflowService
interface stays the same — only this module changes.

Thread safety
-------------
asyncio.Event is safe within a single event loop.  FastAPI/Uvicorn runs
all requests in the same event loop, so no explicit locking is needed.
"""
from __future__ import annotations

import asyncio
from uuid import UUID


class CancellationRegistry:
    """
    Lightweight in-process store for per-run cancellation signals.

    Lifecycle
    ---------
    1. ``register(run_id)`` — called by stream_run before starting astream_events.
       Returns a fresh, *unset* asyncio.Event.
    2. ``request(run_id)`` — called by cancel_run.  Sets the event if registered.
       Returns True if an active stream was signalled, False if none was running
       (caller must update DB status directly in that case).
    3. ``unregister(run_id)`` — called in stream_run's finally block to prevent
       memory leaks.  Safe to call even if the run was never registered.
    """

    def __init__(self) -> None:
        self._events: dict[UUID, asyncio.Event] = {}

    def register(self, run_id: UUID) -> asyncio.Event:
        """
        Create and store a fresh Event for *run_id*.

        Overwrites any previous event for the same run_id (e.g. on retry).
        Returns the new Event so the caller can poll ``ev.is_set()``.
        """
        ev = asyncio.Event()
        self._events[run_id] = ev
        return ev

    def request(self, run_id: UUID) -> bool:
        """
        Signal cancellation for *run_id*.

        Returns True  if an active stream was registered and has been signalled.
        Returns False if no stream was registered (caller handles DB update).
        """
        ev = self._events.get(run_id)
        if ev is not None:
            ev.set()
            return True
        return False

    def is_requested(self, run_id: UUID) -> bool:
        """Return True if cancellation has been requested for *run_id*."""
        ev = self._events.get(run_id)
        return ev is not None and ev.is_set()

    def unregister(self, run_id: UUID) -> None:
        """Remove the event for *run_id*.  No-op if not registered."""
        self._events.pop(run_id, None)


# Module-level singleton shared across all requests in the process.
cancellation_registry = CancellationRegistry()
