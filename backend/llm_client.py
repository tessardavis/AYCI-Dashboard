"""
Thin async wrapper around the Anthropic Python SDK.

Replaces what we used to get from `emergentintegrations.llm.chat.LlmChat` —
that was Emergent's proxy. Now we go direct to Anthropic.

Configuration: set ANTHROPIC_API_KEY (an `sk-ant-…` value created at
https://console.anthropic.com/settings/keys).

Usage:
    from llm_client import complete, get_client

    if get_client() is None:
        return fallback()

    text = await complete(system="You are…", user="Hello")
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)

# Default model — overridable per-call.
DEFAULT_MODEL = "claude-sonnet-4-5-20250929"

_client: Optional[AsyncAnthropic] = None


def get_client() -> Optional[AsyncAnthropic]:
    """Return the singleton Anthropic client, or None if no API key is set.
    Callers can check this to decide whether to short-circuit before paying
    for a request that would just fail."""
    global _client
    if _client is not None:
        return _client
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        return None
    _client = AsyncAnthropic(api_key=key)
    return _client


async def complete(
    *,
    system: str,
    user: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 1024,
) -> str:
    """Send a single user message + system prompt; return the assistant's
    response as plain text. Raises RuntimeError if the API key isn't set.
    """
    client = get_client()
    if client is None:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not configured — cannot call Claude."
        )
    response = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    # Anthropic returns a list of content blocks; for text-only chat there's
    # exactly one TextBlock.
    parts = [getattr(block, "text", "") for block in response.content]
    return "".join(parts)
