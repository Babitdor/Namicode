"""First-run onboarding wizard and secret management for Nami CLI.

This module provides secure storage of API keys and interactive onboarding
workflow for first-time setup.
"""

import json
import os
import stat
from getpass import getpass
from pathlib import Path
from typing import Any

import requests
from rich.console import Console
from rich.panel import Panel

from namicode_cli.config.config import HOME_DIR, Settings
from namicode_cli.config.nami_config import NamiConfig

console = Console()

# API key names for all supported providers
API_KEY_NAMES = {
    "tavily": "tavily_api_key",
    "openai": "openai_api_key",
    "anthropic": "anthropic_api_key",
    "google": "google_api_key",
    "groq": "groq_api_key",
    "e2b": "e2b_api_key",
}


class SecretManager:
    """Manages secure storage and retrieval of API keys.

    Uses OS keychain (via keyring library) as primary storage,
    with fallback to permission-restricted JSON file.
    """

    SERVICE_NAME = "nami-cli"
    FALLBACK_FILE = HOME_DIR / "secrets.json"

    def __init__(self) -> None:
        """Initialize secret manager with keyring or file fallback."""
        self.use_keyring = False
        try:
            import keyring

            self.keyring = keyring
            # Test if keyring is actually available (not null backend)
            backend = keyring.get_keyring()
            if backend.__class__.__name__ != "fail.Keyring":
                self.use_keyring = True
        except (ImportError, RuntimeError):
            pass

        if not self.use_keyring:
            console.print(
                "[yellow]⚠ OS keychain not available, using file-based storage[/yellow]"
            )
            self._ensure_fallback_file()

    def _ensure_fallback_file(self) -> None:
        """Create secrets.json with secure permissions if it doesn't exist."""
        if not self.FALLBACK_FILE.exists():
            self.FALLBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.FALLBACK_FILE.write_text("{}", encoding="utf-8")
            # Set restrictive permissions (owner read/write only)
            if hasattr(os, "chmod"):
                os.chmod(self.FALLBACK_FILE, stat.S_IRUSR | stat.S_IWUSR)

    def store_secret(self, key: str, value: str) -> bool:
        """Store a secret (API key) securely.

        Args:
            key: The secret key name (e.g., "tavily_api_key")
            value: The secret value

        Returns:
            True if storage was successful, False otherwise
        """
        try:
            if self.use_keyring:
                self.keyring.set_password(self.SERVICE_NAME, key, value)
            else:
                # Fallback: JSON file
                secrets = {}
                if self.FALLBACK_FILE.exists():
                    secrets = json.loads(self.FALLBACK_FILE.read_text(encoding="utf-8"))
                secrets[key] = value
                self.FALLBACK_FILE.write_text(
                    json.dumps(secrets, indent=2), encoding="utf-8"
                )
            return True
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]✗ Failed to store secret: {e}[/red]")
            return False

    def get_secret(self, key: str) -> str | None:
        """Retrieve a secret (API key).

        Args:
            key: The secret key name (e.g., "tavily_api_key")

        Returns:
            The secret value, or None if not found
        """
        try:
            if self.use_keyring:
                return self.keyring.get_password(self.SERVICE_NAME, key)
            # Fallback: JSON file
            if self.FALLBACK_FILE.exists():
                secrets = json.loads(self.FALLBACK_FILE.read_text(encoding="utf-8"))
                return secrets.get(key)
            return None
        except Exception:  # noqa: BLE001, S110
            return None

    def delete_secret(self, key: str) -> bool:
        """Delete a secret (API key).

        Args:
            key: The secret key name (e.g., "tavily_api_key")

        Returns:
            True if deletion was successful, False otherwise
        """
        try:
            if self.use_keyring:
                try:
                    self.keyring.delete_password(self.SERVICE_NAME, key)
                except self.keyring.errors.PasswordDeleteError:
                    # Key doesn't exist, that's ok
                    pass
            else:
                # Fallback: JSON file
                if self.FALLBACK_FILE.exists():
                    secrets = json.loads(self.FALLBACK_FILE.read_text(encoding="utf-8"))
                    secrets.pop(key, None)
                    self.FALLBACK_FILE.write_text(
                        json.dumps(secrets, indent=2), encoding="utf-8"
                    )
            return True
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]✗ Failed to delete secret: {e}[/red]")
            return False

    def list_secrets(self) -> list[str]:
        """List all stored secret keys.

        Returns:
            List of secret key names (not values)
        """
        if self.use_keyring:
            # Keyring doesn't provide list functionality, so we check known keys
            return [
                key
                for key in API_KEY_NAMES.values()
                if self.keyring.get_password(self.SERVICE_NAME, key)
            ]
        # Fallback: JSON file
        if self.FALLBACK_FILE.exists():
            try:
                secrets = json.loads(self.FALLBACK_FILE.read_text(encoding="utf-8"))
                return list(secrets.keys())
            except Exception:  # noqa: BLE001, S110
                return []
        return []


