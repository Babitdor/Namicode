# Vision Capabilities Implementation Plan

## Overview
This plan outlines the implementation of comprehensive Vision capabilities for NamiCode CLI, enabling users to work with images through:

1. **Clipboard paste support** (macOS, Windows, Linux)
2. **Image file upload** (drag-and-drop or file path reference)
3. **Multimodal model integration** (GPT-4o, Claude 3.5+, Gemini 1.5+)
4. **Image management UI** (view, remove, reference images in conversation)
5. **Image preprocessing** (resizing, format conversion, validation)

## Current State Analysis

### Existing Infrastructure
✅ **Already Implemented:**
- `image_utils.py` - Basic ImageData class and macOS clipboard support
- `input.py` - ImageTracker class for tracking images in conversation
- Model creation supports vision-capable models (GPT-4o, Claude 3.5+, Gemini 1.5+)
- LangGraph architecture supports multimodal message content

❌ **Missing Features:**
- Windows/Linux clipboard support
- Image file upload capability
- Model capability detection (vision vs text-only)
- Image preprocessing pipeline
- User-friendly image management UI
- Comprehensive testing

---

## Phase 1: Expand Image Input Methods

### 1.1 Windows Clipboard Support
**File:** `namicode_cli/image_utils.py`

**Task:** Implement `_get_windows_clipboard_image()`
- Use `win32clipboard` or `PIL.ImageGrab`
- Handle multiple image formats (PNG, JPEG, BMP)
- Fall back to temporary file method if direct read fails
- Validate image integrity before returning

**Implementation Details:**
```python
def _get_windows_clipboard_image() -> ImageData | None:
    """Get clipboard image on Windows."""
    try:
        from PIL import ImageGrab
        img = ImageGrab.grabclipboard()
        if isinstance(img, Image.Image):
            # Convert to PNG base64
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            base64_data = base64.b64encode(buffer.getvalue()).decode("utf-8")
            return ImageData(
                base64_data=base64_data,
                format="png",
                placeholder="[image]",
            )
    except Exception:
        return None
```

**Dependencies:**
- No additional dependencies (PIL.ImageGrab already available via Pillow)

### 1.2 Linux Clipboard Support
**File:** `namicode_cli/image_utils.py`

**Task:** Implement `_get_linux_clipboard_image()`
- Use `wl-paste` (Wayland) or `xclip` (X11)
- Detect desktop environment (wayland vs x11)
- Handle both clipboard and selection buffers
- Graceful fallback if clipboard tools not installed

**Implementation Details:**
```python
def _get_linux_clipboard_image() -> ImageData | None:
    """Get clipboard image on Linux."""
    # Try Wayland first
    try:
        result = subprocess.run(
            ["wl-paste", "--type", "image/png"],
            capture_output=True,
            check=False,
            timeout=2,
        )
        if result.returncode == 0 and result.stdout:
            # Validate and encode
            image = Image.open(io.BytesIO(result.stdout))
            base64_data = base64.b64encode(result.stdout).decode("utf-8")
            return ImageData(
                base64_data=base64_data,
                format="png",
                placeholder="[image]",
            )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fall back to X11
    try:
        result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"],
            capture_output=True,
            check=False,
            timeout=2,
        )
        if result.returncode == 0 and result.stdout:
            # Similar processing
            ...
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return None
```

**Dependencies:**
- Requires system tools: `wl-clipboard` (Wayland) or `xclip` (X11)
- Add installation hints in error messages

### 1.3 Image File Upload
**File:** `namicode_cli/image_utils.py` (new functions)

**Task:** Add image file loading functions
- `load_image_from_path(path: Path) -> ImageData`
- Support common formats: PNG, JPEG, GIF, WebP, BMP, TIFF
- File size validation (max 20MB per image)
- Image dimension validation (max 7680x4320)
- Auto-convert to PNG for consistency

