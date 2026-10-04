"""Tiny OpenAI-compatible client (standard library only).

Environment: ``OPENAI_API_KEY``, ``OPENAI_BASE_URL`` (default https://api.openai.com/v1),
``VOICENOTES_CHAT_MODEL`` (default gpt-4o-mini), ``VOICENOTES_STT_MODEL`` (default whisper-1).
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
import uuid
from pathlib import Path


class LLMError(RuntimeError):
    pass


class OpenAICompatible:
    def __init__(self, api_key: str | None = None, base_url: str | None = None, chat_model: str | None = None,
                 stt_model: str | None = None, timeout: float = 120.0) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY")
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.chat_model = chat_model or os.getenv("VOICENOTES_CHAT_MODEL", "gpt-4o-mini")
        self.stt_model = stt_model or os.getenv("VOICENOTES_STT_MODEL", "whisper-1")
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _request(self, path: str, data: bytes, content_type: str) -> dict:
        if not self.api_key:
            raise LLMError("OPENAI_API_KEY is not set")
        req = urllib.request.Request(self.base_url + path, data=data, method="POST",
                                     headers={"Content-Type": content_type,
                                              "Authorization": f"Bearer {self.api_key}"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:  # pragma: no cover - network
            raise LLMError(f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:300]}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:  # pragma: no cover - network
            raise LLMError(str(exc)) from exc

    def chat_json(self, system: str, user: str) -> dict:
        payload = {"model": self.chat_model, "temperature": 0.1,
                   "response_format": {"type": "json_object"},
                   "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        data = self._request("/chat/completions", json.dumps(payload).encode(), "application/json")
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise LLMError("unexpected chat response") from exc
        return extract_json(content)

    def transcribe(self, audio: Path) -> dict:
        boundary = uuid.uuid4().hex
        parts = []
        for name, value in (("model", self.stt_model), ("response_format", "verbose_json")):
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{audio.name}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n".encode() + audio.read_bytes() + b"\r\n"
        )
        parts.append(f"--{boundary}--\r\n".encode())
        return self._request("/audio/transcriptions", b"".join(parts), f"multipart/form-data; boundary={boundary}")


def extract_json(content: str) -> dict:
    """Parse a JSON object from a model reply, tolerating code fences and chatter."""
    content = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.S)
    if fenced:
        content = fenced.group(1)
    else:
        start, end = content.find("{"), content.rfind("}")
        if start == -1 or end <= start:
            raise LLMError("no JSON object in model reply")
        content = content[start : end + 1]
    try:
        value = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMError(f"invalid JSON from model: {exc}") from exc
    if not isinstance(value, dict):
        raise LLMError("model reply was not a JSON object")
    return value
