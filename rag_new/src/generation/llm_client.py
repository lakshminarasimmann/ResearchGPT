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

CHARS_PER_TOKEN: dict = {
    "academic": 3.5,
    "code":     3.0,
    "prompt":   4.5,
    "general":  4.0,
}

MAX_RETRIES = 4
BASE_BACKOFF = 2.0   # seconds — doubles each retry: 2, 4, 8, 16


class LLMClient:
    def __init__(self, provider=Config.LLM_PROVIDER):
        self.provider = provider

    # ------------------------------------------------------------------
    # Token helpers
    # ------------------------------------------------------------------
    @staticmethod
    def estimate_tokens(text: str, content_type: str = "general") -> int:
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
    # Generation (non-streaming)
    # ------------------------------------------------------------------
    def generate(self, prompt: str) -> str:
        token_est = self.estimate_tokens(prompt, content_type="prompt")
        logger.debug("Generating with ~%d prompt tokens.", token_est)
        if self.provider == "ollama":
            return self._generate_ollama(prompt)
        elif self.provider == "openai":
            return self._generate_openai(prompt)
        else:
            raise ValueError(f"Unknown LLM provider: {self.provider}")

    def _generate_ollama(self, prompt: str) -> str:
        url = "http://localhost:11434/api/generate"
        payload = {
            "model": Config.OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": Config.LLM_TEMPERATURE,
                "num_predict": Config.LLM_MAX_TOKENS,
            },
        }
        try:
            response = requests.post(url, json=payload, timeout=600)
            response.raise_for_status()
            return response.json().get("response", "No response from model.")
        except Exception as e:
            raise RuntimeError(f"Ollama timeout or failure: {e}")

    def _generate_openai(self, prompt: str) -> str:
        from openai import OpenAI, APIError, APITimeoutError, APIConnectionError, RateLimitError
        api_key = Config.CEREBRAS_API_KEY or os.environ.get("CEREBRAS_API_KEY")
        if not api_key:
            raise RuntimeError("No API key found. Set CEREBRAS_API_KEY in your .env file.")
        client = OpenAI(api_key=api_key, base_url=Config.CEREBRAS_BASE_URL)

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
                    raise RuntimeError("LLM returned an empty choices list — no content was generated.")
                return response.choices[0].message.content or ""

            except RateLimitError as e:
                wait = BASE_BACKOFF ** attempt  # 1s, 2s, 4s, 8s
                if attempt < MAX_RETRIES - 1:
                    logger.warning("Rate limited (429). Retrying in %.0fs (attempt %d/%d).", wait, attempt + 1, MAX_RETRIES)
                    time.sleep(wait)
                else:
                    raise RuntimeError("Cerebras API rate limit exceeded after all retries. Try again in a few minutes.") from e

            except APITimeoutError:
                wait = BASE_BACKOFF ** attempt
                if attempt < MAX_RETRIES - 1:
                    logger.warning("Request timed out. Retrying in %.0fs (attempt %d/%d).", wait, attempt + 1, MAX_RETRIES)
                    time.sleep(wait)
                else:
                    raise RuntimeError("LLM request timed out after all retries. Try again or use a shorter prompt.")

            except APIConnectionError as e:
                wait = BASE_BACKOFF ** attempt
                if attempt < MAX_RETRIES - 1:
                    logger.warning("Connection error. Retrying in %.0fs (attempt %d/%d).", wait, attempt + 1, MAX_RETRIES)
                    time.sleep(wait)
                else:
                    raise RuntimeError(f"Could not connect to LLM API after all retries: {e}") from e

            except APIError as e:
                if e.status_code in (500, 502, 503, 504):
                    wait = BASE_BACKOFF ** attempt
                    if attempt < MAX_RETRIES - 1:
                        logger.warning("Server error %d. Retrying in %.0fs (attempt %d/%d).", e.status_code, wait, attempt + 1, MAX_RETRIES)
                        time.sleep(wait)
                    else:
                        raise RuntimeError(f"LLM server error {e.status_code} after all retries.") from e
                else:
                    raise RuntimeError(f"LLM API error (status {e.status_code}): {e.message}") from e

        raise RuntimeError("LLM call failed after all retries.")

    # ------------------------------------------------------------------
    # Streaming generation
    # ------------------------------------------------------------------
    def stream(self, prompt: str) -> Generator[str, None, None]:
        if self.provider == "ollama":
            yield from self._stream_ollama(prompt)
        elif self.provider == "openai":
            yield from self._stream_openai(prompt)
        else:
            raise ValueError(f"Unknown LLM provider: {self.provider}")

    def _stream_ollama(self, prompt: str) -> Generator[str, None, None]:
        url = "http://localhost:11434/api/generate"
        payload = {
            "model": Config.OLLAMA_MODEL,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": Config.LLM_TEMPERATURE,
                "num_predict": Config.LLM_MAX_TOKENS,
            },
        }
        with requests.post(url, json=payload, stream=True, timeout=600) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if line:
                    try:
                        chunk = json.loads(line)
                        token = chunk.get("response", "")
                        if token:
                            yield token
                        if chunk.get("done"):
                            break
                    except json.JSONDecodeError:
                        continue

    def _stream_openai(self, prompt: str) -> Generator[str, None, None]:
        from openai import OpenAI, RateLimitError, APIError, APIConnectionError
        api_key = Config.CEREBRAS_API_KEY or os.environ.get("CEREBRAS_API_KEY")
        client = OpenAI(api_key=api_key, base_url=Config.CEREBRAS_BASE_URL)

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
                        delta = chunk.choices[0].delta.content
                        if delta:
                            yield delta
                return

            except RateLimitError as e:
                wait = BASE_BACKOFF ** attempt
                if attempt < MAX_RETRIES - 1:
                    logger.warning("Stream rate limited. Retrying in %.0fs (attempt %d/%d).", wait, attempt + 1, MAX_RETRIES)
                    time.sleep(wait)
                else:
                    raise RuntimeError("Cerebras API rate limit exceeded during streaming.") from e

            except (APIConnectionError, APIError) as e:
                wait = BASE_BACKOFF ** attempt
                if attempt < MAX_RETRIES - 1:
                    logger.warning("Stream error: %s. Retrying in %.0fs.", e, wait)
                    time.sleep(wait)
                else:
                    raise RuntimeError(f"Streaming failed after all retries: {e}") from e
