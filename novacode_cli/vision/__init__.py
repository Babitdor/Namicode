"""Vision capabilities module for NovaCode.

This module provides comprehensive image handling, preprocessing, and
multimodal model integration features.

Components:
- models: Vision model capability detection and registry
- processor: Image preprocessing and optimization
- ui: Image management UI components
"""

from novacode_cli.vision.models import (
    VISION_CAPABLE_MODELS,
    get_vision_models,
    model_supports_vision,
    suggest_vision_model,
)

__all__ = [
    "VISION_CAPABLE_MODELS",
    "get_vision_models",
    "model_supports_vision",
    "suggest_vision_model",
]
