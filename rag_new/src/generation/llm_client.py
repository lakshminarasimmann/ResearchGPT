import json
import logging
import os
import sys
from typing import Generator

import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config.config import Config

logger = logging.getLogger(__name__)

# Chars-per-token ratios vary by content type.
# Academic prose is denser than average English; code is denser still.
CHARS_PER_TOKEN: dict = {
    "academic": 3.5,
    "code":     3.0,
    "prompt":   4.5,
    "general":  4.0,
}


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
        from openai import OpenAI, APIError, APITimeoutError, APIConnectionError
        api_key = Config.CEREBRAS_API_KEY or os.environ.get("CEREBRAS_API_KEY")
        if not api_key:
            raise RuntimeError("No API key found. Set CEREBRAS_API_KEY in your .env file.")
        client = OpenAI(api_key=api_key, base_url=Config.CEREBRAS_BASE_URL)
        try:
            response = client.chat.completions.create(
                model=Config.OPENAI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=Config.LLM_TEMPERATURE,
                max_tokens=Config.LLM_MAX_TOKENS,
                timeout=120,
            )
        except APITimeoutError:
            raise RuntimeError("LLM request timed out after 120s. Try again or use a shorter prompt.")
        except APIConnectionError as e:
            raise RuntimeError(f"Could not connect to LLM API: {e}")
        except APIError as e:
            raise RuntimeError(f"LLM API error (status {e.status_code}): {e.message}")
        if not response.choices:
            raise RuntimeError("LLM returned an empty choices list — no content was generated.")
        return response.choices[0].message.content or ""

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
        from openai import OpenAI
        api_key = Config.CEREBRAS_API_KEY or os.environ.get("CEREBRAS_API_KEY")
        client = OpenAI(api_key=api_key, base_url=Config.CEREBRAS_BASE_URL)
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
