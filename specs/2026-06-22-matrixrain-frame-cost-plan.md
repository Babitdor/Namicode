# MatrixRain Frame-Cost Reduction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make each `MatrixRain._tick` frame cheaper (so the home-banner rain stays smooth and stops taxing the main loop / GIL) with no perceptible visual change.

**Architecture:** Extract the frame build into a testable `_build_frame() -> Text` helper, then apply pixel-identical per-frame optimizations: cache the theme palette/art-style, slice-assignment buffer clear, a precomputed random-char pool, leaner `Text` assembly, and hoisted imports. All edits live inside the `MatrixRain` class in `novacode_cli/tui/app.py`.

**Tech Stack:** Python 3.12, `uv`, `pytest`, `ruff` (select=ALL, line 100, Google docstrings), Textual + Rich. Reference: `specs/2026-06-22-matrixrain-frame-cost-design.md`.

---

## File structure

**Modified**
- `novacode_cli/tui/app.py` — the `MatrixRain` class only (`__init__`, `_init_columns`, `_tick`, new `_build_frame` + `_ensure_theme_cache` + `_theme_key`), and (Task 3) two import tidy-ups.

**Tests**
- `tests/test_matrix_rain.py` (new) — characterization (frame well-formed, valid chars) + targeted optimization tests (palette cache, blank buffers, char pool).

