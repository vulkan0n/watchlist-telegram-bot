"""Handler tests using a recording fake Telegram API and fake pipeline."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from handlers import BotHandlers
from session import SessionStore

ALLOWED_CHAT = 1234567890
OTHER_CHAT = 999


def make_movie(title: str, year: int = 2020, imdb_id: str = "tt0000001") -> SimpleNamespace:
    return SimpleNamespace(
        movie=SimpleNamespace(title=title, year=year, imdb_id=imdb_id),
        available=True,
        torrents=[
            SimpleNamespace(
                magnet_url="magnet:?xt=urn:btih:abc",
                seeds=10,
                quality="1080p",
            )
        ],
        search_failed=False,
    )


class FakeAPI:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._next_message_id = 100

    def send_message(
        self, chat_id: int, text: str, *, reply_markup: dict | None = None
    ) -> dict:
        self._next_message_id += 1
        self.calls.append(
            {
                "method": "send_message",
                "chat_id": chat_id,
                "text": text,
                "reply_markup": reply_markup,
            }
        )
        return {"message_id": self._next_message_id}

    def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        *,
        reply_markup: dict | None = None,
    ) -> bool:
        self.calls.append(
            {
                "method": "edit_message_text",
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "reply_markup": reply_markup,
            }
        )
        return True

    def answer_callback_query(
        self, callback_query_id: str, text: str | None = None
    ) -> None:
        self.calls.append(
            {
                "method": "answer_callback_query",
                "callback_query_id": callback_query_id,
                "text": text,
            }
        )


class FakePipeline:
    def __init__(
        self,
        movies: list[Any] | None = None,
        results: list[tuple[Any, bool]] | None = None,
        error: BaseException | None = None,
        statuses: list[Any] | None = None,
        status_error: BaseException | None = None,
    ) -> None:
        self.movies = movies or []
        self.results = results
        self.error = error
        self.statuses = statuses or []
        self.status_error = status_error
        self.list_calls = 0
        self.status_calls = 0
        self.download_calls: list[list[Any]] = []

    def list_status(self) -> list[Any]:
        self.status_calls += 1
        if self.status_error is not None:
            raise self.status_error
        return list(self.statuses)

    def list_available(self) -> list[Any]:
        self.list_calls += 1
        if self.error is not None:
            raise self.error
        return list(self.movies)

    def download(self, movies: list[Any]) -> list[tuple[Any, bool]]:
        self.download_calls.append(list(movies))
        if self.results is not None:
            return self.results
        return [(movie, True) for movie in movies]


def make_handlers(
    movies: list[Any] | None = None,
    results: list[tuple[Any, bool]] | None = None,
    error: BaseException | None = None,
    statuses: list[Any] | None = None,
    status_error: BaseException | None = None,
) -> tuple[BotHandlers, FakeAPI, FakePipeline, SessionStore]:
    api = FakeAPI()
    pipeline = FakePipeline(movies, results, error, statuses, status_error)
    sessions = SessionStore()
    handlers = BotHandlers(api, pipeline, sessions, ALLOWED_CHAT)
    return handlers, api, pipeline, sessions


def message_update(chat_id: int, text: str, update_id: int = 1) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": 1,
            "chat": {"id": chat_id},
            "text": text,
        },
    }


def callback_update(
    chat_id: int,
    data: str,
    message_id: int = 101,
    update_id: int = 2,
) -> dict:
    return {
        "update_id": update_id,
        "callback_query": {
            "id": "cq-1",
            "data": data,
            "message": {
                "message_id": message_id,
                "chat": {"id": chat_id},
            },
        },
    }


def test_message_from_unauthorized_chat_is_ignored() -> None:
    handlers, api, pipeline, sessions = make_handlers([make_movie("Movie")])

    handlers.handle_update(message_update(OTHER_CHAT, "/lista"))

    assert api.calls == []
    assert pipeline.list_calls == 0
    assert sessions.get(OTHER_CHAT) is None


def test_list_command_renders_keyboard_and_stores_session() -> None:
    movies = [make_movie("First"), make_movie("Second")]
    handlers, api, _, sessions = make_handlers(movies)

    handlers.handle_update(message_update(ALLOWED_CHAT, "/lista@some_bot"))

    session = sessions.get(ALLOWED_CHAT)
    assert session is not None
    assert session.movies == movies
    assert session.message_id == 101
    assert api.calls[0]["method"] == "send_message"
    assert "Buscando películas" in api.calls[0]["text"]

    edit = api.calls[-1]
    assert edit["method"] == "edit_message_text"
    assert edit["message_id"] == 101
    assert "Películas disponibles: 2" in edit["text"]
    assert edit["reply_markup"]["inline_keyboard"][-1][0]["text"] == "Descargar (0)"


def test_toggle_callback_updates_selection_and_edits_message() -> None:
    movies = [make_movie("First"), make_movie("Second")]
    handlers, api, _, sessions = make_handlers(movies)
    handlers.handle_update(message_update(ALLOWED_CHAT, "/lista"))
    api.calls.clear()

    handlers.handle_update(callback_update(ALLOWED_CHAT, "t:0"))

    assert sessions.get(ALLOWED_CHAT).selected == {0}
    assert api.calls[0]["method"] == "answer_callback_query"
    assert api.calls[-1]["method"] == "edit_message_text"
    first_button = api.calls[-1]["reply_markup"]["inline_keyboard"][0][0]
    assert first_button["text"].startswith("☑")


def test_page_callback_clamps_to_valid_range() -> None:
    movies = [make_movie(f"Movie {i}") for i in range(10)]
    handlers, api, _, sessions = make_handlers(movies)
    handlers.handle_update(message_update(ALLOWED_CHAT, "/lista"))
    api.calls.clear()

    handlers.handle_update(callback_update(ALLOWED_CHAT, "p:99"))
    assert sessions.get(ALLOWED_CHAT).page == 1
    navigation = api.calls[-1]["reply_markup"]["inline_keyboard"][2]
    assert navigation[1]["text"] == "Página 2/2"

    api.calls.clear()
    handlers.handle_update(callback_update(ALLOWED_CHAT, "p:-5"))
    assert sessions.get(ALLOWED_CHAT).page == 0
    navigation = api.calls[-1]["reply_markup"]["inline_keyboard"][8]
    assert navigation[0]["text"] == "Página 1/2"


def test_download_callback_calls_pipeline_once_and_reports_results() -> None:
    movies = [make_movie("First"), make_movie("Second"), make_movie("Third")]
    results = [(movies[0], True), (movies[1], False)]
    handlers, api, pipeline, sessions = make_handlers(movies, results)
    handlers.handle_update(message_update(ALLOWED_CHAT, "/lista"))
    handlers.handle_update(callback_update(ALLOWED_CHAT, "t:0"))
    handlers.handle_update(callback_update(ALLOWED_CHAT, "t:1"))
    api.calls.clear()

    handlers.handle_update(callback_update(ALLOWED_CHAT, "d"))

    assert pipeline.download_calls == [[movies[0], movies[1]]]
    assert len(pipeline.download_calls) == 1
    assert api.calls[0]["method"] == "answer_callback_query"
    result_text = api.calls[-1]["text"]
    assert "✅ Encoladas: 1" in result_text
    assert "❌ Fallaron: 1" in result_text
    assert api.calls[-1]["reply_markup"] == {"inline_keyboard": []}
    assert sessions.get(ALLOWED_CHAT) is None


def test_download_with_empty_selection_does_not_call_pipeline() -> None:
    handlers, api, pipeline, sessions = make_handlers([make_movie("First")])
    handlers.handle_update(message_update(ALLOWED_CHAT, "/lista"))
    api.calls.clear()

    handlers.handle_update(callback_update(ALLOWED_CHAT, "d"))

    assert pipeline.download_calls == []
    assert len(api.calls) == 1
    assert api.calls[0]["method"] == "answer_callback_query"
    assert api.calls[0]["text"] == "No hay películas seleccionadas."
    assert sessions.get(ALLOWED_CHAT) is not None


def test_unknown_callback_is_answered_safely() -> None:
    handlers, api, _, sessions = make_handlers([make_movie("First")])
    handlers.handle_update(message_update(ALLOWED_CHAT, "/lista"))
    api.calls.clear()

    handlers.handle_update(callback_update(ALLOWED_CHAT, "bogus"))

    assert len(api.calls) == 1
    assert api.calls[0]["method"] == "answer_callback_query"
    assert api.calls[0]["text"] == "Acción desconocida."
    assert sessions.get(ALLOWED_CHAT) is not None


def test_empty_list_is_reported_without_a_session_or_keyboard() -> None:
    handlers, api, _, sessions = make_handlers([])

    handlers.handle_update(message_update(ALLOWED_CHAT, "/lista"))

    assert sessions.get(ALLOWED_CHAT) is None
    edit = api.calls[-1]
    assert edit["method"] == "edit_message_text"
    assert edit["text"] == "No hay películas nuevas disponibles ahora."
    assert edit["reply_markup"] == {"inline_keyboard": []}


def test_yts_outage_is_reported_with_a_specific_message() -> None:
    class YTSUnavailableError(RuntimeError):
        pass

    handlers, api, _, sessions = make_handlers(
        error=YTSUnavailableError("down")
    )

    handlers.handle_update(message_update(ALLOWED_CHAT, "/lista"))

    assert sessions.get(ALLOWED_CHAT) is None
    edit = api.calls[-1]
    assert edit["method"] == "edit_message_text"
    assert "YTS no está disponible" in edit["text"]


def test_generic_pipeline_failure_is_reported_without_raising() -> None:
    handlers, api, _, sessions = make_handlers(error=RuntimeError("boom"))

    handlers.handle_update(message_update(ALLOWED_CHAT, "/lista"))

    assert sessions.get(ALLOWED_CHAT) is None
    edit = api.calls[-1]
    assert edit["method"] == "edit_message_text"
    assert "No se pudo obtener la lista" in edit["text"]


def test_cancel_callback_removes_keyboard_and_drops_session() -> None:
    handlers, api, _, sessions = make_handlers([make_movie("First")])
    handlers.handle_update(message_update(ALLOWED_CHAT, "/lista"))
    api.calls.clear()

    handlers.handle_update(callback_update(ALLOWED_CHAT, "x"))

    assert sessions.get(ALLOWED_CHAT) is None
    assert api.calls[0]["method"] == "answer_callback_query"
    assert api.calls[-1]["text"] == "Operación cancelada."
    assert api.calls[-1]["reply_markup"] == {"inline_keyboard": []}


def test_callback_from_unauthorized_chat_is_acknowledged_without_action() -> None:
    handlers, api, _, sessions = make_handlers([make_movie("First")])
    handlers.handle_update(message_update(ALLOWED_CHAT, "/lista"))
    api.calls.clear()

    handlers.handle_update(callback_update(OTHER_CHAT, "d"))

    assert len(api.calls) == 1
    assert api.calls[0]["method"] == "answer_callback_query"
    assert sessions.get(ALLOWED_CHAT) is not None


# ── /status ───────────────────────────────────────────────────────────


def make_status(
    name: str,
    percent_done: float,
    status: str = "downloading",
) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        percent_done=percent_done,
        status=status,
        eta_seconds=None,
        rate_download=0,
        rate_upload=0,
        ratio=0.0,
    )


def test_status_command_lists_progress() -> None:
    statuses = [
        make_status("Downloading Movie", 0.42, "downloading"),
        make_status("Done Movie", 1.0, "completed"),
    ]
    handlers, api, pipeline, _ = make_handlers(statuses=statuses)

    handlers.handle_update(message_update(ALLOWED_CHAT, "/status"))

    assert pipeline.status_calls == 1
    assert api.calls[0]["method"] == "send_message"
    text = api.calls[-1]["text"]
    assert "42%" in text
    assert "100%" in text
    assert "Downloading Movie" in text
    assert "Done Movie" in text


def test_status_command_alias_and_empty() -> None:
    handlers, api, _, _ = make_handlers(statuses=[])

    handlers.handle_update(message_update(ALLOWED_CHAT, "/estado"))

    assert "No hay torrents" in api.calls[-1]["text"]


def test_status_command_reports_transmission_failure() -> None:
    handlers, api, _, _ = make_handlers(status_error=RuntimeError("down"))

    handlers.handle_update(message_update(ALLOWED_CHAT, "/status"))

    assert "No pude consultar Transmission" in api.calls[-1]["text"]


def test_status_command_ignores_unauthorized_chat() -> None:
    handlers, api, pipeline, _ = make_handlers(
        statuses=[make_status("Movie", 0.5)]
    )

    handlers.handle_update(message_update(OTHER_CHAT, "/status"))

    assert api.calls == []
    assert pipeline.status_calls == 0
