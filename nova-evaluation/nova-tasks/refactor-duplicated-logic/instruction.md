# De-duplicate the shop package

The `shop` package in `/app/shop` has a maintainability problem: the exact same
validation logic (SKU format check and price check) is copy-pasted into two
modules, `orders.py` and `inventory.py`.

Your job:

1. Create a shared module `/app/shop/validation.py` exposing two functions:
   - `validate_sku(sku)` — raises `ValueError` on a bad SKU, returns it otherwise
   - `validate_price(price)` — raises `ValueError` on a bad price, returns it otherwise
2. Update `orders.py` and `inventory.py` to import and use these shared
   functions instead of their private copies.
3. Remove the duplicated private helpers from both modules.
4. Do **not** change any public behavior — existing callers must keep working.

Verify with the test suite:

```bash
cd /app
python -m pytest tests/ -v
```

The tests check two things: that behavior is unchanged, and that the
duplicated helpers are actually gone from `orders.py` and `inventory.py`.
Do not modify the tests.

## Notes

- The validation rules are identical in both modules — extract them verbatim.
- Keep the public function names and signatures (`create_order`, `restock`)
  exactly as they are.
