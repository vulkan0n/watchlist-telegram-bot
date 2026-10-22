# Watchlist Telegram Bot

Telegram front end for the [watchlist-downloader](https://github.com/vulkan0n/watchlist-downloader)
pipeline. It reads a Letterboxd watchlist, shows the movies that are available
on YTS as a paginated inline keyboard, and queues the selected magnets into
Transmission.

Polling is outgoing long polling only. The bot never opens a port and never
runs arbitrary commands: the only actions are list, select, and download.

## How it works

```
Telegram /lista
  -> watchlist_downloader.service.prepare()   (scrape + TMDB + YTS, cached)
  -> inline keyboard, 8 movies per page
  -> user toggles movies and presses "Descargar"
  -> watchlist_downloader.service.download()  (Transmission + state)
```

The bot is a thin adapter: all business rules (2160p filter, cache TTL, what is
"available") live in the sibling package, so the TUI and the bot stay
consistent.

## Requirements

- Linux with Python 3.10 or newer. It runs as a user service, not as root.
- A Telegram bot token and the numeric `chat_id` allowed to use it.
- A TMDB API v3 key: <https://www.themoviedb.org/settings/api>.
- A public Letterboxd watchlist.
- A running Transmission RPC endpoint (default
  `http://localhost:9091/transmission/rpc`).
- The sibling `watchlist-downloader` checkout. It is not published on PyPI; the
  bot adds it to `sys.path` at startup and needs its runtime dependencies
  (`requests`, `beautifulsoup4`, `transmission-rpc`).

The bot itself uses only the Python standard library.

## Setup

Clone both repositories side by side, because the default path for the sibling
package is `../watchlist-downloader`:

```bash
git clone https://github.com/vulkan0n/watchlist-downloader.git
git clone https://github.com/vulkan0n/watchlist-telegram-bot.git
cd watchlist-telegram-bot
```

Install the sibling package and the test runner in a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ../watchlist-downloader pytest
```

## Secrets

Keep credentials outside the repository:

```bash
mkdir -p ~/.config/watchlist-telegram-bot
cp secrets.env.example ~/.config/watchlist-telegram-bot/secrets.env
chmod 600 ~/.config/watchlist-telegram-bot/secrets.env
$EDITOR ~/.config/watchlist-telegram-bot/secrets.env
```

Required variables:

| Variable | Meaning |
|----------|---------|
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather. |
| `TELEGRAM_CHAT_ID` | Numeric chat id allowed to use the bot. |
| `TMDB_API_KEY` | TMDB API v3 key. |
| `LETTERBOXD_USERNAME` | Letterboxd username whose watchlist is read. |

Optional variables:

| Variable | Default |
|----------|---------|
| `TRANSMISSION_URL` | `http://localhost:9091/transmission/rpc` |
| `WATCHLIST_DOWNLOADER_PATH` | `../watchlist-downloader` from this repo |

Values from the real process environment override the secrets file.

To find your numeric `chat_id`, send a message to the bot and run
`../telegram-notifier/notify.py --chat-id`, or read it from
`getUpdates` with any Telegram API client.

## Run

```bash
python3 bot.py
```

Available commands:

- `/start` or `/help` — show usage.
- `/lista` (aliases `/watchlist` and `/pelis`) — fetch and show available
  movies, 8 per page.
- Tap a movie to toggle `☐` / `☑`, use `◀` and `▶` to page, then press
  `Descargar` to confirm or `Cancelar` to discard the selection.

The list excludes movies that are already downloaded according to
`~/.config/watchlist-downloader/state.json`.

## Tests

```bash
python3 -m pytest -q
```

The test suite does not require the sibling package and makes no network calls.

## systemd user service

The unit in `systemd/` assumes the repository was cloned to
`~/watchlist-telegram-bot` and runs the system Python. Adjust
`WorkingDirectory` and `ExecStart` if your layout differs. If you created a
virtual environment, point `ExecStart` at
`%h/watchlist-telegram-bot/.venv/bin/python`.

```bash
mkdir -p ~/.config/systemd/user
cp systemd/watchlist-telegram-bot.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now watchlist-telegram-bot.service
```

Follow the logs:

```bash
journalctl --user -u watchlist-telegram-bot -f
```

Only one process may call `getUpdates` for a bot token. Do not run a second
copy of this bot or another poller with the same token at the same time
(`notify.py --chat-id` from `telegram-notifier` also calls `getUpdates`).

## Architecture

| Path | Responsibility |
|---|---|
| `bot.py` | Long-polling loop, backlog drain, backoff, signal shutdown. |
| `handlers.py` | Commands and callback dispatch: list, toggle, page, download. |
| `keyboard.py` | Paginated inline keyboard layout and callback-data limits. |
| `session.py` | In-memory per-chat session: movies, selection, page. |
| `telegram_api.py` | Stdlib Bot API client (`getUpdates`, `sendMessage`, edits, callbacks). |
| `config.py` | Secrets/env loading and validation. |
| `pipeline.py` | Adapter over `watchlist_downloader.service`; lazy import. |
| `tests/` | Fakes only: no Telegram, no Transmission, no network. |

## Security notes

- The bot whitelists a single `chat_id`. Messages and callback queries from
  every other chat are ignored.
- Actions are fixed: list, toggle, page, download, cancel. There is no shell
  execution and no pass-through of user text to system commands.
- Downloads require an explicit `Descargar` confirmation.
- The token lives in `~/.config/watchlist-telegram-bot/secrets.env` with mode
  `600`, never in the repository.
- User-facing messages never include the token, the chat id, magnet links, or
  filesystem paths.
- `secrets.env` is git-ignored. Only `secrets.env.example` belongs in the repo.

## Sibling package path

`watchlist_downloader` is resolved at startup from the configured path. The
default is the sibling checkout `../watchlist-downloader`; set
`WATCHLIST_DOWNLOADER_PATH` to point somewhere else. The bot imports
`watchlist_downloader.service` and `watchlist_downloader.state_store` lazily, so
its own modules can be imported and tested without the sibling package.

## License

MIT. See [LICENSE](LICENSE).
