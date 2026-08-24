# Fix the broken calculator package

The Python package in `/app/calculator` is broken. It was working recently, but
several bugs were introduced: the package does not even import cleanly, and
when you get it importing, some functions return wrong results.

Your job:

1. Make the package importable (`python -c "import calculator"` must succeed).
2. Make every function behave correctly.
3. Verify by running the test suite:

```bash
cd /app
python -m pytest tests/ -v
```

The test suite lives in `/app/tests/` and is the source of truth — do not
modify it. Fix the package code only. When all tests pass, you are done.

## Notes

- There are multiple independent bugs. Fixing one and stopping will not pass.
- Read the code before editing; some bugs are subtle.
- You may install packages if needed, but the standard library should suffice.
