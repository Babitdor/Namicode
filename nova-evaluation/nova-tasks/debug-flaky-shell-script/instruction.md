# Fix the flaky report script

`/app/report.sh` is a small bash script that sorts a data file and writes a
line-count summary to an output file:

```bash
./report.sh <data-file> <output-file>
```

It works for simple cases, but it is **flaky and unreliable**:

- It breaks when the data file or output file path contains spaces.
- It can produce wrong results when two instances run at the same time.
- It reports success even when the underlying command fails.

Your job: fix the script so it is robust. Verify with the test suite:

```bash
cd /app
python -m pytest tests/ -v
```

The tests exercise exactly the failure modes above (paths with spaces,
concurrent runs, missing input file). Do not modify the tests or the script's
interface — `./report.sh <data-file> <output-file>` must keep working.

## Notes

- Read the script carefully; each failure mode is a distinct bug.
- The output file must contain the line count of the *sorted* data.
- A missing data file must cause a non-zero exit code.
