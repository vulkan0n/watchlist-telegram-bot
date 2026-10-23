"""Adapter between the bot and the sibling ``watchlist_downloader`` package."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from config import Config


def ensure_package_path(path: Path) -> None:
    """Make the sibling package importable without installing it."""
    resolved = str(Path(path).expanduser().resolve())
    if resolved not in sys.path:
        sys.path.insert(0, resolved)


class WatchlistPipeline:
    """Thin facade over ``watchlist_downloader.service``."""

    def __init__(self, config: Config) -> None:
        ensure_package_path(config.watchlist_downloader_path)
        # Imported lazily so this module never requires the sibling package.
        from watchlist_downloader import service as service_module
        from watchlist_downloader import state_store as state_store_module
        from watchlist_downloader import transmission_client as transmission_module

        self._config = config
        self._service = service_module
        self._state_store = state_store_module
        self._transmission = transmission_module

    def list_available(self) -> list[Any]:
        """Return available, not-yet-downloaded movies with torrents."""
        prepared = self._service.prepare(
            self._config.letterboxd_username,
            self._config.tmdb_api_key,
        )
        state = self._state_store.StateStore().load()
        return [
            movie
            for movie in prepared.movies
            if movie.available
            and movie.torrents
            and movie.movie.imdb_id
            and movie.movie.imdb_id not in state.downloaded_imdb_ids
        ]

    def download(self, movies: list[Any]) -> list[tuple[Any, bool]]:
        """Submit movies to Transmission and return per-movie results."""
        return self._service.download(
            movies,
            transmission_url=self._config.transmission_url,
        )

    def list_status(self) -> list[Any]:
        """Return the progress of every torrent currently in Transmission."""
        client = self._transmission.TransmissionClient(
            url=self._config.transmission_url
        )
        return client.list_torrents()
