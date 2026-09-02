"""Anthropic API wrapper: retries, prompt caching, token accounting."""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path

import anthropic
from dotenv import load_dotenv

# Loaded here rather than in the CLI so every entry point (CLI, eval scripts,
# tests) resolves credentials the same way. .env.local wins over .env, and the
# current directory wins over the project root - so the tool can be run from any
# working directory (say, wherever you want the XML written) and still find a key.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
for _directory in (Path.cwd(), _PROJECT_ROOT):
    for _name in (".env.local", ".env"):
        load_dotenv(_directory / _name, override=False)

# Sonnet 5 is the measured default: it matched Opus on validity and rubric
# gradation at roughly half the cost. Override per run with --model.
DEFAULT_MODEL = "claude-sonnet-5"
MARKER_OPEN = "<json>"
MARKER_CLOSE = "</json>"


# Model capability gates. output_config.effort errors on Haiku 4.5 and the other
# pre-4.6 models; the server-side refusal fallback beta is Opus 5 / Fable only.
NO_EFFORT_MODELS = ("claude-haiku-4-5", "claude-sonnet-4-5", "claude-3")
FALLBACK_MODELS = ("claude-opus-5", "claude-fable-5")


def supports_effort(model: str) -> bool:
    return not model.startswith(NO_EFFORT_MODELS)


def supports_fallbacks(model: str) -> bool:
    return model.startswith(FALLBACK_MODELS)


class RefusalError(RuntimeError):
    """The model declined the request. Logged per record, never retried blindly."""


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
    max_tokens: int = 16000
    fallbacks: bool = True
    usage: Usage = dc_field(default_factory=Usage)
    _client: anthropic.Anthropic | None = None

    def __post_init__(self) -> None:
        # ANTHROPIC_KEY is accepted as an alias; the SDK only reads ANTHROPIC_API_KEY.
        key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_KEY")
        if not key:
            raise RuntimeError(
                "no API key found - set ANTHROPIC_API_KEY (or ANTHROPIC_KEY) "
                "in .env.local, .env, or the environment"
            )
        self._client = anthropic.Anthropic(api_key=key)

    def _create(self, system: list, user_message: str, effort: str):
        """Issue the request, with server-side refusal fallback when available.

        The fallback beta is not enabled on every account, so a rejection of the
        beta itself downgrades the client once and carries on unprotected rather
        than failing the run.
        """
        common = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user_message}],
        }
        if supports_effort(self.model):
            common["output_config"] = {"effort": effort}
        if self.fallbacks and supports_fallbacks(self.model):
            try:
                return self._client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                    **common,
                )
            except anthropic.BadRequestError as exc:
                if "fallback" not in str(exc).lower() and "beta" not in str(exc).lower():
                    raise
                self.fallbacks = False
        return self._client.messages.create(**common)

    def complete(
        self,
        cached_system: str,
        system_suffix: str,
        user_message: str,
        effort: str = "high",
    ) -> str:
        """One call. ``cached_system`` is byte-identical across a run and cached.

        Depth is controlled by ``output_config.effort``, not temperature - the
        sampling parameters were removed on Opus 5 and return a 400. Thinking is
        on by default on this model, so it is left unset.
        """
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
                response = self._create(system, user_message, effort)
                self.usage.add(response.usage)
                if response.stop_reason == "refusal":
                    detail = getattr(response.stop_details, "category", None)
                    raise RefusalError(f"model declined the request (category: {detail})")
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
