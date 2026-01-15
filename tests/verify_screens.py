
import sys
import os
from pathlib import Path

# Add project root to sys.path
sys.path.append(os.getcwd())

import asyncio
from rich.console import Console

console = Console()

async def verify_screens():
    console.print("[bold]Verifying Textual Screens...[/bold]")
    
    try:
        # Import App
        from namicode_cli.app import NamiCodeApp
        console.print("[green]✓ Imported NamiCodeApp[/green]")
        
        # Import Screens
        from namicode_cli.widgets.screens import (
            ModelSelectionModal,
            MCPScreen,
            SkillsScreen,
            AgentsScreen,
            AgentCreateModal,
            SessionsScreen,
            ServersScreen
        )
        console.print("[green]✓ Imported screen classes[/green]")
        
        # Instantiate Screens (Mocking app/dependencies if needed)
        # Note: Screens usually require binding to an app, but we just check instantiation logic
        # Some might fail if they access `self.app` in __init__, but Textual widgets usually don't until mount.
        
        # MCPScreen
        mcp_screen = MCPScreen()
        console.print(f"[green]✓ Instantiated MCPScreen: {mcp_screen}[/green]")

        # SkillsScreen
        skills_screen = SkillsScreen()
        console.print(f"[green]✓ Instantiated SkillsScreen: {skills_screen}[/green]")

        # AgentsScreen
        agents_screen = AgentsScreen()
        console.print(f"[green]✓ Instantiated AgentsScreen: {agents_screen}[/green]")

        # SessionsScreen
        from namicode_cli.app import TextualSessionState
        dummy_state = TextualSessionState()
        sessions_screen = SessionsScreen(session_state=dummy_state)
        console.print(f"[green]✓ Instantiated SessionsScreen: {sessions_screen}[/green]")

        # ServersScreen
        servers_screen = ServersScreen()
        console.print(f"[green]✓ Instantiated ServersScreen: {servers_screen}[/green]")

        # Modals might need arguments
        # ModelSelectionModal
        model_modal = ModelSelectionModal()
        console.print(f"[green]✓ Instantiated ModelSelectionModal: {model_modal}[/green]")

        # AgentCreateModal
        agent_modal = AgentCreateModal()
        console.print(f"[green]✓ Instantiated AgentCreateModal: {agent_modal}[/green]")

        console.print("\n[bold green]All screens verified successfully![/bold green]")
        return True

    except Exception as e:
        console.print(f"\n[bold red]Verification Failed:[/bold red] {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(verify_screens())
    sys.exit(0 if success else 1)
