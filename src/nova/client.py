from typing import Any

import httpx

from nova.config import Settings


class ModelClient:
    """OpenAI-compatible chat client. Works with Ollama, vLLM, and hosted APIs."""

    def __init__(self, settings: Settings, timeout: float = 120.0):
        self.settings = settings
        self._client = httpx.Client(
            base_url=settings.base_url,
            headers={"Authorization": f"Bearer {settings.api_key}"},
            timeout=timeout,
        )

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        **kwargs: Any,
    ) -> str:
        payload = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": (
                temperature if temperature is not None else self.settings.temperature
            ),
            **kwargs,
        }
        response = self._client.post("/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ModelClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()