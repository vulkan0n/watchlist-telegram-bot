"""Configuration loading for the watchlist Telegram bot."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "watchlist-telegram-bot"
DEFAULT_SECRETS_PATH = DEFAULT_CONFIG_DIR / "secrets.env"
REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_DOWNLOADER_PATH = (REPO_ROOT.parent / "watchlist-downloader").resolve()

REQUIRED_VARIABLES = (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TMDB_API_KEY",
    "LETTERBOXD_USERNAME",
)


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


def _strip_optional_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_secrets(path: Path | None = None) -> dict[str, str]:
    """Parse a simple ``KEY=VALUE`` secrets file.

    Blank lines and lines starting with ``#`` are ignored. Values may be
    wrapped in single or double quotes. A missing file yields an empty
    mapping so callers can fall back to the real process environment.
    """
    secrets_path = path or DEFAULT_SECRETS_PATH
    if not secrets_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in secrets_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, raw_value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        values[key] = _strip_optional_quotes(raw_value.strip())
    return values


@dataclass(frozen=True)
class Config:
    """Runtime configuration assembled from secrets and environment."""

    bot_token: str
    chat_id: int
    tmdb_api_key: str
    letterboxd_username: str
    transmission_url: str = "http://localhost:9091/transmission/rpc"
    watchlist_downloader_path: Path = DEFAULT_DOWNLOADER_PATH
    poll_timeout: int = 50
    page_size: int = 8


def load_config(
    env: Mapping[str, str] | None = None,
    secrets_path: Path | None = None,
) -> Config:
    """Merge secrets-file defaults with the real environment.

    Values from ``env`` (or ``os.environ`` when omitted) always win over
    values found in the secrets file.
    """
    merged = load_secrets(secrets_path)
    process_env = os.environ if env is None else env
    merged.update(process_env)

    missing = [name for name in REQUIRED_VARIABLES if not merged.get(name, "").strip()]
    if missing:
        raise ConfigError(
            "Missing required configuration: " + ", ".join(missing)
        )

    raw_chat_id = merged["TELEGRAM_CHAT_ID"].strip()
    try:
        chat_id = int(raw_chat_id)
    except ValueError as exc:
        raise ConfigError("TELEGRAM_CHAT_ID must be an integer") from exc

    downloader_path = Path(
        merged.get("WATCHLIST_DOWNLOADER_PATH", str(DEFAULT_DOWNLOADER_PATH))
    ).expanduser().resolve()

    return Config(
        bot_token=merged["TELEGRAM_BOT_TOKEN"].strip(),
        chat_id=chat_id,
        tmdb_api_key=merged["TMDB_API_KEY"].strip(),
        letterboxd_username=merged["LETTERBOXD_USERNAME"].strip(),
        transmission_url=merged.get(
            "TRANSMISSION_URL", "http://localhost:9091/transmission/rpc"
        ).strip()
        or "http://localhost:9091/transmission/rpc",
        watchlist_downloader_path=downloader_path,
    )
