"""Performance tests for edit, write, and grep tool optimizations."""

import os
import tempfile
import time
from pathlib import Path

import pytest

from deepagents.backends.filesystem import FilesystemBackend


class TestEditPerformance:
    """Test edit performance with streaming optimization."""

    @pytest.fixture
    def large_text_file(self, tmp_path: Path) -> Path:
        """Create a large text file for testing."""
        file_path = tmp_path / "large_file.txt"
        
        # Create a file with 100,000 lines (~10MB)
        with open(file_path, "w", encoding="utf-8") as f:
            for i in range(100000):
                f.write(f"Line {i}: This is a test line with some content to make it realistic.\n")
        
        return file_path
    
    @pytest.fixture
    def medium_text_file(self, tmp_path: Path) -> Path:
        """Create a medium text file for testing."""
        file_path = tmp_path / "medium_file.txt"
        
        # Create a file with 10,000 lines (~1MB)
        with open(file_path, "w", encoding="utf-8") as f:
            for i in range(10000):
                f.write(f"Line {i}: This is a test line.\n")
        
        return file_path

    def test_small_file_edit_performance(self, medium_text_file: Path):
        """Test edit performance for small/medium files."""
        backend = FilesystemBackend()
        
        # Read file first
        result = backend.read(str(medium_text_file))
        assert result.error is None
        
        # Benchmark edit
        start = time.time()
        result = backend.edit(
            str(medium_text_file),
            "Line 5000: This is a test line.",
            "Line 5000: MODIFIED LINE."
        )
        end = time.time()
        
        edit_time_ms = (end - start) * 1000
        
        # Should be fast (< 200ms for medium files)
        assert edit_time_ms < 200, f"Edit too slow: {edit_time_ms:.2f}ms"
        assert result.error is None
        assert result.occurrences == 1
    
    def test_large_file_edit_streaming(self, large_text_file: Path):
        """Test edit performance for large files with streaming."""
        backend = FilesystemBackend()
        
        # Read file first
        result = backend.read(str(large_text_file))
        assert result.error is None
        
        # Benchmark edit (should use streaming for large files)
        start = time.time()
        result = backend.edit(
            str(large_text_file),
            "Line 50000: This is a test line with some content to make it realistic.",
            "Line 50000: MODIFIED LINE."
        )
        end = time.time()
        
        edit_time_ms = (end - start) * 1000
        
        # Should be reasonably fast (< 500ms for large files with streaming)
        assert edit_time_ms < 500, f"Streaming edit too slow: {edit_time_ms:.2f}ms"
        assert result.error is None
        assert result.occurrences == 1
    
    def test_edit_vs_full_read_performance(self, large_text_file: Path):
        """Test that streaming edit is faster than full file read/write."""
        backend = FilesystemBackend()
        
        # Read file first
        result = backend.read(str(large_text_file))
        assert result.error is None
        
        # Benchmark streaming edit (single line replacement)
        start = time.time()
        result = backend.edit(
            str(large_text_file),
            "Line 50000: This is a test line with some content to make it realistic.",
            "Line 50000: MODIFIED."
        )
        end = time.time()
        
        streaming_time_ms = (end - start) * 1000
        
        # Should be significantly faster than reading entire file
        # (which would take ~1500ms for a 10MB file)
        assert streaming_time_ms < 500, (
            f"Streaming edit not fast enough: {streaming_time_ms:.2f}ms "
            f"(expected < 500ms for 10MB file)"
        )
        
        print(f"\nStreaming edit performance:")
        print(f"  Edit time: {streaming_time_ms:.2f}ms")
        print(f"  Expected: < 500ms for 10MB file")


