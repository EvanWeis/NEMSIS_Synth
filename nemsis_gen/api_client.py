"""Anthropic API wrapper: retries, prompt caching, token accounting."""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from dataclasses import field as dc_field

import anthropic

DEFAULT_MODEL = "claude-opus-5"
MARKER_OPEN = "<json>"
MARKER_CLOSE = "</json>"


class OutputContractError(RuntimeError):
    """The model returned something without the agreed markers.

    A logged failure, never a silent skip - the manifest records the raw text so a
    contract break is debuggable after the fact.
    """

    def __init__(self, message: str, raw: str):
        super().__init__(message)
        self.raw = raw


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    calls: int = 0

    def add(self, usage) -> None:
        self.input_tokens += getattr(usage, "input_tokens", 0) or 0
        self.output_tokens += getattr(usage, "output_tokens", 0) or 0
        self.cache_creation_input_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.cache_read_input_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.calls += 1

    def to_json(self) -> dict:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
        }


@dataclass
class ApiClient:
    model: str = DEFAULT_MODEL
    max_retries: int = 5
    max_tokens: int = 8000
    usage: Usage = dc_field(default_factory=Usage)
    _client: anthropic.Anthropic | None = None

    def __post_init__(self) -> None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set (put it in .env or the environment)")
        self._client = anthropic.Anthropic()

    def complete(
        self,
        cached_system: str,
        system_suffix: str,
        user_message: str,
        temperature: float = 0.7,
    ) -> str:
        """One call. ``cached_system`` is byte-identical across a run and cached."""
        system = [
            {
                "type": "text",
                "text": cached_system,
                "cache_control": {"type": "ephemeral"},
            },
            {"type": "text", "text": system_suffix},
        ]

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = self._client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    temperature=temperature,
                    system=system,
                    messages=[{"role": "user", "content": user_message}],
                )
                self.usage.add(response.usage)
                return "".join(block.text for block in response.content if block.type == "text")
            except (
                anthropic.RateLimitError,
                anthropic.APIStatusError,
                anthropic.APIConnectionError,
            ) as exc:
                status = getattr(exc, "status_code", None)
                if status is not None and status < 429 and status != 408:
                    raise
                last_error = exc
                backoff = min(2**attempt, 30) + random.uniform(0, 1)
                time.sleep(backoff)

        raise RuntimeError(f"giving up after {self.max_retries} attempts") from last_error


def extract_json_block(text: str) -> str:
    """Pull the payload from between the output-contract markers."""
    if MARKER_OPEN not in text or MARKER_CLOSE not in text:
        raise OutputContractError("response did not contain <json>...</json> markers", text)
    body = text.split(MARKER_OPEN, 1)[1].split(MARKER_CLOSE, 1)[0]
    return body.strip()
