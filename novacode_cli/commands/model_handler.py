"""Handler for the /model command for LLM provider management."""

import os
from typing import Any

from prompt_toolkit import PromptSession
from rich.console import Console
from rich.text import Text

from novacode_cli.config.config import COLORS, console
from novacode_cli.config.model_manager import MODEL_PRESETS, ModelManager, get_ollama_models
from novacode_cli.config.model_create import create_model


async def handle_model_command(session_state: Any | None = None) -> bool:
    """Handle the /model command for LLM provider management.
    
    Args:
        session_state: Optional session state for dynamic model switching
        
    Returns:
        True (command always handled)
    """
    session = PromptSession()
    model_manager = ModelManager()

    console.print()
    console.print("[bold]Model Provider Management[/bold]", style=COLORS["primary"])
    console.print()

    # Show current model
    current = model_manager.get_current_provider()
    if current:
        provider_name, model_name = current
        console.print(
            f"[bold]Current:[/bold] {provider_name} - {model_name}",
            style=COLORS["primary"],
        )
        console.print()

    # Show menu
    console.print("What would you like to do?", style=COLORS["primary"])
    console.print("  1. View available providers")
    console.print("  2. Switch provider")
    console.print("  3. View current provider details")
    console.print("  4. Cancel")
    console.print()

    choice = (await session.prompt_async("Choose (1-4): ")).strip()

    if choice == "1":
        # List available providers
        available = model_manager.get_available_providers()
        console.print()
        console.print("[bold]Available Providers:[/bold]", style=COLORS["primary"])
        console.print()

        if not available:
            console.print("[yellow]No providers configured[/yellow]")
            console.print(
                "[dim]Configure API keys in environment variables to enable providers[/dim]"
            )
            console.print()
            console.print("[bold]Required environment variables:[/bold]")
            for provider_id, preset in MODEL_PRESETS.items():
                if preset["requires_api_key"]:
                    console.print(f"  • {preset['name']}: {preset['api_key_var']}")
        else:
            for provider_id, preset in available:
                icon = "✓" if current and preset["name"] == current[0] else " "
                console.print(
                    f"  {icon} [bold]{preset['name']}[/bold]", style=COLORS["primary"]
                )
                console.print(f"    {preset['description']}", style=COLORS["dim"])
                console.print(
                    f"    Default model: {preset['default_model']}", style=COLORS["dim"]
                )
                console.print()

    elif choice == "2":
        # Switch provider
        available = model_manager.get_available_providers()

        if not available:
            console.print()
            console.print("[yellow]No providers available[/yellow]")
            console.print("[dim]Configure API keys to enable more providers[/dim]")
            return True

        console.print()
        console.print("[bold]Available Providers:[/bold]", style=COLORS["primary"])
        for i, (provider_id, preset) in enumerate(available, 1):
            console.print(f"  {i}. {preset['name']} ({preset['default_model']})")

        console.print()
        provider_choice = (
            await session.prompt_async("Choose provider number (or 'cancel'): ")
        ).strip()

        if provider_choice.lower() != "cancel":
            try:
                provider_idx = int(provider_choice) - 1
                if 0 <= provider_idx < len(available):
                    provider_id, preset = available[provider_idx]

                    # Validate API key for cloud providers
                    if preset["requires_api_key"]:
                        from novacode_cli.onboarding import SecretManager

                        secret_manager = SecretManager()
                        api_key_name = preset[
                            "api_key_var"
                        ].lower()  # e.g., OPENAI_API_KEY -> openai_api_key

                        # Check if API key exists in keyring or environment
                        api_key = secret_manager.get_secret(
                            api_key_name
                        ) or os.environ.get(preset["api_key_var"])

                        if not api_key:
                            # Prompt user to provide API key
                            console.print()
                            console.print(
                                f"[yellow]⚠ {preset['name']} requires an API key to proceed[/yellow]"
                            )
                            console.print()
                            console.print(
                                f"[bold]Enter {preset['name']} API key:[/bold]"
                            )
                            console.print(
                                "[dim]This will be stored securely in your system keychain[/dim]"
                            )
                            console.print()

                            new_api_key = (
                                await session.prompt_async(
                                    f"{preset['api_key_var']}: ",
                                    is_password=True,
                                )
                            ).strip()

                            if not new_api_key:
                                console.print()
                                console.print(
                                    "[yellow]⚠ No API key provided, cancelled[/yellow]"
                                )
                                console.print()
                                return True

                            # Store the API key
                            if secret_manager.store_secret(api_key_name, new_api_key):
                                # Also set in environment for immediate use
                                os.environ[preset["api_key_var"]] = new_api_key
                                console.print()
                                console.print(
                                    "[green]✓ API key saved to system keychain[/green]"
                                )
                                console.print()
                            else:
                                console.print()
                                console.print("[red]✗ Failed to save API key[/red]")
                                console.print()
                                return True

                    # Ask if user wants to specify a different model
                    console.print()
                    console.print(
                        f"[bold]Available models for {preset['name']}:[/bold]",
                        style=COLORS["primary"],
                    )

                    # Get models list (dyNovac for Ollama, static for others)
                    if provider_id == "ollama":
                        models_list = get_ollama_models()
                        console.print(
                            f"[dim]  Found {len(models_list)} Ollama models on your system[/dim]"
                        )
                        console.print()
                    else:
                        models_list = preset["models"]

                    for i, model in enumerate(models_list, 1):
                        default_marker = (
                            " (default)" if model == preset["default_model"] else ""
                        )
                        console.print(f"  {i}. {model}{default_marker}")

                    console.print()
                    model_choice = (
                        await session.prompt_async(
                            "Choose model number (or press Enter for default): ",
                            default="",
                        )
                    ).strip()

                    model_name = None
                    if model_choice and model_choice.isdigit():
                        model_idx = int(model_choice) - 1
                        if 0 <= model_idx < len(models_list):
                            model_name = models_list[model_idx]

                    # Set the provider
                    try:
                        model_manager.set_provider(provider_id, model_name)  # type: ignore[arg-type]
                        console.print()
                        console.print(
                            f"✓ Switched to {preset['name']}!",
                            style=COLORS["primary"],
                        )
                        console.print()
                        console.print(
                            "[green]✓ Configuration saved to ~/.nova/Nova.config.json[/green]"
                        )
                        
                        # Attempt dynamic model switching if session state is available
                        if session_state is not None:
                            try:
                                # Create new model instance
                                new_model = create_model()
                                
                                # Switch model dynamically (recreates agent with preserved state)
                                await session_state.switch_model(new_model)
                                
                                console.print()
                                console.print("[green]✓ Model switched dynamically![/green]")
                                console.print("[dim]New model is active immediately[/dim]")
                            except Exception as e:
                                console.print()
                                console.print(f"[yellow]⚠ Could not switch model dynamically: {e}[/yellow]")
                                console.print("[dim]Model change will take effect after restarting the CLI[/dim]")
                        else:
                            console.print()
                            console.print(
                                "[yellow]⚠ Note: Model change will take effect after restarting the CLI[/yellow]"
                            )
                            console.print(
                                "[dim]The saved configuration will be loaded automatically on next start[/dim]"
                            )
                    except ValueError as e:
                        console.print()
                        console.print(f"[bold red]Error:[/bold red] {e}")
                else:
                    console.print()
                    console.print("[yellow]Invalid choice[/yellow]")
            except (ValueError, IndexError):
                console.print()
                console.print("[yellow]Invalid choice[/yellow]")

    elif choice == "3":
        # View current provider details
        console.print()
        if current:
            provider_name, model_name = current
            console.print(
                f"[bold]Current Provider:[/bold] {provider_name}",
                style=COLORS["primary"],
            )
            console.print(
                f"[bold]Current Model:[/bold] {model_name}", style=COLORS["primary"]
            )
            console.print()

            # Find preset info
            for provider_id, preset in MODEL_PRESETS.items():
                if preset["name"] == provider_name:
                    console.print(f"[bold]Description:[/bold] {preset['description']}")
                    console.print()
                    console.print("[bold]Available models:[/bold]")
                    for model in preset["models"]:
                        current_marker = " (current)" if model == model_name else ""
                        console.print(
                            f"  • {model}{current_marker}", style=COLORS["dim"]
                        )
                    break
        else:
            console.print("[yellow]No provider currently active[/yellow]")
        console.print()

    console.print()
    return True
