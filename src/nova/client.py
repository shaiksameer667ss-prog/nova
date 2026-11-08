import json
from typing import Any
import httpx
from nova.config import Settings

class ModelClient:
    def __init__(self, settings: Settings, timeout: float = 120.0):
        self.settings = settings
        self._client = httpx.Client(
            base_url=settings.base_url,
            headers={"Authorization": f"Bearer {settings.api_key}"},
            timeout=timeout,
        )

    def chat(self, messages: list[dict[str, str]], temperature: float | None = None, **kwargs: Any) -> str:
        content, usage_info, status = self.chat_with_usage(messages, temperature, **kwargs)
        if status != "success":
            raise RuntimeError(f"Model call failed: {status}")
        return content

    def chat_with_usage(self, messages: list[dict[str, str]], temperature: float | None = None, **kwargs: Any) -> tuple[str, dict, str]:
        payload = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.settings.temperature,
            **kwargs,
        }
        
        try:
            response = self._client.post("/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            
            raw_usage = data.get("usage")
            required = ("prompt_tokens", "completion_tokens", "total_tokens")
            
            # Strict validation: type must be exactly int (not bool) and non-negative
            is_complete = (
                isinstance(raw_usage, dict)
                and all(type(raw_usage.get(k)) is int and raw_usage[k] >= 0 for k in required)
            )
            
            p_tok = c_tok = t_tok = None
            
            if is_complete:
                p_tok = raw_usage["prompt_tokens"]
                c_tok = raw_usage["completion_tokens"]
                t_tok = raw_usage["total_tokens"]
                
                # Reject inconsistent accounting
                if p_tok + c_tok != t_tok:
                    is_complete = False
                    p_tok = c_tok = t_tok = None
                    
            usage_info = {
                "prompt_tokens": p_tok,
                "completion_tokens": c_tok,
                "total_tokens": t_tok,
                "usage_complete": is_complete,
                "usage_json": json.dumps(raw_usage) if raw_usage else None
            }
            return content, usage_info, "success"
            
        except Exception as e:
            usage_info = {
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
                "usage_complete": False,
                "usage_json": None
            }
            return "", usage_info, f"error: {type(e).__name__}: {str(e)}"

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ModelClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()