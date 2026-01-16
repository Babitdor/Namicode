#!/usr/bin/env python3
"""
Example Usage of Ralph Agent System

This file demonstrates how to use the Ralph agent system for various tasks.
"""
import asyncio
from agent_system import RalphAgentSystem


async def example_basic_task():
    """Example 1: Basic autonomous task execution."""
    system = RalphAgentSystem()
    
    await system.run_task(
        task="Create a simple Python CLI tool that greets users",
        agent_name="ralph",
        max_iterations=3  # Run for 3 iterations
    )


async def example_coder_agent():
    """Example 2: Using the coder agent for code generation."""
    system = RalphAgentSystem()
    
    await system.run_task(
        task="Create a REST API using FastAPI with endpoints for CRUD operations",
        agent_name="coder",
        max_iterations=5
    )


async def example_custom_workspace():
    """Example 3: Using a custom workspace directory."""
    system = RalphAgentSystem()
    
    await system.run_task(
        task="Build a React component library",
        agent_name="coder",
        max_iterations=0,  # Unlimited iterations
        work_dir="./my-react-project"
    )


async def example_list_agents():
    """Example 4: List all available agents."""
    system = RalphAgentSystem()
    system.list_agents()


async def main():
    """Run all examples."""
    print("=" * 60)
    print("Ralph Agent System - Example Usage")
    print("=" * 60)
    
    # Example 1: List available agents
    print("\n1. Listing available agents...")
    await example_list_agents()
    
    print("\n" + "=" * 60)
    print("To run a specific example, modify the main() function")
    print("and uncomment the example you want to run.")
    print("=" * 60)


if __name__ == "__main__":
    # Uncomment one of these examples to run:
    
    # asyncio.run(example_basic_task())
    # asyncio.run(example_coder_agent())
    # asyncio.run(example_custom_workspace())
    asyncio.run(example_list_agents())