**Implementation Details:**
```python
MAX_IMAGE_SIZE_BYTES = 20 * 1024 * 1024  # 20MB
MAX_IMAGE_DIMENSION = 7680

def load_image_from_path(image_path: Path) -> ImageData:
    """Load an image from a file path.

    Args:
        image_path: Path to the image file

    Returns:
        ImageData with base64 encoding

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file is too large or invalid image
    """
    if not image_path.exists():
        raise FileNotFoundError(f"Image file not found: {image_path}")

    # Check file size
    file_size = image_path.stat().st_size
    if file_size > MAX_IMAGE_SIZE_BYTES:
        raise ValueError(
            f"Image too large ({file_size / 1024 / 1024:.1f}MB). "
            f"Maximum size is {MAX_IMAGE_SIZE_BYTES / 1024 / 1024}MB"
        )

    # Load and validate image
    image = Image.open(image_path)

    # Check dimensions
    width, height = image.size
    if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
        raise ValueError(
            f"Image dimensions too large: {width}x{height}. "
            f"Maximum dimension is {MAX_IMAGE_DIMENSION}px"
        )

    # Convert to PNG
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    base64_data = base64.b64encode(buffer.getvalue()).decode("utf-8")

    return ImageData(
        base64_data=base64_data,
        format="png",
        placeholder=f"[image {image_path.name}]",
    )
```

**Dependencies:**
- Pillow (already available)

---

## Phase 2: Model Vision Capability Detection

### 2.1 Vision-Capable Model Registry
**File:** `namicode_cli/config/model_create.py` (new data)

**Task:** Create registry of vision-capable models
- Define mapping of model names to capabilities
- Include Anthropic, OpenAI, Google, and Ollama models
- Add helper function to check model capabilities

**Implementation Details:**
```python
VISION_CAPABLE_MODELS = {
    # Anthropic
    "claude-sonnet-4-5-20250929": True,
    "claude-opus-4-5-20251001": True,
    "claude-3-5-sonnet-20241022": True,
    "claude-3-5-sonnet-20240620": True,
    "claude-3-5-haiku-20241022": True,
    "claude-3-opus-20240229": True,

    # OpenAI
    "gpt-4o": True,
    "gpt-4o-mini": True,
    "gpt-4-turbo": True,
    "gpt-4-vision-preview": True,

    # Google
    "gemini-1.5-pro": True,
    "gemini-1.5-flash": True,
    "gemini-2.0-flash-exp": True,

    # Ollama (depends on model)
    # Will be detected dynamically
}

def model_supports_vision(model_name: str) -> bool:
    """Check if a model supports vision capabilities.

    Args:
        model_name: Name of the model

    Returns:
        True if model supports vision, False otherwise
    """
    # Check registry first
    if model_name in VISION_CAPABLE_MODELS:
        return VISION_CAPABLE_MODELS[model_name]

    # For Ollama, make a best guess based on naming convention
    # Models with "-vision", "-multimodal", or similar usually support vision
    vision_keywords = ["vision", "multimodal", "mm", "llava", "bakllava", "moondream"]
    return any(keyword in model_name.lower() for keyword in vision_keywords)
```

### 2.2 Model Selection Enhancement
**File:** `namicode_cli/config/model_create.py`

