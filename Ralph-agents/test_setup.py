#!/usr/bin/env python3
"""
Quick test to verify Ralph Agents setup is working.
"""
import sys
from pathlib import Path

def test_setup():
    """Test that all files are in place."""
    print("Testing Ralph Agents setup...")
    print("=" * 60)
    
    # Check directory exists (support running from inside or outside Ralph-agents)
    ralph_dir = Path("Ralph-agents")
    if not ralph_dir.exists():
        # Try current directory
        if Path("config.yaml").exists() and Path("agent_system.py").exists():
            ralph_dir = Path(".")
        else:
            print("[X] Ralph-agents directory not found")
            return False
    
    print("[OK] Ralph-agents directory exists")
    
    # Check required files
    required_files = [
        "config.yaml",
        "agent_system.py",
        "example_usage.py",
        "README.md"
    ]
    
    for file in required_files:
        file_path = ralph_dir / file
        if file_path.exists():
            size = file_path.stat().st_size
            print(f"[OK] {file} ({size} bytes)")
        else:
            print(f"[X] {file} not found")
            return False
    
    # Test imports
    print("\n" + "=" * 60)
    print("Testing imports...")
    try:
        sys.path.insert(0, str(ralph_dir))
        from agent_system import RalphAgentSystem
        print("[OK] agent_system module imports successfully")
        
        # Test system initialization
        system = RalphAgentSystem()
        print("[OK] RalphAgentSystem initializes successfully")
        
        # Test agent loading
        if system.config and system.config.agents:
            print(f"[OK] Loaded {len(system.config.agents)} agent profiles:")
            for name, agent in system.config.agents.items():
                print(f"   - {name}: {agent.description}")
        else:
            print("[!]  No agents loaded (using defaults)")
        
        return True
        
    except Exception as e:
        print(f"[X] Import failed: {e}")
        return False

if __name__ == "__main__":
    success = test_setup()
    print("\n" + "=" * 60)
    if success:
        print("[OK] All tests passed! Ralph Agents is ready to use.")
        print("\nNext steps:")
        print("  1. cd Ralph-agents")
        print("  2. python agent_system.py --list")
        print("  3. python agent_system.py \"Your task here\"")
    else:
        print("[X] Some tests failed. Please check the setup.")
    sys.exit(0 if success else 1)