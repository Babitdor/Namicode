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
        mw._build_frame()


def test_palette_cache_reuses_until_theme_changes(monkeypatch):  # noqa: ANN001
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


def test_blank_buffers_match_grid_width():
    mw = _rain()
    assert mw._blank_line == [" "] * mw._col_count
    # None, not "": the style buffer holds Rich Style objects that go straight
    # into a Segment, and None is Segment's "no style".
    assert mw._blank_style == [None] * mw._col_count


def test_char_pool_is_nonempty_valid_katakana():
    mw = _rain()
    katakana = set(MatrixRain.KATAKANA)
    assert mw._char_pool
    assert all(c in katakana for c in mw._char_pool)


# ── render_line: the actual render path ─────────────────────────────────────
#
# The widget renders through render_line()/Strip rather than Static.update().
# Handing Textual a Rich Text of ~1100 style spans measured 13 ms per frame to
# turn into segments — 4x the cost of simulating the rain — which at 15 fps was
# a 25% duty cycle on the main thread and made typing feel laggy. Building
# Segments directly measured ~2.5 ms. These pin the output stays correct.


def _built(width: int = 200):
    mw = _rain(width=width)
    mw._strips = mw._build_strips()
    return mw


def test_every_row_is_a_full_width_strip():
    """A short strip would leave the terminal's previous frame showing through."""
    mw = _built()
    assert len(mw._strips) == mw._row_count
    for y, strip in enumerate(mw._strips):
        assert strip.cell_length == mw._col_count, f"row {y} is ragged"


def test_render_line_serves_each_row_and_is_bounded():
    mw = _built()
    for y in range(mw._row_count):
        assert mw.render_line(y) is mw._strips[y]
    # Out of range must not raise: Textual asks for lines beyond content when
    # the widget's box is taller than the frame.
    assert mw.render_line(mw._row_count).cell_length == mw._col_count
    assert mw.render_line(-1).cell_length == mw._col_count


def test_render_line_before_the_first_tick_does_not_raise():
    """Textual can paint between mount and the first timer tick."""
    mw = _rain()
    assert mw.render_line(0).cell_length == mw._col_count


def test_strip_text_matches_the_text_rendering():
    """The fast path and the readable path must not drift apart."""
    mw = _rain()
    mw._strips = mw._build_strips()
    strip_rows = [s.text for s in mw._strips]
    assert len(strip_rows) == mw._row_count
    katakana = set(MatrixRain.KATAKANA)
    for row in strip_rows:
        assert len(row) == mw._col_count
        assert all(c == " " or c in katakana or c in _ART for c in row)


def test_styles_are_cached_objects_so_identity_runs_work():
    """_build_strips run-length-scans with `is`; that needs shared singletons."""
    mw = _rain()
    mw._ensure_theme_cache()
    first = mw._styles
    mw._ensure_theme_cache()
    assert mw._styles is first
    assert all(s is not None for s in mw._styles)
    assert mw._art_style_obj is not None


def test_a_frame_carries_no_style_strings():
    """A style string in the buffer means Rich would parse it per cell."""
    mw = _rain()
    mw._build_strips()
    for row in mw._frame_styles:
        for cell in row:
            assert cell is None or not isinstance(cell, str)


def test_render_reports_the_frame_without_advancing_it():
    """render() is an inspection view, not a frame step.

    Static.render() would otherwise return the empty renderable this widget no
    longer sets, which reads as "the banner is blank". It must show the live
    frame — but stepping the rain from it would make any inspection (a test, a
    snapshot) silently change what is on screen.
    """
    mw = _rain()
    mw._build_strips()
    before = [row[:] for row in mw._frame_lines]
    first = mw.render().plain
    second = mw.render().plain
    assert first == second
    assert [row[:] for row in mw._frame_lines] == before


def test_render_shows_the_logo_over_the_rain():
    mw = _rain()
    mw._build_strips()
    assert _ART in mw.render().plain
