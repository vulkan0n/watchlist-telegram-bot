"""Telegram update handlers for the watchlist bot."""

from __future__ import annotations

import logging
from typing import Any

from keyboard import PAGE_SIZE, build_keyboard, clamp_page
from session import ChatSession, SessionStore

logger = logging.getLogger(__name__)

SEARCHING_TEXT = "⏳ Buscando películas en tu watchlist…"
YTS_UNAVAILABLE_TEXT = "⚠️ YTS no está disponible. Probá de nuevo más tarde."
GENERIC_ERROR_TEXT = "⚠️ No se pudo obtener la lista. Intenta de nuevo más tarde."
EMPTY_TEXT = "No hay películas nuevas disponibles ahora."
CANCEL_TEXT = "Operación cancelada."
NO_SELECTION_TEXT = "No hay películas seleccionadas."
UNKNOWN_ACTION_TEXT = "Acción desconocida."
DOWNLOAD_ERROR_TEXT = (
    "⚠️ No se pudo encolar la descarga. Intenta de nuevo más tarde."
)
HELP_TEXT = (
    "Comandos disponibles:\n"
    "/lista — ver películas disponibles\n"
    "/help — mostrar esta ayuda"
)
UNKNOWN_COMMAND_TEXT = (
    "Comando desconocido. Envía /help para ver la ayuda."
)
EMPTY_KEYBOARD = {"inline_keyboard": []}


def _summary_text(count: int) -> str:
    return (
        f"🎬 Películas disponibles: {count}\n"
        'Tocá para seleccionar y después "Descargar".'
    )


def _message_id(result: Any) -> int | None:
    if isinstance(result, dict):
        value = result.get("message_id")
        if isinstance(value, int):
            return value
    return None


def _parse_command(text: str) -> str | None:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    first_token = stripped.split(maxsplit=1)[0]
    name = first_token[1:].split("@", 1)[0].strip().lower()
    return name or None


