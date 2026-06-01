"""Tests for the notification system."""

import asyncio

from novacode_cli.commands.notifications_handler import handle_notifications_command
from novacode_cli.states.Session import Notification, SessionState


def test_add_notification():
    s = SessionState()
    nid = s.add_notification("info", "Test title", "Test message", "test")
    assert len(s.notifications) == 1
    assert s.unread_notification_count() == 1
    assert s.notifications[0].id == nid
    assert s.notifications[0].level == "info"
    assert s.notifications[0].title == "Test title"
    assert isinstance(s.notifications[0], Notification)


def test_dismiss_notification():
    s = SessionState()
    nid = s.add_notification("warning", "Test", "Test", "test")
    assert s.dismiss_notification(nid) is True
    assert s.notifications[0].dismissed is True
    assert s.unread_notification_count() == 0


def test_dismiss_nonexistent():
    s = SessionState()
    assert s.dismiss_notification("nope") is False


def test_notification_queue_maxlen():
    s = SessionState()
    for i in range(110):
        s.add_notification("info", str(i), "", "test")
    assert len(s.notifications) == 100  # bounded
    # newest is appended left; oldest retained is "10"
    assert s.notifications[0].title == "109"
    assert s.notifications[-1].title == "10"


def test_clear_notifications():
    s = SessionState()
    for i in range(10):
        s.add_notification("info", str(i), "", "test")
    assert s.clear_notifications() == 10
    assert len(s.notifications) == 0
    assert s.unread_notification_count() == 0


def test_unread_excludes_dismissed():
    s = SessionState()
    a = s.add_notification("info", "a", "", "test")
    s.add_notification("error", "b", "", "test")
    assert s.unread_notification_count() == 2
    s.dismiss_notification(a)
    assert s.unread_notification_count() == 1


def test_handler_list_dismiss_clear():
    s = SessionState()
    nid = s.add_notification("error", "Boom", "details", "tests")
    # list (default)
    assert asyncio.run(handle_notifications_command(s, None)) is True
    # dismiss
    assert asyncio.run(handle_notifications_command(s, f"dismiss {nid}")) is True
    assert s.notifications[0].dismissed is True
    # clear
    assert asyncio.run(handle_notifications_command(s, "clear")) is True
    assert len(s.notifications) == 0
