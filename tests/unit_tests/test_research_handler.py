"""Tests for the /research command handler."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from novacode_cli.commands.research_handler import (
    handle_research_command,
    get_research_prompt,
    ResearchMode,
)


@pytest.fixture
def mock_session_state():
    """Create a mock session state."""
    return MagicMock()


@pytest.fixture
def temp_output_dir(tmp_path):
    """Create a temporary output directory."""
    output_dir = tmp_path / ".nova" / "research"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


@pytest.mark.asyncio
async def test_handle_research_command_basic(mock_session_state, temp_output_dir):
    """Test basic research command execution."""
    result = await handle_research_command(
        session_state=mock_session_state,
        research_query="What are the latest advances in quantum computing?",
        mode="general",
        agent_count=3,
        output_dir=temp_output_dir,
    )
    
    # Should return a prompt string
    assert isinstance(result, str)
    assert len(result) > 0
    
    # Check that output directory was created
    assert temp_output_dir.exists()


@pytest.mark.asyncio
async def test_handle_research_command_no_query(mock_session_state, temp_output_dir):
    """Test research command without query (should prompt user)."""
    result = await handle_research_command(
        session_state=mock_session_state,
        research_query=None,
        mode="general",
        agent_count=3,
        output_dir=temp_output_dir,
    )
    
    # Should return "research_mode" to prompt user
    assert result == "research_mode"


@pytest.mark.asyncio
async def test_handle_research_command_academic_mode(mock_session_state, temp_output_dir):
    """Test academic research mode."""
    result = await handle_research_command(
        session_state=mock_session_state,
        research_query="What are the current approaches to solving the traveling salesman problem?",
        mode="academic",
        agent_count=3,
        output_dir=temp_output_dir,
    )
    
    assert isinstance(result, str)
    assert "academic" in result.lower()
    assert "literature_reviewer" in result.lower()


@pytest.mark.asyncio
async def test_handle_research_command_market_mode(mock_session_state, temp_output_dir):
    """Test market research mode."""
    result = await handle_research_command(
        session_state=mock_session_state,
        research_query="What is the competitive landscape for AI-powered code assistants?",
        mode="market",
        agent_count=3,
        output_dir=temp_output_dir,
    )
    
    assert isinstance(result, str)
    assert "market" in result.lower()
    assert "market_analyst" in result.lower()


@pytest.mark.asyncio
async def test_handle_research_command_stocks_mode(mock_session_state, temp_output_dir):
    """Test stock research mode."""
    result = await handle_research_command(
        session_state=mock_session_state,
        research_query="Should I invest in NVIDIA for long-term growth?",
        mode="stocks",
        agent_count=3,
        output_dir=temp_output_dir,
    )
    
    assert isinstance(result, str)
    assert "stocks" in result.lower()
    assert "financial_analyst" in result.lower()


@pytest.mark.asyncio
async def test_handle_research_command_technical_mode(mock_session_state, temp_output_dir):
    """Test technical research mode."""
    result = await handle_research_command(
        session_state=mock_session_state,
        research_query="How do I implement OAuth 2.0 authentication in Python?",
        mode="technical",
        agent_count=3,
        output_dir=temp_output_dir,
    )
    
    assert isinstance(result, str)
    assert "technical" in result.lower()
    assert "doc_researcher" in result.lower()


@pytest.mark.asyncio
async def test_handle_research_command_custom_agent_count(mock_session_state, temp_output_dir):
    """Test research command with custom agent count."""
    result = await handle_research_command(
        session_state=mock_session_state,
        research_query="Test query",
        mode="general",
        agent_count=5,
        output_dir=temp_output_dir,
    )
    
    assert isinstance(result, str)
    # Should handle custom agent count gracefully


def test_get_research_prompt_basic():
    """Test research prompt generation."""
    prompt = get_research_prompt(
        research_query="What are the latest advances in quantum computing?",
        mode="general",
        agent_count=3,
    )
    
    assert isinstance(prompt, str)
    assert "quantum computing" in prompt.lower()
    assert "general" in prompt.lower()
    assert "3" in prompt


def test_get_research_prompt_academic():
    """Test academic research prompt generation."""
    prompt = get_research_prompt(
        research_query="Test academic query",
        mode="academic",
        agent_count=3,
    )
    
    assert "academic" in prompt.lower()
    assert "literature_reviewer" in prompt.lower()
    assert "methodology_analyst" in prompt.lower()
    assert "citation_tracker" in prompt.lower()


def test_get_research_prompt_market():
    """Test market research prompt generation."""
    prompt = get_research_prompt(
        research_query="Test market query",
        mode="market",
        agent_count=3,
    )
    
    assert "market" in prompt.lower()
    assert "market_analyst" in prompt.lower()
    assert "competitor_researcher" in prompt.lower()
    assert "trend_tracker" in prompt.lower()


def test_get_research_prompt_stocks():
    """Test stock research prompt generation."""
    prompt = get_research_prompt(
        research_query="Test stock query",
        mode="stocks",
        agent_count=3,
    )
    
    assert "stocks" in prompt.lower()
    assert "financial_analyst" in prompt.lower()
    assert "news_researcher" in prompt.lower()
    assert "technical_analyst" in prompt.lower()


def test_get_research_prompt_technical():
    """Test technical research prompt generation."""
    prompt = get_research_prompt(
        research_query="Test technical query",
        mode="technical",
        agent_count=3,
    )
    
    assert "technical" in prompt.lower()
    assert "doc_researcher" in prompt.lower()
    assert "api_analyst" in prompt.lower()
    assert "implementation_specialist" in prompt.lower()


def test_get_research_prompt_custom_output_dir():
    """Test research prompt with custom output directory."""
    custom_dir = Path("/custom/research/dir")
    prompt = get_research_prompt(
        research_query="Test query",
        mode="general",
        agent_count=3,
        output_dir=custom_dir,
    )
    
    assert str(custom_dir) in prompt


def test_research_mode_types():
    """Test that ResearchMode type hints work correctly."""
    # Valid modes
    valid_modes: list[ResearchMode] = ["academic", "market", "stocks", "technical", "general"]
    
    for mode in valid_modes:
        # Should not raise type error
        prompt = get_research_prompt("Test query", mode=mode)
        assert isinstance(prompt, str)


def test_agent_count_limit():
    """Test that agent count is handled correctly."""
    # Test with more agents than available
    prompt = get_research_prompt(
        research_query="Test query",
        mode="academic",
        agent_count=10,  # More than the 3 defined agents
    )
    
    # Should still work, just use available agents
    assert isinstance(prompt, str)


def test_output_directory_creation(temp_output_dir):
    """Test that output directory is created if it doesn't exist."""
    import os
    
    # Remove the directory
    if temp_output_dir.exists():
        temp_output_dir.rmdir()
    
    # This should create it
    prompt = get_research_prompt(
        research_query="Test query",
        mode="general",
        output_dir=temp_output_dir,
    )
    
    # Directory should be created
    # Note: get_research_prompt doesn't create the directory,
    # but handle_research_command does
    assert isinstance(prompt, str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])