def _parse_index(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_yts_unavailable(exc: BaseException) -> bool:
    # Checked by name so handlers never import the sibling package.
    return exc.__class__.__name__ == "YTSUnavailableError"


class BotHandlers:
    """Dispatch Telegram updates to the watchlist flows."""

    def __init__(
        self,
        api: Any,
        pipeline: Any,
        sessions: SessionStore,
        allowed_chat_id: int,
        *,
        page_size: int = PAGE_SIZE,
    ) -> None:
        self._api = api
        self._pipeline = pipeline
        self._sessions = sessions
        self._allowed_chat_id = allowed_chat_id
        self._page_size = page_size

    def handle_update(self, update: dict) -> None:
        """Dispatch one update and never let an exception escape."""
        try:
            if "message" in update:
                self._handle_message(update["message"])
            elif "callback_query" in update:
                self._handle_callback(update["callback_query"])
        except Exception:  # noqa: BLE001 - one bad update must not stop polling
            logger.exception(
                "Failed to handle update %s", update.get("update_id")
            )

    def _handle_message(self, message: dict) -> None:
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id != self._allowed_chat_id:
            logger.warning("Ignoring message from an unauthorized chat")
            return

        command = _parse_command(message.get("text") or "")
        if command is None:
            return
        if command in {"start", "help"}:
            self._api.send_message(chat_id, HELP_TEXT)
        elif command in {"lista", "watchlist", "pelis"}:
            self._start_list(chat_id)
        else:
            self._api.send_message(chat_id, UNKNOWN_COMMAND_TEXT)

    def _start_list(self, chat_id: int) -> None:
        self._sessions.drop(chat_id)
        placeholder = self._api.send_message(chat_id, SEARCHING_TEXT)
        message_id = _message_id(placeholder)

        try:
            movies = self._pipeline.list_available()
        except Exception as exc:  # noqa: BLE001 - report failures to the user
            if _is_yts_unavailable(exc):
                text = YTS_UNAVAILABLE_TEXT
            else:
                logger.exception("Failed to load the watchlist")
                text = GENERIC_ERROR_TEXT
            self._edit_or_send(chat_id, message_id, text, EMPTY_KEYBOARD)
            return

        if not movies:
            self._edit_or_send(chat_id, message_id, EMPTY_TEXT, EMPTY_KEYBOARD)
            return

        session = ChatSession(movies=movies, message_id=message_id)
        self._sessions.put(chat_id, session)
        self._render(chat_id, session, _summary_text(len(movies)))

    def _handle_callback(self, callback: dict) -> None:
        callback_id = callback.get("id", "")
        data = callback.get("data") or ""
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")

        # Always acknowledge first so the client spinner never hangs.
        if chat_id != self._allowed_chat_id:
            self._api.answer_callback_query(callback_id)
            logger.warning("Ignoring callback from an unauthorized chat")
            return

        session = self._sessions.get(chat_id)

        if data == "n":
            self._api.answer_callback_query(callback_id)
            return

        if data.startswith("p:"):
            self._api.answer_callback_query(callback_id)
            page = _parse_index(data[2:])
            if page is None or session is None:
                return
            session.page = clamp_page(
                page, len(session.movies), self._page_size
            )
            self._render(chat_id, session, _summary_text(len(session.movies)))
            return

        if data.startswith("t:"):
            self._api.answer_callback_query(callback_id)
            index = _parse_index(data[2:])
            if (
                index is None
                or session is None
                or not 0 <= index < len(session.movies)
            ):
                return
            if index in session.selected:
                session.selected.discard(index)
            else:
                session.selected.add(index)
            self._render(chat_id, session, _summary_text(len(session.movies)))
            return

        if data == "x":
            self._api.answer_callback_query(callback_id)
            if session is not None:
                message_id = session.message_id
            else:
                message_id = message.get("message_id")
            if not isinstance(message_id, int):
                message_id = None
            self._edit_or_send(chat_id, message_id, CANCEL_TEXT, EMPTY_KEYBOARD)
            self._sessions.drop(chat_id)
            return

        if data == "d":
            self._download(chat_id, callback_id, session)
            return

        self._api.answer_callback_query(callback_id, UNKNOWN_ACTION_TEXT)

    def _download(
        self,
        chat_id: int,
        callback_id: str,
        session: ChatSession | None,
    ) -> None:
        if session is None or not session.selected:
            self._api.answer_callback_query(callback_id, NO_SELECTION_TEXT)
            return

        selected_movies = [
            session.movies[index]
            for index in sorted(session.selected)
            if 0 <= index < len(session.movies)
        ]
        if not selected_movies:
            self._api.answer_callback_query(callback_id, NO_SELECTION_TEXT)
            return

        self._api.answer_callback_query(callback_id)
        try:
            results = self._pipeline.download(selected_movies)
        except Exception:  # noqa: BLE001 - report failures to the user
            logger.exception("Failed to queue the selected download")
            self._finish(chat_id, session, DOWNLOAD_ERROR_TEXT)
            return

        succeeded = sum(1 for _movie, ok in results if ok)
        failed = len(selected_movies) - succeeded
        text = f"✅ Encoladas: {succeeded}"
        if failed:
            text += f"\n❌ Fallaron: {failed}"
        self._finish(chat_id, session, text)

    def _render(
        self,
        chat_id: int,
        session: ChatSession,
        text: str,
    ) -> None:
        markup = build_keyboard(
            session.movies,
            session.selected,
            session.page,
            self._page_size,
        )
        if session.message_id is None:
            response = self._api.send_message(
                chat_id, text, reply_markup=markup
            )
            session.message_id = _message_id(response)
            self._sessions.put(chat_id, session)
        else:
            self._api.edit_message_text(
                chat_id,
                session.message_id,
                text,
                reply_markup=markup,
            )

    def _edit_or_send(
        self,
        chat_id: int,
        message_id: int | None,
        text: str,
        reply_markup: dict,
    ) -> None:
        if message_id is None:
            self._api.send_message(chat_id, text, reply_markup=reply_markup)
        else:
            self._api.edit_message_text(
                chat_id,
                message_id,
                text,
                reply_markup=reply_markup,
            )

    def _finish(self, chat_id: int, session: ChatSession, text: str) -> None:
        self._edit_or_send(chat_id, session.message_id, text, EMPTY_KEYBOARD)
        self._sessions.drop(chat_id)
