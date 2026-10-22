"""Long-polling entry point for the watchlist Telegram bot."""

from __future__ import annotations

import logging
import signal
import sys
import threading

from config import ConfigError, load_config
from handlers import BotHandlers
from pipeline import WatchlistPipeline
from session import SessionStore
from telegram_api import TelegramAPIError, TelegramClient

logger = logging.getLogger(__name__)

ALLOWED_UPDATES = ["message", "callback_query"]
INITIAL_BACKOFF_SECONDS = 1
MAX_BACKOFF_SECONDS = 30


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        config = load_config()
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    api = TelegramClient(config.bot_token)
    try:
        pipeline = WatchlistPipeline(config)
    except ImportError as exc:
        print(
            "Could not import watchlist_downloader from "
            f"{config.watchlist_downloader_path}. Set "
            "WATCHLIST_DOWNLOADER_PATH to the sibling checkout.\n"
            f"{exc}",
            file=sys.stderr,
        )
        return 1
    sessions = SessionStore()
    handlers = BotHandlers(
        api,
        pipeline,
        sessions,
        config.chat_id,
        page_size=config.page_size,
    )

    stop_event = threading.Event()

    def request_stop(signum: int, _frame: object) -> None:
        logger.info("Received signal %s, stopping after this poll.", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    offset: int | None = None
    try:
        backlog = api.get_updates(timeout=0, offset=-1)
    except TelegramAPIError as exc:
        logger.warning("Could not drain the update backlog: %s", exc)
        backlog = []
    backlog_ids = [
        update.get("update_id")
        for update in backlog
        if isinstance(update.get("update_id"), int)
    ]
    if backlog_ids:
        offset = max(backlog_ids) + 1
        logger.info("Discarded %d stale updates.", len(backlog))

    backoff = INITIAL_BACKOFF_SECONDS
    logger.info("Polling for updates.")
    while not stop_event.is_set():
        try:
            updates = api.get_updates(
                offset=offset,
                timeout=config.poll_timeout,
                allowed_updates=ALLOWED_UPDATES,
            )
        except TelegramAPIError as exc:
            logger.error("Polling failed: %s", exc)
            if stop_event.wait(backoff):
                break
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            continue

        backoff = INITIAL_BACKOFF_SECONDS
        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                offset = update_id + 1
            handlers.handle_update(update)
            if stop_event.is_set():
                break

    logger.info("Stopping.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
