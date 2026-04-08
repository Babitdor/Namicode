"""Test browser console capture tool."""

import pytest


def test_capture_browser_console_import():
    """Test that capture_browser_console can be imported."""
    from novacode_cli.tools import capture_browser_console
    
    assert callable(capture_browser_console)


def test_capture_browser_console_signature():
    """Test that capture_browser_console has correct signature."""
    from novacode_cli.tools import capture_browser_console
    import inspect
    
    sig = inspect.signature(capture_browser_console)
    params = list(sig.parameters.keys())
    
    assert "url" in params
    assert "duration" in params
    assert "capture_errors" in params
    assert "capture_warnings" in params
    assert "capture_logs" in params
    assert "headless" in params
    
    # Check defaults
    assert sig.parameters["duration"].default == 30
    assert sig.parameters["capture_errors"].default is True
    assert sig.parameters["capture_warnings"].default is True
    assert sig.parameters["capture_logs"].default is True
    assert sig.parameters["headless"].default is True


def test_capture_browser_console_docstring():
    """Test that capture_browser_console has proper docstring."""
    from novacode_cli.tools import capture_browser_console
    
    assert capture_browser_console.__doc__ is not None
    assert "browser console" in capture_browser_console.__doc__.lower()
    assert "url" in capture_browser_console.__doc__.lower()
    assert "duration" in capture_browser_console.__doc__.lower()


@pytest.mark.asyncio
async def test_capture_browser_console_invalid_url():
    """Test capture with invalid URL."""
    from novacode_cli.tools import capture_browser_console
    
    result = capture_browser_console("not-a-valid-url", duration=1)
    
    # Should handle gracefully
    assert "success" in result
    assert result["success"] is False or "error" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])