class OnboardingWizard:
    """Interactive wizard for first-time setup of Nami CLI.

    Guides users through:
    1. LLM provider selection
    2. Provider-specific configuration
    3. Tavily API key setup
    4. Connection testing
    5. Configuration saving
    """

    PROVIDERS = {
        "1": {"name": "ollama", "display": "Ollama (local)"},
        "2": {"name": "openai", "display": "OpenAI"},
        "3": {"name": "anthropic", "display": "Anthropic"},
    }

    def __init__(self) -> None:
        """Initialize the onboarding wizard."""
        self.secret_manager = SecretManager()
        self.config_path = HOME_DIR / "config.json"
        self.nami_config = NamiConfig()

    def run(self) -> bool:
        """Run the interactive onboarding wizard.

        Returns:
            True if onboarding completed successfully, False otherwise
        """
        console.print()
        console.print(
            Panel.fit(
                "[bold cyan]Welcome to Nami 👋[/bold cyan]\n\n"
                "Let's set up your AI coding assistant.",
                border_style="cyan",
            )
        )
        console.print()

        # Step 1: Choose LLM provider
        provider = self._prompt_provider()
        if not provider:
            return False

        # Step 2: Configure provider
        provider_config = self._prompt_provider_config(provider)
        if not provider_config:
            return False

        # Step 3: Get Tavily API key (optional - can skip for now)
        tavily_key = self._prompt_tavily_key()

        # Step 4: Get E2B API key (optional - can skip for now)
        e2b_key = self._prompt_e2b_key()

        # Step 5: Test connections
        console.print()
        console.print("[bold]Testing connections:[/bold]")
        if not self._test_connections(provider, provider_config, tavily_key, e2b_key):
            console.print()
            console.print(
                "[yellow]⚠ Connection tests failed. "
                "You can continue but may need to fix configuration later.[/yellow]"
            )
            response = input("Continue anyway? [y/N]: ").strip().lower()
            if response != "y":
                return False

        # Step 6: Save configuration
        self._save_config(provider, provider_config, tavily_key)

        console.print()
        console.print("[green]✓ Setup complete![/green]")
        console.print()
        console.print(f"[dim]Configuration saved to {self.config_path}[/dim]")
        if self.secret_manager.use_keyring:
            console.print("[dim]API keys stored in system keychain[/dim]")
        else:
            console.print(
                f"[dim]API keys stored in {self.secret_manager.FALLBACK_FILE}[/dim]"
            )
        console.print()
        console.print("[bold cyan]You're ready to go![/bold cyan]\"")

        return True

    def _prompt_provider(self) -> str | None:
        """Prompt user to select an LLM provider.

        Returns:
            Provider name (ollama/openai/anthropic/groq) or None if cancelled
        """
        console.print("[bold]Choose LLM provider:[/bold]")
        for key, provider in self.PROVIDERS.items():
            console.print(f"  {key}. {provider['display']}")
        console.print()

        choice = input("> ").strip()

        if choice not in self.PROVIDERS:
            console.print("[red]✗ Invalid choice[/red]")
            return None

        return self.PROVIDERS[choice]["name"]

    def _prompt_provider_config(self, provider: str) -> dict[str, Any] | None:
        """Prompt for provider-specific configuration.

        Args:
            provider: Provider name (ollama/openai/anthropic)

        Returns:
            Configuration dict or None if cancelled
        """
        console.print()
        console.print(f"[bold]{provider.title()} configuration:[/bold]")

        if provider == "ollama":
            # Ollama: just needs host
            host = input("  Host [http://localhost:11434]: ").strip()
            if not host:
                host = "http://localhost:11434"
            return {"host": host}

        # Cloud providers: need API key
        api_key = getpass(f"  {provider.title()} API key: ")
        if not api_key:
            console.print(f"[red]✗ {provider.title()} API key required[/red]")
            return None

        # Store API key in secret manager
        key_name = API_KEY_NAMES[provider]
        self.secret_manager.store_secret(key_name, api_key)

        return {"api_key": api_key}

    def _prompt_tavily_key(self) -> str | None:
        """Prompt for Tavily Search API key (optional).

        Returns:
            Tavily API key or None if skipped
        """
        console.print()
        console.print("[bold]Search provider (Tavily):[/bold]")
        console.print("  [dim]Required for web search. Press Enter to skip.[/dim]")
        tavily_key = getpass("  Tavily API key: ")

        if tavily_key:
            self.secret_manager.store_secret(API_KEY_NAMES["tavily"], tavily_key)
            return tavily_key

        return None

    def _prompt_e2b_key(self) -> str | None:
        """Prompt for E2B Sandbox API key (optional).

        Returns:
            E2B API key or None if skipped
        """
        console.print()
        console.print("[bold]Sandbox execution provider (E2B):[/bold]")
        console.print("  [dim]Required for secure code execution. Press Enter to skip.[/dim]")
        console.print("  [dim]Get your free API key at: https://e2b.dev[/dim]")
        e2b_key = getpass("  E2B API key: ")

        if e2b_key:
            self.secret_manager.store_secret(API_KEY_NAMES["e2b"], e2b_key)
            return e2b_key

        return None

    def _test_connections(
        self,
        provider: str,
        provider_config: dict[str, Any],
        tavily_key: str | None,
        e2b_key: str | None,
    ) -> bool:
        """Test connections to LLM provider, Tavily, and E2B.

        Args:
            provider: Provider name
            provider_config: Provider configuration
            tavily_key: Tavily API key (optional)
            e2b_key: E2B API key (optional)

        Returns:
            True if all tests passed, False otherwise
        """
        all_passed = True

        # Test LLM provider
        if provider == "ollama":
            console.print(f"  → Testing {provider} connection... ", end="")
            try:
                host = provider_config["host"]
                response = requests.get(f"{host}/api/tags", timeout=5)
                if response.status_code == 200:  # noqa: PLR2004
                    console.print("[green]✓[/green]")
                else:
                    console.print(f"[red]✗ (HTTP {response.status_code})[/red]")
                    all_passed = False
            except Exception as e:  # noqa: BLE001
                console.print(f"[red]✗ ({e})[/red]")
                all_passed = False
        else:
            # For cloud providers, try to create model instance
            console.print(f"  → Testing {provider} connection... ", end="")
            try:
                # Temporarily set API key in environment for testing
                api_key = provider_config["api_key"]
                os.environ[f"{provider.upper()}_API_KEY"] = api_key

                # Try to create model using ModelManager
                from namicode_cli.config.model_manager import ModelManager

                model_manager = ModelManager()
                _ = model_manager.create_model_for_provider(provider)

                console.print("[green]✓[/green]")
            except Exception as e:  # noqa: BLE001
                console.print(f"[red]✗ ({e})[/red]")
                all_passed = False

        # Test Tavily if key provided
        if tavily_key:
            console.print("  → Testing Tavily connection... ", end="")
            try:
                from tavily import TavilyClient

                client = TavilyClient(api_key=tavily_key)
                # Simple test query
                _ = client.search("test", max_results=1)
                console.print("[green]✓[/green]")
            except Exception as e:  # noqa: BLE001
                console.print(f"[red]✗ ({e})[/red]")
                all_passed = False

        # Test E2B if key provided
        if e2b_key:
            console.print("  → Testing E2B sandbox connection... ", end="")
            try:
                from namicode_cli.integrations.e2b_executor import E2BExecutor

                executor = E2BExecutor(api_key=e2b_key)
                # Simple test execution
                result = executor.execute("print('test')", language="python", timeout=10)
                if result.exit_code == 0:
                    console.print("[green]✓[/green]")
                else:
                    console.print(f"[red]✗ (exit code {result.exit_code})[/red]")
                    all_passed = False
            except Exception as e:  # noqa: BLE001
                console.print(f"[red]✗ ({e})[/red]")
                all_passed = False

        return all_passed

    def _save_config(
        self, provider: str, provider_config: dict[str, Any], tavily_key: str | None
    ) -> None:
        """Save configuration to config.json and secrets.

        Args:
            provider: Provider name
            provider_config: Provider configuration
            tavily_key: Tavily API key (optional)
        """
        # Build config (non-secret parts only)
        config: dict[str, Any] = {
            "provider": provider,
            "onboarding_completed": True,
        }

        if provider == "ollama":
            config["ollama"] = {"host": provider_config["host"]}
        # For cloud providers, API key is already stored in secret manager

        if tavily_key:
            config["search"] = {"provider": "tavily"}

        # Save to config.json
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

        # Also save to NamiConfig for backward compatibility
        if provider == "ollama":
            # Check if Ollama models are installed
            from namicode_cli.config.model_manager import get_ollama_models

            available_models = get_ollama_models()

            if "minimax-m2.1:cloud" in available_models:
                model_name = "minimax-m2.1:cloud"
            elif available_models:
                # Use the first available model
                model_name = available_models[0]
                console.print()
                console.print(
                    f"[yellow]⚠ minimax-m2.1:cloud not found, using {model_name}[/yellow]"
                )
                console.print()
            else:
                # No models installed
                model_name = "minimax-m2.1:cloud"  # Set as default anyway
                console.print()
                console.print(
                    "[yellow]⚠ No Ollama models found on your system[/yellow]"
                )
                console.print()
                console.print("[bold]To install Ollama models:[/bold]")
                console.print(
                    "  1. Install a model: [cyan]ollama pull minimax-m2.1:cloud[/cyan]"
                )
                console.print(
                    "  2. Or browse models: [cyan]https://ollama.com/library[/cyan]"
                )
                console.print()
                console.print(
                    "[dim]After installing models, use the [bold]/model[/bold] command to configure them[/dim]"
                )
                console.print()
        else:
            model_name = "default"

        self.nami_config.set_model_config(provider, model_name)

        # Create completion marker
        (HOME_DIR / ".onboarded").touch()
