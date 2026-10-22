"""Paginated inline keyboard layout for the watchlist."""

from __future__ import annotations

from typing import Any

PAGE_SIZE = 8
LABEL_LIMIT = 48


def truncate_label(text: str, limit: int = LABEL_LIMIT) -> str:
    """Shorten a button label with an ellipsis when it exceeds ``limit``."""
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _total_pages(total_items: int, page_size: int) -> int:
    if page_size <= 0:
        return 1
    return max(1, (total_items + page_size - 1) // page_size)


def clamp_page(page: int, total_items: int, page_size: int) -> int:
    """Clamp a page index into the valid range for ``total_items``."""
    last_page = _total_pages(total_items, page_size) - 1
    return min(max(0, page), last_page)


def _validate_callback_data(data: str) -> str:
    try:
        encoded = data.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError(f"callback_data must be ASCII: {data!r}") from exc
    if not 1 <= len(encoded) <= 64:
        raise ValueError(
            f"callback_data must be 1-64 bytes, got {len(encoded)}: {data!r}"
        )
    return data


def _button(text: str, callback_data: str) -> dict[str, str]:
    return {
        "text": text,
        "callback_data": _validate_callback_data(callback_data),
    }


def build_keyboard(
    movies: list[Any],
    selected: set[int],
    page: int,
    page_size: int = PAGE_SIZE,
) -> dict:
    """Build the inline keyboard for the current page.

    Movie buttons use global indices so selection survives pagination.
    """
    total_pages = _total_pages(len(movies), page_size)
    current_page = clamp_page(page, len(movies), page_size)
    start = current_page * page_size
    end = min(start + page_size, len(movies))

    rows: list[list[dict[str, str]]] = []
    for index in range(start, end):
        item = movies[index]
        title = item.movie.title
        year = item.movie.year
        marker = "☑" if index in selected else "☐"
        label = truncate_label(f"{marker} {title} ({year})")
        rows.append([_button(label, f"t:{index}")])

    navigation: list[dict[str, str]] = []
    if current_page > 0:
        navigation.append(_button("◀", f"p:{current_page - 1}"))
    navigation.append(
        _button(f"Página {current_page + 1}/{total_pages}", "n")
    )
    if current_page + 1 < total_pages:
        navigation.append(_button("▶", f"p:{current_page + 1}"))
    rows.append(navigation)

    rows.append(
        [
            _button(f"Descargar ({len(selected)})", "d"),
            _button("Cancelar", "x"),
        ]
    )
    return {"inline_keyboard": rows}
