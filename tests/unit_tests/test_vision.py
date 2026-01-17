"""Tests for vision module including model detection and image utilities."""

import base64
import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from namicode_cli.vision import (
    model_supports_vision,
    get_vision_models,
    suggest_vision_model,
    VISION_CAPABLE_MODELS,
)
from namicode_cli.image_utils import (
    ImageData,
    load_image_from_path,
    create_multimodal_content,
    is_image_file,
    ImageProcessor,
    SUPPORTED_FORMATS,
    MAX_IMAGE_SIZE_BYTES,
    MAX_IMAGE_DIMENSION,
)
from namicode_cli.input import ImageTracker


class TestVisionModelDetection:
    """Test vision model capability detection."""

    def test_known_vision_models_supported(self) -> None:
        """Test that known vision models are correctly identified."""
        known_vision_models = [
            "gpt-4o",
            "gpt-4o-mini",
            "claude-sonnet-4-5-20250929",
            "claude-3-5-sonnet-20241022",
            "gemini-1.5-pro",
            "qwen3-vl:235b-cloud",
            "llava",
            "moondream",
        ]
        for model in known_vision_models:
            assert model_supports_vision(model), f"{model} should support vision"

    def test_non_vision_models_not_supported(self) -> None:
        """Test that non-vision models are correctly identified."""
        non_vision_models = [
            "gpt-3.5-turbo",
            "gpt-4",  # Base gpt-4 without vision
            "claude-instant-1.2",
            "text-davinci-003",
            "llama-2-70b",
        ]
        for model in non_vision_models:
            assert not model_supports_vision(model), f"{model} should not support vision"

    def test_qwen_vl_models_supported(self) -> None:
        """Test that qwen3-vl variants are detected as vision-capable."""
        assert model_supports_vision("qwen3-vl")
        assert model_supports_vision("qwen3-vl:235b-cloud")
        assert model_supports_vision("qwen3-vl:latest")

    def test_model_with_vision_keyword_detected(self) -> None:
        """Test that models with vision keywords are detected."""
        assert model_supports_vision("some-model-vision")
        assert model_supports_vision("multimodal-model")
        assert model_supports_vision("llava-custom")

    def test_get_vision_models_by_provider(self) -> None:
        """Test getting vision models by provider."""
        ollama_models = get_vision_models("ollama")
        assert "qwen3-vl" in ollama_models
        assert "llava" in ollama_models

        openai_models = get_vision_models("openai")
        assert any("gpt-4" in m for m in openai_models)

    def test_suggest_vision_model_returns_none_for_vision_model(self) -> None:
        """Test that no suggestion is made for already vision-capable models."""
        assert suggest_vision_model("gpt-4o") is None
        assert suggest_vision_model("qwen3-vl:235b-cloud") is None

    def test_suggest_vision_model_returns_suggestion_for_non_vision(self) -> None:
        """Test that a suggestion is made for non-vision models."""
        suggestion = suggest_vision_model("gpt-3.5-turbo")
        assert suggestion is not None
        assert model_supports_vision(suggestion)


class TestImageTracker:
    """Test ImageTracker class functionality."""

    def test_add_image_returns_id(self) -> None:
        """Test that adding an image returns an ID."""
        tracker = ImageTracker()
        image = ImageData(
            base64_data="dGVzdA==",
            format="png",
            placeholder="[image]",
        )
        image_id = tracker.add_image(image)
        assert image_id == "image-1"

    def test_add_multiple_images_increments_id(self) -> None:
        """Test that adding multiple images increments the ID."""
        tracker = ImageTracker()
        img1 = ImageData(base64_data="dGVzdA==", format="png", placeholder="[image]")
        img2 = ImageData(base64_data="dGVzdA==", format="png", placeholder="[image]")

        id1 = tracker.add_image(img1)
        id2 = tracker.add_image(img2)

        assert id1 == "image-1"
        assert id2 == "image-2"

    def test_get_image_returns_correct_image(self) -> None:
        """Test getting an image by ID."""
        tracker = ImageTracker()
        image = ImageData(base64_data="dGVzdA==", format="png", placeholder="[image]")
        image_id = tracker.add_image(image)

        retrieved = tracker.get_image(image_id)
        assert retrieved is not None
        assert retrieved.base64_data == "dGVzdA=="

    def test_get_nonexistent_image_returns_none(self) -> None:
        """Test that getting a nonexistent image returns None."""
        tracker = ImageTracker()
        assert tracker.get_image("image-999") is None

    def test_remove_image(self) -> None:
        """Test removing an image."""
        tracker = ImageTracker()
        image = ImageData(base64_data="dGVzdA==", format="png", placeholder="[image]")
        image_id = tracker.add_image(image)

        assert tracker.remove_image(image_id) is True
        assert tracker.get_image(image_id) is None

    def test_remove_nonexistent_image_returns_false(self) -> None:
        """Test that removing a nonexistent image returns False."""
        tracker = ImageTracker()
        assert tracker.remove_image("image-999") is False

    def test_list_images(self) -> None:
        """Test listing all images."""
        tracker = ImageTracker()
        img1 = ImageData(base64_data="dGVzdA==", format="png", placeholder="[image]")
        img2 = ImageData(base64_data="dGVzdDI=", format="jpeg", placeholder="[image]")

        tracker.add_image(img1)
        tracker.add_image(img2)

        images = tracker.list_images()
        assert len(images) == 2
        assert images[0]["id"] == "image-1"
        assert images[1]["id"] == "image-2"

    def test_clear_images(self) -> None:
        """Test clearing all images."""
        tracker = ImageTracker()
        img = ImageData(base64_data="dGVzdA==", format="png", placeholder="[image]")
        tracker.add_image(img)

        tracker.clear()
        assert tracker.count == 0
        assert tracker.get_images() == []

    def test_count_property(self) -> None:
        """Test the count property."""
        tracker = ImageTracker()
        assert tracker.count == 0

        img = ImageData(base64_data="dGVzdA==", format="png", placeholder="[image]")
        tracker.add_image(img)
        assert tracker.count == 1