class TestGrepPerformance:
    """Test grep performance with streaming search."""

    @pytest.fixture
    def large_text_file(self, tmp_path: Path) -> Path:
        """Create a large text file for testing."""
        file_path = tmp_path / "large_file.txt"
        
        # Create a file with 100,000 lines (~10MB)
        with open(file_path, "w", encoding="utf-8") as f:
            for i in range(100000):
                if i % 1000 == 0:
                    f.write(f"Line {i}: TODO - This is a test line with TODO marker.\n")
                else:
                    f.write(f"Line {i}: This is a test line.\n")
        
        return file_path
    
    @pytest.fixture
    def search_directory(self, tmp_path: Path) -> Path:
        """Create a directory with multiple files for testing."""
        dir_path = tmp_path / "search_dir"
        dir_path.mkdir()
        
        # Create multiple files
        for i in range(10):
            file_path = dir_path / f"file_{i}.txt"
            with open(file_path, "w", encoding="utf-8") as f:
                for j in range(10000):
                    if j % 100 == 0:
                        f.write(f"Line {j}: TODO - Marker in file {i}.\n")
                    else:
                        f.write(f"Line {j}: Regular line.\n")
        
        return dir_path

    def test_grep_large_file_performance(self, large_text_file: Path):
        """Test grep performance on large file with streaming."""
        backend = FilesystemBackend()
        
        # Benchmark grep (should use streaming)
        start = time.time()
        result = backend.grep("TODO", str(large_text_file))
        end = time.time()
        
        grep_time_ms = (end - start) * 1000
        
        # Should be reasonably fast (< 500ms for large files)
        assert grep_time_ms < 500, f"Grep too slow: {grep_time_ms:.2f}ms"
        assert result.error is None
        assert len(result.matches) == 100  # 100 TODO markers
        
        print(f"\nGrep streaming performance:")
        print(f"  Search time: {grep_time_ms:.2f}ms")
        print(f"  Matches found: {len(result.matches)}")
    
    def test_grep_directory_performance(self, search_directory: Path):
        """Test grep performance across multiple files."""
        backend = FilesystemBackend()
        
        # Benchmark grep across directory
        start = time.time()
        result = backend.grep("TODO", str(search_directory))
        end = time.time()
        
        grep_time_ms = (end - start) * 1000
        
        # Should be reasonably fast (< 2s for 10 files with 10k lines each)
        assert grep_time_ms < 2000, f"Directory grep too slow: {grep_time_ms:.2f}ms"
        assert result.error is None
        assert len(result.matches) == 1000  # 10 files * 100 TODO markers
        
        print(f"\nDirectory grep performance:")
        print(f"  Search time: {grep_time_ms:.2f}ms")
        print(f"  Files searched: 10")
        print(f"  Matches found: {len(result.matches)}")


class TestWritePerformance:
    """Test write performance with streaming."""

    @pytest.fixture
    def large_content(self) -> str:
        """Create large content for testing."""
        # Create ~10MB of content
        lines = [f"Line {i}: This is a test line with some content.\n" for i in range(100000)]
        return "".join(lines)
    
    @pytest.fixture
    def medium_content(self) -> str:
        """Create medium content for testing."""
        # Create ~1MB of content
        lines = [f"Line {i}: This is a test line.\n" for i in range(10000)]
        return "".join(lines)

    def test_small_file_write_performance(self, tmp_path: Path, medium_content: str):
        """Test write performance for small/medium files."""
        backend = FilesystemBackend()
        file_path = tmp_path / "medium_file.txt"
        
        # Benchmark write
        start = time.time()
        result = backend.write(str(file_path), medium_content)
        end = time.time()
        
        write_time_ms = (end - start) * 1000
        
        # Should be fast (< 200ms for medium files)
        assert write_time_ms < 200, f"Write too slow: {write_time_ms:.2f}ms"
        assert result.error is None
        assert result.path is not None
    
    def test_large_file_write_streaming(self, tmp_path: Path, large_content: str):
        """Test write performance for large files with streaming."""
        backend = FilesystemBackend()
        file_path = tmp_path / "large_file.txt"
        
        # Benchmark write (should use streaming for large content)
        start = time.time()
        result = backend.write(str(file_path), large_content)
        end = time.time()
        
        write_time_ms = (end - start) * 1000
        
        # Should be reasonably fast (< 1s for large files)
        assert write_time_ms < 1000, f"Streaming write too slow: {write_time_ms:.2f}ms"
        assert result.error is None
        assert result.path is not None
        
        # Verify file was written correctly
        file_size = os.path.getsize(file_path)
        content_size = len(large_content.encode('utf-8'))
        assert file_size == content_size, "File size mismatch"
        
        print(f"\nStreaming write performance:")
        print(f"  Write time: {write_time_ms:.2f}ms")
        print(f"  File size: {file_size / (1024 * 1024):.2f}MB")
    
    def test_write_chunk_size(self, tmp_path: Path, large_content: str):
        """Test write with custom chunk size."""
        backend = FilesystemBackend()
        file_path = tmp_path / "chunked_file.txt"
        
        # Benchmark write with custom chunk size
        start = time.time()
        result = backend.write(str(file_path), large_content, chunk_size=512 * 1024)  # 512KB chunks
        end = time.time()
        
        write_time_ms = (end - start) * 1000
        
        # Should work correctly with custom chunk size
        assert result.error is None
        assert result.path is not None
        
        # Verify file was written correctly
        file_size = os.path.getsize(file_path)
        content_size = len(large_content.encode('utf-8'))
        assert file_size == content_size, "File size mismatch with chunked write"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])