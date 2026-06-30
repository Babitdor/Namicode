"""Headless (non-interactive) Nova: ``nova -p "<prompt>"``."""

from novacode_cli.headless.output import HeadlessOutput
from novacode_cli.headless.runner import run_headless

__all__ = ["HeadlessOutput", "run_headless"]
