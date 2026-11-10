"""The single LLM client used by every module in the pipeline.

Supports two providers, chosen with RAG_LLM_PROVIDER:

* ``ollama`` - a model served by a local Ollama daemon (default: mistral:7b).
  Fully local, no API key.
* ``openai`` - any OpenAI-compatible HTTP endpoint (Cerebras by default).

``src.generation.generator`` re-exports ``LLMClient`` from here, so
``from src.generation.generator import LLMClient`` keeps working.
"""
import json
import logging
import os
import sys
import time
from typing import Generator

import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config.config import Config

logger = logging.getLogger(__name__)

# Chars-per-token ratios vary by content type.
# Academic prose is denser than average English; code is denser still.
CHARS_PER_TOKEN: dict = {
    "academic": 3.5,   # dense scientific text
    "code":     3.0,   # identifiers and symbols are short
    "prompt":   4.5,   # template text with lots of whitespace/boilerplate
    "general":  4.0,   # default
}
_CHARS_PER_TOKEN = CHARS_PER_TOKEN  # backwards-compatible alias

MAX_RETRIES = 4
BASE_BACKOFF = 2.0   # seconds - 1, 2, 4, 8


class LLMError(RuntimeError):
    """Raised with a message that is safe (and useful) to show in the UI."""


class LLMClient:
    def __init__(self, provider: str = None):
        self.provider = (provider or Config.LLM_PROVIDER).lower()
        if self.provider not in ("ollama", "openai"):
            raise LLMError(
                f"Unknown LLM provider {self.provider!r}. "
                "Set RAG_LLM_PROVIDER to 'ollama' or 'openai' in your .env."
            )

    # ------------------------------------------------------------------
    # Token helpers
    # ------------------------------------------------------------------
    @staticmethod
    def estimate_tokens(text: str, content_type: str = "general") -> int:
        """Approximate token count using a content-type-aware chars/token ratio."""
        cpt = CHARS_PER_TOKEN.get(content_type, 4.0)
        return max(1, int(len(text) / cpt))

    @staticmethod
    def truncate_to_token_budget(text: str, max_tokens: int, content_type: str = "general") -> str:
        cpt = CHARS_PER_TOKEN.get(content_type, 4.0)
        max_chars = int(max_tokens * cpt)
        if len(text) <= max_chars:
            return text
        return text[:max_chars]

    # ------------------------------------------------------------------
    # Health / readiness
    # ------------------------------------------------------------------
    @staticmethod
    def health() -> dict:
        """Check that the configured provider can actually serve a request.

        Never raises - returns a dict the API and UI can render directly.
        """
        provider = Config.LLM_PROVIDER
        info = {
            "provider": provider,
            "model": Config.active_model(),
            "ready": False,
            "detail": "",
        }

        if provider == "ollama":
            info["base_url"] = Config.OLLAMA_BASE_URL
            info["num_ctx"] = Config.OLLAMA_NUM_CTX
            try:
                resp = requests.get(f"{Config.OLLAMA_BASE_URL}/api/tags", timeout=5)
                resp.raise_for_status()
            except requests.RequestException as e:
                info["detail"] = (
                    f"Cannot reach the Ollama daemon at {Config.OLLAMA_BASE_URL} ({e.__class__.__name__}). "
                    "Start it with 'ollama serve'."
                )
                return info

            try:
                names = [m.get("name", "") for m in resp.json().get("models", [])]
            except ValueError:
                info["detail"] = "Ollama returned a response that could not be parsed."
                return info

            info["available_models"] = names
            want = Config.OLLAMA_MODEL
            # "mistral:7b" should also match a daemon that lists plain "mistral".
            if want in names or want.split(":")[0] in [n.split(":")[0] for n in names]:
                info["ready"] = True
                info["detail"] = f"Ollama is serving {want}."
            else:
                info["detail"] = (
                    f"Model {want!r} is not installed. Run 'ollama pull {want}'. "
                    f"Installed: {', '.join(names) or 'none'}."
                )
            return info

        # openai-compatible
        info["base_url"] = Config.CEREBRAS_BASE_URL
        if not (Config.CEREBRAS_API_KEY or os.environ.get("CEREBRAS_API_KEY")):
            info["detail"] = "No API key. Set CEREBRAS_API_KEY in .env, or use RAG_LLM_PROVIDER=ollama."
            return info
        info["ready"] = True
        info["detail"] = f"Configured for {Config.OPENAI_MODEL} at {Config.CEREBRAS_BASE_URL}."
        return info

    # ------------------------------------------------------------------
    # Generation (non-streaming)
    # ------------------------------------------------------------------
    def generate(self, prompt: str) -> str:
        token_est = self.estimate_tokens(prompt, content_type="prompt")
        logger.debug("Generating with ~%d prompt tokens.", token_est)
        if self.provider == "ollama":
            return self._generate_ollama(prompt)
        return self._generate_openai(prompt)

    # ---- Ollama ------------------------------------------------------
    def _ollama_payload(self, prompt: str, stream: bool) -> dict:
        return {
            "model": Config.OLLAMA_MODEL,
            "prompt": prompt,
            "stream": stream,
            "keep_alive": Config.OLLAMA_KEEP_ALIVE,
            "options": {
                "temperature": Config.LLM_TEMPERATURE,
                "num_predict": Config.LLM_MAX_TOKENS,
                # Without an explicit num_ctx, Ollama loads the model with a
                # small default window and silently drops the start of the
                # prompt - which is exactly where the retrieved papers are.
                "num_ctx": Config.OLLAMA_NUM_CTX,
            },
        }

    def _ollama_error(self, exc: Exception) -> LLMError:
        """Turn a requests/HTTP failure into something actionable."""
        url = Config.OLLAMA_BASE_URL
        if isinstance(exc, requests.ConnectionError):
            return LLMError(
                f"Could not connect to Ollama at {url}. Is the daemon running? "
                "Start it with 'ollama serve'."
            )
        if isinstance(exc, requests.Timeout):
            return LLMError(
                f"Ollama did not respond within {Config.OLLAMA_TIMEOUT}s. "
                f"{Config.OLLAMA_MODEL} may be loading, or the prompt is too long for this machine. "
                "Raise RAG_OLLAMA_TIMEOUT or lower RAG_OLLAMA_NUM_CTX."
            )
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            status = exc.response.status_code
            body = (exc.response.text or "")[:300]
            if status == 404:
                return LLMError(
                    f"Ollama does not have the model {Config.OLLAMA_MODEL!r}. "
                    f"Run 'ollama pull {Config.OLLAMA_MODEL}'."
                )
            return LLMError(f"Ollama returned HTTP {status}: {body}")
        return LLMError(f"Ollama request failed: {exc}")

    def _generate_ollama(self, prompt: str) -> str:
        url = f"{Config.OLLAMA_BASE_URL}/api/generate"
        payload = self._ollama_payload(prompt, stream=False)

        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                response = requests.post(url, json=payload, timeout=Config.OLLAMA_TIMEOUT)
                response.raise_for_status()
                data = response.json()
                if data.get("error"):
                    raise LLMError(f"Ollama error: {data['error']}")
                text = data.get("response", "")
                if not text.strip():
                    raise LLMError("Ollama returned an empty response.")
                return text
            except (requests.ConnectionError, requests.Timeout) as e:
                # Transient: the daemon may still be loading the model.
                last_exc = e
                if attempt < MAX_RETRIES - 1:
                    wait = BASE_BACKOFF ** attempt
                    logger.warning(
                        "Ollama unavailable (%s). Retrying in %.0fs (attempt %d/%d).",
                        e.__class__.__name__, wait, attempt + 1, MAX_RETRIES,
                    )
                    time.sleep(wait)
                    continue
                raise self._ollama_error(e) from e
            except requests.HTTPError as e:
                status = e.response.status_code if e.response is not None else 0
                if status in (500, 502, 503, 504) and attempt < MAX_RETRIES - 1:
                    wait = BASE_BACKOFF ** attempt
                    logger.warning("Ollama HTTP %d. Retrying in %.0fs.", status, wait)
                    time.sleep(wait)
                    last_exc = e
                    continue
                raise self._ollama_error(e) from e
            except ValueError as e:  # bad JSON
                raise LLMError(f"Could not parse the Ollama response: {e}") from e

        raise self._ollama_error(last_exc or RuntimeError("unknown"))

    # ---- OpenAI-compatible -------------------------------------------
    @staticmethod
    def _openai_client():
        from openai import OpenAI
        api_key = Config.CEREBRAS_API_KEY or os.environ.get("CEREBRAS_API_KEY")
        if not api_key:
            raise LLMError(
                "No API key found. Set CEREBRAS_API_KEY in your .env file, "
                "or switch to the local model with RAG_LLM_PROVIDER=ollama."
            )
        return OpenAI(api_key=api_key, base_url=Config.CEREBRAS_BASE_URL)

    def _generate_openai(self, prompt: str) -> str:
        from openai import APIError, APITimeoutError, APIConnectionError, RateLimitError
        client = self._openai_client()

        for attempt in range(MAX_RETRIES):
            try:
                response = client.chat.completions.create(
                    model=Config.OPENAI_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=Config.LLM_TEMPERATURE,
                    max_tokens=Config.LLM_MAX_TOKENS,
                    timeout=120,
                )
                if not response.choices:
                    raise LLMError("The LLM returned no choices - nothing was generated.")
                return response.choices[0].message.content or ""

            except RateLimitError as e:
                wait = BASE_BACKOFF ** attempt
                if attempt < MAX_RETRIES - 1:
                    logger.warning("Rate limited (429). Retrying in %.0fs (attempt %d/%d).",
                                   wait, attempt + 1, MAX_RETRIES)
                    time.sleep(wait)
                else:
                    raise LLMError(
                        "API rate limit exceeded after all retries. Try again in a few minutes."
                    ) from e

            except APITimeoutError as e:
                wait = BASE_BACKOFF ** attempt
                if attempt < MAX_RETRIES - 1:
                    logger.warning("Request timed out. Retrying in %.0fs (attempt %d/%d).",
                                   wait, attempt + 1, MAX_RETRIES)
                    time.sleep(wait)
                else:
                    raise LLMError(
                        "LLM request timed out after all retries. Try a shorter prompt."
                    ) from e

            except APIConnectionError as e:
                wait = BASE_BACKOFF ** attempt
                if attempt < MAX_RETRIES - 1:
                    logger.warning("Connection error. Retrying in %.0fs (attempt %d/%d).",
                                   wait, attempt + 1, MAX_RETRIES)
                    time.sleep(wait)
                else:
                    raise LLMError(f"Could not connect to the LLM API after all retries: {e}") from e

            except APIError as e:
                if e.status_code in (500, 502, 503, 504) and attempt < MAX_RETRIES - 1:
                    wait = BASE_BACKOFF ** attempt
                    logger.warning("Server error %s. Retrying in %.0fs (attempt %d/%d).",
                                   e.status_code, wait, attempt + 1, MAX_RETRIES)
                    time.sleep(wait)
                else:
                    raise LLMError(f"LLM API error (status {e.status_code}): {e.message}") from e

        raise LLMError("LLM call failed after all retries.")

    # ------------------------------------------------------------------
    # Streaming generation
    # ------------------------------------------------------------------
    def stream(self, prompt: str) -> Generator[str, None, None]:
        if self.provider == "ollama":
            yield from self._stream_ollama(prompt)
        else:
            yield from self._stream_openai(prompt)

    def _stream_ollama(self, prompt: str) -> Generator[str, None, None]:
        url = f"{Config.OLLAMA_BASE_URL}/api/generate"
        payload = self._ollama_payload(prompt, stream=True)
        try:
            with requests.post(url, json=payload, stream=True, timeout=Config.OLLAMA_TIMEOUT) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("error"):
                        raise LLMError(f"Ollama error: {chunk['error']}")
                    token = chunk.get("response", "")
                    if token:
                        yield token
                    if chunk.get("done"):
                        break
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            raise self._ollama_error(e) from e

    def _stream_openai(self, prompt: str) -> Generator[str, None, None]:
        from openai import RateLimitError, APIError, APIConnectionError
        client = self._openai_client()

        for attempt in range(MAX_RETRIES):
            try:
                with client.chat.completions.create(
                    model=Config.OPENAI_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=Config.LLM_TEMPERATURE,
                    max_tokens=Config.LLM_MAX_TOKENS,
                    stream=True,
                ) as stream:
                    for chunk in stream:
                        if not chunk.choices:
                            continue
                        delta = chunk.choices[0].delta.content
                        if delta:
                            yield delta
                return

            except RateLimitError as e:
                wait = BASE_BACKOFF ** attempt
                if attempt < MAX_RETRIES - 1:
                    logger.warning("Stream rate limited. Retrying in %.0fs (attempt %d/%d).",
                                   wait, attempt + 1, MAX_RETRIES)
                    time.sleep(wait)
                else:
                    raise LLMError("API rate limit exceeded during streaming.") from e

            except (APIConnectionError, APIError) as e:
                wait = BASE_BACKOFF ** attempt
                if attempt < MAX_RETRIES - 1:
                    logger.warning("Stream error: %s. Retrying in %.0fs.", e, wait)
                    time.sleep(wait)
                else:
                    raise LLMError(f"Streaming failed after all retries: {e}") from e
