# Feature: watchlist-telegram-bot

## Objective

Telegram bot that reads the Letterboxd watchlist, shows the movies available
on YTS as a paginated inline keyboard, and queues the selected ones into
Transmission. The existing `watchlist-downloader` TUI keeps working unchanged.

## Problem

`watchlist-downloader` has clean domain modules but its orchestration
(`scrape -> resolve -> search -> download`) is mixed with console `print()`
calls and TUI startup in `app.py`, and the download step lives inside
`tui.py`. A long-running bot cannot reuse that block without duplicating the
business rules (2160p filter, 7-day YTS cache TTL, failed lookups never cached).

## Why

Duplicating orchestration in the bot would let the TUI and the bot drift apart
silently. Extracting a headless service keeps a single source of truth.

## Scope

In scope:
- Extract `watchlist_downloader/service.py` with `prepare()` and `download()`.
- Make `app.py`, `tui.py`, and the bot thin adapters over that service.
- New bot: long polling, `/start`, `/lista`, paginated inline keyboard,
  toggle selection, explicit download confirmation, chat_id whitelist.
- Tests for the service and the bot's pure logic.
- systemd user unit and secrets template.

Out of scope:
- TUI redesign or visual changes.
- Additional torrent providers (contract left for later, per NOTES.md).
- Download progress notifications from Transmission.

## Constraints

- Telegram client uses Python stdlib only (`urllib`, `json`), consistent with
  `telegram-notifier`. No new runtime dependency.
- Whitelist `chat_id`; every other update is ignored.
- Bot token lives in `~/.config/watchlist-telegram-bot/secrets.env` (mode 600),
  never in the repository.
- `watchlist_downloader` is not pip-installed; the bot resolves it via an
  explicit `sys.path` entry pointing at the sibling checkout.
- Only movies with `available == True`, non-empty torrents, and an `imdb_id`
  absent from `downloaded_imdb_ids` are shown.

## Decisions

- D1: Option B (extract `service.py`) instead of re-orchestrating in the bot.
- D2: stdlib Telegram client instead of `python-telegram-bot`.
- D3: Transmission runs as `transmission-gtk -m` via XDG autostart; RPC stays
  on `localhost:9091` with the existing localhost whitelist.

## Tasks

- [x] T1 Extract `watchlist_downloader/service.py` with `prepare()` and
      `download()`; keep behavior identical.
- [x] T2 Rewire `app.py` and `tui.py` to call the service; TUI unchanged.
- [x] T3 Add `tests/test_service.py` covering cache reuse, 2160p filtering,
      failed-lookup non-caching, YTS outage, and download state updates.
- [x] T4 Scaffold bot project: git repo, `.gitignore`, secrets template,
      config loader, `sys.path` bootstrap for the sibling package.
- [x] T5 Implement `telegram_api.py`: `getUpdates`, `sendMessage`,
      `editMessageText`, `answerCallbackQuery`, `deleteMessage`.
- [x] T6 Implement `session.py`: per-chat movie list, selection set, page.
- [x] T7 Implement `keyboard.py`: paginated inline keyboard with toggle,
      navigation, and download rows.
- [x] T8 Implement `handlers.py`: `/start`, `/lista`, toggle, pagination,
      download confirmation.
- [x] T9 Implement `bot.py`: long-polling loop, whitelist, dispatcher,
      graceful shutdown.
- [x] T10 Tests for session, keyboard layout, and handler behavior with a fake
      Telegram client.
- [x] T11 systemd user unit and README runbook.
- [x] T12 End-to-end check with Transmission running (requires the daemon or
      `transmission-gtk -m`).

## Acceptance criteria

- `python3 -m pytest -q` is green in both repositories.
- `/lista` shows only available, not-yet-downloaded movies, 8 per page.
- Toggling, paging, and confirming queue magnets and update `state.json`.
- Updates from any `chat_id` other than the configured one are ignored.
- The TUI still opens, navigates, and downloads as before.

## Verification

- `cd ../watchlist-downloader && python3 -m pytest -q` (baseline: 90 passed).
- `cd . && python3 -m pytest -q`.
- Manual: start bot, send `/lista`, toggle, download, inspect Transmission.

## Route and delivery

- Route: delegated writer for the multi-file refactor and bot implementation.
- Delivery: one feature branch per repository, one work-unit commit per task.
  No remote is configured yet, so PR chaining is deferred.

Forecast: ~1400 authored lines across both repositories, above the 400-line
delivery budget. Since neither repository has a remote or PR target, commits
stay as reviewable work units on a feature branch instead of chained PRs.

## Progress

- T1-T3 complete in `watchlist-downloader` on `feat/headless-service`, commit
  `5036389`. `python3 -m pytest -q` -> 99 passed (90 baseline + 9 new).
- T4-T11 complete in this repository on `feat/telegram-bot`, commit `1ee150b`.
  `python3 -m pytest -q` -> 21 passed. `py_compile` and import checks pass.
- RDD review for the refactor candidate was offered and declined by the user
  (`declined_this_candidate`); the candidate was not reviewed.
- `~/.config/watchlist-telegram-bot/secrets.env` created with mode 600 and the
  existing token, chat id and TMDB key. Values are not recorded here.
- T12 complete. `watchlist-telegram-bot.service` is active and polling.
  `pipeline.list_available()` returned 20 available movies in 2.5s against the
  real Letterboxd/TMDB/YTS stack. Transmission RPC answered on `localhost:9091`
  (`HTTP 409`, meaning the CSRF challenge was served). The user completed two
  real selections from Telegram and both queued successfully.
- `notify.py` from `telegram-notifier` remains compatible: its cron path only
  sends `sendMessage`/`sendPoll`. `getUpdates` is limited to the manual
  `--chat-id` diagnostic flag, which must not run while this bot polls.
- Outstanding, non-technical: rename the bot in BotFather. A rename keeps the
  token, so no secrets change or service restart is required.
