"""Vision capabilities module for NamiCode.

This module provides comprehensive image handling, preprocessing, and
multimodal model integration features.

Components:
- models: Vision model capability detection and registry
- processor: Image preprocessing and optimization
- ui: Image management UI components
"""

from namicode_cli.vision.models import (
    model_supports_vision,
    get_vision_models,
    suggest_vision_model,
    VISION_CAPABLE_MODELS,
)

__all__ = [
    "model_supports_vision",
    "get_vision_models",
    "suggest_vision_model",
    "VISION_CAPABLE_MODELS",
]