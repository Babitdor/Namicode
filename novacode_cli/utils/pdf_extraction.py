"""PDF text extraction utility for converting PDF content blocks to text.

When the read_file tool encounters a PDF, it returns a ToolMessage with a
content block of type "file" containing base64-encoded PDF data. Most LLM
backends (especially Ollama) don't support "file" type content blocks, so
we intercept these and extract the text content instead.
"""

import base64
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Maximum characters per extracted page (prevents runaway extraction on
# PDFs with very dense text like research papers)
_MAX_CHARS_PER_PAGE = 50_000

# Maximum total characters across all pages
_MAX_TOTAL_CHARS = 500_000


def extract_text_from_base64_pdf(b64_data: str) -> str | None:
    """Extract text from a base64-encoded PDF.

    Args:
        b64_data: Base64-encoded PDF content.

    Returns:
        Extracted text content, or None if extraction failed.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.warning("PyMuPDF (fitz) not installed — cannot extract PDF text")
        return None

    try:
        pdf_bytes = base64.b64decode(b64_data)
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        logger.error(f"Failed to open PDF: {e}")
        return None

    try:
        pages_text: list[str] = []
        total_chars = 0

        for page_num in range(len(doc)):
            page = doc[page_num]
            page_text = page.get_text("text")
            if len(page_text) > _MAX_CHARS_PER_PAGE:
                page_text = page_text[:_MAX_CHARS_PER_PAGE] + "\n... [page text truncated]"
            pages_text.append(f"--- Page {page_num + 1} ---\n{page_text}")
            total_chars += len(page_text)
            if total_chars >= _MAX_TOTAL_CHARS:
                pages_text.append("\n... [remaining pages truncated]")
                break

        full_text = "\n\n".join(pages_text)
        if not full_text.strip():
            return None
        return full_text
    except Exception as e:
        logger.error(f"Failed to extract text from PDF: {e}")
        return None
    finally:
        doc.close()


def convert_file_content_block_to_text(
    content: list[str | dict[str, Any]],
) -> list[str | dict[str, Any]]:
    """Convert 'file' type content blocks (PDFs) in a ToolMessage content list to text.

    For each content block with type "file" and mime_type "application/pdf",
    the base64 data is decoded and text is extracted using PyMuPDF. The block
    is replaced with a text block containing the extracted text.

    Args:
        content: The content list from a ToolMessage (list of str/dict).

    Returns:
        Modified content list with PDF file blocks replaced by text blocks.
    """
    if not isinstance(content, list):
        return content

    new_content: list[str | dict[str, Any]] = []
    has_file_block = False

    for block in content:
        if isinstance(block, dict) and block.get("type") == "file":
            mime_type = block.get("mime_type", "")
            b64_data = block.get("base64", "")

            if mime_type == "application/pdf" and b64_data:
                has_file_block = True
                text = extract_text_from_base64_pdf(b64_data)
                if text:
                    new_content.append({
                        "type": "text",
                        "text": f"[PDF content extracted as text]\n\n{text}",
                    })
                else:
                    new_content.append({
                        "type": "text",
                        "text": "[PDF file could not be read — text extraction failed. "
                                "Install PyMuPDF (pip install PyMuPDF) for PDF support.]",
                    })
            else:
                # Non-PDF file block — convert to a descriptive text block
                has_file_block = True
                new_content.append({
                    "type": "text",
                    "text": f"[Unsupported file type: {mime_type}. "
                            f"Only PDF text extraction is currently supported.]",
                })
        else:
            new_content.append(block)

    return new_content if has_file_block else content


def sanitize_messages_file_blocks(messages: list) -> list:
    """Scan a list of messages for ToolMessages with file-type content blocks.

    This is a safety net for messages that might contain file-type content blocks
    (e.g., from restored session history) that weren't converted at the tool-call
    layer. Converts any file blocks to text blocks so they don't crash backends
    like Ollama.

    Args:
        messages: List of BaseMessage instances.

    Returns:
        The same list (possibly modified in-place) with file blocks converted.
        Returns the original list unchanged if no file blocks were found.
    """
    from langchain_core.messages import ToolMessage

    modified = False
    for i, msg in enumerate(messages):
        if not isinstance(msg, ToolMessage):
            continue
        content = msg.content
        if not isinstance(content, list):
            continue
        # Check if any block has type "file"
        if not any(isinstance(b, dict) and b.get("type") == "file" for b in content):
            continue
        # Convert file blocks to text
        converted = convert_file_content_block_to_text(content)
        if converted is not content:
            messages[i] = ToolMessage(
                content=converted,
                tool_call_id=msg.tool_call_id,
                name=msg.name if hasattr(msg, "name") else None,
            )
            modified = True

    return messages