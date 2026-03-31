from __future__ import annotations

from typing import Any

import httpx


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    async def chat(self, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self._model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response: httpx.Response | None = None
            last_exc: Exception | None = None
            for endpoint in ("/api/chat", "/v1/chat/completions"):
                try:
                    response = await client.post(f"{self._base_url}{endpoint}", json=payload)
                    response.raise_for_status()
                    break
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    response = None
            if response is None:
                if last_exc:
                    raise last_exc
                raise RuntimeError("LLM endpoint unavailable")

        data = response.json()
        return self._extract_content(data)

    async def health_check(self) -> tuple[bool, str]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            payloads: list[dict[str, Any]] = []
            for endpoint in ("/api/tags", "/v1/models"):
                try:
                    response = await client.get(f"{self._base_url}{endpoint}")
                    response.raise_for_status()
                    payload = response.json()
                    if isinstance(payload, dict):
                        payloads.append(payload)
                except Exception:
                    continue

        if not payloads:
            return False, "No compatible model-list endpoint reachable"

        available_names = self._extract_model_names(payloads)
        if not available_names:
            return False, "Model list endpoint reachable but no models were returned"

        if self._model not in available_names:
            sample = ", ".join(sorted(available_names)[:3])
            return False, f"LLM reachable but model '{self._model}' is not available. Available: {sample}"

        return True, "LLM reachable"

    @staticmethod
    def _extract_content(data: dict[str, Any]) -> str:
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str) and content.strip():
                        return content.strip()
                text = first.get("text")
                if isinstance(text, str) and text.strip():
                    return text.strip()

        message = data.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()

        text = data.get("response")
        if isinstance(text, str) and text.strip():
            return text.strip()

        return ""

    @staticmethod
    def _extract_model_names(payloads: list[dict[str, Any]]) -> set[str]:
        names: set[str] = set()
        for payload in payloads:
            for key in ("models", "data"):
                models = payload.get(key)
                if not isinstance(models, list):
                    continue
                for model in models:
                    if not isinstance(model, dict):
                        continue
                    for candidate_key in ("name", "model", "id"):
                        value = model.get(candidate_key)
                        if isinstance(value, str) and value.strip():
                            names.add(value.strip())
        return names
