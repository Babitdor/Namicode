"""Tests for novacode_cli.image_utils — image handling utilities."""

import base64
import struct
import zlib

import pytest

import novacode_cli.image_utils as image_utils
from novacode_cli.image_utils import (
    MAX_IMAGE_DIMENSION,
    MAX_IMAGE_SIZE_BYTES,
    SUPPORTED_FORMATS,
    ImageData,
    load_image_from_path,
)


def _make_valid_png_bytes(width: int = 100, height: int = 100) -> bytes:
    """Construct a minimal valid PNG file without PIL."""
    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        chunk_len = struct.pack(">I", len(data))
        crc_data = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(crc_data) & 0xFFFFFFFF)
        return chunk_len + crc_data + crc

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr = _chunk(b"IHDR", ihdr_data)

    raw_row = b"\x00" + b"\xff\x00\x00" * width
    compressed = zlib.compress(raw_row * height)
    idat = _chunk(b"IDAT", compressed)
    iend = _chunk(b"IEND", b"")

    return signature + ihdr + idat + iend


def _make_test_image_data(
    format: str = "png",
    width: int = 100,
    height: int = 100,
) -> ImageData:
    """Helper: create a valid ImageData from raw PNG bytes."""
    raw = _make_valid_png_bytes(width=width, height=height)
    b64 = base64.b64encode(raw).decode("utf-8")
    return ImageData(base64_data=b64, format=format, placeholder="[test image]")


class TestImageData:
    """Tests for ImageData dataclass and its methods."""

    def test_to_message_content(self):
        data = _make_test_image_data()
        result = data.to_message_content()
        assert result["type"] == "image_url"
        assert f"data:image/png;base64,{data.base64_data}" == result["image_url"]["url"]

    def test_size_kb_property(self):
        data = _make_test_image_data()
        assert data.size_kb > 0
        assert isinstance(data.size_kb, float)


class TestLoadImageValidation:
    """The size/format/dimension limits are enforced in ``load_image_from_path``.

    (These previously targeted an ``ImageData.validate()`` helper that does not
    exist — the limits are applied at load time and raise, rather than being
    collected into an error list. Same rules, real entry point.)
    """

    def _write_png(self, tmp_path, name="img.png", width=100, height=100):
        p = tmp_path / name
        p.write_bytes(_make_valid_png_bytes(width=width, height=height))
        return p

    def test_load_accepts_valid_image(self, tmp_path):
        data = load_image_from_path(self._write_png(tmp_path))
        assert isinstance(data, ImageData)
        assert data.base64_data

    def test_load_rejects_oversized_image(self, tmp_path, monkeypatch):
        # Shrink the cap rather than writing a 20MB file — same branch, fast.
        monkeypatch.setattr(image_utils, "MAX_IMAGE_SIZE_BYTES", 128)
        with pytest.raises(ValueError, match="too large"):
            load_image_from_path(self._write_png(tmp_path))

    def test_load_rejects_overdimensioned_image(self, tmp_path):
        over = MAX_IMAGE_DIMENSION + 100
        with pytest.raises(ValueError, match="dimensions too large"):
            load_image_from_path(self._write_png(tmp_path, width=over, height=100))

    def test_load_rejects_overdimensioned_image_tall(self, tmp_path):
        over = MAX_IMAGE_DIMENSION + 100
        with pytest.raises(ValueError, match="dimensions too large"):
            load_image_from_path(self._write_png(tmp_path, height=over, width=100))

    def test_load_rejects_unsupported_format(self, tmp_path):
        bad = tmp_path / "img.ico"
        bad.write_bytes(_make_valid_png_bytes())
        with pytest.raises(ValueError, match="Unsupported image format"):
            load_image_from_path(bad)

    def test_load_rejects_corrupt_image(self, tmp_path):
        bad = tmp_path / "corrupt.png"
        bad.write_bytes(b"not actually a png")
        with pytest.raises(ValueError, match="Invalid image file"):
            load_image_from_path(bad)

    def test_load_rejects_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_image_from_path(tmp_path / "nope.png")


class TestConstants:
    """Tests for module-level constants."""

    def test_max_image_size_bytes_positive(self):
        assert MAX_IMAGE_SIZE_BYTES == 20 * 1024 * 1024

    def test_max_image_dimension_positive(self):
        assert MAX_IMAGE_DIMENSION == 7680

    def test_supported_formats_contains_common(self):
        assert ".png" in SUPPORTED_FORMATS
        assert ".jpg" in SUPPORTED_FORMATS
        assert ".jpeg" in SUPPORTED_FORMATS
        assert ".gif" in SUPPORTED_FORMATS