# Harden the product-search app

`/app/app.py` is a minimal product-search web app (stdlib only). It serves
`/search?q=<query>` and returns products whose name contains the query.

The app has a **security vulnerability**: a malicious query can break out of
the intended search and execute arbitrary SQL against the database — for
example, reading every row, or even dropping the `products` table.

Your job:

1. Find the vulnerability.
2. Fix it so queries are always treated as *data*, never as SQL.
3. Verify with the test suite:

```bash
cd /app
python -m pytest tests/ -v
```

The tests check that normal searches still work and that malicious input
cannot break out of the query or destroy the database. Do not modify the
tests, the database schema, or the `/search` endpoint behavior.

## Notes

- The vulnerability is in `search_products()`.
- The fix is a few lines; do not rewrite the app.
