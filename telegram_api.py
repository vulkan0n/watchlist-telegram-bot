"""Telegram Bot API client built on the Python standard library."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)


class TelegramAPIError(Exception):
    """A Telegram API or transport failure.

    The token is never included in the message or attributes.
    """

    def __init__(
        self,
        message: str,
        *,
        description: str | None = None,
        error_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.description = description
        self.error_code = error_code


class TelegramClient:
    """Minimal long-polling client for the Telegram Bot API."""

    def __init__(
        self,
        token: str,
        *,
        base_url: str = "https://api.telegram.org",
        request_timeout: int = 65,
    ) -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._request_timeout = request_timeout

    def call(self, method: str, payload: dict | None = None) -> Any:
        """Call one Bot API method and return its ``result`` value."""
        url = f"{self._base_url}/bot{self._token}/{method}"
        body = json.dumps(payload or {}).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                request, timeout=self._request_timeout
            ) as response:
                raw_body = response.read()
        except urllib.error.HTTPError as exc:
            raw_body = exc.read()
            data = _try_decode(raw_body)
            description = None
            error_code = exc.code
            if isinstance(data, dict):
                description = data.get("description")
                error_code = data.get("error_code", error_code)
            detail = description or f"HTTP {exc.code}"
            raise TelegramAPIError(
                f"{method} failed: {detail}",
                description=description,
                error_code=error_code,
            ) from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise TelegramAPIError(f"{method} transport error") from exc

        data = _try_decode(raw_body)
        if not isinstance(data, dict):
            raise TelegramAPIError(f"{method} returned invalid JSON")

        if not data.get("ok"):
            description = data.get("description")
            raise TelegramAPIError(
                f"{method} failed: {description or 'unknown error'}",
                description=description,
                error_code=data.get("error_code"),
            )
        return data.get("result")

    def get_updates(
        self,
        *,
        offset: int | None = None,
        timeout: int = 50,
        allowed_updates: list[str] | None = None,
    ) -> list[dict]:
        payload: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        if allowed_updates is not None:
            payload["allowed_updates"] = allowed_updates
        result = self.call("getUpdates", payload)
        return result if isinstance(result, list) else []

    def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_markup: dict | None = None,
    ) -> dict:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        result = self.call("sendMessage", payload)
        return result if isinstance(result, dict) else {}

    def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        *,
        reply_markup: dict | None = None,
    ) -> bool:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        try:
            self.call("editMessageText", payload)
        except TelegramAPIError as exc:
            if "message is not modified" in (exc.description or "").lower():
                return False
            raise
        return True

    def answer_callback_query(
        self,
        callback_query_id: str,
        text: str | None = None,
    ) -> None:
        """Acknowledge a callback without ever letting an error kill the loop."""
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text is not None:
            payload["text"] = text
        try:
            self.call("answerCallbackQuery", payload)
        except Exception as exc:  # noqa: BLE001 - acknowledgement is best effort
            logger.warning("Could not answer callback query: %s", exc)

    def delete_message(self, chat_id: int, message_id: int) -> bool:
        """Best-effort message deletion; never raises."""
        try:
            result = self.call(
                "deleteMessage",
                {"chat_id": chat_id, "message_id": message_id},
            )
        except Exception as exc:  # noqa: BLE001 - deletion is best effort
            logger.warning("Could not delete message: %s", exc)
            return False
        return bool(result)


def _try_decode(raw_body: bytes) -> Any:
    try:
        return json.loads(raw_body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
