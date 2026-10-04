from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ChatHistory:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.chats: list[dict[str, Any]] = []
        self.active_id: str | None = None
        self.load()

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            data = {}
        except (OSError, json.JSONDecodeError):
            data = {}
        chats = data.get("chats", []) if isinstance(data, dict) else []
        self.chats = [chat for chat in chats if isinstance(chat, dict) and isinstance(chat.get("messages", []), list)]
        active_id = data.get("active_id") if isinstance(data, dict) else None
        self.active_id = active_id if any(chat.get("id") == active_id for chat in self.chats) else None
        if self.active_id is None and self.chats:
            self.active_id = self.chats[-1].get("id")
        if self.active_id is None:
            self.new_chat()

    @property
    def active_chat(self) -> dict[str, Any]:
        chat = next((item for item in self.chats if item.get("id") == self.active_id), None)
        if chat is None:
            return self.new_chat()
        return chat

    def new_chat(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        chat = {"id": uuid.uuid4().hex, "title": "New chat", "created_at": now, "updated_at": now, "messages": []}
        self.chats.append(chat)
        self.active_id = chat["id"]
        self.save()
        return chat

    def add_message(self, role: str, text: str, image: str | None = None) -> None:
        if role not in {"user", "assistant"}:
            raise ValueError("Chat role must be user or assistant.")
        chat = self.active_chat
        message: dict[str, str] = {"role": role, "text": text}
        if image:
            message["image"] = image
        chat["messages"].append(message)
        chat["updated_at"] = datetime.now(timezone.utc).isoformat()
        if role == "user" and chat["title"] == "New chat" and text.strip():
            chat["title"] = " ".join(text.strip().split())[:42]
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps({"version": 1, "active_id": self.active_id, "chats": self.chats}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)
