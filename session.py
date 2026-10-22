"""In-memory per-chat session state for the Telegram bot."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatSession:
    """Movies shown to one chat plus its selection and page cursor."""

    movies: list[Any] = field(default_factory=list)
    selected: set[int] = field(default_factory=set)
    page: int = 0
    message_id: int | None = None


class SessionStore:
    """Thread-safe mapping of chat id to :class:`ChatSession`."""

    def __init__(self) -> None:
        self._sessions: dict[int, ChatSession] = {}
        self._lock = threading.Lock()

    def get(self, chat_id: int) -> ChatSession | None:
        with self._lock:
            return self._sessions.get(chat_id)

    def put(self, chat_id: int, session: ChatSession) -> None:
        with self._lock:
            self._sessions[chat_id] = session

    def drop(self, chat_id: int) -> None:
        with self._lock:
            self._sessions.pop(chat_id, None)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()


def page_count(session: ChatSession, page_size: int) -> int:
    """Return the number of pages for a session, never less than one."""
    if page_size <= 0:
        return 1
    return max(1, (len(session.movies) + page_size - 1) // page_size)
