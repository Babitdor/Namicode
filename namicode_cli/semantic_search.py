"""Semantic code search using embeddings.

This module provides embedding-based semantic search capabilities for
finding code by meaning rather than exact text match. Useful for
large codebases where grep/glob may miss relevant code.

Key Features:
- Natural language queries ("find authentication code")
- Semantic similarity matching
- Multi-language support
- Incremental indexing
- Persistent index storage

Dependencies:
- sentence-transformers: For embedding generation
- faiss-cpu or faiss-gpu: For efficient similarity search
- numpy: For embedding operations

Usage:
    from namicode_cli.semantic_search import SemanticCodeSearch

    search = SemanticCodeSearch()
    results = search.search("how is user authentication handled")
    for result in results:
        print(f"{result['file']}:{result['line']}: {result['snippet']}")
"""

import hashlib
import os
import pickle
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # Fast, good quality for code
INDEX_DIR = Path.home() / ".nami" / "semantic_index"
CHUNK_SIZE = 500  # Characters per chunk
CHUNK_OVERLAP = 100  # Overlap between chunks
MAX_FILE_SIZE = 500_000  # Skip files larger than this
SUPPORTED_EXTENSIONS = {
    # Python
    "py",
    "pyi",
    "pyx",
    "pyd",
    # JavaScript/TypeScript
    "js",
    "jsx",
    "ts",
    "tsx",
    "mjs",
    "cjs",
    # Web
    "html",
    "css",
    "scss",
    "sass",
    "less",
    "vue",
    "svelte",
    # Data/Config
    "json",
    "yaml",
    "yml",
    "toml",
    "xml",
    # Shell
    "sh",
    "bash",
    "zsh",
    "fish",
    # Systems
    "c",
    "cpp",
    "cc",
    "cxx",
    "h",
    "hpp",
    "rs",
    "go",
    # JVM
    "java",
    "kt",
    "kts",
    "scala",
    "groovy",
    # Other
    "md",
    "rst",
    "txt",
    "sql",
    "prisma",
    "graphql",
}

# Files/directories to skip
SKIP_PATTERNS = {
    "node_modules",
    "venv",
    ".venv",
    "__pycache__",
    ".git",
    ".hg",
    ".svn",
    "dist",
    "build",
    "*.egg-info",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".tox",
    "htmlcov",
    ".coverage",
}


@dataclass
class CodeChunk:
    """A chunk of code with metadata."""

    file_path: str
    start_line: int
    end_line: int
    content: str
    language: str
    file_hash: str
    function_name: str | None = None
    class_name: str | None = None
    docstring: str | None = None


@dataclass
class SearchResult:
    """A search result with similarity score."""

    file_path: str
    start_line: int
    end_line: int
    snippet: str
    score: float
    language: str
    function_name: str | None = None
    class_name: str | None = None


