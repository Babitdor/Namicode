"""Performance tests for read_file optimization.

Tests the lazy line reading optimization to ensure it provides
significant performance improvements for paginated reads.
"""

import os
import tempfile
import time
from pathlib import Path

import pytest

from deepagents.backends.filesystem import FilesystemBackend
from deepagents.backends.state import StateBackend


class TestReadPerformance:
    """Test read performance with lazy line reading."""

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
                f.write(f"Line {i}: This is a test line with some content.\n")
        
        return file_path
    
    @pytest.fixture
    def small_text_file(self, tmp_path: Path) -> Path:
        """Create a small text file for testing."""
        file_path = tmp_path / "small_file.txt"
        
        # Create a file with 100 lines (~10KB)
        with open(file_path, "w", encoding="utf-8") as f:
            for i in range(100):
                f.write(f"Line {i}: This is a test line.\n")
        
        return file_path
    
    @pytest.fixture
    def binary_file(self, tmp_path: Path) -> Path:
        """Create a binary file for testing."""
        file_path = tmp_path / "binary_file.bin"
        
        # Create a 5MB binary file
        with open(file_path, "wb") as f:
            f.write(os.urandom(5 * 1024 * 1024))
        
        return file_path

    def test_small_file_read_performance(self, small_text_file: Path):
        """Test read performance for small files (< 100KB)."""
        backend = FilesystemBackend()
        
        # Warm up
        result = backend.read(str(small_text_file), offset=0, limit=100)
        assert result.error is None
        
        # Benchmark
        start = time.time()
        for _ in range(10):
            result = backend.read(str(small_text_file), offset=0, limit=100)
        end = time.time()
        
        avg_time_ms = (end - start) * 1000 / 10
        
        # Should be fast (< 50ms for small files)
        assert avg_time_ms < 50, f"Small file read too slow: {avg_time_ms:.2f}ms"
        assert result.error is None
        assert "Line 0" in result.file_data["content"]
    
    def test_medium_file_read_performance(self, medium_text_file: Path):
        """Test read performance for medium files (100KB - 1MB)."""
        backend = FilesystemBackend()
        
        # Warm up
        result = backend.read(str(medium_text_file), offset=0, limit=100)
        assert result.error is None
        
        # Benchmark full file read
        start = time.time()
        result = backend.read(str(medium_text_file), offset=0, limit=10000)
        end = time.time()
        
        full_read_time_ms = (end - start) * 1000
        
        # Should be reasonably fast (< 200ms for medium files)
        assert full_read_time_ms < 200, f"Medium file full read too slow: {full_read_time_ms:.2f}ms"
        assert result.error is None
        
        # Benchmark paginated read (should be much faster)
        start = time.time()
        result = backend.read(str(medium_text_file), offset=5000, limit=100)
        end = time.time()
        
        paginated_time_ms = (end - start) * 1000
        
        # Paginated read should be at least 2x faster than full read
        assert paginated_time_ms < full_read_time_ms / 2, (
            f"Paginated read not faster: {paginated_time_ms:.2f}ms vs {full_read_time_ms:.2f}ms"
        )
        assert result.error is None
        assert "Line 5000" in result.file_data["content"]
    
    def test_large_file_pagination_performance(self, large_text_file: Path):
        """Test read performance for large files with pagination."""
        backend = FilesystemBackend()
        
        # Benchmark reading from beginning
        start = time.time()
        result = backend.read(str(large_text_file), offset=0, limit=100)
        end = time.time()
        
        beginning_time_ms = (end - start) * 1000
        
        # Should be fast even for large files (< 100ms for first 100 lines)
        assert beginning_time_ms < 100, f"Beginning read too slow: {beginning_time_ms:.2f}ms"
        assert result.error is None
        assert "Line 0" in result.file_data["content"]
        
        # Benchmark reading from middle
        start = time.time()
        result = backend.read(str(large_text_file), offset=50000, limit=100)
        end = time.time()
        
        middle_time_ms = (end - start) * 1000
        
        # Middle read should also be fast (< 200ms)
        assert middle_time_ms < 200, f"Middle read too slow: {middle_time_ms:.2f}ms"
        assert result.error is None
        assert "Line 50000" in result.file_data["content"]
        
        # Benchmark reading from end
        start = time.time()
        result = backend.read(str(large_text_file), offset=99900, limit=100)
        end = time.time()
        
        end_time_ms = (end - start) * 1000
        
        # End read should also be reasonably fast (< 500ms)
        assert end_time_ms < 500, f"End read too slow: {end_time_ms:.2f}ms"
        assert result.error is None
        assert "Line 99900" in result.file_data["content"]
    
    def test_pagination_vs_full_read_performance(self, large_text_file: Path):
        """Test that pagination is significantly faster than full file read."""
        backend = FilesystemBackend()
        
        # Benchmark full file read (all 100,000 lines)
        start = time.time()
        result = backend.read(str(large_text_file), offset=0, limit=100000)
        end = time.time()
        
        full_read_time_ms = (end - start) * 1000
        
        # Full read should work but may be slow
        assert result.error is None
        
        # Benchmark paginated read (only 100 lines from middle)
        start = time.time()
        result = backend.read(str(large_text_file), offset=50000, limit=100)
        end = time.time()
        
        paginated_time_ms = (end - start) * 1000
        
        # Paginated read should be at least 10x faster than full read
        # (ideally 100x faster with lazy line reading)
        speedup = full_read_time_ms / paginated_time_ms
        assert speedup > 10, (
            f"Pagination not fast enough: {paginated_time_ms:.2f}ms vs {full_read_time_ms:.2f}ms "
            f"(speedup: {speedup:.1f}x, expected > 10x)"
        )
        
        print(f"\nPerformance improvement:")
        print(f"  Full read: {full_read_time_ms:.2f}ms")
        print(f"  Paginated read: {paginated_time_ms:.2f}ms")
        print(f"  Speedup: {speedup:.1f}x")
    
    def test_binary_file_read_performance(self, binary_file: Path):
        """Test read performance for binary files."""
        backend = FilesystemBackend()
        
        # Benchmark reading entire binary file
        start = time.time()
        result = backend.read(str(binary_file), offset=0, limit=5 * 1024 * 1024)
        end = time.time()
        
        full_read_time_ms = (end - start) * 1000
        
        # Should be reasonably fast (< 500ms for 5MB)
        assert full_read_time_ms < 500, f"Binary file read too slow: {full_read_time_ms:.2f}ms"
        assert result.error is None
        assert result.file_data["encoding"] == "base64"
        
        # Benchmark reading partial binary file
        start = time.time()
        result = backend.read(str(binary_file), offset=0, limit=1024)
        end = time.time()
        
        partial_read_time_ms = (end - start) * 1000
        
        # Partial read should be faster
        assert partial_read_time_ms < full_read_time_ms, (
            f"Partial read not faster: {partial_read_time_ms:.2f}ms vs {full_read_time_ms:.2f}ms"
        )
        assert result.error is None
    
    def test_memory_efficiency(self, large_text_file: Path):
        """Test that pagination uses less memory than full file read."""
        import tracemalloc
        
        backend = FilesystemBackend()
        
        # Measure memory for full file read
        tracemalloc.start()
        result = backend.read(str(large_text_file), offset=0, limit=100000)
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        
        full_read_memory_kb = peak / 1024
        
        # Measure memory for paginated read
        tracemalloc.start()
        result = backend.read(str(large_text_file), offset=50000, limit=100)
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        
        paginated_memory_kb = peak / 1024
        
        # Paginated read should use significantly less memory
        memory_reduction = full_read_memory_kb / paginated_memory_kb
        assert memory_reduction > 5, (
            f"Memory reduction not enough: {paginated_memory_kb:.2f}KB vs {full_read_memory_kb:.2f}KB "
            f"(reduction: {memory_reduction:.1f}x, expected > 5x)"
        )
        
        print(f"\nMemory efficiency:")
        print(f"  Full read: {full_read_memory_kb:.2f}KB")
        print(f"  Paginated read: {paginated_memory_kb:.2f}KB")
        print(f"  Memory reduction: {memory_reduction:.1f}x")
    
    def test_state_backend_pagination(self):
        """Test that StateBackend also benefits from pagination optimization."""
        # This test verifies that slice_read_response is efficient
        from deepagents.backends.utils import slice_read_response
        from deepagents.backends.protocol import FileData
        
        # Create a large content string
        lines = [f"Line {i}: This is a test line with some content.\n" for i in range(10000)]
        content = "".join(lines)
        file_data = FileData(content=content, encoding="utf-8")
        
        # Benchmark full content slice
        start = time.time()
        result = slice_read_response(file_data, offset=0, limit=10000)
        end = time.time()
        
        full_slice_time_ms = (end - start) * 1000
        
        # Should be a string, not ReadResult
        assert isinstance(result, str)
        
        # Benchmark paginated slice
        start = time.time()
        result = slice_read_response(file_data, offset=5000, limit=100)
        end = time.time()
        
        paginated_slice_time_ms = (end - start) * 1000
        
        # Paginated slice should be faster
        assert paginated_slice_time_ms < full_slice_time_ms, (
            f"Paginated slice not faster: {paginated_slice_time_ms:.2f}ms vs {full_slice_time_ms:.2f}ms"
        )
        
        print(f"\nStateBackend slice performance:")
        print(f"  Full slice: {full_slice_time_ms:.2f}ms")
        print(f"  Paginated slice: {paginated_slice_time_ms:.2f}ms")
        print(f"  Speedup: {full_slice_time_ms / paginated_slice_time_ms:.1f}x")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])