from __future__ import annotations

import os
import threading
import base64
import io
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from dotenv import load_dotenv


SYSTEM_PROMPT = """You are KHULA JARVIS, a bilingual Hindi/English AI app developer. Be accurate, state uncertainty, and never claim to have performed an action you did not perform. For attached images, inspect visual details carefully and give concrete, ordered troubleshooting or implementation steps. Do not request secrets. Coding requests that require file edits belong in the coding agent."""
DEFAULT_MODEL = "gemini-3.5-flash-lite"


class GeminiBrain:
    def __init__(self) -> None:
        self.model_name = DEFAULT_MODEL
        self.api_key = ""
        self._client = None
        self.use_rest = os.getenv("KHULA_USE_GEMINI_REST", "").strip().lower() in {"1", "true", "yes"}
        self._lock = threading.RLock()
        self._history: list[tuple[str, str]] = []
        self.env_path = Path(__file__).resolve().parents[1] / ".env"
        self.reload_credentials()

    def reload_credentials(self) -> None:
        with self._lock:
            load_dotenv(self.env_path, override=True)
            api_key = os.getenv("GEMINI_API_KEY", "").strip()
            model_name = os.getenv("GEMINI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
            if api_key == self.api_key and model_name == self.model_name:
                return

            client = None
            if api_key and not self.use_rest:
                try:
                    from google import genai
                except ImportError as exc:
                    raise RuntimeError("Install requirements.txt to use Gemini.") from exc
                client = genai.Client(api_key=api_key)
            self.api_key = api_key
            self.model_name = model_name
            self._client = client

    def _require_model(self):
        self.reload_credentials()
        if not self.api_key:
            raise RuntimeError("Gemini is not configured. Add GEMINI_API_KEY to KHULA_JARVIS/.env and retry.")
        if self.use_rest:
            return None
        if self._client is None:
            raise RuntimeError("Gemini client is unavailable. Check the google-genai installation.")
        return self._client

    def _generate_content(self, client, **kwargs):
        if self.use_rest:
            return self._generate_rest_content(**kwargs)
        try:
            return client.models.generate_content(**kwargs)
        except Exception as exc:
            code = getattr(exc, "code", None)
            details = str(exc)
            if code == 429 or "RESOURCE_EXHAUSTED" in details or "429" in details:
                raise RuntimeError(
                    f"Gemini quota/rate limit reached for {self.model_name}. Check Google AI Studio, "
                    f"wait until the provider's reset time, or increase the project's quota. Details: {details}"
                ) from exc
            raise

    def _generate_rest_content(self, *, model: str, contents, config: dict) -> SimpleNamespace:
        parts: list[dict[str, object]] = []
        for item in contents if isinstance(contents, list) else [contents]:
            if isinstance(item, str):
                parts.append({"text": item})
            else:
                image_buffer = io.BytesIO()
                item.save(image_buffer, format="PNG")
                parts.append({
                    "inline_data": {
                        "mime_type": "image/png",
                        "data": base64.b64encode(image_buffer.getvalue()).decode("ascii"),
                    }
                })

        generation_config = {
            {
                "max_output_tokens": "maxOutputTokens",
                "response_mime_type": "responseMimeType",
            }.get(key, key): value
            for key, value in config.items()
        }
        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": generation_config,
        }
        endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{urllib.parse.quote(model, safe='')}:generateContent"
        )
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            if exc.code == 429 or "RESOURCE_EXHAUSTED" in details:
                raise RuntimeError(
                    f"Gemini quota/rate limit reached for {model}. Check Google AI Studio "
                    f"or wait until the provider's reset time. Details: {details}"
                ) from exc
            raise RuntimeError(f"Gemini API request failed (HTTP {exc.code}): {details}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Gemini API request failed: {exc.reason}") from exc

        candidates = data.get("candidates", [])
        if not candidates:
            message = data.get("promptFeedback", {}).get("blockReason", "No response candidate was returned.")
            return SimpleNamespace(text=f"Gemini could not answer: {message}")
        response_parts = candidates[0].get("content", {}).get("parts", [])
        return SimpleNamespace(text="".join(
            str(part["text"]) for part in response_parts if isinstance(part, dict) and "text" in part
        ))

    def ask(self, prompt: str, image_path: Path | None = None) -> str:
        client = self._require_model()
        with self._lock:
            history = "\n".join(f"{role}: {text}" for role, text in self._history[-12:])
            request = f"{SYSTEM_PROMPT}\n\nConversation so far:\n{history}\n\nUser: {prompt}"
            contents: str | list[object] = request
            if image_path is not None:
                try:
                    from PIL import Image
                except ImportError as exc:
                    raise RuntimeError("Install Pillow to analyze attached images.") from exc
                with Image.open(image_path) as image:
                    contents = [request, image.copy()]
                    response = self._generate_content(
                        client,
                        model=self.model_name,
                        contents=contents,
                        config={"temperature": 0.35, "max_output_tokens": 4096},
                    )
            else:
                response = self._generate_content(
                    client,
                    model=self.model_name,
                    contents=contents,
                    config={"temperature": 0.35, "max_output_tokens": 4096},
                )
            answer = (response.text or "Gemini returned an empty response.").strip()
            self._history.extend((("User", prompt), ("Assistant", answer)))
            self._history = self._history[-12:]
            return answer

    def generate_file_plan(self, task: str, project_root: Path, diagnostics: str = "") -> str:
        client = self._require_model()
        prompt = f"""You are generating a focused code change for a local project. Return ONLY a JSON object with this schema: {{"summary":"...","files":[{{"path":"relative/path","content":"complete file contents"}}]}}. Do not use markdown fences. Paths must be relative to the project root. Do not edit secrets, credentials, or files outside the project. Preserve unrelated files and make the smallest complete change. Never include shell commands or instructions to execute arbitrary commands.
Project root: {project_root}
Task: {task}
Current build/test diagnostics (empty on first pass):
{diagnostics[:16000]}"""
        response = self._generate_content(
            client,
            model=self.model_name,
            contents=prompt,
            config={"temperature": 0.15, "max_output_tokens": 8192, "response_mime_type": "application/json"},
        )
        return (response.text or "").strip()

    def analyze_image(self, image_path: Path, prompt: str) -> str:
        return self.ask(prompt, image_path=image_path)