class SemanticCodeSearch:
    """Embedding-based semantic code search.

    This class provides semantic search capabilities using sentence embeddings.
    It indexes code files and allows natural language queries to find relevant
    code based on meaning, not just keywords.

    Example:
        >>> search = SemanticCodeSearch("/path/to/project")
        >>> results = search.search("how does user authentication work")
        >>> for r in results[:5]:
        ...     print(f"{r.file_path}:{r.start_line} (score: {r.score:.2f})")
        ...     print(r.snippet[:200])
    """

    def __init__(
        self,
        root_dir: str | Path = ".",
        index_dir: Path | None = None,
        embedding_model: str = EMBEDDING_MODEL,
    ):
        """Initialize semantic search.

        Args:
            root_dir: Root directory to index
            index_dir: Directory to store index files (default: ~/.nami/semantic_index)
            embedding_model: Name of sentence-transformers model to use
        """
        self.root_dir = Path(root_dir).resolve()
        self.index_dir = index_dir or INDEX_DIR
        self.embedding_model_name = embedding_model
        self.model = None
        self.index = None
        self.chunks: list[CodeChunk] = []

        # Create index directory
        self.index_dir.mkdir(parents=True, exist_ok=True)

        # Index file paths
        self._index_file = self.index_dir / f"index_{self._project_hash()}.pkl"
        self._embeddings_file = self.index_dir / f"embeddings_{self._project_hash()}.npy"

    def _project_hash(self) -> str:
        """Generate a unique hash for this project."""
        hash_input = str(self.root_dir)
        return hashlib.md5(hash_input.encode()).hexdigest()[:12]

    def _load_model(self):
        """Load the embedding model (lazy loading)."""
        if self.model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError:
                raise ImportError(
                    "sentence-transformers not installed.\n"
                    "Install with: pip install sentence-transformers\n"
                    "For faster performance, also install: pip install faiss-cpu"
                )
            self.model = SentenceTransformer(self.embedding_model_name)

    def _should_index(self, file_path: Path) -> bool:
        """Check if a file should be indexed."""
        # Check extension
        ext = file_path.suffix.lstrip(".").lower()
        if ext not in SUPPORTED_EXTENSIONS:
            return False

        # Check if in skip pattern
        path_str = str(file_path)
        for pattern in SKIP_PATTERNS:
            if pattern in path_str.split(os.sep):
                return False

        # Check file size
        try:
            if file_path.stat().st_size > MAX_FILE_SIZE:
                return False
        except OSError:
            return False

        return True

    def _detect_language(self, file_path: Path) -> str:
        """Detect programming language from file extension."""
        ext_to_lang = {
            "py": "python",
            "pyi": "python",
            "pyx": "python",
            "pyd": "python",
            "js": "javascript",
            "jsx": "javascript",
            "mjs": "javascript",
            "cjs": "javascript",
            "ts": "typescript",
            "tsx": "typescript",
            "html": "html",
            "css": "css",
            "scss": "scss",
            "sass": "sass",
            "json": "json",
            "yaml": "yaml",
            "yml": "yaml",
            "toml": "toml",
            "sh": "shell",
            "bash": "shell",
            "zsh": "shell",
            "c": "c",
            "cpp": "cpp",
            "cc": "cpp",
            "cxx": "cpp",
            "h": "c",
            "hpp": "cpp",
            "rs": "rust",
            "go": "go",
            "java": "java",
            "kt": "kotlin",
            "kts": "kotlin",
            "scala": "scala",
            "md": "markdown",
            "rst": "rst",
            "txt": "text",
            "sql": "sql",
            "prisma": "prisma",
            "graphql": "graphql",
        }
        return ext_to_lang.get(file_path.suffix.lstrip(".").lower(), "unknown")

    def _extract_code_structure(self, content: str, language: str) -> dict[str, Any]:
        """Extract function/class names and docstrings from code."""
        structure = {"functions": [], "classes": []}

        if language == "python":
            # Python function/class extraction
            func_pattern = (
                r'def\s+(\w+)\s*\([^)]*\):(?:\s*"""([^"]*)""")?(?:\s*\'\'\'([^\']*)\'\'\')?'
            )
            class_pattern = (
                r'class\s+(\w+)(?:\([^)]*\))?:\s*(?:"""([^"]*)""")?(?:\'\'\'([^\']*)\'\'\')?'
            )

            for match in re.finditer(func_pattern, content):
                structure["functions"].append(
                    {
                        "name": match.group(1),
                        "docstring": match.group(2) or match.group(3),
                    }
                )

            for match in re.finditer(class_pattern, content):
                structure["classes"].append(
                    {
                        "name": match.group(1),
                        "docstring": match.group(2) or match.group(3),
                    }
                )

        elif language in ("javascript", "typescript"):
            # JS/TS function/class extraction
            func_pattern = r"(?:async\s+)?function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:\([^)]*\)|[^=])\s*=>|(\w+)\s*\([^)]*\)\s*\{"
            class_pattern = r"class\s+(\w+)"

            for match in re.finditer(func_pattern, content):
                name = match.group(1) or match.group(2) or match.group(3)
                if name and not name.startswith(("if", "for", "while", "switch")):
                    structure["functions"].append({"name": name})

            for match in re.finditer(class_pattern, content):
                structure["classes"].append({"name": match.group(1)})

        return structure

    def _chunk_file(self, file_path: Path) -> list[CodeChunk]:
        """Split a file into chunks for embedding."""
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return []

        language = self._detect_language(file_path)
        structure = self._extract_code_structure(content, language)
        file_hash = hashlib.md5(content.encode()).hexdigest()[:8]

        # Split into chunks
        chunks = []
        lines = content.split("\n")
        current_chunk_lines = []
        current_start_line = 1
        line_idx = 0

        while line_idx < len(lines):
            line = lines[line_idx]
            current_chunk_lines.append(line)

            # Check if chunk is full
            chunk_content = "\n".join(current_chunk_lines)
            if len(chunk_content) >= CHUNK_SIZE:
                # Find function/class name for this chunk
                func_name = None
                class_name = None

                # Look for function/class in chunk
                for func in structure.get("functions", []):
                    if (
                        f"def {func['name']}" in chunk_content
                        or f"function {func['name']}" in chunk_content
                    ):
                        func_name = func["name"]
                        break

                for cls in structure.get("classes", []):
                    if f"class {cls['name']}" in chunk_content:
                        class_name = cls["name"]
                        break

                # Find docstring
                docstring = None
                for func in structure.get("functions", []):
                    doc_match = re.search(rf'def {func["name"]}[^"]*"""([^"]*)"""', chunk_content)
                    if doc_match:
                        docstring = doc_match.group(1)
                        break

                chunks.append(
                    CodeChunk(
                        file_path=str(file_path.relative_to(self.root_dir)),
                        start_line=current_start_line,
                        end_line=line_idx + 1,
                        content=chunk_content,
                        language=language,
                        file_hash=file_hash,
                        function_name=func_name,
                        class_name=class_name,
                        docstring=docstring,
                    )
                )

                # Start new chunk with overlap
                overlap_lines = current_chunk_lines[-(CHUNK_OVERLAP // 20) :]  # Approximate overlap
                current_chunk_lines = overlap_lines if overlap_lines else []
                current_start_line = line_idx - len(overlap_lines) + 2

            line_idx += 1

        # Add final chunk
        if current_chunk_lines:
            chunk_content = "\n".join(current_chunk_lines)
            chunks.append(
                CodeChunk(
                    file_path=str(file_path.relative_to(self.root_dir)),
                    start_line=current_start_line,
                    end_line=len(lines),
                    content=chunk_content,
                    language=language,
                    file_hash=file_hash,
                )
            )

        return chunks

    def index_files(self, force_reindex: bool = False) -> dict[str, Any]:
        """Index all code files in the project.

        Args:
            force_reindex: If True, rebuild index even if cached

        Returns:
            Dictionary with indexing statistics
        """
        # Check for cached index
        if not force_reindex and self._index_file.exists():
            try:
                with open(self._index_file, "rb") as f:
                    self.chunks = pickle.load(f)
                return {
                    "success": True,
                    "cached": True,
                    "chunks": len(self.chunks),
                    "files": len(set(c.file_path for c in self.chunks)),
                }
            except Exception:
                pass  # Rebuild if cached index is corrupted

        self._load_model()

        # Find all files to index
        all_files = []
        for ext in SUPPORTED_EXTENSIONS:
            all_files.extend(self.root_dir.glob(f"**/*.{ext}"))

        # Filter and index
        self.chunks = []
        indexed_files = 0

        for file_path in all_files:
            if self._should_index(file_path):
                file_chunks = self._chunk_file(file_path)
                self.chunks.extend(file_chunks)
                indexed_files += 1

        # Save index
        with open(self._index_file, "wb") as f:
            pickle.dump(self.chunks, f)

        return {
            "success": True,
            "cached": False,
            "chunks": len(self.chunks),
            "files": indexed_files,
        }

    def search(
        self,
        query: str,
        top_k: int = 10,
        language: str | None = None,
        file_pattern: str | None = None,
    ) -> list[SearchResult]:
        """Search for code using natural language query.

        Args:
            query: Natural language search query
            top_k: Maximum number of results to return
            language: Filter by programming language (optional)
            file_pattern: Filter by file path pattern (optional)

        Returns:
            List of search results sorted by relevance
        """
        self._load_model()

        # Index if not done
        if not self.chunks:
            self.index_files()

        if not self.chunks:
            return []

        # Filter chunks
        filtered_chunks = self.chunks
        if language:
            filtered_chunks = [c for c in filtered_chunks if c.language == language]
        if file_pattern:
            filtered_chunks = [c for c in filtered_chunks if file_pattern in c.file_path]

        if not filtered_chunks:
            return []

        # Generate query embedding
        query_embedding = self.model.encode(query, convert_to_numpy=True)

        # Encode all chunk content for semantic matching
        # For large codebases, consider using FAISS for efficiency
        try:
            import numpy as np

            # Try to use FAISS for faster search
            try:
                import faiss

                # Encode chunks
                chunk_texts = [c.content for c in filtered_chunks]
                chunk_embeddings = self.model.encode(
                    chunk_texts, convert_to_numpy=True, show_progress_bar=False
                )

                # Build FAISS index
                dimension = chunk_embeddings.shape[1]
                index = faiss.IndexFlatIP(dimension)  # Inner product for cosine similarity
                faiss.normalize_L2(chunk_embeddings)
                index.add(chunk_embeddings.astype("float32"))

                # Search
                faiss.normalize_L2(query_embedding.reshape(1, -1))
                scores, indices = index.search(
                    query_embedding.reshape(1, -1).astype("float32"),
                    min(top_k, len(filtered_chunks)),
                )

                results = []
                for score, idx in zip(scores[0], indices[0]):
                    if idx < len(filtered_chunks):  # Safety check
                        chunk = filtered_chunks[idx]
                        results.append(
                            SearchResult(
                                file_path=chunk.file_path,
                                start_line=chunk.start_line,
                                end_line=chunk.end_line,
                                snippet=chunk.content[:500]
                                + ("..." if len(chunk.content) > 500 else ""),
                                score=float(score),
                                language=chunk.language,
                                function_name=chunk.function_name,
                                class_name=chunk.class_name,
                            )
                        )
                return results

            except ImportError:
                # Fallback to numpy-based search (slower)
                chunk_texts = [c.content for c in filtered_chunks]
                chunk_embeddings = self.model.encode(
                    chunk_texts, convert_to_numpy=True, show_progress_bar=False
                )

                # Compute cosine similarity
                chunk_embeddings = chunk_embeddings / np.linalg.norm(
                    chunk_embeddings, axis=1, keepdims=True
                )
                query_embedding = query_embedding / np.linalg.norm(query_embedding)
                similarities = np.dot(chunk_embeddings, query_embedding)

                # Get top-k indices
                top_indices = np.argsort(similarities)[::-1][:top_k]

                results = []
                for idx in top_indices:
                    chunk = filtered_chunks[idx]
                    results.append(
                        SearchResult(
                            file_path=chunk.file_path,
                            start_line=chunk.start_line,
                            end_line=chunk.end_line,
                            snippet=chunk.content[:500]
                            + ("..." if len(chunk.content) > 500 else ""),
                            score=float(similarities[idx]),
                            language=chunk.language,
                            function_name=chunk.function_name,
                            class_name=chunk.class_name,
                        )
                    )
                return results

        except ImportError:
            raise ImportError(
                "numpy is required for semantic search.\n"
                "Install with: pip install numpy sentence-transformers"
            )

    def find_similar(
        self,
        code_snippet: str,
        top_k: int = 5,
        exclude_same_file: bool = True,
    ) -> list[SearchResult]:
        """Find code similar to a given snippet.

        Args:
            code_snippet: Code snippet to find similar code for
            top_k: Maximum number of results
            exclude_same_file: Exclude results from same file as snippet

        Returns:
            List of similar code chunks
        """
        results = self.search(code_snippet, top_k=top_k * 2)

        if exclude_same_file:
            # Try to detect file from snippet patterns
            # This is a heuristic - may not work for all cases
            results = [r for r in results if r.score < 0.99]  # Exclude exact matches

        return results[:top_k]

    def find_by_function(
        self,
        function_name: str,
        language: str | None = None,
    ) -> list[SearchResult]:
        """Find code by function name.

        Args:
            function_name: Name of function to find
            language: Filter by language (optional)

        Returns:
            List of results containing the function
        """
        if not self.chunks:
            self.index_files()

        results = []
        for chunk in self.chunks:
            if chunk.function_name == function_name:
                if language is None or chunk.language == language:
                    results.append(
                        SearchResult(
                            file_path=chunk.file_path,
                            start_line=chunk.start_line,
                            end_line=chunk.end_line,
                            snippet=chunk.content[:500],
                            score=1.0,
                            language=chunk.language,
                            function_name=chunk.function_name,
                            class_name=chunk.class_name,
                        )
                    )

        return results


# Tool function for agent use
def semantic_search(
    query: str,
    root_dir: str = ".",
    top_k: int = 10,
    language: str | None = None,
    file_pattern: str | None = None,
    force_reindex: bool = False,
) -> dict[str, Any]:
    """Search for code using natural language queries.

    This tool uses semantic embeddings to find relevant code based on meaning,
    not just keywords. Useful for finding implementations when you don't know
    the exact variable or function names.

    Args:
        query: Natural language search query (e.g., "authentication logic",
               "how is user data validated", "error handling for API calls")
        root_dir: Root directory to search (default: current directory)
        top_k: Maximum number of results (default: 10)
        language: Filter by language - "python", "javascript", "typescript", etc.
        file_pattern: Filter by file path pattern (e.g., "test_", "src/")
        force_reindex: Force rebuilding the index (default: False, uses cache)

    Returns:
        Dictionary containing:
        - success: Whether search succeeded
        - results: List of search results with file_path, line numbers, snippet, score
        - total_chunks: Total number of indexed code chunks
        - query: The original query

    Example:
        semantic_search("how is user authentication implemented")
        semantic_search("database connection pool", language="python")
        semantic_search("API rate limiting", file_pattern="src/", top_k=5)

    Note: Requires sentence-transformers package. Install with:
          pip install sentence-transformers faiss-cpu
    """
    try:
        searcher = SemanticCodeSearch(root_dir)

        # Index files
        index_result = searcher.index_files(force_reindex=force_reindex)
        if not index_result["success"]:
            return {
                "success": False,
                "error": "Failed to index codebase",
                "query": query,
            }

        # Search
        results = searcher.search(
            query,
            top_k=top_k,
            language=language,
            file_pattern=file_pattern,
        )

        # Format results
        formatted_results = []
        for r in results:
            formatted_results.append(
                {
                    "file_path": r.file_path,
                    "start_line": r.start_line,
                    "end_line": r.end_line,
                    "snippet": r.snippet,
                    "score": round(r.score, 3),
                    "language": r.language,
                    "function_name": r.function_name,
                    "class_name": r.class_name,
                }
            )

        return {
            "success": True,
            "query": query,
            "results": formatted_results,
            "total_chunks": len(searcher.chunks),
            "files_indexed": index_result.get("files", "unknown"),
        }

    except ImportError as e:
        return {
            "success": False,
            "error": str(e),
            "query": query,
            "hint": "Install required packages: pip install sentence-transformers faiss-cpu",
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Search failed: {e!s}",
            "query": query,
        }


def find_similar_code(
    code_snippet: str,
    root_dir: str = ".",
    top_k: int = 5,
) -> dict[str, Any]:
    """Find code similar to a given snippet.

    Useful for finding duplicate code, similar implementations, or
    related functionality across the codebase.

    Args:
        code_snippet: Code snippet to find similar code for
        root_dir: Root directory to search (default: current directory)
        top_k: Maximum number of results (default: 5)

    Returns:
        Dictionary with similar code chunks and similarity scores

    Example:
        find_similar_code('''
            def authenticate(user, password):
                if not user or not password:
                    return False
                return verify_password(user, password)
        ''')
    """
    try:
        searcher = SemanticCodeSearch(root_dir)
        searcher.index_files()

        results = searcher.find_similar(code_snippet, top_k=top_k)

        formatted_results = []
        for r in results:
            formatted_results.append(
                {
                    "file_path": r.file_path,
                    "start_line": r.start_line,
                    "end_line": r.end_line,
                    "snippet": r.snippet,
                    "score": round(r.score, 3),
                }
            )

        return {
            "success": True,
            "results": formatted_results,
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Find similar failed: {e!s}",
        }


def find_function(
    function_name: str,
    root_dir: str = ".",
    language: str | None = None,
) -> dict[str, Any]:
    """Find function definition by name.

    Searches indexed code for function definitions matching the given name.

    Args:
        function_name: Name of function to find
        root_dir: Root directory to search (default: current directory)
        language: Filter by language (optional)

    Returns:
        Dictionary with function locations and code snippets

    Example:
        find_function("authenticate", language="python")
        find_function("handleRequest")
    """
    try:
        searcher = SemanticCodeSearch(root_dir)
        searcher.index_files()

        results = searcher.find_by_function(function_name, language=language)

        formatted_results = []
        for r in results:
            formatted_results.append(
                {
                    "file_path": r.file_path,
                    "start_line": r.start_line,
                    "end_line": r.end_line,
                    "snippet": r.snippet,
                    "language": r.language,
                    "class_name": r.class_name,
                }
            )

        return {
            "success": True,
            "function_name": function_name,
            "results": formatted_results,
            "total_found": len(formatted_results),
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Find function failed: {e!s}",
            "function_name": function_name,
        }
