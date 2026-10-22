"""Tests for the paginated inline keyboard layout."""

from __future__ import annotations

from types import SimpleNamespace

from keyboard import PAGE_SIZE, build_keyboard, clamp_page, truncate_label


def make_movie(title: str, year: int = 2020) -> SimpleNamespace:
    return SimpleNamespace(
        movie=SimpleNamespace(title=title, year=year, imdb_id="tt0000001"),
        available=True,
        torrents=[SimpleNamespace(magnet_url="magnet:?xt=urn:btih:abc")],
    )


def all_callback_data(keyboard: dict) -> list[str]:
    return [
        button["callback_data"]
        for row in keyboard["inline_keyboard"]
        for button in row
    ]


def test_first_page_has_eight_movies_and_action_rows() -> None:
    movies = [make_movie(f"Movie {i}", 2000 + i) for i in range(10)]

    keyboard = build_keyboard(movies, set(), page=0)

    rows = keyboard["inline_keyboard"]
    movie_rows = rows[:PAGE_SIZE]
    assert len(movie_rows) == 8
    assert movie_rows[0][0]["callback_data"] == "t:0"
    assert movie_rows[7][0]["callback_data"] == "t:7"
    assert movie_rows[0][0]["text"] == "☐ Movie 0 (2000)"

    navigation = rows[8]
    assert navigation[0]["text"] == "Página 1/2"
    assert navigation[0]["callback_data"] == "n"
    assert navigation[-1]["text"] == "▶"
    assert navigation[-1]["callback_data"] == "p:1"
    assert all(button["text"] != "◀" for button in navigation)

    actions = rows[9]
    assert actions[0]["text"] == "Descargar (0)"
    assert actions[0]["callback_data"] == "d"
    assert actions[1]["text"] == "Cancelar"
    assert actions[1]["callback_data"] == "x"


def test_second_page_hides_next_arrow_and_uses_global_indices() -> None:
    movies = [make_movie(f"Movie {i}") for i in range(10)]

    keyboard = build_keyboard(movies, set(), page=1)

    rows = keyboard["inline_keyboard"]
    assert rows[0][0]["callback_data"] == "t:8"
    assert rows[1][0]["callback_data"] == "t:9"

    navigation = rows[2]
    assert navigation[0]["text"] == "◀"
    assert navigation[0]["callback_data"] == "p:0"
    assert navigation[1]["text"] == "Página 2/2"
    assert navigation[-1]["text"] == "◀" or len(navigation) == 2
    assert all(button["text"] != "▶" for button in navigation)


def test_selected_movies_are_checked_and_counted() -> None:
    movies = [make_movie("First"), make_movie("Second")]

    keyboard = build_keyboard(movies, selected={1}, page=0)

    rows = keyboard["inline_keyboard"]
    assert rows[0][0]["text"].startswith("☐")
    assert rows[1][0]["text"].startswith("☑")
    assert rows[-1][0]["text"] == "Descargar (1)"


def test_every_callback_data_is_ascii_and_within_telegram_limit() -> None:
    movies = [make_movie(f"Película {i}") for i in range(40)]

    for page in range(5):
        keyboard = build_keyboard(movies, selected={0, 39}, page=page)
        for data in all_callback_data(keyboard):
            assert data
            assert data.isascii()
            assert 1 <= len(data.encode("ascii")) <= 64


def test_truncate_label_keeps_short_text_and_cuts_long_text() -> None:
    assert truncate_label("Short") == "Short"

    truncated = truncate_label("x" * 100, limit=48)
    assert len(truncated) == 48
    assert truncated.endswith("…")


def test_clamp_page_stays_within_bounds() -> None:
    assert clamp_page(-4, total_items=10, page_size=8) == 0
    assert clamp_page(0, total_items=10, page_size=8) == 0
    assert clamp_page(1, total_items=10, page_size=8) == 1
    assert clamp_page(99, total_items=10, page_size=8) == 1
    assert clamp_page(99, total_items=0, page_size=8) == 0