**Task:** Add auto-selection of vision-capable models when images present
- Detect if images are in user input
- Automatically switch to vision-capable model if needed
- Warn user if current model doesn't support vision
- Respect saved configuration (don't auto-switch without permission)

**Implementation Details:**
```python
def suggest_vision_model(current_model: str) -> str | None:
    """Suggest a vision-capable model if current model doesn't support vision.

    Args:
        current_model: Current model name

    Returns:
        Suggested model name or None
    """
    if model_supports_vision(current_model):
        return None  # Current model supports vision

    # Suggest best available model
    if settings.has_anthropic:
        return "claude-sonnet-4-5-20250929"
    elif settings.has_openai:
        return "gpt-4o"
    elif settings.has_google:
        return "gemini-1.5-pro"
    else:
        return None
```

---

## Phase 3: Image Preprocessing Pipeline

### 3.1 Image Validation & Optimization
**File:** `namicode_cli/image_utils.py` (new module)

**Task:** Create `ImageProcessor` class
- Resize oversized images (max 4096x4096 for most APIs)
- Convert to optimal format (PNG for quality, JPEG for size)
- Compress images to reduce token usage
- Extract EXIF metadata (optional, for debugging)

**Implementation Details:**
```python
class ImageProcessor:
    """Handle image preprocessing for optimal API usage."""

    MAX_DIMENSION = 4096  # Most vision APIs support up to 4096x4096
    TARGET_QUALITY = 85  # JPEG quality
    MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5MB target

    @staticmethod
    def optimize_image(
        image: Image.Image,
        format: str = "jpeg",  # "jpeg" or "png"
    ) -> bytes:
        """Optimize an image for API transmission.

        Args:
            image: PIL Image object
            format: Output format ("jpeg" or "png")

        Returns:
            Optimized image bytes
        """
        # Resize if too large
        width, height = image.size
        if width > ImageProcessor.MAX_DIMENSION or height > ImageProcessor.MAX_DIMENSION:
            image.thumbnail(
                (ImageProcessor.MAX_DIMENSION, ImageProcessor.MAX_DIMENSION),
                Image.Resampling.LANCZOS,
            )

        # Save with optimization
        buffer = io.BytesIO()
        save_kwargs = {
            "optimize": True,
        }

        if format == "jpeg":
            save_kwargs.update({
                "quality": ImageProcessor.TARGET_QUALITY,
                "progressive": True,
            })
        elif format == "png":
            save_kwargs.update({
                "compress_level": 6,
            })

        image.save(buffer, format=format, **save_kwargs)
        return buffer.getvalue()

    @staticmethod
    def process_image_data(image_data: ImageData) -> ImageData:
        """Process and optimize ImageData.

        Args:
            image_data: Raw ImageData

        Returns:
            Optimized ImageData
        """
        # Decode base64
        image_bytes = base64.b64decode(image_data.base64_data)
        image = Image.open(io.BytesIO(image_bytes))

        # Convert to RGB if necessary (remove alpha for JPEG)
        if image.mode in ("RGBA", "LA", "P"):
            # Create white background for transparency
            background = Image.new("RGB", image.size, (255, 255, 255))
            if image.mode == "P":
                image = image.convert("RGBA")
            background.paste(image, mask=image.split()[-1])  # Use alpha channel as mask
            image = background
        elif image.mode != "RGB":
            image = image.convert("RGB")

        # Optimize
        optimized_bytes = ImageProcessor.optimize_image(image, format="jpeg")
        optimized_base64 = base64.b64encode(optimized_bytes).decode("utf-8")

        return ImageData(
            base64_data=optimized_base64,
            format="jpeg",
            placeholder=image_data.placeholder,
        )
```

---

## Phase 4: Image Management UI

### 4.1 Image Reference System
**File:** `namicode_cli/input.py`

**Task:** Enhance ImageTracker with reference system
- Assign stable IDs to images (image-1, image-2)
- Allow referencing images by ID in conversation
- Display image list with `/images` command
- Support removing images from conversation

**Implementation Details:**
```python
class ImageTracker:
    """Track pasted images in the current conversation."""

    def __init__(self) -> None:
        self.images: dict[str, ImageData] = {}  # id -> ImageData
        self.next_id = 1

    def add_image(self, image_data: ImageData) -> str:
        """Add an image and return its ID.

        Args:
            image_data: The image data to track

        Returns:
            Image ID like "image-1"
        """
        image_id = f"image-{self.next_id}"
        image_data.placeholder = f"[{image_id}]"
        self.images[image_id] = image_data
        self.next_id += 1
        return image_id

    def get_image(self, image_id: str) -> ImageData | None:
        """Get an image by ID."""
        return self.images.get(image_id)

    def remove_image(self, image_id: str) -> bool:
        """Remove an image by ID.

        Returns:
            True if removed, False if not found
        """
        return self.images.pop(image_id, None) is not None

    def list_images(self) -> list[dict]:
        """List all images with metadata."""
        return [
            {
                "id": image_id,
                "format": img.format,
                "size_kb": len(img.base64_data) / 1024,
                "placeholder": img.placeholder,
            }
            for image_id, img in self.images.items()
        ]

    def clear(self) -> None:
        """Clear all tracked images and reset counter."""
        self.images.clear()
        self.next_id = 1
```

### 4.2 /images Command
**File:** `namicode_cli/commands/commands.py`

**Task:** Add image management command
- List all images in current conversation
- Show image details (format, size)
- Support removing images: `/images remove image-1`
- Clear all images: `/images clear`

**Implementation Details:**
```python
def execute_images_command(
    action: str | None = None,
    image_id: str | None = None,
    image_tracker: ImageTracker | None = None,
) -> str:
    """Execute /images command.

    Args:
        action: "list", "remove", "clear"
        image_id: Image ID to remove (for "remove" action)
        image_tracker: Current image tracker

    Returns:
        Command result message
    """
    if image_tracker is None:
        return "No active image tracker"

    if action is None or action == "list":
        images = image_tracker.list_images()
        if not images:
            return "No images in current conversation"

        result = ["Images in conversation:"]
        for img in images:
            result.append(
                f"  {img['id']}: {img['format']}, "
                f"{img['size_kb']:.1f}KB"
            )
        return "\n".join(result)

    elif action == "remove":
        if image_id is None:
            return "Usage: /images remove <image-id>"
        if image_tracker.remove_image(image_id):
            return f"Removed {image_id}"
        else:
            return f"Image not found: {image_id}"

    elif action == "clear":
        count = len(image_tracker.images)
        image_tracker.clear()
        return f"Cleared {count} image(s)"

    else:
        return f"Unknown action: {action}. Use: list, remove, clear"
```

### 4.3 Image Display in Input
**File:** `namicode_cli/input.py`

**Task:** Show image placeholders in prompt
- Display `[image 1]` when image is added
- Highlight image references in conversation
- Show total image count in prompt prefix

**Implementation Details:**
```python
def get_prompt_prefix(image_tracker: ImageTracker) -> str:
    """Get prompt prefix showing image count.

    Args:
        image_tracker: Current image tracker

    Returns:
        Prefix string (e.g., "📷 (2) > ")
    """
    count = len(image_tracker.images)
    if count == 0:
        return "> "
    else:
        return f"📷 ({count}) > "
```

---

## Phase 5: Multimodal Message Integration

### 5.1 Agent State Update
**File:** `deepagents-nami/nami_deepagents/middleware/filesystem.py` (or similar)

**Task:** Extend AgentState to include images
- Add `images: dict[str, str]` field (image_id -> base64_data)
- Ensure images persist through message history
- Support image references in tool calls

**Implementation Details:**
```python
class MultimodalState(AgentState):
    """State for multimodal conversations."""

    images: dict[str, str] = {}  # image_id -> base64_data
    image_count: int = 0
```

### 5.2 Message Construction
**File:** `namicode_cli/main.py` or `namicode_cli/ui/execution.py`

**Task:** Build multimodal messages from user input
- Parse text for image references (e.g., "Analyze [image-1]")
- Attach image data to message content
- Use LangChain multimodal message format

**Implementation Details:**
```python
def create_multimodal_message(
    text: str,
    images: dict[str, ImageData],
) -> dict:
    """Create a multimodal message with text and images.

    Args:
        text: User's text input
        images: Dictionary of images keyed by ID

    Returns:
        Message dict with multimodal content
    """
    content_blocks = [{"type": "text", "text": text}]

    # Parse text for image references
    import re
    image_ref_pattern = r'\[image-(\d+)\]'
    image_ids = re.findall(image_ref_pattern, text)

    # Add referenced images
    for image_id in image_ids:
        if image_id in images:
            image_data = images[image_id]
            content_blocks.append(image_data.to_message_content())

    return {
        "role": "user",
        "content": content_blocks,
    }
```

---

## Phase 6: Testing

### 6.1 Unit Tests
**File:** `tests/unit_tests/test_vision.py` (new file)

**Test Coverage:**
- ImageData serialization/deserialization
- Clipboard image capture (mock subprocess calls)
- Image file loading (with invalid files)
- ImageProcessor optimization
- Model vision capability detection
- ImageTracker CRUD operations
- Multimodal message construction

**Test Structure:**
```python
import pytest
from pathlib import Path
from PIL import Image
from namicode_cli.image_utils import (
    ImageData,
    load_image_from_path,
    ImageProcessor,
)
from namicode_cli.input import ImageTracker
from namicode_cli.config.model_create import model_supports_vision

class TestImageData:
    def test_to_message_content(self):
        """Test ImageData conversion to LangChain format."""
        ...

class TestImageLoading:
    def test_load_png_image(self, tmp_path):
        """Test loading a PNG image."""
        ...

    def test_file_not_found(self, tmp_path):
        """Test error when file doesn't exist."""
        ...

    def test_image_too_large(self, tmp_path):
        """Test error when image exceeds size limit."""
        ...

class TestImageProcessor:
    def test_resize_large_image(self):
        """Test image resizing."""
        ...

    def test_convert_rgba_to_rgb(self):
        """Test RGBA to RGB conversion."""
        ...

class TestImageTracker:
    def test_add_and_retrieve_image(self):
        """Test adding and retrieving images."""
        ...

    def test_remove_image(self):
        """Test removing an image."""
        ...

    def test_list_images(self):
        """Test listing images with metadata."""
        ...

class TestModelVisionDetection:
    def test_claude_sonnet_supports_vision(self):
        """Test Claude Sonnet vision capability."""
        assert model_supports_vision("claude-sonnet-4-5-20250929")

    def test_gpt4o_supports_vision(self):
        """Test GPT-4o vision capability."""
        assert model_supports_vision("gpt-4o")

    def test_text_only_model_no_vision(self):
        """Test text-only model lacks vision."""
        assert not model_supports_vision("gpt-3.5-turbo")
```

### 6.2 Integration Tests
**File:** `tests/integration_tests/test_vision_integration.py` (new file)

**Test Coverage:**
- End-to-end image workflow (paste -> model -> response)
- Cross-platform clipboard functionality
- Model response with image analysis
- Image persistence across session save/restore

**Test Structure:**
```python
@pytest.mark.integration
class TestVisionIntegration:
    def test_clipboard_to_model(self, agent):
        """Test full clipboard-to-model workflow."""
        ...

    def test_image_file_upload(self, agent):
        """Test image file upload workflow."""
        ...

    def test_multimodal_conversation(self, agent):
        """Test conversation with multiple images."""
        ...

    def test_image_persistence(self, agent):
        """Test image persistence across session save/restore."""
        ...
```

---

## Phase 7: Documentation & User Guide

### 7.1 User Documentation
**File:** `docs/vision-guide.md` (new file)

**Contents:**
- Supported image formats and limitations
- How to paste images (macOS, Windows, Linux)
- How to upload image files
- Referencing images in conversation
- Supported models with vision capabilities
- Tips for best results

**Example:**
```markdown
# Vision Capabilities Guide

## Supported Image Formats

- PNG, JPEG, GIF, WebP, BMP, TIFF
- Maximum file size: 20MB
- Maximum dimensions: 7680x4320

## Adding Images

### Clipboard Paste (macOS)
1. Copy an image (Cmd+C)
2. Paste into NamiCode (Cmd+V)
3. Image appears as `[image 1]`

### Clipboard Paste (Windows)
1. Copy an image (Ctrl+C)
2. Paste into NamiCode (Ctrl+V)
3. Image appears as `[image 1]`

### Image File Upload
Use `@` to reference image files:

```
@./screenshot.png What does this UI show?
```

### Image Management
List images: `/images list`
Remove image: `/images remove image-1`
Clear all: `/images clear`

## Supported Models

Vision-capable models:
- Claude 3.5+ (Sonnet, Opus, Haiku)
- GPT-4o, GPT-4 Vision
- Gemini 1.5+ (Pro, Flash)
- Ollama models (llava, bakllava, etc.)

## Tips

- Crop images to focus on relevant content
- Avoid excessive images (max 5 per message)
- Reference images explicitly: "Analyze [image-1] and [image-2]"
```

### 7.2 Developer Documentation
**File:** `docs/vision-architecture.md` (new file)

**Contents:**
- Architecture overview
- Data flow (input -> processing -> model -> response)
- API contract for ImageData
- Extension points for new image sources
- Testing guidelines

---

## Implementation Timeline

### Sprint 1 (Week 1)
- ✅ Windows clipboard support
- ✅ Linux clipboard support
- ✅ Image file loading
- ✅ Unit tests for image utilities

### Sprint 2 (Week 2)
- ✅ Vision model capability registry
- ✅ Image preprocessing pipeline
- ✅ ImageTracker enhancement
- ✅ /images command

### Sprint 3 (Week 3)
- ✅ Multimodal message construction
- ✅ Agent state updates
- ✅ Integration tests
- ✅ Documentation

### Sprint 4 (Week 4)
- ✅ Cross-platform testing
- ✅ Performance optimization
- ✅ Edge case handling
- ✅ Release preparation

---

## Risks & Mitigation

### Risk 1: Clipboard Tool Dependencies
**Risk:** Linux systems may not have `wl-paste` or `xclip` installed

**Mitigation:**
- Graceful fallback with helpful error messages
- Document installation steps for popular distros
- Consider bundling Python-only clipboard library as fallback

### Risk 2: API Token Costs
**Risk:** Vision models consume significantly more tokens

**Mitigation:**
- Default image preprocessing to compress images
- Add user option to disable optimization
- Show warning for large images before sending

### Risk 3: Model Compatibility
**Risk:** Different APIs have varying image format requirements

**Mitigation:**
- Standardize on JPEG/PNG formats
- Model-specific preprocessing if needed
- Extensive testing across providers

### Risk 4: Performance Impact
**Risk:** Large images slow down encoding/transmission

**Mitigation:**
- Async image processing
- Progress indicators for large images
- Configurable optimization levels

---

## Success Criteria

✅ **Functional Requirements:**
- Users can paste images on macOS, Windows, and Linux
- Users can upload image files via `@` reference
- Images are processed and optimized before sending
- Vision-capable models correctly analyze images
- Images persist across session save/restore
- `/images` command works as expected

✅ **Quality Requirements:**
- All unit tests pass
- Integration tests cover major workflows
- Code follows existing conventions
- Documentation is complete and accurate

✅ **Performance Requirements:**
- Image preprocessing < 2 seconds for 5MB images
- Clipboard paste < 1 second
- Memory usage increase < 100MB with images

---

## Future Enhancements

### Post-Release Features
1. **Batch image processing** - Drag-and-drop multiple images
2. **Image annotation** - Draw on images before sending
3. **Video support** - Short video clip analysis
4. **Screen capture integration** - Direct screenshot capture
5. **Image editing** - Crop, rotate, adjust before sending
6. **Image comparison** - Side-by-side image diff
7. **OCR capabilities** - Extract text from images
8. **Image search** - Find similar images in repository

---

## Appendix: Code Reference

### Key Files Modified/Created

```
namicode_cli/
├── image_utils.py              # ✏️ Modified (add Windows/Linux support, file loading)
├── input.py                    # ✏️ Modified (enhance ImageTracker)
├── config/
│   └── model_create.py         # ✏️ Modified (vision capability registry)
├── commands/
│   └── commands.py             # ✏️ Modified (add /images command)
└── vision/                     # 🆕 New directory
    ├── __init__.py
    ├── processor.py            # Image preprocessing
    ├── models.py               # Vision model registry
    └── ui.py                   # Image management UI components

tests/
├── unit_tests/
│   └── test_vision.py          # 🆕 New file
└── integration_tests/
    └── test_vision_integration.py  # 🆕 New file

docs/
├── vision-guide.md             # 🆕 New file
└── vision-architecture.md      # 🆕 New file
```

### Dependencies

**New Dependencies:**
- None (using existing Pillow)

**Optional System Dependencies:**
- macOS: `pngpaste` (optional, for faster clipboard)
- Linux (Wayland): `wl-clipboard` (`wl-paste`, `wl-copy`)
- Linux (X11): `xclip`
- Windows: None (PIL.ImageGrab built-in)

---

## Conclusion

This implementation plan provides a comprehensive roadmap for adding Vision capabilities to NamiCode. The phased approach ensures incremental progress with testing at each stage, while maintaining backward compatibility with existing functionality.

The plan addresses cross-platform support, model integration, user experience, and performance considerations, setting a solid foundation for future enhancements.