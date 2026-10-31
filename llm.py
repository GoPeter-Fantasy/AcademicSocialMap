import json
import logging
import random
import time
from typing import Any

import requests

import config

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


# Status codes worth retrying — these are transient infrastructure problems.
_RETRY_STATUSES = {408, 429, 500, 502, 503, 504}


class LLMClient:
    """OpenAI-compatible chat client. Primary: DeepSeek, fallback: MiniMax.

    Retries only on transient errors (network / 408 / 429 / 5xx). 4xx other
    than 408/429 fail immediately so we don't waste quota on bad requests."""

    def __init__(self, provider: str | None = None, timeout: int = 120):
        if provider is None:
            provider = "deepseek"
        self.provider = provider
        self.timeout = timeout
        self._session = requests.Session()

    def _providers(self):
        if self.provider == "minimax":
            return [
                ("minimax", config.MINIMAX_BASE_URL, config.MINIMAX_API_KEY, config.MINIMAX_MODEL),
            ]
        return [
            ("deepseek", config.DEEPSEEK_BASE_URL, config.DEEPSEEK_API_KEY, config.DEEPSEEK_MODEL),
            ("minimax", config.MINIMAX_BASE_URL, config.MINIMAX_API_KEY, config.MINIMAX_MODEL),
        ]

    @staticmethod
    def _endpoint(base_url: str) -> str:
        return f"{base_url.rstrip('/')}/v1/chat/completions"

    def chat(
        self,
        messages: list[dict],
        json_mode: bool = False,
        temperature: float = 0.2,
        max_tokens: int = 4000,
    ) -> str:
        last_err: Exception | None = None
        for name, base_url, api_key, model in self._providers():
            if not api_key:
                logger.debug("provider %s skipped: no API key", name)
                last_err = RuntimeError(f"{name} API key not configured")
                continue
            for attempt in range(3):
                try:
                    payload: dict[str, Any] = {
                        "model": model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    }
                    if json_mode:
                        payload["response_format"] = {"type": "json_object"}
                    resp = self._session.post(
                        self._endpoint(base_url),
                        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        json=payload,
                        timeout=self.timeout,
                    )
                except requests.exceptions.RequestException as e:
                    # Network errors: retry.
                    last_err = e
                    time.sleep(1.5 * (2 ** attempt) + random.random())
                    continue

                status = resp.status_code
                if status == 429:
                    # Honor Retry-After when the upstream provides it.
                    retry_after = resp.headers.get("Retry-After")
                    try:
                        wait = float(retry_after) if retry_after else 3 * (attempt + 1)
                    except (TypeError, ValueError):
                        wait = 3 * (attempt + 1)
                    time.sleep(wait + random.random())
                    continue
                if status in _RETRY_STATUSES:
                    last_err = RuntimeError(f"{name} HTTP {status}")
                    time.sleep(1.5 * (2 ** attempt) + random.random())
                    continue
                if status >= 400:
                    # Non-retryable client error — surface upstream detail once.
                    raise LLMError(f"{name} HTTP {status}: {resp.text[:300]}")

                # 2xx: try to parse the response. On failure, do NOT retry the
                # same provider (likely a model-output problem, not network).
                try:
                    return resp.json()["choices"][0]["message"]["content"]
                except (KeyError, ValueError, IndexError) as e:
                    last_err = e
                    break
            logger.warning("provider %s failed after retries, trying next", name)
        raise LLMError(f"all LLM providers failed: {last_err}")

    def chat_json(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 4000) -> dict:
        text = self.chat(messages, json_mode=True, temperature=temperature, max_tokens=max_tokens)
        return _parse_json_lenient(text)

    def chat_json_list(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 4000) -> list:
        text = self.chat(messages, json_mode=True, temperature=temperature, max_tokens=max_tokens)
        data = _parse_json_lenient(text)
        if isinstance(data, list):
            return data
        for key in ("results", "items", "data"):
            if isinstance(data.get(key), list):
                return data[key]
        raise LLMError(f"LLM returned JSON without a list: {text[:300]}")


def _parse_json_lenient(text: str):
    """Parse LLM JSON output; attempts repair for truncated/embellished output."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    for sep in ("},\n", "},\r\n", "}]", "]\n"):
        idx = text.rfind(sep)
        if idx != -1:
            candidate = text[: idx + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
    raise LLMError(f"LLM returned invalid JSON: {text[:300]}")
