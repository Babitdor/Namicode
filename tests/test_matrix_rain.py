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
