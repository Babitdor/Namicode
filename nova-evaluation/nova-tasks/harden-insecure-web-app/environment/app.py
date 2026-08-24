"""A minimal product-search web app (stdlib only).

Serves GET /search?q=<query> and returns products whose name contains the
query, as JSON.
"""

import json
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

DB_PATH = "/app/products.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS products "
        "(id INTEGER PRIMARY KEY, name TEXT, price REAL)"
    )
    conn.executemany(
        "INSERT OR IGNORE INTO products (id, name, price) VALUES (?, ?, ?)",
        [(1, "widget", 9.99), (2, "gadget", 19.99), (3, "gizmo", 4.50)],
    )
    conn.commit()
    conn.close()


def search_products(query):
    """Return products whose name contains the query string."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        f"SELECT name, price FROM products WHERE name LIKE '%{query}%'"
    ).fetchall()
    conn.close()
    return rows


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/search"):
            q = parse_qs(urlparse(self.path).query).get("q", [""])[0]
            results = search_products(q)
            body = json.dumps(
                [{"name": n, "price": p} for n, p in results]
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    init_db()
    HTTPServer(("0.0.0.0", 5000), Handler).serve_forever()
