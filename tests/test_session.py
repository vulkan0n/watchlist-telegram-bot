"""Tests for in-memory chat sessions."""

from __future__ import annotations

from session import ChatSession, SessionStore, page_count


def test_session_store_put_get_drop_and_clear() -> None:
    store = SessionStore()
    session = ChatSession(movies=[object()])

    store.put(42, session)
    assert store.get(42) is session

    store.drop(42)
    assert store.get(42) is None

    store.put(1, ChatSession())
    store.put(2, ChatSession())
    store.clear()
    assert store.get(1) is None
    assert store.get(2) is None


def test_chat_session_defaults_are_independent() -> None:
    first = ChatSession()
    second = ChatSession()

    first.selected.add(3)
    assert second.selected == set()
    assert first.page == 0
    assert first.message_id is None


def test_page_count_is_at_least_one() -> None:
    assert page_count(ChatSession(), 8) == 1
    assert page_count(ChatSession(movies=list(range(8))), 8) == 1
    assert page_count(ChatSession(movies=list(range(9))), 8) == 2
    assert page_count(ChatSession(movies=list(range(10))), 3) == 4
    assert page_count(ChatSession(movies=list(range(10))), 0) == 1
