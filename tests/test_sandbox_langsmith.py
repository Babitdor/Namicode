"""Tests for the LangSmith sandbox backend integration."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from novacode_cli.integrations.sandbox_factory import (
    _PROVIDER_TO_WORKING_DIR,
    _SANDBOX_PROVIDERS,
    get_available_sandbox_types,
)


class TestProviderRegistration:
    """Verify provider is registered in all required maps."""

    def test_provider_in_providers_map(self):
        assert "langsmith" in _SANDBOX_PROVIDERS

    def test_provider_in_working_dir_map(self):
        assert "langsmith" in _PROVIDER_TO_WORKING_DIR
        assert _PROVIDER_TO_WORKING_DIR["langsmith"] == "/home/user"

    def test_available_types_includes_langsmith(self):
        types = get_available_sandbox_types()
        assert "langsmith" in types


class TestLangSmithBackendExecute:
    """Tests for LangSmithBackend.execute()."""

    @pytest.fixture
    def mock_sandbox(self):
        """Create a mock LangSmith Sandbox with a simple run()."""
        sb = MagicMock()
        sb.name = "test-langsmith-box"
        sb.id = "550e8400-e29b-41d4-a716-446655440000"
        return sb

    @pytest.fixture
    def backend(self, mock_sandbox):
        from novacode_cli.integrations.langsmith import LangSmithBackend

        return LangSmithBackend(mock_sandbox)

    def test_id_uses_name(self, backend, mock_sandbox):
        assert backend.id == mock_sandbox.name

    def test_execute_returns_combined_output(self, backend, mock_sandbox):
        # Configure the mock to return an ExecutionResult-like object
        result = MagicMock()
        result.stdout = "hello world\n"
        result.stderr = ""
        result.exit_code = 0
        mock_sandbox.run.return_value = result

        response = backend.execute("echo hello world")

        mock_sandbox.run.assert_called_once_with(
            "echo hello world",
            timeout=backend._timeout,
            shell="/bin/bash",
        )
        assert response.output == "hello world\n"
        assert response.exit_code == 0
        assert response.truncated is False

    def test_execute_combines_stderr(self, backend, mock_sandbox):
        result = MagicMock()
        result.stdout = "stdout line\n"
        result.stderr = "stderr line\n"
        result.exit_code = 1
        mock_sandbox.run.return_value = result

        response = backend.execute("failing_command")

        assert "stdout line" in response.output
        assert "stderr line" in response.output
        assert response.exit_code == 1

    def test_execute_with_only_stderr(self, backend, mock_sandbox):
        result = MagicMock()
        result.stdout = None
        result.stderr = "error occurred\n"
        result.exit_code = 2
        mock_sandbox.run.return_value = result

        response = backend.execute("bad_command")

        assert response.output == "error occurred\n"
        assert response.exit_code == 2


class TestLangSmithBackendFileOps:
    """Tests for LangSmithBackend file operations."""

    @pytest.fixture
    def mock_sandbox(self):
        sb = MagicMock()
        sb.name = "file-test-box"
        return sb

    @pytest.fixture
    def backend(self, mock_sandbox):
        from novacode_cli.integrations.langsmith import LangSmithBackend

        return LangSmithBackend(mock_sandbox)

    def test_download_files_success(self, backend, mock_sandbox):
        mock_sandbox.read.side_effect = [b"content1", b"content2"]

        responses = backend.download_files(["/app/file1.txt", "/home/user/file2.py"])

        assert len(responses) == 2
        assert responses[0].path == "/app/file1.txt"
        assert responses[0].content == b"content1"
        assert responses[0].error is None
        assert responses[1].path == "/home/user/file2.py"
        assert responses[1].content == b"content2"
        assert responses[1].error is None
        assert mock_sandbox.read.call_count == 2

    def test_download_files_partial_failure(self, backend, mock_sandbox):
        mock_sandbox.read.side_effect = [b"ok", Exception("not found")]

        responses = backend.download_files(["/ok.txt", "/missing.txt"])

        assert len(responses) == 2
        assert responses[0].error is None
        assert responses[0].content == b"ok"
        assert responses[1].content == b""
        assert responses[1].error is not None
        assert "not found" in responses[1].error

    def test_upload_files_success(self, backend, mock_sandbox):
        files = [("/app/script.py", b"print('hello')"), ("/data/file.csv", b"a,b,c\n1,2,3")]

        responses = backend.upload_files(files)

        assert len(responses) == 2
        assert responses[0].path == "/app/script.py"
        assert responses[0].error is None
        assert responses[1].path == "/data/file.csv"
        assert responses[1].error is None
        assert mock_sandbox.write.call_count == 2
        mock_sandbox.write.assert_any_call("/app/script.py", b"print('hello')")
        mock_sandbox.write.assert_any_call("/data/file.csv", b"a,b,c\n1,2,3")

    def test_upload_files_partial_failure(self, backend, mock_sandbox):
        mock_sandbox.write.side_effect = [None, Exception("disk full")]

        responses = backend.upload_files([("/ok.txt", b"data"), ("/fail.txt", b"data2")])

        assert len(responses) == 2
        assert responses[0].error is None
        assert responses[1].path == "/fail.txt"
        assert responses[1].error is not None
        assert "disk full" in responses[1].error


class TestLangSmithFactory:
    """Tests for the LangSmith sandbox factory."""

    def test_factory_raises_without_api_key(self):
        """create_langsmith_sandbox should raise ValueError when no API key."""
        from novacode_cli.integrations.sandbox_factory import create_langsmith_sandbox

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="LANGSMITH_API_KEY"):
                with create_langsmith_sandbox():
                    pass

    @patch.dict(os.environ, {"LANGSMITH_API_KEY": "test-key-123"}, clear=True)
    @patch("langsmith.sandbox.SandboxClient")
    def test_factory_creates_sandbox(self, mock_client_cls):
        """Verify factory calls create_sandbox and returns a backend."""
        from novacode_cli.integrations.sandbox_factory import create_langsmith_sandbox

        # Mock the SandboxClient
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        # Mock the sandbox returned by create_sandbox
        mock_sb = MagicMock()
        mock_sb.name = "ls-sandbox-abc"
        mock_sb.status = "ready"
        mock_client.create_sandbox.return_value = mock_sb

        with create_langsmith_sandbox() as backend:
            assert backend is not None
            assert backend.id == "ls-sandbox-abc"

        # After the context manager exits, sandbox.delete() should be called
        mock_sb.delete.assert_called_once()
        mock_client.create_sandbox.assert_called_once_with(
            timeout=120, idle_ttl_seconds=0
        )

    @patch.dict(os.environ, {"LANGSMITH_API_KEY": "test-key-123"}, clear=True)
    @patch("langsmith.sandbox.SandboxClient")
    def test_factory_reuses_existing_sandbox(self, mock_client_cls):
        """Verify factory can reconnect to an existing sandbox by name."""
        from novacode_cli.integrations.sandbox_factory import create_langsmith_sandbox

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_sb = MagicMock()
        mock_sb.name = "existing-box"
        mock_sb.status = "ready"
        mock_client.get_sandbox.return_value = mock_sb

        with create_langsmith_sandbox(sandbox_id="existing-box") as backend:
            assert backend.id == "existing-box"

        mock_client.get_sandbox.assert_called_once_with("existing-box")
        # Should NOT have called create_sandbox since we reused
        mock_client.create_sandbox.assert_not_called()
        # Cleanup still deletes on exit
        mock_sb.delete.assert_called_once()


class TestRegistryTermination:
    """Tests for LangSmith termination in the sandbox registry."""

    def test_terminate_record_for_langsmith(self):
        """Verify _terminate_record handles langsmith provider."""
        from novacode_cli.integrations.sandbox_registry import _terminate_record

        record = {
            "sandbox_id": "ls-sandbox-xyz",
            "provider": "langsmith",
            "session_id": "test-session",
            "pid": 99999,
        }

        with patch.dict(os.environ, {"LANGSMITH_API_KEY": "test-key"}, clear=True):
            with patch(
                "langsmith.sandbox.SandboxClient"
            ) as mock_cls:
                mock_client = MagicMock()
                mock_cls.return_value = mock_client
                mock_sb = MagicMock()
                mock_client.get_sandbox.return_value = mock_sb

                result = _terminate_record(record)

                assert result is True
                mock_client.get_sandbox.assert_called_once_with("ls-sandbox-xyz")
                mock_sb.delete.assert_called_once()

    def test_terminate_record_no_api_key(self):
        """Should return False when API key is missing."""
        from novacode_cli.integrations.sandbox_registry import _terminate_record

        record = {
            "sandbox_id": "ls-sandbox-xyz",
            "provider": "langsmith",
            "session_id": "test-session",
            "pid": 99999,
        }

        with patch.dict(os.environ, {}, clear=True):
            result = _terminate_record(record)
            assert result is False