class TestImageData:
    """Test ImageData dataclass functionality."""

    def test_to_message_content(self) -> None:
        """Test converting ImageData to message content format."""
        image = ImageData(
            base64_data="dGVzdA==",
            format="png",
            placeholder="[image]",
        )
        content = image.to_message_content()

        assert content["type"] == "image_url"
        assert "image_url" in content
        assert content["image_url"]["url"].startswith("data:image/png;base64,")

    def test_size_kb_calculation(self) -> None:
        """Test size_kb property calculates correctly."""
        # 1000 bytes of base64 data (approx 750 bytes original)
        base64_data = "a" * 1000
        image = ImageData(
            base64_data=base64_data,
            format="png",
            placeholder="[image]",
        )
        # 1000 * 3/4 / 1024 ≈ 0.73 KB
        assert 0.7 < image.size_kb < 0.8


class TestCreateMultimodalContent:
    """Test multimodal content creation."""

    def test_create_with_text_and_images(self) -> None:
        """Test creating content with both text and images."""
        text = "Describe this image"
        images = [
            ImageData(base64_data="dGVzdA==", format="png", placeholder="[image-1]"),
        ]
        content = create_multimodal_content(text, images)

        assert len(content) == 2
        assert content[0]["type"] == "text"
        assert content[0]["text"] == text
        assert content[1]["type"] == "image_url"

    def test_create_with_empty_text(self) -> None:
        """Test creating content with empty text."""
        images = [
            ImageData(base64_data="dGVzdA==", format="png", placeholder="[image-1]"),
        ]
        content = create_multimodal_content("", images)

        assert len(content) == 1
        assert content[0]["type"] == "image_url"

    def test_create_with_multiple_images(self) -> None:
        """Test creating content with multiple images."""
        text = "Compare these images"
        images = [
            ImageData(base64_data="dGVzdA==", format="png", placeholder="[image-1]"),
            ImageData(base64_data="dGVzdDI=", format="jpeg", placeholder="[image-2]"),
        ]
        content = create_multimodal_content(text, images)

        assert len(content) == 3
        assert content[0]["type"] == "text"
        assert content[1]["type"] == "image_url"
        assert content[2]["type"] == "image_url"


class TestImageFileLoading:
    """Test image file loading functionality."""

    def test_is_image_file(self, tmp_path: Path) -> None:
        """Test is_image_file function."""
        # Create a test image file
        img_file = tmp_path / "test.png"
        img_file.write_bytes(b"fake image data")

        assert is_image_file(img_file) is True

        # Non-image file
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("not an image")
        assert is_image_file(txt_file) is False

    def test_supported_formats(self) -> None:
        """Test that expected formats are supported."""
        expected_formats = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
        for fmt in expected_formats:
            assert fmt in SUPPORTED_FORMATS

    def test_load_image_from_path_nonexistent(self, tmp_path: Path) -> None:
        """Test loading a nonexistent image file."""
        with pytest.raises(FileNotFoundError):
            load_image_from_path(tmp_path / "nonexistent.png")

    def test_load_image_from_path_unsupported_format(self, tmp_path: Path) -> None:
        """Test loading an unsupported format."""
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("not an image")
        with pytest.raises(ValueError, match="Unsupported image format"):
            load_image_from_path(txt_file)


class TestImageProcessor:
    """Test ImageProcessor class."""

    def test_max_dimension_constant(self) -> None:
        """Test that MAX_DIMENSION is set correctly."""
        assert ImageProcessor.MAX_DIMENSION == 4096

    def test_target_quality_constant(self) -> None:
        """Test that TARGET_QUALITY is set correctly."""
        assert ImageProcessor.TARGET_QUALITY == 85

    def test_max_file_size_constant(self) -> None:
        """Test that MAX_FILE_SIZE_BYTES is set correctly."""
        assert ImageProcessor.MAX_FILE_SIZE_BYTES == 5 * 1024 * 1024


class TestVisionModelRegistry:
    """Test the vision model registry."""

    def test_registry_contains_qwen_models(self) -> None:
        """Test that qwen3-vl models are in registry."""
        assert "qwen3-vl" in VISION_CAPABLE_MODELS
        assert "qwen3-vl:235b-cloud" in VISION_CAPABLE_MODELS

    def test_registry_contains_major_providers(self) -> None:
        """Test that major providers have models in registry."""
        # Check for at least one model from each major provider
        has_anthropic = any("claude" in m for m in VISION_CAPABLE_MODELS)
        has_openai = any("gpt" in m for m in VISION_CAPABLE_MODELS)
        has_google = any("gemini" in m for m in VISION_CAPABLE_MODELS)
        has_ollama = any("llava" in m for m in VISION_CAPABLE_MODELS)

        assert has_anthropic, "Registry should have Anthropic models"
        assert has_openai, "Registry should have OpenAI models"
        assert has_google, "Registry should have Google models"
        assert has_ollama, "Registry should have Ollama models"
