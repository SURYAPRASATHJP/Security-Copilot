import hashlib
import json
import time
from collections.abc import Sequence
from functools import lru_cache
from typing import Any

import diskcache
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError
from tenacity import RetryCallState, retry, retry_if_exception, stop_after_attempt, wait_exponential

from copilot.settings import Settings, get_settings, require_groq_key

Message = dict[str, str]


class BudgetExhaustedError(RuntimeError):
    pass


class WaitTooLongError(RuntimeError):
    pass


_BACKOFF = wait_exponential(multiplier=1, min=1, max=30)

# A daily quota can ask for a quarter of an hour. Blocking a caller that long is worse
# than telling them to come back, so a wait beyond this gives up instead.
MAX_WAIT_SECONDS = 90.0


@lru_cache
def _client() -> OpenAI:
    settings = require_groq_key()
    return OpenAI(
        api_key=settings.groq_api_key,
        base_url=settings.groq_base_url,
        timeout=settings.request_timeout_seconds,
        max_retries=0,
    )


@lru_cache
def _response_cache() -> diskcache.Cache:
    path = get_settings().llm_response_cache
    path.mkdir(parents=True, exist_ok=True)
    return diskcache.Cache(str(path))


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, RateLimitError):
        # Waiting out a daily quota is not retrying, it is hanging.
        asked = _retry_after_seconds(exc)
        return asked is None or asked <= MAX_WAIT_SECONDS
    if isinstance(exc, APITimeoutError | APIConnectionError):
        return True
    return isinstance(exc, APIStatusError) and exc.status_code >= 500


def _retry_after_seconds(exc: BaseException | None) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    raw = headers.get("retry-after") or headers.get("Retry-After")
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _wait_honouring_retry_after(state: RetryCallState) -> float:
    backoff = _BACKOFF(state)
    exc = state.outcome.exception() if state.outcome else None
    server_wait = _retry_after_seconds(exc)
    # Groq sends retry-after on 429, and waiting less than it asks just burns another attempt.
    return max(backoff, server_wait) if server_wait else backoff


def cache_key(
    model: str,
    messages: Sequence[Message],
    json_schema: dict[str, Any] | None,
    temperature: float,
) -> str:
    """Return a stable hash of everything that can change the model's reply."""
    payload = {
        "model": model,
        "messages": list(messages),
        "json_schema": json_schema,
        "temperature": temperature,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _response_format(json_schema: dict[str, Any] | None) -> dict[str, Any] | None:
    if json_schema is None:
        return None
    return {
        "type": "json_schema",
        "json_schema": {"name": "answer", "strict": True, "schema": json_schema},
    }


@retry(
    retry=retry_if_exception(_is_retryable),
    wait=_wait_honouring_retry_after,
    stop=stop_after_attempt(5),
    reraise=True,
)
def _create_completion(
    model: str,
    messages: Sequence[Message],
    json_schema: dict[str, Any] | None,
    temperature: float,
) -> tuple[Any, float]:
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": list(messages),
        "temperature": temperature,
    }
    response_format = _response_format(json_schema)
    if response_format:
        kwargs["response_format"] = response_format

    # Time only the attempt that worked, so waiting out a rate limit is not called latency.
    started = time.perf_counter()
    response = _client().chat.completions.create(**kwargs)
    return response, time.perf_counter() - started


def _usd_cost(settings: Settings, input_tokens: int, output_tokens: int) -> float:
    per_million = settings.input_usd_per_million_tokens
    out_per_million = settings.output_usd_per_million_tokens
    return input_tokens / 1_000_000 * per_million + output_tokens / 1_000_000 * out_per_million


def log_call(
    settings: Settings,
    prompt_name: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    latency_seconds: float,
    elapsed_seconds: float = 0.0,
) -> None:
    """Append one line describing a real API call to data/llm_calls.jsonl."""
    record = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "prompt_name": prompt_name,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "latency_seconds": round(latency_seconds, 3),
        "elapsed_seconds": round(elapsed_seconds or latency_seconds, 3),
        "cost_usd": round(_usd_cost(settings, input_tokens, output_tokens), 8),
    }
    log_path = settings.llm_call_log
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def ask_llm(
    messages: Sequence[Message],
    json_schema: dict[str, Any] | None = None,
    temperature: float = 0,
    prompt_name: str = "unnamed",
    model: str | None = None,
    use_cache: bool = True,
    cache_only: bool = False,
) -> str:
    """Return the model's reply text, served from the disk cache when it has been asked before."""
    settings = get_settings()
    model = model or settings.model_name
    key = cache_key(model, messages, json_schema, temperature)

    cache = _response_cache() if use_cache else None
    if cache is not None:
        cached = cache.get(key)
        if isinstance(cached, str):
            return cached

    if cache_only:
        raise BudgetExhaustedError(
            "today's token budget is spent, so only a question asked before can be answered"
        )

    started = time.perf_counter()
    response, latency = _create_completion(model, messages, json_schema, temperature)
    elapsed = time.perf_counter() - started

    text = response.choices[0].message.content or ""
    usage = getattr(response, "usage", None)
    log_call(
        settings,
        prompt_name=prompt_name,
        model=model,
        input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        latency_seconds=latency,
        elapsed_seconds=elapsed,
    )

    if cache is not None:
        cache.set(key, text)
    return text
