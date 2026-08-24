"""Test suite for the product-search app. Do not modify."""

import sqlite3
import sys

sys.path.insert(0, "/app")

from app import DB_PATH, init_db, search_products


def setup_module():
    init_db()


def test_normal_search():
    assert search_products("wid") == [("widget", 9.99)]


def test_empty_query_returns_all():
    assert len(search_products("")) == 3


def test_injection_does_not_break_out():
    # A tautology injection must not return every row.
    assert search_products("' OR 1=1 --") == []


def test_injection_cannot_drop_table():
    # A stacked-query injection must not be able to destroy the database.
    search_products("'; DROP TABLE products; --")
    conn = sqlite3.connect(DB_PATH)
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]
    conn.close()
    assert "products" in tables
