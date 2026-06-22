# Design — MatrixRain frame-cost reduction (pixel-identical)

**Date:** 2026-06-22
**Status:** Approved (design); pending implementation plan
**Area:** TUI / home-screen banner animation
**Approach:** 2 — per-frame hotspot removal, no visible change

## 1. Goal & scope

Make each `MatrixRain._tick` frame cheaper so the home-screen rain stays smooth
**and** stops taxing the main asyncio loop / GIL (so background threads — `/ralph`,
voice — run smoothly), with **no perceptible visual change**: same 25 fps, same
colors, same random-katakana look, same logo compositing.

`MatrixRain` (`novacode_cli/tui/app.py`) is the home banner: the NOVA ASCII logo
composited over falling rain, animated by `set_interval(0.04, self._tick)` on the
main event loop. It scrolls off once the user sends messages, after which `_tick`
early-returns via the existing viewport guard.

All edits are internal to the `MatrixRain` class plus two module-level imports.
The public surface (`__init__`, `reflow`, `pause`, `resume`, `on_mount`) and the
existing `_tick` guards (TTS-pause, viewport-skip) are unchanged.

Out of scope (explicitly not done): fps changes; adaptive/load-based throttling;
pausing the timer when off-screen (Approach 3); any char-churn or other visual
change; moving work to a thread (the GIL makes that pointless for pure-Python
string work); anything outside `MatrixRain`.

## 2. Background — where the per-frame cost goes (verified)

In `_tick` today, every frame (25×/sec while visible):
- `_rain_palette()` parses the theme color and calls `.darken().hex` four times;
  `_art_style()` parses the theme color again.
- `import sys` and `from rich.text import Text` run inside `_tick`.
- Buffers are cleared with a nested `rows × cols` Python loop.
- `random.choice(self._chars)` is called for every drawn cell (hundreds/frame).
- A `segments` list is built (run-length coalesced) then unpacked into
  `Text.assemble(*segments)`.
- `self.update(text)` recomposites the widget.

The tick runs on the main loop and holds the GIL during the build, so cheaper
frames directly improve fairness for background threads.

## 3. The five optimizations

### (a) Cache palette + art-style, keyed on the theme color

Add `_ensure_theme_cache()`: read the active theme's primary color string (a
cheap attribute read — the same source `_theme_base_color()` already uses) as a
cache key. Only when it differs from the stored key recompute the
`(head, near, mid, tail)` palette tuple and the bold art-style string, storing
both on `self`. `_tick` reads `self._palette` and `self._art_style_str`. A live
`/theme` switch changes the key → the cache recomputes → the rain recolors, as
today. The existing `_rain_palette()` / `_art_style()` helpers stay (used by the
cache builder and any other callers); the change is that `_tick` no longer calls
them every frame.

### (b) Hoist per-frame imports

Move `import sys` and `from rich.text import Text` to module top (next to the
other `app.py` imports). `_tick` references them directly.

### (c) Slice-assignment buffer clear

In `_init_columns`, prebuild `self._blank_line = [" "] * self._col_count` and
`self._blank_style = [""] * self._col_count`. In `_tick`, clear each row with:

```python
for y in range(rows):
    lines[y][:] = self._blank_line
    styles[y][:] = self._blank_style
```

Slice assignment copies the blank row into the existing buffer list at C level
(no per-frame allocation — preserves the current no-GC-churn design), replacing
the nested per-cell Python loop.

### (d) Cheaper random chars, same random look

Build `self._char_pool` once in `_init_columns` — a large list (512) of random
katakana drawn from `self._chars`. At the **start of each frame** pick a single
random offset `idx = random.randrange(len(self._char_pool))`; per drawn cell take
`ch = self._char_pool[idx]` then advance `idx` (wrapping at the end). This
replaces the per-cell `random.choice` (a `random()` call + index each) with one
RNG call per frame plus a counter increment per cell. The per-frame random
offset prevents any fixed alignment pattern, so the result still reads as random
flickering katakana — visually indistinguishable from per-cell random.

### (e) Leaner Text assembly

Keep the existing run-length coalescing, but `append` each coalesced run directly
into a single `Text`:

```python
text = Text()
for y in range(rows):
    # ... run-length walk over the row ...
    text.append(segment, style or None)
    if y < rows - 1:
        text.append("\n")
self.update(text)
```

This removes the intermediate `segments` list and the large
`Text.assemble(*segments)` positional unpack. One `self.update` per frame, as
before.

## 4. New instance state

Added on `self`: `_palette`, `_art_style_str`, `_palette_key` (cache);
`_blank_line`, `_blank_style` (buffer clear); `_char_pool` (RNG). Initialized in
`__init__` (cache fields to a "not yet computed" sentinel) and/or `_init_columns`
(width-dependent buffers + pool), matching where `_frame_lines`/`_frame_styles`
are built today so a `reflow()` rebuilds them too.

## 5. Look-equivalence (how identical is guaranteed)

- **Colors:** identical hex values — caching only avoids recomputing the same
  strings; the derivation (`base.darken(...)`) is unchanged.
- **Characters:** still uniformly-random katakana per cell (random pool + a fresh
  per-frame offset); a human cannot distinguish it from per-cell `random.choice`.
- **Geometry / motion / logo:** untouched — same column math, speeds, trail
  lengths, composite, and fps.

## 6. Error handling

`_ensure_theme_cache()` mirrors the existing `_theme_base_color()` fallbacks (any
exception reading the theme → fall back to the matrix-green default and a stable
key), so a theme read failure never breaks a frame. The pool/buffer indexing is
bounds-safe by construction (modulo / slice). No new failure modes.

## 7. Testing

Animation code — assert structure and equivalence, not pixels:

- **Theme cache:** `_ensure_theme_cache()` recomputes only on key change — patch
  the theme color, call twice, assert the palette is the *same object* on the
  second call and a *new* object after the color changes.
- **Buffer reset:** after a `_tick`, each buffer row has length `col_count` and
  no stale cell from a prior frame leaks where no column draws (clear a known
  cell, tick with a column that doesn't cover it, assert it's blank).
- **Char pool:** every produced char is in `self._chars`; pool index wraps
  correctly at the boundary (advance past the end, assert it returns to 0).
- **Frame output:** `_tick` yields a `Text` whose plain content is `row_count`
  newline-separated lines, each `col_count` wide, with logo cells where the art
  is non-space. Drive it with a minimal fake `app`/`parent` so the viewport guard
  passes (reuse the existing `is_testing` path).
- **Smoke:** a few hundred `_tick` calls run without exception and keep the
  content well-formed (guards pool/buffer index bugs).
- `tests/test_tui_app.py` still passes (no public-API change).

## 8. Files touched

- Modify: `novacode_cli/tui/app.py` — the `MatrixRain` class (`__init__`,
  `_init_columns`, `_tick`, new `_ensure_theme_cache`) + hoist two imports.
- New: `tests/test_matrix_rain.py` — the structural/equivalence tests above.
