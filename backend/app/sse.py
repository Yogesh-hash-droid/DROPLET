"""
Server-Sent Events (SSE) broadcast bus.

One in-process asyncio queue per connected client. When a new reading is
ingested (POST /api/readings) it publishes the JSON payload to every waiting
client via GET /api/stream. Clients that disconnect are cleaned up silently.

Why SSE instead of WebSocket?
  - SSE is unidirectional (server→client) which matches this use-case perfectly.
  - Works over plain HTTPS with no extra protocol upgrade; Render free tier
    supports it without upgrading.
  - Native browser EventSource auto-reconnects with backoff.
  - WebSocket would require a separate library on both ends and provides no
    advantage here since the browser never pushes data to the server.

Thread-safety: asyncio.Queue is not thread-safe from a synchronous thread.
The `publish` helper accepts both sync and async contexts:
  - From sync code (FastAPI endpoint with a non-async def): call
    `publish_sync(data)` which schedules the coroutine on the event loop.
  - From async code: `await publish(data)`.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Set

logger = logging.getLogger("app.sse")

# All connected SSE clients (each has its own queue).
_clients: Set[asyncio.Queue] = set()


def _get_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        return None


async def publish(data: dict) -> None:
    """Broadcast `data` (as JSON) to every connected SSE client."""
    if not _clients:
        return
    message = json.dumps(data, default=str)
    dead: Set[asyncio.Queue] = set()
    for queue in list(_clients):
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            dead.add(queue)
    for queue in dead:
        _clients.discard(queue)


def publish_sync(data: dict) -> None:
    """Thread-safe publish from a synchronous FastAPI endpoint."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(publish(data))
        else:
            loop.run_until_complete(publish(data))
    except Exception as exc:  # noqa: BLE001 - SSE must never break the HTTP response
        logger.debug("SSE publish skipped: %s", exc)


async def event_generator(request):
    """
    Async generator that yields SSE-formatted lines for one client.

    Yields a `data: {...}\\n\\n` frame per reading, plus a heartbeat every
    15 s so the connection does not time out on Render / Vercel / proxies.
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=60)
    _clients.add(queue)
    logger.info("SSE client connected (total=%d)", len(_clients))
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                message = await asyncio.wait_for(queue.get(), timeout=15.0)
                yield f"data: {message}\n\n"
            except asyncio.TimeoutError:
                # Heartbeat keeps the TCP connection alive through Render/nginx.
                yield ": heartbeat\n\n"
    finally:
        _clients.discard(queue)
        logger.info("SSE client disconnected (total=%d)", len(_clients))
