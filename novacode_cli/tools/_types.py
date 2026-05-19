"""Type constants for tools modules.

This module provides common type constants used across tool modules.
"""

from __future__ import annotations

# HTTP status code constants
_HTTP_CLIENT_ERROR = 400
_HTTP_SERVER_ERROR = 500
_HTTP_TOO_MANY_REQUESTS = 429
_HTTP_NOT_FOUND = 404

# Time constants
_HOUR_MODULUS = 12

# Content processing constants
_MIN_SECTION_LENGTH = 200

# Message severity constants
_MSG_SEVERITY_ERROR = 2

# TypeScript compiler constants
_TSC_PARTS_MIN = 4