**Verified facts (rely on these — confirmed live):**
- A bare `MatrixRain(art="NOVA", width=80)` + `mw._init_columns()` + the frame-build code runs WITHOUT a live Textual app: all `self.app` reads in the build are inside guarded helpers (`_theme_base_color` try/except → falls back to matrix green). The build produces `row_count` newline-separated lines, each `col_count` wide, chars ∈ KATAKANA ∪ logo.
- `self.update(...)` does NOT work bare (Textual's `Static.update` → `widget.app.console` raises `NoActiveAppError`). Therefore tests must call `_build_frame()` (which returns the `Text` and does NOT call `update`), never `_tick()`.
- `app.py` already imports `Text` at module top (`from rich.text import Text`), so `_tick`'s local `from rich.text import Text as RichText` is redundant.

**Conventions:** one test `uv run pytest <path>::<test> -q`; format/lint `uv run ruff format <files> && uv run ruff check <files>`. `app.py` has a large pre-existing lint baseline — only fix findings YOUR change introduces (compare with `git stash`).

---

## Task 1: Extract `_build_frame()` + characterization tests (safety net)

This is a behaviour-preserving refactor: move the frame-building body of `_tick` into `_build_frame()`. `_tick` keeps its guards (TTS pause, viewport skip) and calls `self.update(self._build_frame())`. The characterization tests pin the current observable output so the later optimization tasks can't regress it.

**Files:**
- Modify: `novacode_cli/tui/app.py` (`MatrixRain._tick`)
- Test: `tests/test_matrix_rain.py`

- [ ] **Step 1: Write the failing tests at `tests/test_matrix_rain.py`**

```python
"""Characterization + optimization tests for the MatrixRain widget."""

from __future__ import annotations

from novacode_cli.tui.app import MatrixRain

_ART = "NOVA"


def _rain(width: int = 80, art: str = _ART) -> MatrixRain:
    mw = MatrixRain(art=art, width=width)
    mw._init_columns()
    return mw


def test_build_frame_is_well_formed():
    mw = _rain()
    text = mw._build_frame()
    lines = text.plain.split("\n")
    assert len(lines) == mw._row_count
    assert all(len(ln) == mw._col_count for ln in lines)


def test_build_frame_chars_are_katakana_or_logo():
    mw = _rain()
    katakana = set(MatrixRain.KATAKANA)
    logo = set(_ART)
    for ch in mw._build_frame().plain:
        assert ch in (" ", "\n") or ch in katakana or ch in logo


def test_build_frame_runs_many_times_without_error():
    mw = _rain()
    for _ in range(200):
        mw._build_frame()  # exercises column reset / wrap paths
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_matrix_rain.py -q`
Expected: FAIL — `AttributeError: 'MatrixRain' object has no attribute '_build_frame'`.

- [ ] **Step 3: Extract `_build_frame` from `_tick`**

In `novacode_cli/tui/app.py`, `_tick` currently ends (after its TTS guard and viewport guard) with the frame build. Replace the body FROM the line `cols = self._col_count` THROUGH the final `self.update(RichText.assemble(*segments))` so that `_tick` ends with:

```python
        # (TTS guard and viewport guard stay exactly as they are above)
        self.update(self._build_frame())

    def _build_frame(self) -> Text:
        """Build one rain frame as a Rich ``Text`` (no side effects)."""
        cols = self._col_count
        rows = self._row_count
        lines = self._frame_lines
        styles = self._frame_styles

        # Clear buffers for the new frame.
        for y in range(rows):
            for x in range(cols):
                lines[y][x] = " "
                styles[y][x] = ""

        head_c, near_c, mid_c, tail_c = self._rain_palette()
        choice = random.choice
        chars = self._chars

        for col, d in enumerate(self._columns):
            d["pos"] += d["speed"]
            if d["pos"] > rows + d["trail"]:  # reset when fully off-screen
                d["pos"] = random.uniform(-rows, -3)
                d["speed"] = random.uniform(0.05, 0.14)
                d["trail"] = random.randint(5, 14)

            tail_start = max(0, int(d["pos"]) - d["trail"])
            head = min(rows - 1, int(d["pos"]))
            for y in range(tail_start, head + 1):
                dist = head - y
                lines[y][col] = choice(chars)
                if dist == 0:
                    styles[y][col] = head_c
                elif dist <= 2:
                    styles[y][col] = near_c
                elif dist <= 5:
                    styles[y][col] = mid_c
                else:
                    styles[y][col] = tail_c

        # Composite the logo on top.
        if self._art_lines:
            art_style = self._art_style()
            for ay, art_line in enumerate(self._art_lines):
                gy = self._art_top + ay
                if not 0 <= gy < rows:
                    continue
                row_l = lines[gy]
                row_s = styles[gy]
                left = self._art_left
                for ax, ch in enumerate(art_line):
                    if ch == " ":
                        continue
                    gx = left + ax
                    if 0 <= gx < cols:
                        row_l[gx] = ch
                        row_s[gx] = art_style

        from rich.text import Text as RichText

        segments: list[tuple[str, str | None]] = []
        for y in range(rows):
            line = lines[y]
            st = styles[y]
            x = 0
            while x < cols:
                s = st[x]
                j = x + 1
                while j < cols and st[j] == s:
                    j += 1
                segment = "".join(line[x:j]) if s else " " * (j - x)
                segments.append((segment, s or None))
                x = j
            if y < rows - 1:
                segments.append(("\n", None))

        return RichText.assemble(*segments)
```

This is a verbatim move of the existing build logic (only the trailing `self.update(...)` becomes `return ...`, and `_tick` now calls `self.update(self._build_frame())`). Do not change any logic in this task.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_matrix_rain.py -q`
Expected: PASS (3 passed). Then `uv run pytest tests/test_tui_app.py -q -k matrix` if any matrix tests exist (skip if none); the full TUI suite is heavy — run it in Task 4.

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format novacode_cli/tui/app.py tests/test_matrix_rain.py
uv run ruff check tests/test_matrix_rain.py
```
Fix any NEW lint findings in the test file (`app.py` baseline is large — only fix what you introduced). Commit:
```bash
git add novacode_cli/tui/app.py tests/test_matrix_rain.py
git commit -m "refactor(tui): extract MatrixRain._build_frame + characterization tests"
```
End the commit body with: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

---

## Task 2: Cache the theme palette + art-style

**Files:**
- Modify: `novacode_cli/tui/app.py` (`MatrixRain.__init__`, new `_theme_key` + `_ensure_theme_cache`, `_build_frame`)
- Test: `tests/test_matrix_rain.py` (append)

- [ ] **Step 1: Append the failing test**

```python
def test_palette_cache_reuses_until_theme_changes(monkeypatch):
    mw = _rain()
    keys = iter(["#abcdef", "#abcdef", "#123456"])
    monkeypatch.setattr(mw, "_theme_key", lambda: next(keys))
    mw._ensure_theme_cache()
    p1 = mw._palette
    mw._ensure_theme_cache()
    p2 = mw._palette  # same key -> cached (same object)
    mw._ensure_theme_cache()
    p3 = mw._palette  # key changed -> recomputed (new object)
    assert p1 is p2
    assert p3 is not p2
    assert mw._art_style_str  # populated alongside the palette
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_matrix_rain.py::test_palette_cache_reuses_until_theme_changes -q`
Expected: FAIL — `AttributeError: ... '_ensure_theme_cache'`.

- [ ] **Step 3a: Add cache fields in `__init__`**

In `MatrixRain.__init__`, after `self._timer: Any = None  # set_interval handle for pause/resume`, add:

```python
        # Theme-derived render values, recomputed only when the theme changes
        # (keyed by _theme_key) instead of every frame.
        self._palette: tuple[str, str, str, str] | None = None
        self._art_style_str: str = ""
        self._palette_key: str | None = None
```

- [ ] **Step 3b: Add `_theme_key` + `_ensure_theme_cache`**

Add these methods to `MatrixRain` (place next to `_rain_palette`):

```python
    def _theme_key(self) -> str:
        """The active theme's primary color string — the palette cache key."""
        raw = None
        try:
            raw = self.app.current_theme.primary
        except Exception:  # noqa: BLE001
            try:
                raw = self.app.theme_variables.get("primary")
            except Exception:  # noqa: BLE001
                raw = None
        return (raw or "#00ff88").strip()

    def _ensure_theme_cache(self) -> None:
        """Recompute the palette + art style only when the theme color changes."""
        key = self._theme_key()
        if key != self._palette_key:
            self._palette = self._rain_palette()
            self._art_style_str = self._art_style()
            self._palette_key = key
```

- [ ] **Step 3c: Use the cache in `_build_frame`**

In `_build_frame`, replace:
```python
        head_c, near_c, mid_c, tail_c = self._rain_palette()
```
with:
```python
        self._ensure_theme_cache()
        head_c, near_c, mid_c, tail_c = self._palette
```
and replace (in the logo-composite block):
```python
            art_style = self._art_style()
```
with:
```python
            art_style = self._art_style_str
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_matrix_rain.py -q`
Expected: PASS (4 passed — the 3 characterization tests still green, proving no visual change).

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format novacode_cli/tui/app.py tests/test_matrix_rain.py
uv run ruff check tests/test_matrix_rain.py
git add novacode_cli/tui/app.py tests/test_matrix_rain.py
git commit -m "perf(tui): cache MatrixRain palette/art-style by theme color"
```
End the commit body with the Co-Authored-By trailer.

---

## Task 3: Buffer slice-clear + char pool + leaner assembly + hoist imports

The inner-loop optimizations. All keep `_build_frame` output identical (guarded by Task 1's characterization tests).

**Files:**
- Modify: `novacode_cli/tui/app.py` (`MatrixRain._init_columns`, `_build_frame`, `_tick` import)
- Test: `tests/test_matrix_rain.py` (append)

- [ ] **Step 1: Append the failing tests**

```python
def test_blank_buffers_match_grid_width():
    mw = _rain()
    assert mw._blank_line == [" "] * mw._col_count
    assert mw._blank_style == [""] * mw._col_count


def test_char_pool_is_nonempty_valid_katakana():
    mw = _rain()
    katakana = set(MatrixRain.KATAKANA)
    assert mw._char_pool
    assert all(c in katakana for c in mw._char_pool)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_matrix_rain.py -k "blank_buffers or char_pool" -q`
Expected: FAIL — `AttributeError: ... '_blank_line'` / `'_char_pool'`.

- [ ] **Step 3a: Build blank rows + char pool in `_init_columns`**

In `MatrixRain._init_columns`, the tail currently is:
```python
        # Pre-allocate frame buffers (reused in _tick to avoid GC churn)
        self._frame_lines = [[" "] * self._col_count for _ in range(self._row_count)]
        self._frame_styles = [[""] * self._col_count for _ in range(self._row_count)]
```
Replace it with:
```python
        # Pre-allocate frame buffers (reused per frame to avoid GC churn).
        self._frame_lines = [[" "] * self._col_count for _ in range(self._row_count)]
        self._frame_styles = [[""] * self._col_count for _ in range(self._row_count)]
        # Prebuilt blank rows copied in (slice-assign) to clear buffers at C speed.
        self._blank_line = [" "] * self._col_count
        self._blank_style = [""] * self._col_count
        # Precomputed random-char pool: strided per frame from a random offset so
        # the look stays random without a random.choice() call per cell.
        self._char_pool = [random.choice(self._chars) for _ in range(512)]
```

- [ ] **Step 3b: Slice-clear + pool-stride + leaner assembly in `_build_frame`**

Replace the buffer-clear block:
```python
        # Clear buffers for the new frame.
        for y in range(rows):
            for x in range(cols):
                lines[y][x] = " "
                styles[y][x] = ""
```
with:
```python
        # Clear buffers for the new frame (C-level slice copy of prebuilt rows).
        blank_l = self._blank_line
        blank_s = self._blank_style
        for y in range(rows):
            lines[y][:] = blank_l
            styles[y][:] = blank_s
```

Replace the char-selection setup:
```python
        head_c, near_c, mid_c, tail_c = self._palette
        choice = random.choice
        chars = self._chars
```
with:
```python
        head_c, near_c, mid_c, tail_c = self._palette
        pool = self._char_pool
        pool_len = len(pool)
        idx = random.randrange(pool_len)  # one RNG call per frame
```
and inside the column loop replace:
```python
                lines[y][col] = choice(chars)
```
with:
```python
                lines[y][col] = pool[idx]
                idx += 1
                if idx == pool_len:
                    idx = 0
```

Replace the assembly block (the `from rich.text import Text as RichText` line, the `segments` accumulation, and `return RichText.assemble(*segments)`) with a direct-append build using the module-level `Text` (already imported at the top of `app.py`):
```python
        text = Text()
        for y in range(rows):
            line = lines[y]
            st = styles[y]
            x = 0
            while x < cols:
                s = st[x]
                j = x + 1
                while j < cols and st[j] == s:
                    j += 1
                segment = "".join(line[x:j]) if s else " " * (j - x)
                text.append(segment, s or None)
                x = j
            if y < rows - 1:
                text.append("\n")
        return text
```

- [ ] **Step 3c: Drop the redundant local `Text` import in `_tick`/`_build_frame`**

Confirm `app.py` imports `Text` at module top (`grep -n "^from rich.text import Text" novacode_cli/tui/app.py`). The local `from rich.text import Text as RichText` was removed by Step 3b. If `_tick` still has a local `import sys`, leave it (the viewport guard uses it) — only the Rich import is removed here.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_matrix_rain.py -q`
Expected: PASS (6 passed — the 3 characterization tests STILL green, proving the inner-loop rewrite is output-equivalent).

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format novacode_cli/tui/app.py tests/test_matrix_rain.py
uv run ruff check tests/test_matrix_rain.py
git add novacode_cli/tui/app.py tests/test_matrix_rain.py
git commit -m "perf(tui): slice-clear buffers, char pool, leaner Text assembly in MatrixRain"
```
End the commit body with the Co-Authored-By trailer.

---

## Task 4: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Run the MatrixRain suite**

Run: `uv run pytest tests/test_matrix_rain.py -q`
Expected: PASS (6 passed).

- [ ] **Step 2: Run the TUI app suite (heavy — allow ~60s; flaky tests pass individually)**

Run: `uv run pytest tests/test_tui_app.py -q`
Expected: PASS. If a test fails, re-run it alone (`uv run pytest tests/test_tui_app.py::<name> -q`) to distinguish a real regression from the suite's known timing flakiness; only a per-test failure is a real regression.

- [ ] **Step 3: Lint delta on app.py**

```bash
uv run ruff check novacode_cli/tui/app.py
```
Expected: no new findings beyond the pre-existing baseline (compare with `git stash` if unsure).

- [ ] **Step 4: Manual smoke (document the result)**

Run `uv run nova`; the home banner rain should look identical and animate smoothly. Optionally confirm it still recolors when you switch themes (`/theme <name>`), proving the palette cache invalidates on theme change.

- [ ] **Step 5: Commit any fixups** (if Steps 1-3 surfaced issues)

```bash
git add -A
git commit -m "test: verify MatrixRain frame-cost optimization"
```

---

## Self-review notes (author)

- **Spec coverage:** §3(a) palette/art cache → Task 2; §3(b) hoist imports → Task 3 Step 3b/3c (use module-level `Text`); §3(c) slice-clear → Task 3 Step 3a/3b; §3(d) char pool → Task 3; §3(e) leaner assembly → Task 3 Step 3b; §7 testing → Tasks 1-3 (characterization + cache + buffers + pool); §5 look-equivalence → enforced by Task 1's characterization tests staying green through Tasks 2-3.
- **Type consistency:** `_build_frame() -> Text`, `_ensure_theme_cache()`, `_theme_key() -> str`, `_palette` (4-tuple), `_art_style_str`, `_palette_key`, `_blank_line`, `_blank_style`, `_char_pool` — names used identically across tasks and tests.
- **Testability rationale:** tests call `_build_frame()` (not `_tick`), because `self.update()` needs a live app (verified) while `_build_frame` runs bare via the guarded theme reads.
- **No public-API change:** `__init__`/`reflow`/`pause`/`resume`/`on_mount`/`_tick` signatures unchanged; only internal helpers + state added.
