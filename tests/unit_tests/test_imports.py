"""Test importing files."""



def test_imports() -> None:
    """Test importing deepagents modules."""
    from namicode_cli import (
        integrations,  # noqa: F401
    )
    from namicode_cli.main import cli_main  # noqa: F401
