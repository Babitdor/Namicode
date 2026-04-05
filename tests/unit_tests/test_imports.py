"""Test importing files."""



def test_imports() -> None:
    """Test importing deepagents modules."""
    from novacode_cli import (
        integrations,  # noqa: F401
    )
    from novacode_cli.main import cli_main  # noqa: F401
