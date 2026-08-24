# Fix the sales summary script

`/app/process.py` reads a sales CSV (`product,quantity,price` per line, with
a header row) and writes a per-product total summary to an output file:

```bash
python3 process.py <input.csv> <output.txt>
```

Example input:

```
product,quantity,price
apple,2,1.50
banana,3,0.75
apple,1,2.00
cherry,5,0.10
```

Expected output (sorted by product name, two decimals):

```
apple: 5.00
banana: 2.25
cherry: 0.50
```

The script has a **subtle bug**: it silently drops the last record of the
input file. Your job is to find and fix it, then verify with the test suite:

```bash
cd /app
python -m pytest tests/ -v
```

Do not modify the tests or the script's interface. When all tests pass, you
are done.

## Notes

- The bug is a single line. Read the file-handling logic carefully.
- The output must be sorted by product name and formatted to two decimals.
