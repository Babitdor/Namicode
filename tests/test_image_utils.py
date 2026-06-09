"""Tests for novacode_cli.image_utils — image handling utilities."""

import base64
import struct
import zlib

import pytest

from novacode_cli.image_utils import (
    MAX_IMAGE_DIMENSION,
    MAX_IMAGE_SIZE_BYTES,
    SUPPORTED_FORMATS,
    ImageData,
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

    def test_validate_accepts_valid_image(self):
        data = _make_test_image_data(width=100, height=100)
        errors = data.validate()
        assert errors == []

    def test_validate_rejects_oversized_image(self):
        oversized_b64 = "A" * int(MAX_IMAGE_SIZE_BYTES * 4 / 3 * 1.1)
        data = ImageData(base64_data=oversized_b64, format="png", placeholder="[big]")
        errors = data.validate()
        assert any("size" in err.lower() for err in errors)

    def test_validate_rejects_overdimensioned_image(self):
        over = MAX_IMAGE_DIMENSION + 100
        data = _make_test_image_data(width=over, height=100)
        errors = data.validate()
        assert any("dimension" in err.lower() or "resolution" in err.lower() for err in errors)

    def test_validate_rejects_overdimensioned_image_tall(self):
        over = MAX_IMAGE_DIMENSION + 100
        data = _make_test_image_data(width=100, height=over)
        errors = data.validate()
        assert any("dimension" in err.lower() or "resolution" in err.lower() for err in errors)

    def test_validate_rejects_unsupported_format(self):
        data = ImageData(base64_data="AAAA", format="ico", placeholder="[bad]")
        errors = data.validate()
        assert any("format" in err.lower() or "unsupported" in err.lower() for err in errors)

    def test_validate_rejects_empty_base64(self):
        data = ImageData(base64_data="", format="png", placeholder="[empty]")
        errors = data.validate()
        assert len(errors) > 0

    def test_validate_returns_multiple_errors(self):
        oversized_b64 = "A" * int(MAX_IMAGE_SIZE_BYTES * 4 / 3 * 1.1)
        data = ImageData(base64_data=oversized_b64, format="ico", placeholder="[double]")
        errors = data.validate()
        assert len(errors) >= 2


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