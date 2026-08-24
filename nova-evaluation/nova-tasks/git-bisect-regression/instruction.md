# Find and fix the regression

The git repository at `/app/repo` contains a small Python module, `prices.py`,
with a function `total_price(unit_price, quantity=1, tax_rate=0.0)`.

The function is currently **wrong**: it does not apply the tax rate correctly.
A regression was introduced somewhere in the repository's history — the
function worked in earlier commits.

Your job:

1. Investigate the repository with git (`git log`, `git show`, `git blame`,
   `git bisect`, …) to find the commit that introduced the regression.
2. Fix `total_price` so it behaves correctly:
   - `total_price(10, 1, 0.1)` → `11.0` (10% tax on 10)
   - `total_price(10, 3, 0.0)` → `30.0`
   - `total_price(5, 2, 0.2)` → `12.0`
3. Verify with the test suite:

```bash
cd /app/repo
python -m pytest /app/tests/ -v
```

Do not modify the tests. When all tests pass, you are done.

## Notes

- The bug is in the current `HEAD` of the repo — you must fix the working tree.
- Use git to understand *what changed* and *when*; it will tell you exactly
  which line is wrong.
