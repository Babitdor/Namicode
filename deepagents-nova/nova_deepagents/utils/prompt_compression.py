"""System prompt compression for context optimization."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool


class PromptCompressor:
    """Compresses system prompts and tool descriptions to reduce token usage.
    
    This utility uses various techniques to reduce the length of prompts while
    preserving their semantic meaning:
    
    1. Remove redundant phrases
    2. Use abbreviations for common terms
    3. Condense whitespace
    4. Remove unnecessary examples
    5. Simplify complex sentences
    
    Example:
        ```python
        from nova_deepagents.utils.prompt_compression import PromptCompressor
        
        compressor = PromptCompressor()
        
        # Compress a system prompt
        original = "You are a helpful AI assistant that can help users with various tasks."
        compressed = compressor.compress_prompt(original)
        # Result: "You are a helpful AI assistant."
        
        # Compress a tool description
        tool_desc = "This tool allows you to read files from the filesystem..."
        compressed_desc = compressor.compress_tool_description(tool_desc)
        ```
    """
    
    # Common abbreviations
    ABBREVIATIONS = {
        'information': 'info',
        'configuration': 'config',
        'specification': 'spec',
        'documentation': 'docs',
        'application': 'app',
        'environment': 'env',
        'parameter': 'param',
        'argument': 'arg',
        'function': 'func',
        'variable': 'var',
        'implementation': 'impl',
        'development': 'dev',
        'production': 'prod',
        'repository': 'repo',
        'directory': 'dir',
        'database': 'db',
        'identifier': 'id',
        'number': 'num',
        'string': 'str',
        'integer': 'int',
        'boolean': 'bool',
        'character': 'char',
        'expression': 'expr',
        'statement': 'stmt',
        'reference': 'ref',
        'value': 'val',
        'result': 'res',
        'response': 'resp',
        'request': 'req',
        'message': 'msg',
        'error': 'err',
        'exception': 'exc',
        'component': 'comp',
        'module': 'mod',
        'package': 'pkg',
        'library': 'lib',
        'framework': 'fw',
        'interface': 'iface',
        'abstract': 'abs',
        'implementation': 'impl',
        'initialize': 'init',
        'synchronize': 'sync',
        'asynchronous': 'async',
        'synchronous': 'sync',
    }
    
    # Redundant phrases to remove
    REDUNDANT_PHRASES = [
        r'\b(?:please\s+)?note\s+that\b',
        r'\b(?:it\s+)?(?:is|are)\s+(?:important|worth|useful)\s+to\s+(?:note|mention|remember)\b',
        r'\b(?:as\s+)?(?:mentioned|stated|noted)\s+(?:above|earlier|before)\b',
        r'\b(?:in\s+)?(?:order|an\s+effort)\s+to\b',
        r'\b(?:for\s+)?(?:the\s+)?(?:purpose|reason)\s+of\b',
        r'\b(?:it|this)\s+(?:is|should\s+be)\s+(?:noted|mentioned|noted)\s+that\b',
        r'\b(?:you\s+can|one\s+can)\s+(?:use|utilize|employ)\b',
        r'\b(?:in\s+)?(?:the\s+)?(?:following|below)\s+(?:manner|way|fashion)\b',
        r'\b(?:as\s+)?(?:follows|below)\s*:',
        r'\b(?:this|the)\s+(?:tool|function|method|feature)\s+(?:allows|enables|permits)\s+(?:you|users)\s+to\b',
        r'\b(?:it|this)\s+(?:is|will\s+be)\s+(?:helpful|useful|beneficial)\s+(?:for|to)\b',
        r'\b(?:make\s+sure|ensure)\s+(?:that\s+)?you\b',
        r'\b(?:keep\s+in\s+mind|remember)\s+that\b',
    ]
    
    # Phrases to simplify
    SIMPLIFICATIONS = {
        r'\b(?:in\s+order\s+to|so\s+as\s+to)\b': 'to',
        r'\b(?:due\s+to\s+the\s+fact\s+that|owing\s+to\s+the\s+fact\s+that)\b': 'because',
        r'\b(?:in\s+the\s+event\s+that|in\s+case)\b': 'if',
        r'\b(?:at\s+this\s+point\s+in\s+time|at\s+present)\b': 'now',
        r'\b(?:in\s+the\s+near\s+future|shortly)\b': 'soon',
        r'\b(?:for\s+the\s+purpose\s+of|with\s+the\s+intention\s+of)\b': 'to',
        r'\b(?:with\s+regard\s+to|in\s+relation\s+to|with\s+respect\s+to)\b': 'about',
        r'\b(?:in\s+spite\s+of\s+the\s+fact\s+that|despite\s+the\s+fact\s+that)\b': 'although',
        r'\b(?:on\s+the\s+grounds\s+that|for\s+the\s+reason\s+that)\b': 'because',
        r'\b(?:in\s+the\s+course\s+of|during\s+the\s+course\s+of)\b': 'during',
        r'\b(?:a\s+large\s+number\s+of|a\s+great\s+many)\b': 'many',
        r'\b(?:a\s+small\s+number\s+of|a\s+few)\b': 'few',
        r'\b(?:the\s+majority\s+of|most\s+of)\b': 'most',
        r'\b(?:the\s+fact\s+that)\b': 'that',
        r'\b(?:it\s+is\s+essential\s+that|it\s+is\s+necessary\s+that)\b': 'must',
        r'\b(?:it\s+is\s+possible\s+that|there\s+is\s+a\s+chance\s+that)\b': 'might',
        r'\b(?:has\s+the\s+ability\s+to|is\s+able\s+to)\b': 'can',
        r'\b(?:has\s+the\s+potential\s+to|has\s+the\s+capacity\s+to)\b': 'can',
    }
    
    @classmethod
    def compress_prompt(cls, prompt: str, compression_level: str = 'medium') -> str:
        """Compress a system prompt to reduce token usage.
        
        Args:
            prompt: The system prompt to compress
            compression_level: Compression level ('light', 'medium', 'aggressive')
            
        Returns:
            Compressed prompt
        """
        if not prompt:
            return prompt
        
        compressed = prompt
        
        # Apply compression based on level
        if compression_level in ('medium', 'aggressive'):
            # Remove redundant phrases
            for pattern in cls.REDUNDANT_PHRASES:
                compressed = re.sub(pattern, '', compressed, flags=re.IGNORECASE)
            
            # Apply simplifications
            for pattern, replacement in cls.SIMPLIFICATIONS.items():
                compressed = re.sub(pattern, replacement, compressed, flags=re.IGNORECASE)
        
        if compression_level == 'aggressive':
            # Apply abbreviations
            for full, abbr in cls.ABBREVIATIONS.items():
                # Only abbreviate if word appears multiple times
                if compressed.lower().count(full) > 1:
                    compressed = re.sub(
                        r'\b' + full + r'\b',
                        abbr,
                        compressed,
                        flags=re.IGNORECASE
                    )
        
        # Clean up whitespace (all levels)
        compressed = re.sub(r'\s+', ' ', compressed)  # Multiple spaces to single
        compressed = re.sub(r'\n\s*\n\s*\n+', '\n\n', compressed)  # Multiple newlines to double
        compressed = compressed.strip()
        
        return compressed
    
    @classmethod
    def compress_tool_description(cls, description: str, compression_level: str = 'medium') -> str:
        """Compress a tool description to reduce token usage.
        
        Args:
            description: The tool description to compress
            compression_level: Compression level ('light', 'medium', 'aggressive')
            
        Returns:
            Compressed description
        """
        if not description:
            return description
        
        compressed = description
        
        # Remove common filler phrases in tool descriptions
        tool_fillers = [
            r'\b(?:this\s+tool|this\s+function|this\s+method)\s+(?:allows|enables|permits)\s+(?:you|users)\s+to\b',
            r'\b(?:use\s+this\s+tool\s+to|use\s+this\s+function\s+to)\b',
            r'\b(?:the\s+)?(?:purpose|goal|objective)\s+of\s+this\s+(?:tool|function)\s+is\s+to\b',
            r'\b(?:this\s+is\s+useful\s+for|this\s+is\s+helpful\s+for)\b',
        ]
        
        if compression_level in ('medium', 'aggressive'):
            for pattern in tool_fillers:
                compressed = re.sub(pattern, '', compressed, flags=re.IGNORECASE)
        
        # Apply general compression
        compressed = cls.compress_prompt(compressed, compression_level)
        
        return compressed
    
    @classmethod
    def compress_tools(cls, tools: list[BaseTool], compression_level: str = 'medium') -> list[BaseTool]:
        """Compress descriptions for multiple tools.
        
        Args:
            tools: List of tools to compress
            compression_level: Compression level ('light', 'medium', 'aggressive')
            
        Returns:
            List of tools with compressed descriptions
        """
        from langchain_core.tools import StructuredTool
        
        compressed_tools = []
        for tool in tools:
            # Compress description
            compressed_desc = cls.compress_tool_description(
                tool.description,
                compression_level
            )
            
            # Create new tool with compressed description
            if isinstance(tool, StructuredTool):
                compressed_tool = StructuredTool.from_function(
                    func=tool.func,
                    name=tool.name,
                    description=compressed_desc,
                    args_schema=tool.args_schema,
                )
            else:
                # For other tool types, just update the description
                tool.description = compressed_desc
                compressed_tool = tool
            
            compressed_tools.append(compressed_tool)
        
        return compressed_tools
    
    @classmethod
    def estimate_token_savings(cls, original: str, compressed: str) -> dict[str, int]:
        """Estimate token savings from compression.
        
        Args:
            original: Original text
            compressed: Compressed text
            
        Returns:
            Dictionary with token counts and savings
        """
        # Rough token estimation (4 chars per token on average)
        original_tokens = len(original) // 4
        compressed_tokens = len(compressed) // 4
        savings = original_tokens - compressed_tokens
        percentage = (savings / original_tokens * 100) if original_tokens > 0 else 0
        
        return {
            'original_tokens': original_tokens,
            'compressed_tokens': compressed_tokens,
            'savings': savings,
            'savings_percentage': percentage, # type: ignore
        }


__all__ = ['PromptCompressor']